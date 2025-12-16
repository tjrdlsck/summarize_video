import os
import uuid
import asyncio
import json
import shutil
import unicodedata  # [Add] 유니코드 정규화를 위해 추가
import re
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
from services.downloader import VideoDownloader
from services.transcriber import VideoTranscriber, TaskCancelledError
from services.summarizer import VideoSummarizer
from services.task_manager import TaskManager
from services.clipper import VideoClipper
from services.refiner import TextRefiner
from services.shorts_maker import ShortsMaker


# --- [Lifespan Manager] ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    앱의 수명 주기(시작과 끝)를 관리하는 함수입니다.
    기존 @app.on_event("startup")을 대체합니다.
    """
    # [Startup] 앱 시작 시 실행
    print("--- [Lifespan] Starting Background Worker... ---")
    worker_task = asyncio.create_task(worker())
    
    yield  # 앱이 실행되는 동안 여기서 대기 (Control Yield)
    
    # [Shutdown] 앱 종료 시 실행 (필요시 자원 해제 로직 추가)
    print("--- [Lifespan] Shutting down... ---")
    # 예: worker_task.cancel() 등을 여기서 수행할 수 있음

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

# --- [Pydantic Models] ---
class AnalyzeRequest(BaseModel):
    url: Optional[str] = None      # 유튜브 URL
    filename: Optional[str] = None # 업로드된 파일명
    custom_title: Optional[str] = None # [New] 사용자가 지정한 영상 제목

class UpdateTitleRequest(BaseModel): # [New] 제목 수정 요청용 모델
    title: str

class ClipRequest(BaseModel):
    filename: str       # 대상 파일명
    start_time: float   # 시작 시간 (초)
    end_time: float     # 종료 시간 (초)
    title: Optional[str] = "Untitled Clip" # [New] 사용자가 지정한 클립 제목

class ShortsGenerateRequest(BaseModel):
    filename: str  # 원본 영상 파일명

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

async def run_analysis_pipeline(task_id: str, req: AnalyzeRequest):
    """
    [Background] 영상 분석 통합 파이프라인 (Real-time Progress 적용)
    구간 계획:
    - 0~10%: 다운로드
    - 10~70%: 오디오 변환 및 자막 생성 (Transcriber)
    - 70~90%: 요약 및 챕터 생성 (Summarizer)
    - 90~100%: 블로그 글 윤문 (Refiner)
    """
    video_filename = req.filename 
    display_title = req.custom_title
    
    # 정리 함수
    def cleanup_files(filename):
        if not filename: return
        try:
            base_name = os.path.splitext(filename)[0]
            targets = [
                os.path.join("static/videos", filename),           
                os.path.join("static/results", f"{base_name}.srt"),      
                os.path.join("static/results", f"{base_name}.vtt"),      
                os.path.join("static/results", f"{base_name}_transcript.json"), 
                os.path.join("static/results", f"{base_name}_summary.json"),
                os.path.join("static/results", f"{base_name}_temp.wav")
            ]
            for path in targets:
                if os.path.exists(path): os.remove(path)
        except Exception:
            pass

    try:
        loop = asyncio.get_running_loop()
        
        # [Start]
        if task_manager.is_cancelled(task_id): raise TaskCancelledError()
        task_manager.update_progress(task_id, 0, "작업 시작...")
        
        # --- Phase 1: Video Preparation (0~10%) ---
        if req.url:
            task_manager.update_progress(task_id, 1, "영상 다운로드 중...")
            
            def dl_callback(percent, msg):
                # 0~100 -> 1~10% 매핑
                scaled = 1 + int(percent * 0.09)
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
            
            if result["status"] == "error": raise Exception(result["message"])
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

        # --- Phase 2: Transcription (10~70%) ---
        # [Change] 시뮬레이션 제거, 리얼타임 진행률 적용
        task_manager.update_progress(task_id, 10, "오디오 변환 준비 중...")
        
        # Transcriber용 진행률 래퍼 생성 (10%에서 시작, 전체의 60% 비중)
        # Transcriber 내부의 0~100% 진행률이 -> 전체 파이프라인의 10~70%로 자동 변환됨
        progress_wrapper = TaskProgressWrapper(task_manager, task_id, start_offset=10, scale_factor=0.6)
        
        # 콜백 함수 정의 (Wrapper 사용)
        def transcriber_callback(local_percent, msg):
            loop.call_soon_threadsafe(progress_wrapper.update_progress, task_id, local_percent, msg)

        # Transcriber 실행 (wrapper를 task_manager로 전달하여 내부의 direct call도 커버)
        transcribe_result = await loop.run_in_executor(
            None,
            partial(
                transcriber.transcribe, 
                video_path, 
                progress_callback=transcriber_callback,
                task_manager=progress_wrapper, # [Injection] Wrapper 주입
                task_id=task_id            
            )
        )
        
        if task_manager.is_cancelled(task_id): raise TaskCancelledError()
        if transcribe_result.get("status") == "error": raise Exception("Transcription failed")
        segments = transcribe_result["segments"]

        # --- Phase 3: Summarization (70~90%) ---
        task_manager.update_progress(task_id, 70, "내용 구조화 및 요약 중 (LLM)...")
        
        # LLM Callback
        def summarizer_callback(msg):
             loop.call_soon_threadsafe(task_manager.update_progress, task_id, 75, msg)

        summary_result = await loop.run_in_executor(
            None,
            partial(
                summarizer.summarize, 
                segments, 
                video_filename, 
                custom_title=display_title,
                status_callback=summarizer_callback
            )
        )
        
        if summary_result.get("error"): raise Exception(summary_result["error"])
        if task_manager.is_cancelled(task_id): raise TaskCancelledError()

        # --- Phase 4: Refining Content (90~100%) ---
        task_manager.update_progress(task_id, 90, "블로그 포스팅 작성 중...")
        
        chapters = summary_result.get("chapters", [])
        total_chaps = len(chapters)
        sorted_segments = sorted(segments, key=lambda x: x['start'])

        for i, chapter in enumerate(chapters):
            if task_manager.is_cancelled(task_id): raise TaskCancelledError()

            # 90~99% 구간 매핑
            current_progress = 90 + int((i / total_chaps) * 9)
            task_manager.update_progress(task_id, current_progress, f"블로그 작성 중... ({i+1}/{total_chaps})")

            # 챕터에 해당하는 텍스트 추출
            c_start = chapter['time']['start']
            c_end = chapter['time']['end']
            chapter_text_list = [
                s['text'] for s in sorted_segments 
                if s['start'] >= c_start and s['start'] < c_end
            ]
            raw_text_chunk = " ".join(chapter_text_list)
            
            # 윤문 (Refine)
            refined_md = await loop.run_in_executor(
                None,
                partial(refiner.refine_chapter, raw_text_chunk, chapter['title'])
            )
            chapter['blog_content'] = refined_md

        # 결과 저장
        base_name = os.path.splitext(video_filename)[0]
        json_path = os.path.join("static/results", f"{base_name}_summary.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary_result, f, ensure_ascii=False, indent=2)

        # --- Phase 5: Finish ---
        task_manager.complete_task(task_id, summary_result)
        print(f"[{task_id}] Analysis Completed: {video_filename}")

    except TaskCancelledError:
        print(f"[{task_id}] Task Cancelled by User.")
        cleanup_files(video_filename)
        task_manager.fail_task(task_id, "취소됨")

    except Exception as e:
        print(f"[{task_id}] Analysis Failed: {e}")
        cleanup_files(video_filename)
        task_manager.fail_task(task_id, str(e))

# --- [Background Pipeline] ---
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
        
        with open(transcript_path, 'r', encoding='utf-8') as f: transcripts = json.load(f)
        
        video_title = req.filename
        if os.path.exists(summary_path):
            with open(summary_path, 'r', encoding='utf-8') as f:
                video_title = json.load(f).get("video_title", req.filename)

        # 2. LLM 기획 (0~30%)
        if task_manager.is_cancelled(task_id): raise Exception("Task cancelled")
        task_manager.update_progress(task_id, 10, "AI가 하이라이트 구간 선별 중...")
        
        loop = asyncio.get_running_loop()
        candidates = await loop.run_in_executor(
            None, 
            partial(shorts_maker.make_shorts_candidates, transcripts, video_title)
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
                if isinstance(req, AnalyzeRequest):
                    await run_analysis_pipeline(task_id, req)
                elif isinstance(req, ClipRequest):
                    await run_clip_pipeline(task_id, req)
                # [Add] 숏츠 생성 요청 처리 추가
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
    """로컬 파일 업로드 (동기 처리, 빠름)"""
    result = downloader.save_uploaded_file(file.file, file.filename)
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["message"])
    return result

# [Modify] 여기가 중요합니다. Queue를 사용하는 버전만 남깁니다.
@app.post("/api/process")
async def start_processing(req: AnalyzeRequest):
    """
    통합 분석 요청 (Queue 방식)
    """
    task_id = str(uuid.uuid4())
    target_name = req.url if req.url else req.filename
    
    # 1. TaskManager 등록 (상태: queued)
    task_manager.add_task(task_id, target_name, task_type="analysis")
    
    # 2. Queue에 작업 추가 (Worker가 가져감)
    await job_queue.put((task_id, req))
    
    # 3. 사용자에게는 "등록됨(Pending)" 응답
    return {
        "task_id": task_id, 
        "message": f"Task queued. Position: {job_queue.qsize()}"
    }

@app.get("/api/tasks")
async def get_active_tasks():
    """현재 실행 중인 작업 목록 조회 (Polling)"""
    return task_manager.get_active_tasks()

@app.delete("/api/history/{filename}")
async def delete_history(filename: str):
    """
    지정된 파일과 관련된 모든 데이터(영상, JSON, SRT, VTT)를 삭제합니다.
    """
    try:
        base_name = os.path.splitext(filename)[0]
        
        # 삭제할 파일 목록
        targets = [
            f"static/videos/{filename}",
            f"static/results/{base_name}_summary.json",
            f"static/results/{base_name}_transcript.json",
            f"static/results/{base_name}.srt",
            f"static/results/{base_name}.vtt"  # [New] VTT 파일도 삭제
        ]
        
        deleted_count = 0
        for path in targets:
            if os.path.exists(path):
                os.remove(path)
                deleted_count += 1
                
        return {"status": "success", "message": f"Deleted {deleted_count} files related to {filename}"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/history/{filename}")
async def update_history_title(filename: str, req: UpdateTitleRequest):
    """
    [New] 이미 분석된 영상의 제목(메타데이터)만 수정합니다.
    """
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
async def export_clip(req: ClipRequest, background_tasks: BackgroundTasks):
    """
    [Async] 클립 내보내기 요청
    파일을 직접 반환하지 않고, 백그라운드 작업 ID를 반환합니다.
    """
    task_id = str(uuid.uuid4())
    
    # 작업 등록 (task_type="clip_export" 명시)
    task_manager.add_task(task_id, req.filename, task_type="clip_export")
    
    # 백그라운드 파이프라인 시작
    background_tasks.add_task(run_clip_pipeline, task_id, req)
    
    return {"task_id": task_id, "message": "Clip generation started"}

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
        "Content-Range": f"bytes {byte_start}-{byte_end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_length),
        "Content-Type": "video/mp4",
    }

    return StreamingResponse(
        iterfile(),
        status_code=206, # [중요] 206 Partial Content
        headers=headers,
        media_type="video/mp4"
    )

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)