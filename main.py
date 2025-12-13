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
from services.clipper import VideoClipper

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
os.makedirs("static/temp", exist_ok=True)
os.makedirs("static/clips", exist_ok=True)  # [New] 영구 클립 저장소 생성
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- [Service Instances] ---
downloader = VideoDownloader(download_dir="static/videos")
transcriber = VideoTranscriber(output_dir="static/results")
summarizer = VideoSummarizer(output_dir="static/results")
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
    [Background] 영상 분석 통합 파이프라인
    1. Download (URL일 경우) -> 2. Transcribe (Whisper) -> 3. Summarize (Gemini)
    """
    try:
        task_manager.update_progress(task_id, 0, "작업 시작...")
        
        # --- Phase 1: Video Preparation (0% ~ 20%) ---
        video_filename = req.filename
        
        if req.url:
            task_manager.update_progress(task_id, 5, "영상 다운로드 중...")
            
            # 다운로드 콜백 (sync 함수 내부에서 호출됨)
            def dl_callback(percent, msg):
                # 5% ~ 20% 사이로 매핑
                scaled = 5 + (percent * 0.15)
                task_manager.update_progress(task_id, int(scaled), msg)

            # Blocking I/O -> Executor 사용 (서버 멈춤 방지)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, 
                partial(downloader.download_from_url, req.url, progress_callback=dl_callback)
            )
            
            if result["status"] == "error":
                raise Exception(result["message"])
            
            video_filename = result["filename"]
            
        # 파일 존재 확인
        video_path = os.path.join("static/videos", video_filename)
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"File not found: {video_filename}")

        # --- Phase 2: Transcription (20% ~ 70%) ---
        task_manager.update_progress(task_id, 20, "AI가 영상을 듣는 중 (STT)...")
        
        # Whisper는 오래 걸리므로 진행률 시뮬레이션(Fake Progress) 시작
        stop_event = asyncio.Event()
        sim_task = asyncio.create_task(
            simulate_progress(task_id, start=20, end=70, duration_sec=60, stop_event=stop_event)
        )
        
        loop = asyncio.get_running_loop()
        # Transcriber 실행 (Blocking)
        transcribe_result = await loop.run_in_executor(
            None,
            partial(transcriber.transcribe, video_path)
        )
        
        # 시뮬레이션 종료
        stop_event.set()
        await sim_task
        
        if transcribe_result.get("status") == "error":
             raise Exception("Transcription failed")

        segments = transcribe_result["segments"]

        # --- Phase 3: Summarization (70% ~ 90%) ---
        task_manager.update_progress(task_id, 70, "내용 요약 및 챕터 생성 중 (LLM)...")
        
        # LLM 실행 (Blocking)
        summary_result = await loop.run_in_executor(
            None,
            partial(
                summarizer.summarize, 
                segments, 
                video_filename, 
                custom_title=req.custom_title
            )
        )
        
        if summary_result.get("error"):
            raise Exception(summary_result["error"])

        # --- Phase 4: Finish (100%) ---
        task_manager.complete_task(task_id, summary_result)
        print(f"[{task_id}] Analysis Completed: {video_filename}")

    except Exception as e:
        print(f"[{task_id}] Analysis Failed: {e}")
        task_manager.fail_task(task_id, str(e))

# --- [Background Pipeline] ---
async def run_clip_pipeline(task_id: str, req: ClipRequest):
    """
    [Background] 영상 클립 생성 및 영구 저장 파이프라인
    1. Cut Video -> 2. Cut Subtitle -> 3. Zip to 'static/clips' -> 4. Metadata Update
    """
    try:
        task_manager.update_progress(task_id, 0, "클립 생성 시작...")
        
        # 1. 경로 준비
        video_path = os.path.join("static/videos", req.filename)
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {req.filename}")

        base_name = os.path.splitext(req.filename)[0]
        temp_files = [] # 나중에 정리할 조각 파일들

        # 2. 비디오 자르기 (10% ~ 60%)
        task_manager.update_progress(task_id, 10, "영상 자르는 중 (가속 모드)...")
        loop = asyncio.get_running_loop()
        
        cut_video_path = await loop.run_in_executor(
            None,
            partial(
                clipper.cut_video,
                video_path,
                req.start_time,
                req.end_time,
                output_filename=f"clip_{base_name}_{task_id[:8]}.mp4"
            )
        )
        temp_files.append(cut_video_path)
        
        # 3. 자막 자르기 (60% ~ 80%)
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
            
        if sub_source_path:
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
        task_manager.update_progress(task_id, 80, "클립 보관함에 저장 중...")
        
        # [New] 파일명을 UUID 기반으로 안전하게 생성 (사용자 입력 제목은 메타데이터에만 저장)
        clip_uuid = str(uuid.uuid4())
        safe_zip_name = f"clip_{base_name}_{clip_uuid[:8]}.zip"
        
        # [New] destination_dir을 static/clips로 지정
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
        # 해당 영상에 대한 클립 목록 파일: {영상파일명}_clips.json
        meta_filename = f"{base_name}_clips.json"
        meta_path = os.path.join("static/results", meta_filename)
        
        new_clip_info = {
            "clip_id": clip_uuid,
            "title": req.title, # 사용자가 입력한 제목
            "filename": safe_zip_name,
            "start_time": req.start_time,
            "end_time": req.end_time,
            "created_at": str(asyncio.get_running_loop().time()), # 간단한 타임스탬프 (실제론 datetime 추천)
            "download_url": f"/static/clips/{safe_zip_name}"
        }
        
        # 기존 목록 읽기 -> 추가 -> 쓰기
        clips_data = []
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    clips_data = json.load(f)
            except Exception:
                clips_data = []
        
        clips_data.insert(0, new_clip_info) # 최신순 추가
        
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(clips_data, f, ensure_ascii=False, indent=2)

        # 6. 완료 처리
        # 결과에 다운로드 URL을 포함하지 않고(새로고침으로 목록 확인), 성공 메시지만 전달
        task_manager.complete_task(task_id, {"message": "Saved to library"})
        print(f"[{task_id}] Clip Saved: {zip_path}")

    except Exception as e:
        print(f"[{task_id}] Clip Pipeline Failed: {e}")
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
    
    # 작업 등록 (task_type="analysis" 명시)
    target_name = req.url if req.url else req.filename
    task_manager.add_task(task_id, target_name, task_type="analysis")
    
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
            
        # 3. 파일 삭제
        zip_filename = target_clip.get("filename")
        if zip_filename:
            zip_path = os.path.join("static/clips", zip_filename)
            if os.path.exists(zip_path):
                os.remove(zip_path)
                print(f"[Deleted] Clip file: {zip_path}")
                
        # 4. 리스트에서 제거 및 저장
        clips = [c for c in clips if c["clip_id"] != clip_id]
        
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(clips, f, ensure_ascii=False, indent=2)
            
        return {"status": "success", "message": "Clip deleted"}
        
    except Exception as e:
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)