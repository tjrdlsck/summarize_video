import os
import uuid
import asyncio
import json
import shutil
from functools import partial
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

# [Custom Services]
from services.downloader import VideoDownloader
from services.transcriber import VideoTranscriber
from services.summarizer import VideoSummarizer
from services.task_manager import TaskManager

# --- [App Initialization] ---
app = FastAPI(title="AI Video Analyst API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- [Directory & Static Files] ---
os.makedirs("static/videos", exist_ok=True)
os.makedirs("static/results", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- [Service Instances] ---
downloader = VideoDownloader(download_dir="static/videos")
transcriber = VideoTranscriber(output_dir="static/results")
summarizer = VideoSummarizer(output_dir="static/results")
task_manager = TaskManager()  # [New] Task Manager Instance

# --- [Pydantic Models] ---
class AnalyzeRequest(BaseModel):
    url: Optional[str] = None      # 유튜브 URL
    filename: Optional[str] = None # 업로드된 파일명
    custom_title: Optional[str] = None # [New] 사용자가 지정한 영상 제목

class UpdateTitleRequest(BaseModel): # [New] 제목 수정 요청용 모델
    title: str

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

# --- [Background Pipeline] ---
async def run_analysis_pipeline(task_id: str, req: AnalyzeRequest):
    """
    [Integration Pipeline]
    1. Download (Video URL provided) -> 0~30%
    2. Transcribe (Whisper) -> 30~90% (Generates SRT & VTT)
    3. Summarize (Gemini) -> 90~99% (Saves Metadata)
    4. Finish -> 100%
    """
    try:
        task_manager.update_progress(task_id, 0, "작업 시작 대기 중...")
        
        # --- Phase 1: File Preparation (0~30%) ---
        video_filename = req.filename
        video_path = ""

        # A. URL 다운로드 모드
        if req.url:
            def download_progress_hook(percent, msg):
                scaled_progress = int(percent * 0.3)
                task_manager.update_progress(task_id, scaled_progress, msg)

            loop = asyncio.get_running_loop()
            dl_result = await loop.run_in_executor(
                None, 
                partial(downloader.download_from_url, req.url, download_progress_hook)
            )
            
            if dl_result["status"] == "error":
                raise Exception(dl_result["message"])
            
            video_filename = dl_result["filename"]
            # 만약 사용자가 제목을 안 정했으면, 유튜브 제목을 기본 제목으로 사용 (옵션)
            if not req.custom_title and "meta" in dl_result:
                req.custom_title = dl_result["meta"].get("title")
        
        # B. 로컬 파일 모드
        else:
            task_manager.update_progress(task_id, 10, "업로드된 파일 확인 완료")
        
        # 경로 확인
        video_path = os.path.join("static/videos", video_filename)
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # --- Phase 2: Transcribe (30~90%) ---
        task_manager.update_progress(task_id, 30, "AI 음성 분석 준비 중...")
        
        def status_updater(msg):
            current_task = task_manager.get_task(task_id)
            if current_task:
                task_manager.update_progress(task_id, current_task['progress'], msg)

        stop_event = asyncio.Event()
        simulator_task = asyncio.create_task(
            simulate_progress(task_id, start=30, end=90, duration_sec=60, stop_event=stop_event)
        )

        loop = asyncio.get_running_loop()
        trans_result = await loop.run_in_executor(
            None,
            partial(transcriber.transcribe, video_path, status_updater)
        )
        
        stop_event.set()
        await simulator_task

        # --- Phase 3: Summarize (90~99%) ---
        task_manager.update_progress(task_id, 90, "내용 요약 및 챕터 생성 중...")
        
        # [New] custom_title 전달
        summary_result = await loop.run_in_executor(
            None,
            partial(
                summarizer.summarize, 
                trans_result["segments"], 
                video_filename, 
                req.custom_title,  # 전달
                status_updater
            )
        )
        
        if "error" in summary_result:
            raise Exception(summary_result["error"])

        # --- Phase 4: Finish (100%) ---
        final_result = {
            "video_filename": video_filename,
            "transcripts": trans_result["segments"],
            "chapters": summary_result["chapters"],
            "srt_path": trans_result["srt_path"],
            "vtt_path": trans_result.get("vtt_path"), # [New] VTT 경로 추가
            "summary_json_path": os.path.basename(summary_result.get("json_path", "") or "")
        }
        
        task_manager.complete_task(task_id, final_result)
        print(f"[{task_id}] Pipeline Completed Successfully.")

    except Exception as e:
        print(f"[{task_id}] Pipeline Failed: {e}")
        task_manager.fail_task(task_id, str(e))

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

@app.post("/api/process")
async def start_processing(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    통합 분석 요청 (URL 모드 or 파일 모드)
    """
    task_id = str(uuid.uuid4())
    
    # 작업 등록
    target_name = req.url if req.url else req.filename
    task_manager.add_task(task_id, target_name)
    
    # 백그라운드 실행
    background_tasks.add_task(run_analysis_pipeline, task_id, req)

    return {"task_id": task_id, "message": "Background analysis started"}

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)