import os
import uuid
import asyncio
import json
import shutil
import unicodedata  # [Add] 유니코드 정규화를 위해 추가
import re
import multiprocessing # [Add] 자식 프로세스 관리를 위해 추가
from functools import partial
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi import Request, Header, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# [Custom Services]
from services.security import SecurityManager
from services.downloader import VideoDownloader
from services.transcriber import VideoTranscriber, TaskCancelledError
from services.summarizer import VideoSummarizer
from services.task_manager import TaskManager
from services.clipper import VideoClipper
from services.refiner import TextRefiner
from services.shorts_maker import ShortsMaker
from services.premiere_exporter import PremiereExporter
from services.system_manager import SystemManager, ConfigManager
from services.subtitle_builder import SubtitleBuilder


# --- [Lifespan Manager] ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    앱의 수명 주기(시작과 끝)를 관리하는 함수입니다.
    기존 @app.on_event("startup")을 대체합니다.
    """
    # [Startup] 앱 시작 시 실행
    print("--- [Lifespan] Starting Background Worker... ---")
    
    # [Cleanup] 서버 시작 시 잔존 임시 파일 정리
    cleanup_orphaned_files()
    
    worker_task = asyncio.create_task(worker())
    
    yield  # 앱이 실행되는 동안 여기서 대기 (Control Yield)
    
    # [Shutdown] 앱 종료 시 실행 (필요시 자원 해제 로직 추가)
    print("--- [Lifespan] Shutting down... ---")
    
    # [Add] 좀비 프로세스 방기: 모든 자식 프로세스 종료
    active_children = multiprocessing.active_children()
    if active_children:
        print(f"--- [Lifespan] Cleaning up {len(active_children)} child processes... ---")
        for child in active_children:
            child.terminate()
            child.join(timeout=1)
            if child.is_alive():
                child.kill()
    
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

# --- [App Initialization] ---
# [수정] lifespan 파라미터를 생성자에 전달
app = FastAPI(
    title="AI Video Analyst API", 
    version="2.0",
    lifespan=lifespan 
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"], # [Add] 프론트엔드에서 파일명을 읽을 수 있도록 허용
)

job_queue = asyncio.Queue()

# --- [Directory & Static Files] ---
os.makedirs("static/videos", exist_ok=True)
os.makedirs("static/results", exist_ok=True)
os.makedirs("static/temp", exist_ok=True)
os.makedirs("static/clips", exist_ok=True)  # [New] 영구 클립 저장소 생성
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- [Service Instances] ---
downloader = VideoDownloader(download_dir="static/videos")
transcriber = VideoTranscriber(output_dir="static/results")
summarizer = VideoSummarizer(output_dir="static/results")
refiner = TextRefiner() # [New] Refiner 인스턴스 추가
task_manager = TaskManager()  # [New] Task Manager Instance
clipper = VideoClipper(temp_dir="static/temp") # [New] 편집기 인스턴스 생성
shorts_maker = ShortsMaker()
premiere_exporter = PremiereExporter(output_dir="static/temp")

# [New] 리소스 제어 세마포어 (동시 실행 작업 수 제한)
resource_semaphore = asyncio.Semaphore(1)

# --- [Pydantic Models] ---
class TranscriptionRequest(BaseModel):
    url: Optional[str] = None      # 유튜브 URL
    filename: Optional[str] = None # 업로드된 파일명
    custom_title: Optional[str] = None # [New] 사용자가 지정한 영상 제목

class SettingsUpdateRequest(BaseModel): # [New] 설정 업데이트 요청 모델
    models: dict

# --- [API Endpoints] ---

@app.get("/api/settings")
async def get_settings():
    """현재 AI 모델 설정을 조회합니다."""
    return ConfigManager.load_config()

@app.post("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    """AI 모델 설정을 업데이트합니다."""
    if ConfigManager.save_config(req.model_dump()):
        return {"status": "success", "message": "Settings applied successfully"}
    raise HTTPException(status_code=500, detail="Failed to save settings")

class SummaryRequest(BaseModel):
    filename: str
    custom_title: Optional[str] = None

class BlogGenerationRequest(BaseModel):
    filename: str

class UpdateTitleRequest(BaseModel): # [New] 제목 수정 요청용 모델
    title: str

class ClipRequest(BaseModel):
    filename: str       # 대상 파일명
    start_time: float   # 시작 시간 (초)
    end_time: float     # 종료 시간 (초)
    title: Optional[str] = "Untitled Clip" # [New] 사용자가 지정한 클립 제목

class ShortsGenerateRequest(BaseModel):
    filename: str  # 원본 영상 파일명
    focus_topic: Optional[str] = None # [New] 사용자가 원하는 주제

class PremiereExportRequest(BaseModel): # [Add] 프리미어 내보내기 요청 모델
    video_filename: str
    clip_id: str
    custom_video_filename: Optional[str] = None # [New] 사용자가 프리미어에서 연결할 실제 영상 파일명
    max_chars: Optional[int] = 10 # [New] 자막 한 줄당 최대 글자 수 (기본값 10)
    max_lines: Optional[int] = 2  # [New] 자막 최대 줄 수 (기본값 2)

# --- [Helper: Progress Wrapper] ---
class TaskProgressWrapper:
    """
    [New] 하위 모듈(Transcriber 등)이 보고하는 0~100% 진행률을
    전체 파이프라인의 특정 구간(예: 10~70%)으로 스케일링하여 TaskManager에 전달하는 래퍼
    """
    def __init__(self, real_task_manager, task_id, start_offset, scale_factor):
        self.tm = real_task_manager
        self.task_id = task_id
        self.offset = start_offset     # 시작 % (예: 10)
        self.scale = scale_factor      # 구간 크기 비율 (예: 0.6 -> 60% 구간)

    def update_progress(self, task_id, progress, message=None):
        # task_id 인자는 무시하고 초기화 시 받은 id 사용
        # 로컬 진행률(0~100) -> 글로벌 진행률 변환
        scaled_progress = self.offset + int(progress * self.scale)
        self.tm.update_progress(self.task_id, scaled_progress, message)

    def is_cancelled(self, task_id):
        # 취소 여부는 원본 매니저에게 위임
        return self.tm.is_cancelled(self.task_id)

def cleanup_orphaned_files():
    """
    [Startup] 서버 시작 시, 불필요한 임시 파일 및 원본 영상이 없는 좀비 결과 파일들을 정리합니다.
    """
    print("--- [Cleanup] Scanning for orphaned and zombie files... ---")
    cleanup_count = 0
    
    # 1. static/temp 폴더 비우기
    temp_dir = "static/temp"
    if os.path.exists(temp_dir):
        for filename in os.listdir(temp_dir):
            if filename == ".gitkeep": continue
            file_path = os.path.join(temp_dir, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                    cleanup_count += 1
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    cleanup_count += 1
            except Exception as e:
                print(f"[Cleanup Error] Failed to delete {file_path}: {e}")

    # 2. static/videos 및 static/clips 내부의 다운로드/편집 찌꺼기 정리
    target_dirs = ["static/videos", "static/clips"]
    for d in target_dirs:
        if os.path.exists(d):
            for filename in os.listdir(d):
                if filename.endswith(".part") or filename.endswith(".ytdl") or filename.endswith(".temp") or ".tmp" in filename:
                    file_path = os.path.join(d, filename)
                    try:
                        os.remove(file_path)
                        cleanup_count += 1
                    except: pass

    # 3. [핵심 추가] 원본 영상이 없는 좀비 결과 파일 정리 (Data Integrity)
    results_dir = "static/results"
    videos_dir = "static/videos"
    if os.path.exists(results_dir):
        # (A) 먼저 모든 _summary.json 파일을 검사하여 원본 영상 존재 여부 확인
        for filename in os.listdir(results_dir):
            if filename.endswith("_summary.json"):
                summary_path = os.path.join(results_dir, filename)
                try:
                    with open(summary_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    video_source = data.get("video_source")
                    if video_source:
                        video_path = os.path.join(videos_dir, video_source)
                        # 만약 원본 영상이 없다면? -> 이 요약본과 관련된 모든 파일은 찌꺼기임
                        if not os.path.exists(video_path):
                            print(f"[Cleanup] Found zombie record: {video_source} (Source missing)")
                            base_name = os.path.splitext(video_source)[0]
                            
                            # 연관 파일 패턴 삭제 (삭제 API 로직 재활용)
                            zombie_targets = [
                                f"{base_name}_summary.json",
                                f"{base_name}_transcript.json",
                                f"{base_name}_blog_view.json",
                                f"{base_name}_blog.json", # 레거시
                                f"{base_name}_clips.json",
                                f"{base_name}.srt",
                                f"{base_name}.vtt"
                            ]
                            for t in zombie_targets:
                                t_path = os.path.join(results_dir, t)
                                if os.path.exists(t_path):
                                    os.remove(t_path)
                                    cleanup_count += 1
                except Exception:
                    continue

        # (B) _summary.json에 등록되지 않은 정체불명의 결과 파일들 추가 정리 (Heuristic)
        # 모든 JSON/SRT/VTT 파일을 돌며, 이 파일의 prefix를 가진 summary.json이 있는지 확인
        # (이 단계는 아주 보수적으로 접근)
        for filename in os.listdir(results_dir):
            if filename.endswith((".json", ".srt", ".vtt")):
                # 이미 위에서 처리된 케이스 제외
                file_path = os.path.join(results_dir, filename)
                # 파일명에서 base_name 추출 시도 (가장 긴 매칭 기준)
                parts = filename.split('_')
                if len(parts) > 1:
                    base_candidate = parts[0] # UUID_ 방식 대응
                    # 해당 base를 가지는 영상이 있는지 체크
                    found_video = False
                    for v in os.listdir(videos_dir):
                        if v.startswith(base_candidate):
                            found_video = True
                            break
                    
                    if not found_video and not filename.startswith("."):
                        # 어떤 영상과도 매칭되지 않는 고립된 파일
                        try:
                            os.remove(file_path)
                            cleanup_count += 1
                            print(f"[Cleanup] Removed orphaned result: {filename}")
                        except: pass
                    
    if cleanup_count > 0:
        print(f"--- [Cleanup] Removed {cleanup_count} orphaned/zombie files in total. ---")
    else:
        print("--- [Cleanup] System is clean. ---")

def remove_temp_files(file_paths: list):
    """
    BackgroundTasks에 의해 호출되어 전송이 끝난 임시 파일들을 삭제합니다.
    """
    for path in file_paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                print(f"[Cleanup] Deleted temp file: {path}")
            except Exception as e:
                print(f"[Cleanup Error] Failed to delete {path}: {e}")

async def run_transcription_pipeline(task_id: str, req: TranscriptionRequest):
    """
    [Background] 1단계: 영상 다운로드 및 자막 생성 (STT) 파이프라인
    - 다운로드 -> 오디오 변환 -> Whisper STT
    - Gemini 분석이나 블로그 생성은 수행하지 않음.
    """
    video_filename = req.filename 
    display_title = req.custom_title
    
    # 정리 함수 (에러 발생 시)
    def cleanup_files(filename):
        if not filename: return
        try:
            # 확장자를 제외한 순수 파일명 (예: Apple.mp4 -> Apple)
            base_name = os.path.splitext(filename)[0]
            
            # 1. 고정된 타겟 파일들 (Results 폴더 위주)
            targets = [
                os.path.join("static/videos", filename),           
                os.path.join("static/results", f"{base_name}.srt"),      
                os.path.join("static/results", f"{base_name}.vtt"),      
                os.path.join("static/results", f"{base_name}_transcript.json"), 
                os.path.join("static/results", f"{base_name}_temp.wav")
            ]
            for path in targets:
                if os.path.exists(path): os.remove(path)

            # 2. [개선] 다운로드 중 남겨진 모든 임시 파일들 정리
            video_dir = "static/videos"
            if os.path.exists(video_dir):
                for f in os.listdir(video_dir):
                    # (A) 원본 파일명과 정확히 일치하거나 
                    # (B) 파일명 중간에 코덱 정보 등이 끼어들었더라도 base_name을 포함하고 임시 확장자를 가진 경우
                    if f == filename or (base_name in f and (".part" in f or ".ytdl" in f or ".temp" in f)):
                        try:
                            os.remove(os.path.join(video_dir, f))
                            print(f"[Cleanup] Removed partial/temp file: {f}")
                        except: pass
        except Exception as e:
            print(f"[Cleanup Error] {e}")

    try:
        loop = asyncio.get_running_loop()
        
        # [Start]
        if task_manager.is_cancelled(task_id): raise TaskCancelledError()
        task_manager.update_progress(task_id, 0, "작업 시작...")
        
        # --- Phase 1: Video Preparation (0~20%) ---
        if req.url:
            task_manager.update_progress(task_id, 1, "영상 다운로드 중...")
            
            def dl_callback(percent, msg):
                # 0~100 -> 1~20% 매핑
                scaled = 1 + int(percent * 0.19)
                loop.call_soon_threadsafe(task_manager.update_progress, task_id, scaled, msg)

            result = await loop.run_in_executor(
                None, 
                partial(
                    downloader.download_from_url, 
                    req.url, 
                    progress_callback=dl_callback,
                    task_manager=task_manager,
                    task_id=task_id
                )
            )
            
            if result["status"] == "error":
                # 에러(취소 포함) 시에도 파일명이 있다면 정리 시도
                if result.get("filename"):
                    video_filename = result["filename"]
                raise Exception(result["message"])

            video_filename = result["filename"]
            
            if not display_title and result.get("meta") and result["meta"].get("title"):
                display_title = result["meta"]["title"]

        if task_manager.is_cancelled(task_id): raise TaskCancelledError()

        video_path = os.path.join("static/videos", video_filename)
        if not os.path.exists(video_path): raise FileNotFoundError(f"File not found: {video_filename}")
        
        # 제목 보정
        if not display_title:
            raw_name = video_filename
            clean_name = re.sub(r'^[0-9a-fA-F]{8}_', '', raw_name)
            display_title = os.path.splitext(clean_name)[0].replace("_", " ").strip()

        # --- Phase 2: Transcription (20~100%) ---
        task_manager.update_progress(task_id, 20, "오디오 변환 및 자막 생성 중...")
        
        # Transcriber용 진행률 래퍼 생성 (20%에서 시작, 전체의 80% 비중)
        progress_wrapper = TaskProgressWrapper(task_manager, task_id, start_offset=20, scale_factor=0.8)
        
        def transcriber_callback(local_percent, msg):
            loop.call_soon_threadsafe(progress_wrapper.update_progress, task_id, local_percent, msg)

        transcribe_result = await loop.run_in_executor(
            None,
            partial(
                transcriber.transcribe, 
                video_path, 
                progress_callback=transcriber_callback,
                task_manager=progress_wrapper,
                task_id=task_id            
            )
        )
        
        if task_manager.is_cancelled(task_id): raise TaskCancelledError()
        if transcribe_result.get("status") == "error": raise Exception("Transcription failed")
        
        # 자막 생성 완료 후 메타데이터(JSON) 초기화 (분석 전 단계임을 표시)
        base_name = os.path.splitext(video_filename)[0]
        summary_path = os.path.join("static/results", f"{base_name}_summary.json")
        
        # 아직 요약은 없지만, 제목 정보 등을 담은 기본 JSON 생성
        initial_data = {
            "video_source": video_filename,
            "video_title": display_title,
            "total_chapters": 0,
            "chapters": [],
            "status": "transcribed_only" # 상태 표시
        }
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(initial_data, f, ensure_ascii=False, indent=2)

        # --- Phase 3: Finish ---
        task_manager.complete_task(task_id, {"status": "success", "message": "자막 생성 완료", "video_title": display_title})
        print(f"[{task_id}] Transcription Completed: {video_filename}")

    except TaskCancelledError:
        print(f"[{task_id}] Task Cancelled by User.")
        cleanup_files(video_filename)
        task_manager.fail_task(task_id, "취소됨")

    except Exception as e:
        print(f"[{task_id}] Transcription Failed: {e}")
        cleanup_files(video_filename)
        task_manager.fail_task(task_id, str(e))

async def run_summary_pipeline(task_id: str, req: SummaryRequest):
    """
    [Background] 2단계: AI 챕터 분석 및 요약 파이프라인
    - 기존 자막(Transcript) 데이터를 기반으로 Gemini 분석 수행.
    """
    base_name = os.path.splitext(req.filename)[0]
    transcript_path = os.path.join("static/results", f"{base_name}_transcript.json")
    
    try:
        task_manager.update_progress(task_id, 0, "AI 분석 시작...")
        
        if not os.path.exists(transcript_path):
            raise FileNotFoundError("자막 데이터가 없습니다. 먼저 자막 생성을 진행해주세요.")
            
        with open(transcript_path, 'r', encoding='utf-8') as f:
            segments = json.load(f)

        loop = asyncio.get_running_loop()
        
        # --- Summarization (0~100%) ---
        task_manager.update_progress(task_id, 10, "Gemini가 내용을 분석하고 있습니다...")
        
        def summarizer_callback(msg):
             loop.call_soon_threadsafe(task_manager.update_progress, task_id, 50, msg)

        summary_result = await loop.run_in_executor(
            None,
            partial(
                summarizer.summarize, 
                segments, 
                req.filename, 
                custom_title=req.custom_title,
                status_callback=summarizer_callback
            )
        )
        
        if summary_result.get("error"): raise Exception(summary_result["error"])
        if task_manager.is_cancelled(task_id): raise TaskCancelledError()

        # 완료
        task_manager.complete_task(task_id, summary_result)
        print(f"[{task_id}] Summary Completed: {req.filename}")

    except TaskCancelledError:
        print(f"[{task_id}] Summary Task Cancelled.")
        task_manager.fail_task(task_id, "취소됨")
    except Exception as e:
        print(f"[{task_id}] Summary Failed: {e}")
        task_manager.fail_task(task_id, str(e))

async def run_blog_pipeline(task_id: str, req: BlogGenerationRequest):
    """
    [Background] 3단계: 블로그 포스트 생성 파이프라인 (Updated)
    - 1. Flash-Lite를 사용하여 전체 블로그 구조(임시 챕터) 설계 (1회 호출)
    - 2. 설계된 구조에 따라 Gemma를 사용하여 각 섹션 상세 작성 (N회 호출)
    - 3. 모든 시간 포맷은 HH:MM:SS 유지
    """
    base_name = os.path.splitext(req.filename)[0]
    transcript_path = os.path.join("static/results", f"{base_name}_transcript.json")
    output_path = os.path.join("static/results", f"{base_name}_blog_view.json")

    try:
        task_manager.update_progress(task_id, 0, "블로그 구조 설계 중 (Gemini 2.5 Flash-Lite)...")
        
        if not os.path.exists(transcript_path):
            raise FileNotFoundError("자막 데이터가 없습니다.")

        with open(transcript_path, 'r', encoding='utf-8') as f:
            segments = json.load(f)
        
        loop = asyncio.get_running_loop()

        # --- Step 1: Flash-Lite를 이용한 마스터 설계도 생성 ---
        blog_plan = await loop.run_in_executor(
            None,
            partial(
                summarizer.plan_blog_structure,
                segments,
                req.filename,
                status_callback=lambda msg: loop.call_soon_threadsafe(task_manager.update_progress, task_id, 10, msg)
            )
        )

        if "error" in blog_plan:
            raise Exception(blog_plan["error"])
        
        blog_title = blog_plan.get("blog_title", "Untitled Blog Post")
        temp_chapters = blog_plan.get("chapters", [])
        total_chaps = len(temp_chapters)
        
        if not temp_chapters:
            raise ValueError("생성된 블로그 구조가 없습니다.")

        # --- Step 2: 설계도에 따라 Gemma로 섹션별 상세 작성 ---
        sorted_segments = sorted(segments, key=lambda x: x['start'])
        final_chapters = []

        for i, chap in enumerate(temp_chapters):
            if task_manager.is_cancelled(task_id): raise TaskCancelledError()

            progress = 20 + int((i / total_chaps) * 80)
            task_manager.update_progress(task_id, progress, f"섹션 작성 중... ({i+1}/{total_chaps})")

            # ID 범위에 해당하는 세그먼트 추출 (ID는 1부터 시작하므로 인덱스는 -1)
            start_id = chap['start_id']
            end_id = chap['end_id']
            
            # ID 범위를 기반으로 세그먼트 슬라이싱
            chapter_segments = [
                s for s in sorted_segments 
                if start_id <= s['id'] <= end_id
            ]

            if not chapter_segments:
                continue

            # Gemma를 통한 윤문 (Refine)
            # Flash-Lite가 준 focus_point를 참고하여 작성하도록 유도할 수 있음 (현재 refiner 로직 유지)
            refined_md = await loop.run_in_executor(
                None,
                partial(
                    refiner.refine_chapter, 
                    raw_text="", 
                    chapter_title=chap['title'],
                    segments=chapter_segments
                )
            )
            
            # 시간 정보 추출 (HH:MM:SS)
            start_time = chapter_segments[0]['start']
            end_time = chapter_segments[-1]['end']

            final_chapters.append({
                "title": chap['title'],
                "content": refined_md,
                "focus_point": chap.get("focus_point", ""),
                "time": {
                    "start": start_time,
                    "end": end_time,
                    "start_formatted": summarizer._format_time(start_time),
                    "end_formatted": summarizer._format_time(end_time)
                }
            })

        # 최종 결과 데이터 구성
        result_data = {
            "video_source": req.filename,
            "blog_title": blog_title,
            "chapters": final_chapters,
            "generated_at": datetime.now().isoformat()
        }

        # 결과 저장
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)

        task_manager.complete_task(task_id, result_data)
        print(f"[{task_id}] Blog View Generation Completed: {req.filename}")

    except TaskCancelledError:
        print(f"[{task_id}] Blog Task Cancelled.")
        task_manager.fail_task(task_id, "취소됨")
    except Exception as e:
        print(f"[{task_id}] Blog Generation Failed: {e}")
        task_manager.fail_task(task_id, str(e))

async def run_clip_pipeline(task_id: str, req: ClipRequest):
    """
    [Background] 영상 클립 생성 파이프라인
    [Fix] 입력값 검증 로직 추가 (시간 범위 유효성 체크)
    """
    # 정리 대상 임시 파일 목록
    temp_files = [] 
    
    try:
        task_manager.update_progress(task_id, 0, "클립 생성 준비...")
        
        # [Validation 1] 파일 존재 여부 확인
        video_path = os.path.join("static/videos", req.filename)
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {req.filename}")

        # [Validation 2] 시간 범위 유효성 확인 (종료 시간이 시작 시간보다 앞서면 안 됨)
        if req.end_time <= req.start_time:
            raise ValueError(f"잘못된 구간 설정: 종료 시간({req.end_time})이 시작 시간({req.start_time})보다 빠르거나 같습니다.")

        # [Validation 3] 최소 길이 제한 (0.5초 미만은 오류 가능성 높음)
        if (req.end_time - req.start_time) < 0.5:
            raise ValueError("클립 길이는 최소 0.5초 이상이어야 합니다.")

        base_name = os.path.splitext(req.filename)[0]

        # 1. 비디오 자르기 (10% ~ 60%)
        # Clipper는 Main-aware 하므로 Wrapper 없이 원본 TM 전달
        task_manager.update_progress(task_id, 10, "영상 자르는 중...")
        
        cut_video_path = await clipper.cut_video(
            video_path,
            req.start_time,
            req.end_time,
            output_filename=f"clip_{base_name}_{task_id[:8]}.mp4",
            task_manager=task_manager, 
            task_id=task_id
        )
        temp_files.append(cut_video_path)
        
        # 2. 자막 자르기 (60% ~ 80%)
        if task_manager.is_cancelled(task_id): raise Exception("Task cancelled")
        task_manager.update_progress(task_id, 60, "자막 동기화 중...")
        
        srt_path = os.path.join("static/results", f"{base_name}.srt")
        vtt_path = os.path.join("static/results", f"{base_name}.vtt")
        
        sub_source_path = srt_path if os.path.exists(srt_path) else (vtt_path if os.path.exists(vtt_path) else None)
        sub_ext = ".srt" if sub_source_path == srt_path else ".vtt"

        if sub_source_path:
            loop = asyncio.get_running_loop()
            cut_sub_path = await loop.run_in_executor(
                None,
                partial(
                    clipper.cut_subtitle,
                    sub_source_path,
                    req.start_time,
                    req.end_time,
                    output_filename=f"clip_{base_name}_{task_id[:8]}{sub_ext}"
                )
            )
            if cut_sub_path: temp_files.append(cut_sub_path)

        # 3. 압축 및 저장 (80% ~ 95%)
        if task_manager.is_cancelled(task_id): raise Exception("Task cancelled")
        task_manager.update_progress(task_id, 80, "클립 패키징 중...")
        
        loop = asyncio.get_running_loop()
        clip_uuid = str(uuid.uuid4())
        safe_zip_name = f"clip_{base_name}_{clip_uuid[:8]}.zip"
        
        zip_path = await loop.run_in_executor(
            None,
            partial(
                clipper.create_zip,
                temp_files,
                zip_filename=safe_zip_name,
                destination_dir="static/clips" 
            )
        )
        
        # 4. 메타데이터 저장
        meta_filename = f"{base_name}_clips.json"
        meta_path = os.path.join("static/results", meta_filename)
        
        # [Fix] req.title이 없을 경우를 대비한 기본값 처리
        final_title = req.title if req.title and req.title.strip() else f"Clip {req.start_time}-{req.end_time}"
        
        new_clip_info = {
            "clip_id": clip_uuid,
            "title": final_title,
            "filename": safe_zip_name,
            "start_time": req.start_time,
            "end_time": req.end_time,
            "created_at": str(asyncio.get_running_loop().time()),
            "download_url": f"/static/clips/{safe_zip_name}"
        }
        
        clips_data = []
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    clips_data = json.load(f)
            except Exception: pass
        
        clips_data.insert(0, new_clip_info)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(clips_data, f, ensure_ascii=False, indent=2)

        # 완료
        task_manager.complete_task(task_id, {"message": "Saved to library", "download_url": new_clip_info["download_url"]})
        print(f"[{task_id}] Clip Saved: {zip_path}")

    except Exception as e:
        print(f"[{task_id}] Clip Pipeline Failed: {e}")
        task_manager.fail_task(task_id, str(e))
    
    finally:
        # [Cleanup] 임시 파일 정리 (성공/실패 여부와 관계없이 실행)
        for f in temp_files:
            if f and os.path.exists(f): 
                try:
                    os.remove(f)
                except Exception:
                    pass

# [Modify] run_shorts_pipeline 함수를 아래 코드로 통째로 교체하세요.
async def run_shorts_pipeline(task_id: str, req: ShortsGenerateRequest):
    """
    [Background] AI 숏츠 생성 파이프라인 (Updated)
    - 3분 이내 숏츠 생성
    - Video + SRT + VTT(New) 생성 및 관리
    - 성경 봉독 구간 보호 로직 적용
    """
    temp_files = [] 
    base_name = os.path.splitext(req.filename)[0]
    
    try:
        task_manager.update_progress(task_id, 0, "AI 숏츠 기획 시작...")
        
        # 1. 데이터 로드
        transcript_path = os.path.join("static/results", f"{base_name}_transcript.json")
        srt_path = os.path.join("static/results", f"{base_name}.srt") 
        summary_path = os.path.join("static/results", f"{base_name}_summary.json")

        if not os.path.exists(transcript_path):
            raise FileNotFoundError("분석 데이터가 없습니다.")
        
        with open(transcript_path, 'r', encoding='utf-8') as f: 
            transcripts = json.load(f)
        
        video_title = req.filename
        chapters = None
        if os.path.exists(summary_path):
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary_data = json.load(f)
                video_title = summary_data.get("video_title", req.filename)
                chapters = summary_data.get("chapters") # 챕터 메타데이터 로드

        # 2. LLM 기획 (0~30%)
        if task_manager.is_cancelled(task_id): raise Exception("Task cancelled")
        task_manager.update_progress(task_id, 10, f"AI가 '{req.focus_topic or '자동'}' 주제로 기획 중...")
        
        loop = asyncio.get_running_loop()
        candidates = await loop.run_in_executor(
            None, 
            partial(
                shorts_maker.make_shorts_candidates, 
                transcripts, 
                video_title, 
                chapters=chapters,
                focus_topic=req.focus_topic # [New] 사용자 주제 전달
            )
        )
        
        if not candidates: raise Exception("AI가 숏츠 구간을 찾지 못했습니다.")
        task_manager.update_progress(task_id, 30, f"{len(candidates)}개의 숏츠 기획안 생성 완료.")

        # 3. 렌더링 및 패키징 (30~90%)
        PHASE_START, PHASE_END = 30, 90
        slot_weight = (PHASE_END - PHASE_START) / len(candidates)
        results = []
        video_path = os.path.join("static/videos", req.filename)
        
        for idx, cand in enumerate(candidates):
            if task_manager.is_cancelled(task_id): raise Exception("Task cancelled")
            
            current_base_progress = PHASE_START + (idx * slot_weight)
            
            def ffmpeg_callback(local_percent):
                global_progress = int(current_base_progress + (local_percent / 100.0) * slot_weight)
                task_manager.update_progress(task_id, global_progress, f"숏츠 {idx+1}/{len(candidates)} 제작 중... ({local_percent}%)")

            # 파일명 정리
            safe_title = re.sub(r'[\\/*?:"<>|]', "", cand['title']).replace(" ", "_")
            video_filename = f"AI_Shorts_{idx+1}_{safe_title}.mp4"
            
            # [Update] merge_segments가 {video, subtitle, subtitle_vtt} 딕셔너리를 반환함
            merge_result = await clipper.merge_segments(
                video_path,
                cand['segments'],
                output_filename=video_filename, # 임시 폴더에 생성됨
                sub_input_path=srt_path,        # 원본 자막 전달
                progress_callback=ffmpeg_callback,
                task_manager=task_manager,
                task_id=task_id
            )
            
            generated_video = merge_result['video']
            generated_sub = merge_result['subtitle']
            generated_vtt = merge_result['subtitle_vtt'] # [New] VTT 경로
            
            if generated_video and os.path.exists(generated_video):
                # 1) MP4 이동 -> static/clips
                final_video_path = os.path.join("static/clips", video_filename)
                shutil.move(generated_video, final_video_path)
                
                # 2) SRT 이동
                final_sub_path = None
                if generated_sub and os.path.exists(generated_sub):
                    sub_filename = video_filename.replace(".mp4", ".srt")
                    final_sub_path = os.path.join("static/clips", sub_filename)
                    shutil.move(generated_sub, final_sub_path)
                    
                # 3) [New] VTT 이동 (웹 플레이어용)
                final_vtt_filename = None
                if generated_vtt and os.path.exists(generated_vtt):
                    vtt_filename = video_filename.replace(".mp4", ".vtt")
                    final_vtt_path = os.path.join("static/clips", vtt_filename)
                    shutil.move(generated_vtt, final_vtt_path)
                    final_vtt_filename = vtt_filename

                # 4) ZIP 압축 (다운로드용: MP4 + SRT)
                zip_filename = video_filename.replace(".mp4", ".zip")
                files_to_zip = [final_video_path]
                if final_sub_path: files_to_zip.append(final_sub_path)
                
                # ZIP 생성
                zip_path = await loop.run_in_executor(
                    None,
                    partial(clipper.create_zip, files_to_zip, zip_filename, "static/clips")
                )

                # 메타데이터 생성
                results.append({
                    "clip_id": str(uuid.uuid4()),
                    "title": cand['title'],
                    "reason": cand['reason'],
                    "filename_video": video_filename,
                    "filename_zip": zip_filename,
                    "filename_vtt": final_vtt_filename, # [New] VTT 파일명 저장
                    "duration": cand['total_duration'],
                    "segments": cand['segments'],
                    "created_at": datetime.now().isoformat(),
                    "download_url": f"/static/clips/{zip_filename}",
                    "preview_url": f"/static/clips/{video_filename}"
                })
            else:
                print(f"[Warning] Failed to render shorts candidate {idx+1}")

        # 4. 메타데이터 저장
        task_manager.update_progress(task_id, 90, "메타데이터 저장 중...")
        if not results: raise Exception("숏츠 생성 실패")

        meta_path = os.path.join("static/results", f"{base_name}_clips.json")
        existing_data = []
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f: existing_data = json.load(f)
            except: pass
            
        for res in reversed(results):
            res["is_ai_generated"] = True
            existing_data.insert(0, res)
            
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)

        task_manager.complete_task(task_id, {"count": len(results), "message": "완료"})
        print(f"[{task_id}] AI Shorts Completed: {len(results)}")

    except Exception as e:
        print(f"[{task_id}] Shorts Pipeline Failed: {e}")
        task_manager.fail_task(task_id, str(e))
    finally:
        for f in temp_files:
            if f and os.path.exists(f): 
                try: os.remove(f)
                except: pass

async def worker():
    print("--- [Worker] Analysis Worker Started ---")
    while True:
        task_id, req = await job_queue.get()
        try:
            if task_manager.is_cancelled(task_id):
                print(f"[{task_id}] Task cancelled before start.")
                task_manager.fail_task(task_id, "대기 중 취소됨")
            else:
                # [Resource Control] 세마포어를 획득한 후 작업 수행
                async with resource_semaphore:
                    if isinstance(req, TranscriptionRequest):
                        await run_transcription_pipeline(task_id, req)
                    elif isinstance(req, SummaryRequest):
                        await run_summary_pipeline(task_id, req)
                    elif isinstance(req, BlogGenerationRequest):
                        await run_blog_pipeline(task_id, req)
                    elif isinstance(req, ClipRequest):
                        await run_clip_pipeline(task_id, req)
                    elif isinstance(req, ShortsGenerateRequest):
                        await run_shorts_pipeline(task_id, req)
                    
        except Exception as e:
            print(f"[Worker Error] {e}")
        finally:
            job_queue.task_done()


# --- [API Endpoints] ---

@app.get("/")
async def read_root():
    """메인 페이지 서빙"""
    index_path = "templates/index.html"
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Please create templates/index.html"}

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """로컬 파일 업로드 (비동기 스트림 처리)"""
    print(f"--- [Upload Request] Filename: {file.filename}, Content-Type: {file.content_type} ---")
    try:
        # [Security] 파일명 화이트리스트 검증
        SecurityManager.validate_filename(file.filename)
    except HTTPException as e:
        print(f"--- [Upload Rejected] Reason: {e.detail} ---")
        raise e
    
    # [수정] downloader.save_uploaded_file이 async로 변경되었으므로 await 추가
    result = await downloader.save_uploaded_file(file, file.filename)
    if result["status"] == "error":
        print(f"--- [Upload Error] {result['message']} ---")
        raise HTTPException(status_code=500, detail=result["message"])
    return result

@app.post("/api/transcribe")
async def start_transcription(req: TranscriptionRequest):
    """
    [1단계] 영상 다운로드 및 자막 생성 요청
    """
    # [Security] 파일명 검증 (유튜브 URL이 아닐 경우에만)
    if not req.url and req.filename:
        SecurityManager.validate_filename(req.filename)

    task_id = str(uuid.uuid4())
    target_name = req.url if req.url else req.filename
    
    # 1. TaskManager 등록 (상태: queued)
    task_manager.add_task(task_id, target_name, task_type="transcription")
    
    # 2. Queue에 작업 추가
    await job_queue.put((task_id, req))
    
    return {
        "task_id": task_id, 
        "message": f"Transcription queued. Position: {job_queue.qsize()}"
    }

@app.post("/api/analyze")
async def start_analysis(req: SummaryRequest):
    """
    [2단계] AI 챕터 분석 및 요약 요청
    """
    task_id = str(uuid.uuid4())
    
    # Task Manager 등록
    task_manager.add_task(task_id, req.filename, task_type="analysis")
    
    # Queue에 작업 추가
    await job_queue.put((task_id, req))
    
    return {"task_id": task_id, "message": "Analysis queued"}

@app.post("/api/blog/generate")
async def generate_blog(req: BlogGenerationRequest):
    """
    [3단계] 블로그 포스트 생성 요청
    """
    task_id = str(uuid.uuid4())
    
    # Task Manager 등록
    task_manager.add_task(task_id, req.filename, task_type="blog_generation")
    
    # Queue에 작업 추가
    await job_queue.put((task_id, req))
    
    return {"task_id": task_id, "message": "Blog generation queued"}

@app.get("/api/tasks")
async def get_active_tasks():
    """현재 실행 중인 작업 목록 조회 (Polling)"""
    return task_manager.get_active_tasks()

@app.delete("/api/history/{filename}")
async def delete_history(filename: str):
    """
    지정된 파일과 관련된 모든 데이터(영상, 분석 JSON, 자막, 클립 미디어)를 삭제합니다.
    """
    # [Security] 파일명 검증
    SecurityManager.validate_filename(filename)
    
    try:
        base_name = os.path.splitext(filename)[0]
        
        # 1. static/results 폴더 내의 분석 데이터들 삭제
        results_dir = "static/results"
        result_targets = [
            f"{base_name}_summary.json",
            f"{base_name}_transcript.json",
            f"{base_name}_blog_view.json", # [추가] 블로그 데이터
            f"{base_name}_clips.json",     # [추가] 클립 메타데이터
            f"{base_name}.srt",
            f"{base_name}.vtt"
        ]
        
        deleted_count = 0
        for target in result_targets:
            path = os.path.join(results_dir, target)
            if os.path.exists(path):
                os.remove(path)
                deleted_count += 1

        # 2. static/videos 폴더 내의 원본 영상 및 임시 파일 (.part 등) 삭제
        video_dir = "static/videos"
        if os.path.exists(video_dir):
            for f in os.listdir(video_dir):
                # 원본 파일명과 일치하거나, 확장자 제외 파일명(base_name)을 포함한 임시 파일인 경우
                if f == filename or (base_name in f and (".part" in f or ".ytdl" in f or ".temp" in f)):
                    try:
                        os.remove(os.path.join(video_dir, f))
                        deleted_count += 1
                    except: pass

        # 3. [추가] static/clips 폴더 내의 파생된 모든 클립 미디어 삭제
        # 원본 영상이 사라지면 파생된 클립들도 더 이상 유효하지 않으므로 함께 정리합니다.
        clip_dir = "static/clips"
        if os.path.exists(clip_dir):
            for f in os.listdir(clip_dir):
                # 클립 파일명 규칙: clip_{base_name}_...mp4 또는 AI_Shorts_{base_name}_...
                # 혹은 단순히 파일명에 원본 영상의 base_name이 포함된 경우
                if base_name in f:
                    try:
                        os.remove(os.path.join(clip_dir, f))
                        deleted_count += 1
                    except: pass
                
        return {"status": "success", "message": f"Deleted {deleted_count} files related to {filename}"}
        
    except Exception as e:
        print(f"[Delete History Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/history/{filename}")
async def update_history_title(filename: str, req: UpdateTitleRequest):
    """
    [New] 이미 분석된 영상의 제목(메타데이터)만 수정합니다.
    """
    # [Security] 파일명 검증
    SecurityManager.validate_filename(filename)

    base_name = os.path.splitext(filename)[0]
    json_path = f"static/results/{base_name}_summary.json"
    
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="Analysis result not found")
        
    try:
        # JSON 파일 읽기 -> 수정 -> 쓰기
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['video_title'] = req.title
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        return {"status": "success", "title": req.title}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update title: {str(e)}")

@app.get("/api/history")
async def get_history():
    """분석 완료된 목록 조회"""
    history = []
    results_dir = "static/results"
    videos_dir = "static/videos"

    if not os.path.exists(results_dir):
        return history

    for filename in os.listdir(results_dir):
        if filename.endswith("_summary.json"):
            json_path = os.path.join(results_dir, filename)
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                video_source = data.get("video_source")
                if not video_source: continue

                video_full_path = os.path.join(videos_dir, video_source)
                if not os.path.exists(video_full_path): continue
                
                base_name = os.path.splitext(video_source)[0]
                transcript_filename = f"{base_name}_transcript.json"
                has_transcript = os.path.exists(os.path.join(results_dir, transcript_filename))
                
                # [New] VTT 파일 존재 여부 확인
                vtt_filename = f"{base_name}.vtt"
                has_vtt = os.path.exists(os.path.join(results_dir, vtt_filename))

                # [New] 제목 결정 로직: 저장된 video_title > 첫 챕터 제목 > 파일명
                display_title = data.get("video_title")
                if not display_title:
                    display_title = data.get("chapters", [{}])[0].get("title", video_source)

                history.append({
                    "filename": video_source,
                    "title": display_title,
                    "total_chapters": data.get("total_chapters", 0),
                    "timestamp": os.path.getmtime(json_path),
                    "result_data": {
                        "video_filename": video_source,
                        "video_title": display_title,    # [New] 상세 데이터에도 제목 포함
                        "total_chapters": data.get("total_chapters", 0), # [Fix] 누락된 필드 추가
                        "chapters": data.get("chapters"),
                        "transcripts": [],
                        "has_transcript_file": has_transcript,
                        "transcript_json_filename": transcript_filename,
                        "vtt_filename": vtt_filename if has_vtt else None # [New] VTT 파일명 전달
                    }
                })
            except Exception:
                continue
    
    history.sort(key=lambda x: x['timestamp'], reverse=True)
    return history

@app.post("/api/export/clip")
async def export_clip(req: ClipRequest):
    """
    [Async] 클립 내보내기 요청
    - [Modify] BackgroundTasks 대신 job_queue를 사용하여 순차 처리 보장
    """
    task_id = str(uuid.uuid4())
    
    # 작업 등록 (task_type="clip_export" 명시)
    task_manager.add_task(task_id, req.filename, task_type="clip_export")
    
    # [수정] 큐에 작업 추가 (Worker가 세마포어를 잡고 실행함)
    await job_queue.put((task_id, req))
    
    return {"task_id": task_id, "message": "Clip generation queued"}

@app.post("/api/shorts/auto-generate")
async def auto_generate_shorts(req: ShortsGenerateRequest, background_tasks: BackgroundTasks):
    """
    [Async] AI 숏츠 자동 생성 요청
    """
    # 파일 존재 확인
    video_path = os.path.join("static/videos", req.filename)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    task_id = str(uuid.uuid4())
    
    # Task Manager 등록 (type="shorts_generation")
    task_manager.add_task(task_id, req.filename, task_type="shorts_generation")
    
    # Queue에 작업 추가
    await job_queue.put((task_id, req))
    
    return {"task_id": task_id, "message": "AI Shorts generation queued"}

@app.get("/api/clips/{video_filename}")
async def get_clips_library(video_filename: str):
    """
    특정 원본 영상에 연결된 클립 목록을 조회합니다.
    """
    base_name = os.path.splitext(video_filename)[0]
    meta_path = os.path.join("static/results", f"{base_name}_clips.json")
    
    if not os.path.exists(meta_path):
        return [] # 클립이 없으면 빈 리스트 반환
        
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"[Error] Failed to load clips json: {e}")
        return []

# [Modify] delete_clip 함수를 아래 코드로 통째로 교체하세요.
@app.delete("/api/clips/{video_filename}/{clip_id}")
async def delete_clip(video_filename: str, clip_id: str):
    """
    [Fixed] 클립 삭제: Zip, MP4, SRT, VTT(New) 파일을 모두 찾아 삭제합니다.
    """
    try:
        base_name = os.path.splitext(video_filename)[0]
        meta_path = os.path.join("static/results", f"{base_name}_clips.json")
        
        if not os.path.exists(meta_path):
            raise HTTPException(status_code=404, detail="Clips metadata not found")
            
        with open(meta_path, 'r', encoding='utf-8') as f:
            clips = json.load(f)
            
        target_clip = next((c for c in clips if c.get("clip_id") == clip_id), None)
        
        if not target_clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        
        # 1. 삭제할 파일명 리스트업
        files_to_delete = []
        if target_clip.get("filename"): files_to_delete.append(target_clip["filename"]) # Legacy
        if target_clip.get("filename_video"): files_to_delete.append(target_clip["filename_video"])
        if target_clip.get("filename_zip"): files_to_delete.append(target_clip["filename_zip"])
        if target_clip.get("filename_vtt"): files_to_delete.append(target_clip["filename_vtt"]) # [New] VTT 추가
        
        # 레거시 데이터 SRT 파일명 유추 (vtt 필드가 없는 경우 대비)
        if target_clip.get("filename_video"):
            srt_name = target_clip["filename_video"].replace(".mp4", ".srt")
            files_to_delete.append(srt_name)
            # VTT도 유추해서 시도
            vtt_name = target_clip["filename_video"].replace(".mp4", ".vtt")
            files_to_delete.append(vtt_name)

        clip_dir = "static/clips"
        deleted_count = 0
        
        # 2. 파일 삭제 로직
        if os.path.exists(clip_dir):
            for fname in files_to_delete:
                if not fname: continue

                try:
                    # (A) 직접 경로 삭제 시도
                    path = os.path.join(clip_dir, fname)
                    if os.path.exists(path):
                        os.remove(path)
                        deleted_count += 1
                        continue 

                    # (B) 자소 분리(NFC) 문제 대응
                    target_nfc = unicodedata.normalize('NFC', fname)
                    for f in os.listdir(clip_dir):
                        if unicodedata.normalize('NFC', f) == target_nfc:
                            full_path = os.path.join(clip_dir, f)
                            os.remove(full_path)
                            deleted_count += 1
                            break 
                except Exception as e:
                    print(f"[Warning] Failed to delete file {fname}: {e}")

        # 3. 메타데이터에서 제거 및 저장
        clips = [c for c in clips if c.get("clip_id") != clip_id]
        
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(clips, f, ensure_ascii=False, indent=2)
            
        return {"status": "success", "message": f"Clip deleted ({deleted_count} files removed)"}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"[Delete Clip Error] {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.get("/api/download/temp/{filename}")
async def download_temp_file(filename: str, background_tasks: BackgroundTasks):
    """
    생성된 임시 파일(Zip)을 다운로드하고, 전송 후 삭제합니다.
    """
    file_path = os.path.join("static/temp", filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found or expired")
        
    # 파일 전송 후 삭제 예약
    background_tasks.add_task(remove_temp_files, [file_path])
    
    return FileResponse(
        file_path, 
        media_type='application/zip', 
        filename=filename
    )

@app.get("/api/stream/video/{filename}")
async def stream_video(filename: str, request: Request, range: str = Header(None)):
    """
    [Safari/Mobile 호환] 비디오 스트리밍 전용 엔드포인트
    브라우저의 Range Header를 해석하여, 파일의 특정 바이트 청크(Chunk)만 전송합니다.
    이를 통해 HTTP 206 Partial Content 응답을 구현합니다.
    """
    video_path = os.path.join("static/videos", filename)
    
    if not os.path.exists(video_path):
        # 만약 원본 폴더에 없으면 숏츠 폴더(clips)도 확인 (호환성)
        video_path = os.path.join("static/clips", filename)
        if not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="Video not found")

    file_size = os.path.getsize(video_path)
    
    # Range 헤더 파싱 (예: "bytes=0-")
    # Safari는 이 처리가 없으면 영상을 절대 재생하지 않습니다.
    byte_start = 0
    byte_end = file_size - 1
    
    if range:
        try:
            # "bytes=0-1024" 형식을 파싱
            range_key, range_value = range.strip().split("=")
            if range_key == "bytes":
                range_parts = range_value.split("-")
                byte_start = int(range_parts[0])
                if len(range_parts) > 1 and range_parts[1]:
                    byte_end = int(range_parts[1])
        except Exception:
            # 파싱 실패 시 전체 파일 전송 모드로 fallback
            pass

    # 청크 길이 계산 ($L = E - S + 1$)
    chunk_length = byte_end - byte_start + 1
    
    # [개선] 쿼리 파라미터로 다운로드 모드 확인
    is_download_request = request.query_params.get("download") == "true"

    # 파일 열기 및 제너레이터 생성
    def iterfile():
        with open(video_path, "rb") as f:
            f.seek(byte_start)
            # 한 번에 너무 많은 데이터를 읽지 않도록 64KB 단위로 전송
            remaining = chunk_length
            while remaining > 0:
                chunk_size = min(64 * 1024, remaining)
                data = f.read(chunk_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    # 헤더 설정
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_length),
        "Content-Type": "video/mp4",
    }

    # Range 요청이 실제 있었을 때만 Content-Range 헤더를 추가하고 206 상태 코드를 사용
    # 단, 다운로드 요청 시에는 전체 파일을 안정적으로 받기 위해 200 OK로 처리하는 것이 크롬 호환성에 좋습니다.
    if range and not is_download_request:
        headers["Content-Range"] = f"bytes {byte_start}-{byte_end}/{file_size}"
        status_code = 206
    else:
        status_code = 200

    # 다운로드 요청 시 Content-Disposition 헤더 추가
    if is_download_request:
        from urllib.parse import quote
        # 파일명 정제 (사용자가 지정한 제목이 있다면 그것을 사용하도록 app.js에서 처리하겠지만, 
        # 서버에서도 기본적인 안전장치를 마련합니다.)
        safe_filename = quote(filename)
        headers["Content-Disposition"] = f'attachment; filename="{safe_filename}"; filename*=UTF-8\'\'{safe_filename}'

    return StreamingResponse(
        iterfile(),
        status_code=status_code,
        headers=headers,
        media_type="video/mp4"
    )

@app.post("/api/export/premiere")
async def export_premiere_xml(req: PremiereExportRequest, background_tasks: BackgroundTasks):
    """
    [Sync] 특정 숏츠(Clip)의 컷 정보를 프리미어 프로용 XML 파일로 변환하여 다운로드합니다.
    - AI 쇼츠인 경우: XML + SRT 자막을 ZIP으로 패키징하여 제공
    - 일반 클립인 경우: 기존과 동일하게 XML 단일 파일 제공
    """
    try:
        # 1. 메타데이터(clips.json)에서 해당 클립 정보 조회
        base_name = os.path.splitext(req.video_filename)[0]
        meta_path = os.path.join("static/results", f"{base_name}_clips.json")
        
        if not os.path.exists(meta_path):
            raise HTTPException(status_code=404, detail="Clips metadata not found")
            
        with open(meta_path, 'r', encoding='utf-8') as f:
            clips_data = json.load(f)
            
        target_clip = next((c for c in clips_data if c.get("clip_id") == req.clip_id or c.get("shorts_id") == req.clip_id), None)
        
        if not target_clip:
            raise HTTPException(status_code=404, detail="Clip not found")

        # [New] 원본 영상 제목(video_title) 조회하여 XML 자동 매칭 성능 향상
        summary_path = os.path.join("static/results", f"{base_name}_summary.json")
        video_display_title = None
        if os.path.exists(summary_path):
            try:
                with open(summary_path, 'r', encoding='utf-8') as f:
                    s_data = json.load(f)
                    video_display_title = s_data.get("video_title")
            except: pass

        # 2. 세그먼트 데이터 추출
        segments = []
        if target_clip.get("segments"):
            segments = target_clip["segments"]
        elif "start_time" in target_clip and "end_time" in target_clip:
            segments = [{"start": target_clip["start_time"], "end": target_clip["end_time"]}]
        else:
            raise HTTPException(status_code=400, detail="Invalid clip data: No time segments found")

        # 3. 원본 영상 경로 확인
        video_path = os.path.join("static/videos", req.video_filename)
        if not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="Source video file not found")

        # 4. XML 생성
        safe_title = re.sub(r'[\\/*?:"<>|]', "", target_clip.get("title", "Untitled")).replace(" ", "_")
        xml_filename = f"Premiere_Seq_{safe_title}.xml"
        target_video_name_for_xml = req.custom_video_filename if req.custom_video_filename else video_display_title

        xml_path = premiere_exporter.create_xml(
            video_path=video_path,
            segments=segments,
            output_filename=xml_filename,
            video_name=target_video_name_for_xml
        )

        # 5. [Core Change] AI 쇼츠 여부에 따른 분기 처리
        is_ai_shorts = target_clip.get("is_ai_generated") is True
        
        # AI 쇼츠인 경우 자막 파일을 새로 구성하여 ZIP으로 패키징
        if is_ai_shorts:
            # 실시간 자막 재생성 로직 (사용자 지정 글자수/줄 수 반영)
            transcript_path = os.path.join("static/results", f"{base_name}_transcript.json")
            if os.path.exists(transcript_path):
                try:
                    with open(transcript_path, 'r', encoding='utf-8') as f:
                        full_transcript = json.load(f)
                    
                    # 쇼츠 타임라인에 맞는 세그먼트 추출 및 시간 이동
                    accumulated_offset = 0.0
                    shorts_transcript_data = []
                    
                    for seg in segments:
                        s_start, s_end = seg['start'], seg['end']
                        
                        # 원본 자막에서 해당 구간에 포함되는 내용 필터링
                        for ts in full_transcript:
                            if ts['end'] <= s_start or ts['start'] >= s_end:
                                continue
                            
                            # 복사본 생성 (원본 유지)
                            new_ts = json.loads(json.dumps(ts))
                            
                            # 단어 단위 데이터 처리 (있는 경우)
                            if 'words' in new_ts:
                                # 구간 내 단어만 필터링 및 시간 이동
                                filtered_words = []
                                for w in new_ts['words']:
                                    if w['start'] < s_end and w['end'] > s_start:
                                        # 시간 이동 수식: t_new = t_old - 구간시작 + 누적오프셋
                                        w['start'] = max(0, w['start'] - s_start + accumulated_offset)
                                        w['end'] = max(0, w['end'] - s_start + accumulated_offset)
                                        filtered_words.append(w)
                                new_ts['words'] = filtered_words
                            
                            # 세그먼트 시간 이동
                            new_ts['start'] = max(0, ts['start'] - s_start + accumulated_offset)
                            new_ts['end'] = min((s_end - s_start) + accumulated_offset, ts['end'] - s_start + accumulated_offset)
                            
                            shorts_transcript_data.append(new_ts)
                        
                        accumulated_offset += (s_end - s_start)

                    # SubtitleBuilder를 통한 재구성 (Reflow)
                    builder = SubtitleBuilder(data=shorts_transcript_data)
                    srt_content = builder.to_srt(
                        max_chars=req.max_chars, 
                        max_lines=req.max_lines,
                        remove_punctuation=True # 쇼츠는 가독성을 위해 문장부호 제거 기본 적용
                    )
                    
                    # 임시 SRT 파일 생성
                    custom_srt_filename = f"Custom_Subs_{uuid.uuid4().hex[:8]}.srt"
                    custom_srt_path = os.path.join("static/temp", custom_srt_filename)
                    with open(custom_srt_path, "w", encoding="utf-8") as f_srt:
                        f_srt.write(srt_content)

                    # ZIP 패키징 (XML + 커스텀 SRT)
                    zip_filename = f"Premiere_Pack_{safe_title}.zip"
                    zip_path = clipper.create_zip(
                        [xml_path, custom_srt_path], 
                        zip_filename=zip_filename, 
                        destination_dir="static/temp"
                    )
                    
                    # 전송 후 모든 임시 파일 정리 (XML, 커스텀 SRT, ZIP)
                    background_tasks.add_task(remove_temp_files, [xml_path, custom_srt_path, zip_path])
                    
                    return FileResponse(
                        zip_path,
                        media_type='application/zip',
                        filename=zip_filename
                    )
                except Exception as ex:
                    print(f"[Export Error] Failed to generate custom SRT: {ex}")
                    # 실패 시 기존 로직(보관된 SRT 사용 시도)으로 fallback 하거나 XML만 제공

        # 6. 일반 클립이거나 자막을 찾지 못한 AI 쇼츠인 경우 (기존 로직 100% 보존)
        background_tasks.add_task(remove_temp_files, [xml_path])

        return FileResponse(
            xml_path,
            media_type='application/xml',
            filename=xml_filename
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"[Export XML Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/tasks/{task_id}")
async def cancel_task(task_id: str):
    """
    [New] 진행 중이거나 대기 중인 작업을 취소합니다.
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    # 취소 요청 (TaskManager -> Flag Set)
    task_manager.request_cancel(task_id)
    
    return {"status": "success", "message": "Cancel requested"}

@app.get("/api/download/subtitle/{filename}")
async def download_custom_subtitle(
    filename: str,
    format: str = "srt",
    max_chars: Optional[int] = 20,
    max_lines: Optional[int] = 2,
    remove_punctuation: Optional[bool] = True, # [New]
    background_tasks: BackgroundTasks = None
):
    """
    [New] 저장된 단어 단위 자막 데이터(transcript.json)를 기반으로
    사용자가 원하는 포맷(SRT, VTT, TXT)과 글자 수/줄 수/문장 부호 옵션에 맞춰
    자막 파일을 즉시 생성하여 다운로드합니다.
    """
    base_name = os.path.splitext(filename)[0]
    json_path = os.path.join("static/results", f"{base_name}_transcript.json")
    
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="Transcript data not found. Please transcribe the video first.")

    try:
        # SubtitleBuilder 인스턴스 생성
        builder = SubtitleBuilder(json_path=json_path)
        
        content = ""
        ext = format.lower()
        
        if ext == "srt":
            content = builder.to_srt(max_chars=max_chars, max_lines=max_lines, remove_punctuation=remove_punctuation)
        elif ext == "vtt":
            content = builder.to_vtt(max_chars=max_chars, max_lines=max_lines, remove_punctuation=remove_punctuation)
        elif ext == "txt":
            content = builder.to_txt() # TXT는 문장부호 제거 옵션 적용 여부 고민 필요 (현재는 안 함)
        else:
            raise HTTPException(status_code=400, detail="Unsupported format. Use srt, vtt, or txt.")
            
        # 임시 파일 생성
        # 파일명에 옵션 정보 추가 (예: _30c2l_nopunc.srt)
        punc_tag = "_nopunc" if remove_punctuation else ""
        temp_filename = f"custom_{base_name}_{uuid.uuid4().hex[:8]}.{ext}"
        temp_path = os.path.join("static/temp", temp_filename)
        
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        # 전송 후 삭제 예약
        if background_tasks:
            background_tasks.add_task(remove_temp_files, [temp_path])
            
        return FileResponse(
            temp_path,
            media_type="text/plain" if ext == "txt" else "application/octet-stream",
            filename=f"{base_name}_custom{punc_tag}.{ext}"
        )

    except Exception as e:
        print(f"[Subtitle Gen Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- [System Management Endpoints] ---

@app.get("/api/system/check-update")
async def check_update():
    """
    원격 저장소와 비교하여 업데이트가 필요한지 확인합니다.
    """
    return SystemManager.check_for_updates()

@app.post("/api/system/update")
async def update_system(background_tasks: BackgroundTasks):
    """
    업데이트를 수행하고 서버를 재시작합니다.
    (가디언 프로세스 run.py에 신호를 전달)
    """
    try:
        # 가디언 프로세스에게 업데이트 신호(Exit Code 5) 전달 예약
        # 응답이 사용자에게 전달된 후 실행됩니다.
        background_tasks.add_task(SystemManager.perform_update)
        return {"status": "success", "message": "Update initiated. Server will restart shortly."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

# proxy server 용
# ---- nginx 명령어 ---
# # 1. 업로드 용량 제한 해제 (0 = 무제한, 또는 500M 등 구체적 설정 가능)
# client_max_body_size 0;

# # 2. 타임아웃 설정 (대용량 업로드/다운로드 시 끊김 방지)
# proxy_connect_timeout 600s;
# proxy_send_timeout 600s;
# proxy_read_timeout 600s;

# # 3. 비디오 스트리밍(Range Request) 및 소켓 호환성 강화
# proxy_http_version 1.1;
# proxy_set_header Upgrade $http_upgrade;
# proxy_set_header Connection "upgrade";
# proxy_set_header Host $host;

# # 4. 실제 클라이언트 IP 전달 (FastAPI 로그에 실제 IP가 찍히도록)
# proxy_set_header X-Real-IP $remote_addr;
# proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
# proxy_set_header X-Forwarded-Proto $scheme;

# # 5. [중요] 버퍼링 끄기 (스트리밍 반응 속도 향상)
# proxy_buffering off;
# --- nginx 명령어 끝 ---
if __name__ == "__main__":
    import uvicorn
    # [Modify] reload=False: Guardian(run.py)이 수명 주기를 관리하므로 중복 리로드를 비활성화합니다.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, proxy_headers=True, forwarded_allow_ips="*")