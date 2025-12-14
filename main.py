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
from pydantic import BaseModel
from typing import Optional


# [Custom Services]
from services.downloader import VideoDownloader
from services.transcriber import VideoTranscriber, TaskCancelledError
from services.summarizer import VideoSummarizer
from services.task_manager import TaskManager
from services.clipper import VideoClipper
from services.refiner import TextRefiner



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


# --- [Helper: Progress Simulator] ---
async def simulate_progress(task_id: str, start: int, end: int, duration_sec: int, stop_event: asyncio.Event):
    """
    AI 작업(Whisper)이 진행되는 동안 진행률을 자연스럽게 올리는 시뮬레이터.
    실제 작업이 끝나면 stop_event가 설정되어 루프가 종료됨.
    """
    step_time = 0.5  # 0.5초마다 업데이트
    total_steps = duration_sec / step_time
    increment = (end - start) / total_steps
    
    current_progress = start
    
    while not stop_event.is_set() and current_progress < end:
        current_progress += increment
        # 99%를 넘지 않도록 제한
        if current_progress > end: current_progress = end
        
        task_manager.update_progress(task_id, int(current_progress))
        await asyncio.sleep(step_time)

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
    [Background] 영상 분석 통합 파이프라인 (Queue Consumer에 의해 실행됨)
    [수정] 각 단계별 취소 제어 파라미터 전달 및 예외 처리 강화
    """
    video_filename = req.filename 
    display_title = req.custom_title
    
    # [Helper] 정리(Cleanup) 함수
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
                os.path.join("static/results", f"{base_name}_temp.wav") # [Add] 임시 오디오 파일도 삭제 대상 포함
            ]
            print(f"[{task_id}] Cleaning up files...")
            for path in targets:
                if os.path.exists(path):
                    os.remove(path)
                    print(f" -> Deleted: {path}")
        except Exception as e:
            print(f"[{task_id}] Cleanup Warning: {e}")

    try:
        loop = asyncio.get_running_loop()
        
        # [Checkpoint 1] 시작 전 취소 확인
        if task_manager.is_cancelled(task_id):
            raise TaskCancelledError("Pending task cancelled")

        task_manager.update_progress(task_id, 0, "작업 시작...")
        
        # --- Phase 1: Video Preparation ---
        if req.url:
            if task_manager.is_cancelled(task_id): raise TaskCancelledError()

            task_manager.update_progress(task_id, 5, "영상 다운로드 중...")
            
            def dl_callback(percent, msg):
                scaled = 5 + (percent * 0.15)
                loop.call_soon_threadsafe(task_manager.update_progress, task_id, int(scaled), msg)

            # [수정] downloader에 task_manager와 task_id를 전달하여 다운로드 중단 가능하게 함
            result = await loop.run_in_executor(
                None, 
                partial(
                    downloader.download_from_url, 
                    req.url, 
                    progress_callback=dl_callback,
                    task_manager=task_manager, # [Pass]
                    task_id=task_id            # [Pass]
                )
            )
            
            if result["status"] == "error": raise Exception(result["message"])
            video_filename = result["filename"]
            
            if not display_title and result.get("meta") and result["meta"].get("title"):
                display_title = result["meta"]["title"]

        if task_manager.is_cancelled(task_id): raise TaskCancelledError()

        # 파일 경로 확정
        video_path = os.path.join("static/videos", video_filename)
        if not os.path.exists(video_path): raise FileNotFoundError(f"File not found: {video_filename}")
        
        if not display_title:
            raw_name = video_filename
            clean_name = re.sub(r'^[0-9a-fA-F]{8}_', '', raw_name)
            name_no_ext = os.path.splitext(clean_name)[0]
            display_title = name_no_ext.replace("_", " ").strip()

        # --- Phase 2: Transcription ---
        stop_event = asyncio.Event()
        
        def transcriber_progress_handler(local_percent, msg):
            global_percent = 20 + int(local_percent * 0.5)
            
            if local_percent == 35:
                loop.call_soon_threadsafe(task_manager.update_progress, task_id, global_percent, msg)
                stop_event.clear()
                # 시뮬레이터 시작
                asyncio.run_coroutine_threadsafe(
                    simulate_progress(task_id, start=global_percent, end=65, duration_sec=120, stop_event=stop_event),
                    loop
                )
            elif local_percent >= 90:
                loop.call_soon_threadsafe(stop_event.set) # 시뮬레이터 종료
                loop.call_soon_threadsafe(task_manager.update_progress, task_id, global_percent, msg)
            else:
                if local_percent < 35 or local_percent > 90:
                    loop.call_soon_threadsafe(task_manager.update_progress, task_id, global_percent, msg)

        # [수정] Transcriber는 이제 내부적으로 Multiprocessing을 사용하지만, 
        # 부모 프로세스는 여전히 Polling Loop(Blocking)를 돌므로 run_in_executor 사용이 적절함.
        transcribe_result = await loop.run_in_executor(
            None,
            partial(
                transcriber.transcribe, 
                video_path, 
                progress_callback=transcriber_progress_handler,
                task_manager=task_manager, 
                task_id=task_id            
            )
        )
        
        stop_event.set()
        
        if task_manager.is_cancelled(task_id): raise TaskCancelledError()
        if transcribe_result.get("status") == "error": raise Exception("Transcription failed")
        segments = transcribe_result["segments"]

        # --- Phase 3: Summarization ---
        task_manager.update_progress(task_id, 70, "내용 요약 및 챕터 생성 중 (LLM)...")
        
        # LLM 요약 단계는 API 호출이므로 취소 시 즉각 중단은 어렵지만, 체크포인트로 방어
        if task_manager.is_cancelled(task_id): raise TaskCancelledError()

        summary_result = await loop.run_in_executor(
            None,
            partial(summarizer.summarize, segments, video_filename, custom_title=display_title)
        )
        
        if summary_result.get("error"): raise Exception(summary_result["error"])

        if task_manager.is_cancelled(task_id): raise TaskCancelledError()

        # --- Phase 4: Refining Content ---
        task_manager.update_progress(task_id, 90, "블로그 포스팅 작성 중 (Gemma)...")
        
        chapters = summary_result.get("chapters", [])
        total_chaps = len(chapters)
        sorted_segments = sorted(segments, key=lambda x: x['start'])

        for i, chapter in enumerate(chapters):
            if task_manager.is_cancelled(task_id): raise TaskCancelledError()

            current_progress = 90 + int((i / total_chaps) * 9)
            task_manager.update_progress(task_id, current_progress, f"블로그 작성 중... ({i+1}/{total_chaps})")

            c_start = chapter['time']['start']
            c_end = chapter['time']['end']
            
            chapter_text_list = []
            for seg in sorted_segments:
                if seg['start'] >= c_start and seg['start'] < c_end:
                    chapter_text_list.append(seg['text'])
            
            raw_text_chunk = " ".join(chapter_text_list)
            
            refined_md = await loop.run_in_executor(
                None,
                partial(refiner.refine_chapter, raw_text_chunk, chapter['title'])
            )
            chapter['blog_content'] = refined_md

        # JSON 저장
        base_name = os.path.splitext(video_filename)[0]
        json_path = os.path.join("static/results", f"{base_name}_summary.json")
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary_result, f, ensure_ascii=False, indent=2)

        # --- Phase 5: Finish ---
        task_manager.complete_task(task_id, summary_result)
        print(f"[{task_id}] Analysis Completed: {video_filename}")

    except TaskCancelledError:
        print(f"[{task_id}] Task Cancelled by User.")
        if 'stop_event' in locals(): stop_event.set()
        
        # [Cleanup] 생성된 파일들 즉시 삭제
        cleanup_files(video_filename)
        
        task_manager.fail_task(task_id, "사용자에 의해 취소되었습니다.")

    except Exception as e:
        print(f"[{task_id}] Analysis Failed: {e}")
        if 'stop_event' in locals(): stop_event.set()
        
        cleanup_files(video_filename)
        
        task_manager.fail_task(task_id, str(e))

# --- [Background Pipeline] ---
async def run_clip_pipeline(task_id: str, req: ClipRequest):
    """
    [Background] 영상 클립 생성 파이프라인
    [수정] Clipper가 async로 변경됨에 따라 호출 방식 변경 (await 직접 호출)
    """
    try:
        task_manager.update_progress(task_id, 0, "클립 생성 시작...")
        
        # 1. 경로 준비
        video_path = os.path.join("static/videos", req.filename)
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {req.filename}")

        base_name = os.path.splitext(req.filename)[0]
        temp_files = [] 

        # 2. 비디오 자르기 (10% ~ 60%)
        # [수정] clipper.cut_video는 이제 async 메서드이므로 await로 직접 호출합니다.
        # 또한 task_manager와 task_id를 전달하여 FFmpeg 실행 중 취소를 지원합니다.
        task_manager.update_progress(task_id, 10, "영상 자르는 중 (취소 가능)...")
        
        cut_video_path = await clipper.cut_video(
            video_path,
            req.start_time,
            req.end_time,
            output_filename=f"clip_{base_name}_{task_id[:8]}.mp4",
            task_manager=task_manager, # [Pass]
            task_id=task_id            # [Pass]
        )
        temp_files.append(cut_video_path)
        
        # 3. 자막 자르기 (60% ~ 80%)
        if task_manager.is_cancelled(task_id): raise Exception("Task cancelled")
        task_manager.update_progress(task_id, 60, "자막 동기화 중...")
        
        # 자막 파일 탐색
        srt_path = os.path.join("static/results", f"{base_name}.srt")
        vtt_path = os.path.join("static/results", f"{base_name}.vtt")
        
        sub_source_path = None
        sub_ext = ""
        
        if os.path.exists(srt_path):
            sub_source_path = srt_path
            sub_ext = ".srt"
        elif os.path.exists(vtt_path):
            sub_source_path = vtt_path
            sub_ext = ".vtt"
            
        loop = asyncio.get_running_loop()
        if sub_source_path:
            # cut_subtitle은 순수 Python 로직이므로 run_in_executor 사용
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
            if cut_sub_path:
                temp_files.append(cut_sub_path)

        # 4. 압축 및 영구 저장 (80% ~ 95%)
        if task_manager.is_cancelled(task_id): raise Exception("Task cancelled")
        task_manager.update_progress(task_id, 80, "클립 보관함에 저장 중...")
        
        clip_uuid = str(uuid.uuid4())
        safe_zip_name = f"clip_{base_name}_{clip_uuid[:8]}.zip"
        
        # create_zip도 순수 Python
        zip_path = await loop.run_in_executor(
            None,
            partial(
                clipper.create_zip,
                temp_files,
                zip_filename=safe_zip_name,
                destination_dir="static/clips" 
            )
        )
        
        # 임시 조각 파일 삭제
        for f in temp_files:
            if os.path.exists(f): os.remove(f)

        # 5. 메타데이터(JSON) 업데이트 (95% ~ 100%)
        meta_filename = f"{base_name}_clips.json"
        meta_path = os.path.join("static/results", meta_filename)
        
        new_clip_info = {
            "clip_id": clip_uuid,
            "title": req.title,
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
            except Exception:
                clips_data = []
        
        clips_data.insert(0, new_clip_info)
        
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(clips_data, f, ensure_ascii=False, indent=2)

        # 6. 완료 처리
        task_manager.complete_task(task_id, {"message": "Saved to library"})
        print(f"[{task_id}] Clip Saved: {zip_path}")

    except Exception as e:
        print(f"[{task_id}] Clip Pipeline Failed: {e}")
        # 실패 시 임시 파일 정리
        if 'temp_files' in locals():
            for f in temp_files:
                if os.path.exists(f): os.remove(f)
        task_manager.fail_task(task_id, str(e))

async def worker():
    """
    [Background] 큐에서 작업을 하나씩 꺼내 실행하는 영구 루프 워커
    """
    print("--- [Worker] Analysis Worker Started ---")
    while True:
        # 1. 큐에서 작업 가져오기 (비어있으면 대기)
        task_id, req = await job_queue.get()
        
        try:
            # 2. 작업 실행 (이미 취소된 상태면 스킵)
            if task_manager.is_cancelled(task_id):
                print(f"[{task_id}] Task cancelled before start.")
                task_manager.fail_task(task_id, "대기 중 취소됨")
            else:
                await run_analysis_pipeline(task_id, req)
                
        except Exception as e:
            print(f"[Worker Error] {e}")
            
        finally:
            # 3. 작업 완료 통보 (중요)
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

@app.delete("/api/clips/{video_filename}/{clip_id}")
async def delete_clip(video_filename: str, clip_id: str):
    """
    특정 클립을 메타데이터 목록과 디스크에서 삭제합니다.
    [개선됨] OS별 유니코드(NFC/NFD) 차이로 인한 삭제 실패(Ghost File) 방지 로직 추가
    """
    base_name = os.path.splitext(video_filename)[0]
    meta_path = os.path.join("static/results", f"{base_name}_clips.json")
    
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail="Clips metadata not found")
        
    try:
        # 1. JSON 읽기
        with open(meta_path, 'r', encoding='utf-8') as f:
            clips = json.load(f)
            
        # 2. 삭제 대상 찾기
        target_clip = next((c for c in clips if c["clip_id"] == clip_id), None)
        if not target_clip:
            raise HTTPException(status_code=404, detail="Clip not found")
            
        # 3. 파일 삭제 (강화된 로직)
        zip_filename = target_clip.get("filename")
        if zip_filename:
            clip_dir = "static/clips"
            file_deleted = False
            
            # (A) 1차 시도: 직접 경로 확인 (대부분의 경우 여기서 해결)
            direct_path = os.path.join(clip_dir, zip_filename)
            if os.path.exists(direct_path):
                try:
                    os.remove(direct_path)
                    print(f"[Deleted] Clip file (Direct Match): {direct_path}")
                    file_deleted = True
                except Exception as e:
                    print(f"[Warning] Failed to delete file directly: {e}")

            # (B) 2차 시도: 정규화 스캔 (1차 실패 시 실행, macOS 한글 호환성 해결)
            if not file_deleted and os.path.exists(clip_dir):
                target_nfc = unicodedata.normalize('NFC', zip_filename)
                
                for fname in os.listdir(clip_dir):
                    # 디스크의 파일명과 타겟 파일명을 모두 NFC로 변환하여 비교
                    if unicodedata.normalize('NFC', fname) == target_nfc:
                        full_path = os.path.join(clip_dir, fname)
                        try:
                            os.remove(full_path)
                            print(f"[Deleted] Clip file (Normalized Match): {full_path}")
                            file_deleted = True
                            break # 찾아서 삭제했으면 루프 종료
                        except Exception as e:
                            print(f"[Error] Found file but failed to delete: {e}")
            
            if not file_deleted:
                print(f"[Info] Physical file not found or already deleted: {zip_filename}")
                
        # 4. 리스트에서 제거 및 저장 (파일 삭제 여부와 관계없이 메타데이터 동기화)
        clips = [c for c in clips if c["clip_id"] != clip_id]
        
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(clips, f, ensure_ascii=False, indent=2)
            
        return {"status": "success", "message": "Clip deleted"}
        
    except Exception as e:
        print(f"[Delete Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))

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