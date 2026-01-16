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
from services.pipeline_manager import PipelineManager
from services.system_manager import SystemManager, ConfigManager
from services.subtitle_builder import SubtitleBuilder


# --- [App Initialization] ---
pipeline_manager = PipelineManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    앱의 수명 주기(시작과 끝)를 관리하는 함수입니다.
    """
    # [Startup]
    print("--- [Lifespan] Initializing Pipelines... ---")
    cleanup_orphaned_files()
    await pipeline_manager.start_worker()
    
    yield
    
    # [Shutdown]
    print("--- [Lifespan] Shutting down... ---")
    await pipeline_manager.stop_worker()

app = FastAPI(
    title="AI Video Analyst API", 
    version="2.1", # [Update] Version up for refactoring
    lifespan=lifespan 
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# --- [Directory & Static Files] ---
os.makedirs("static/videos", exist_ok=True)
os.makedirs("static/results", exist_ok=True)
os.makedirs("static/temp", exist_ok=True)
os.makedirs("static/clips", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

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
    
    # [수정] pipeline_manager 내부의 downloader를 사용
    result = await pipeline_manager.downloader.save_uploaded_file(file, file.filename)
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
    
    # PipelineManager를 통해 작업 큐에 추가
    await pipeline_manager.enqueue_task(task_id, req, target_name, task_type="transcription")
    
    return {
        "task_id": task_id, 
        "message": "Transcription queued."
    }

@app.post("/api/analyze")
async def start_analysis(req: SummaryRequest):
    """
    [2단계] AI 챕터 분석 및 요약 요청
    """
    task_id = str(uuid.uuid4())
    
    # PipelineManager를 통해 작업 큐에 추가
    await pipeline_manager.enqueue_task(task_id, req, req.filename, task_type="analysis")
    
    return {"task_id": task_id, "message": "Analysis queued"}

@app.post("/api/blog/generate")
async def generate_blog(req: BlogGenerationRequest):
    """
    [3단계] 블로그 포스트 생성 요청
    """
    task_id = str(uuid.uuid4())
    
    # PipelineManager를 통해 작업 큐에 추가
    await pipeline_manager.enqueue_task(task_id, req, req.filename, task_type="blog_generation")
    
    return {"task_id": task_id, "message": "Blog generation queued"}

@app.get("/api/tasks")
async def get_active_tasks():
    """현재 실행 중인 작업 목록 조회 (Polling)"""
    return pipeline_manager.task_manager.get_active_tasks()

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
            f"{base_name}_blog_view.json", 
            f"{base_name}_clips.json",     
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
                if f == filename or (base_name in f and (".part" in f or ".ytdl" in f or ".temp" in f)):
                    try:
                        os.remove(os.path.join(video_dir, f))
                        deleted_count += 1
                    except: pass

        # 3. static/clips 폴더 내의 파생된 모든 클립 미디어 삭제
        clip_dir = "static/clips"
        if os.path.exists(clip_dir):
            for f in os.listdir(clip_dir):
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
                
                vtt_filename = f"{base_name}.vtt"
                has_vtt = os.path.exists(os.path.join(results_dir, vtt_filename))

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
                        "video_title": display_title,    
                        "total_chapters": data.get("total_chapters", 0), 
                        "chapters": data.get("chapters"),
                        "transcripts": [],
                        "has_transcript_file": has_transcript,
                        "transcript_json_filename": transcript_filename,
                        "vtt_filename": vtt_filename if has_vtt else None 
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
    """
    task_id = str(uuid.uuid4())
    await pipeline_manager.enqueue_task(task_id, req, req.filename, task_type="clip_export")
    return {"task_id": task_id, "message": "Clip generation queued"}

@app.post("/api/shorts/auto-generate")
async def auto_generate_shorts(req: ShortsGenerateRequest, background_tasks: BackgroundTasks):
    """
    [Async] AI 숏츠 자동 생성 요청
    """
    video_path = os.path.join("static/videos", req.filename)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    task_id = str(uuid.uuid4())
    await pipeline_manager.enqueue_task(task_id, req, req.filename, task_type="shorts_generation")
    return {"task_id": task_id, "message": "AI Shorts generation queued"}

@app.get("/api/clips/{video_filename}")
async def get_clips_library(video_filename: str):
    """
    특정 원본 영상에 연결된 클립 목록을 조회합니다.
    """
    base_name = os.path.splitext(video_filename)[0]
    meta_path = os.path.join("static/results", f"{base_name}_clips.json")
    
    if not os.path.exists(meta_path):
        return [] 
        
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"[Error] Failed to load clips json: {e}")
        return []

@app.delete("/api/clips/{video_filename}/{clip_id}")
async def delete_clip(video_filename: str, clip_id: str):
    """
    [Fixed] 클립 삭제: Zip, MP4, SRT, VTT 파일을 모두 찾아 삭제합니다.
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
        
        files_to_delete = []
        if target_clip.get("filename"): files_to_delete.append(target_clip["filename"]) 
        if target_clip.get("filename_video"): files_to_delete.append(target_clip["filename_video"])
        if target_clip.get("filename_zip"): files_to_delete.append(target_clip["filename_zip"])
        if target_clip.get("filename_vtt"): files_to_delete.append(target_clip["filename_vtt"]) 
        
        if target_clip.get("filename_video"):
            srt_name = target_clip["filename_video"].replace(".mp4", ".srt")
            files_to_delete.append(srt_name)
            vtt_name = target_clip["filename_video"].replace(".mp4", ".vtt")
            files_to_delete.append(vtt_name)

        clip_dir = "static/clips"
        deleted_count = 0
        
        if os.path.exists(clip_dir):
            for fname in files_to_delete:
                if not fname: continue
                try:
                    path = os.path.join(clip_dir, fname)
                    if os.path.exists(path):
                        os.remove(path)
                        deleted_count += 1
                        continue 
                    target_nfc = unicodedata.normalize('NFC', fname)
                    for f in os.listdir(clip_dir):
                        if unicodedata.normalize('NFC', f) == target_nfc:
                            os.remove(os.path.join(clip_dir, f))
                            deleted_count += 1
                            break 
                except Exception as e:
                    print(f"[Warning] Failed to delete file {fname}: {e}")

        clips = [c for c in clips if c.get("clip_id") != clip_id]
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(clips, f, ensure_ascii=False, indent=2)
            
        return {"status": "success", "message": f"Clip deleted ({deleted_count} files removed)"}
        
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
    background_tasks.add_task(remove_temp_files, [file_path])
    return FileResponse(file_path, media_type='application/zip', filename=filename)

@app.get("/api/stream/video/{filename}")
async def stream_video(filename: str, request: Request, range: str = Header(None)):
    """
    비디오 스트리밍 전용 엔드포인트
    """
    video_path = os.path.join("static/videos", filename)
    if not os.path.exists(video_path):
        video_path = os.path.join("static/clips", filename)
        if not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="Video not found")

    file_size = os.path.getsize(video_path)
    byte_start = 0
    byte_end = file_size - 1
    
    if range:
        try:
            range_key, range_value = range.strip().split("=")
            if range_key == "bytes":
                range_parts = range_value.split("-")
                byte_start = int(range_parts[0])
                if len(range_parts) > 1 and range_parts[1]:
                    byte_end = int(range_parts[1])
        except Exception: pass

    chunk_length = byte_end - byte_start + 1
    is_download_request = request.query_params.get("download") == "true"

    def iterfile():
        with open(video_path, "rb") as f:
            f.seek(byte_start)
            remaining = chunk_length
            while remaining > 0:
                chunk_size = min(64 * 1024, remaining)
                data = f.read(chunk_size)
                if not data: break
                remaining -= len(data)
                yield data

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(chunk_length), "Content-Type": "video/mp4"}
    if range and not is_download_request:
        headers["Content-Range"] = f"bytes {byte_start}-{byte_end}/{file_size}"
        status_code = 206
    else:
        status_code = 200

    if is_download_request:
        from urllib.parse import quote
        safe_filename = quote(filename)
        headers["Content-Disposition"] = f'attachment; filename="{safe_filename}"; filename*=UTF-8\'\'{safe_filename}'

    return StreamingResponse(iterfile(), status_code=status_code, headers=headers, media_type="video/mp4")

@app.post("/api/export/premiere")
async def export_premiere_xml(req: PremiereExportRequest, background_tasks: BackgroundTasks):
    """
    프리미어 프로용 XML 파일 내보내기
    """
    try:
        base_name = os.path.splitext(req.video_filename)[0]
        meta_path = os.path.join("static/results", f"{base_name}_clips.json")
        if not os.path.exists(meta_path): raise HTTPException(status_code=404, detail="Clips metadata not found")
            
        with open(meta_path, 'r', encoding='utf-8') as f: clips_data = json.load(f)
        target_clip = next((c for c in clips_data if c.get("clip_id") == req.clip_id or c.get("shorts_id") == req.clip_id), None)
        if not target_clip: raise HTTPException(status_code=404, detail="Clip not found")

        summary_path = os.path.join("static/results", f"{base_name}_summary.json")
        video_display_title = None
        if os.path.exists(summary_path):
            with open(summary_path, 'r', encoding='utf-8') as f: video_display_title = json.load(f).get("video_title")

        segments = target_clip.get("segments") or [{"start": target_clip["start_time"], "end": target_clip["end_time"]}]
        video_path = os.path.join("static/videos", req.video_filename)
        if not os.path.exists(video_path): raise HTTPException(status_code=404, detail="Source video file not found")

        safe_title = re.sub(r'[\\/*?:"<>|]', "", target_clip.get("title", "Untitled")).replace(" ", "_")
        xml_filename = f"Premiere_Seq_{safe_title}.xml"
        target_video_name_for_xml = req.custom_video_filename if req.custom_video_filename else video_display_title

        xml_path = pipeline_manager.premiere_exporter.create_xml(
            video_path=video_path, segments=segments, output_filename=xml_filename, video_name=target_video_name_for_xml
        )

        if target_clip.get("is_ai_generated") is True:
            transcript_path = os.path.join("static/results", f"{base_name}_transcript.json")
            if os.path.exists(transcript_path):
                with open(transcript_path, 'r', encoding='utf-8') as f: full_transcript = json.load(f)
                shorts_transcript_data = []
                accumulated_offset = 0.0
                for seg in segments:
                    for ts in full_transcript:
                        if ts['end'] <= seg['start'] or ts['start'] >= seg['end']: continue
                        new_ts = json.loads(json.dumps(ts))
                        if 'words' in new_ts:
                            new_ts['words'] = [dict(w, start=max(0, w['start'] - seg['start'] + accumulated_offset), end=max(0, w['end'] - seg['start'] + accumulated_offset)) 
                                              for w in new_ts['words'] if w['start'] < seg['end'] and w['end'] > seg['start']]
                        new_ts['start'] = max(0, ts['start'] - seg['start'] + accumulated_offset)
                        new_ts['end'] = min((seg['end'] - seg['start']) + accumulated_offset, ts['end'] - seg['start'] + accumulated_offset)
                        shorts_transcript_data.append(new_ts)
                    accumulated_offset += (seg['end'] - seg['start'])

                srt_content = SubtitleBuilder(data=shorts_transcript_data).to_srt(max_chars=req.max_chars, max_lines=req.max_lines, remove_punctuation=True)
                custom_srt_path = os.path.join("static/temp", f"Custom_Subs_{uuid.uuid4().hex[:8]}.srt")
                with open(custom_srt_path, "w", encoding="utf-8") as f_srt: f_srt.write(srt_content)

                zip_filename = f"Premiere_Pack_{safe_title}.zip"
                zip_path = pipeline_manager.clipper.create_zip([xml_path, custom_srt_path], zip_filename, "static/temp")
                background_tasks.add_task(remove_temp_files, [xml_path, custom_srt_path, zip_path])
                return FileResponse(zip_path, media_type='application/zip', filename=zip_filename)

        background_tasks.add_task(remove_temp_files, [xml_path])
        return FileResponse(xml_path, media_type='application/xml', filename=xml_filename)
    except Exception as e:
        print(f"[Export XML Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/tasks/{task_id}")
async def cancel_task(task_id: str):
    """진행 중이거나 대기 중인 작업을 취소합니다."""
    task = pipeline_manager.task_manager.get_task(task_id)
    if not task: raise HTTPException(status_code=404, detail="Task not found")
    pipeline_manager.task_manager.request_cancel(task_id)
    return {"status": "success", "message": "Cancel requested"}

@app.get("/api/download/subtitle/{filename}")
async def download_custom_subtitle(filename: str, format: str = "srt", max_chars: Optional[int] = 20, max_lines: Optional[int] = 2, remove_punctuation: Optional[bool] = True, background_tasks: BackgroundTasks = None):
    """사용자 정의 자막 다운로드"""
    base_name = os.path.splitext(filename)[0]
    json_path = os.path.join("static/results", f"{base_name}_transcript.json")
    if not os.path.exists(json_path): raise HTTPException(status_code=404, detail="Transcript data not found.")

    try:
        builder = SubtitleBuilder(json_path=json_path)
        ext = format.lower()
        if ext == "srt": content = builder.to_srt(max_chars, max_lines, remove_punctuation)
        elif ext == "vtt": content = builder.to_vtt(max_chars, max_lines, remove_punctuation)
        elif ext == "txt": content = builder.to_txt()
        else: raise HTTPException(status_code=400, detail="Unsupported format.")
            
        temp_path = os.path.join("static/temp", f"custom_{base_name}_{uuid.uuid4().hex[:8]}.{ext}")
        with open(temp_path, "w", encoding="utf-8") as f: f.write(content)
        if background_tasks: background_tasks.add_task(remove_temp_files, [temp_path])
        return FileResponse(temp_path, media_type="text/plain" if ext == "txt" else "application/octet-stream", filename=f"{base_name}_custom{'_nopunc' if remove_punctuation else ''}.{ext}")
    except Exception as e:
        print(f"[Subtitle Gen Error] {e}"); raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/system/check-update")
async def check_update():
    return SystemManager.check_for_updates()

@app.post("/api/system/update")
async def update_system(background_tasks: BackgroundTasks):
    background_tasks.add_task(SystemManager.perform_update)
    return {"status": "success", "message": "Update initiated."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, proxy_headers=True, forwarded_allow_ips="*")