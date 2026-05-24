"""Upload and transcription queue routes."""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.container import AppContainer
from app.core.dependencies import get_container
from app.schemas.requests import TranscriptionRequest
from services.security import SecurityManager

class ChunkCompleteRequest(BaseModel):
    identifier: str
    filename: str


router = APIRouter()


@router.post("/api/upload")
async def upload_video(file: UploadFile = File(...), container: AppContainer = Depends(get_container)):
    """로컬 파일 업로드 (비동기 스트림 처리)."""
    print(f"--- [Upload Request] Filename: {file.filename}, Content-Type: {file.content_type} ---")
    try:
        SecurityManager.validate_filename(file.filename)
    except HTTPException as error:
        print(f"--- [Upload Rejected] Reason: {error.detail} ---")
        raise error

    result = await container.downloader.save_uploaded_file(file, file.filename)
    if result["status"] == "error":
        print(f"--- [Upload Error] {result['message']} ---")
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.get("/api/upload/status/{identifier}")
async def get_upload_status(identifier: str, container: AppContainer = Depends(get_container)):
    """현재 파일의 업로드된 크기를 확인 (이어올리기)"""
    size = await container.downloader.get_uploaded_size(identifier)
    return {"uploaded": size}


@router.post("/api/upload/chunk")
async def upload_chunk(
    identifier: str = Form(...),
    chunk: UploadFile = File(...),
    container: AppContainer = Depends(get_container)
):
    """청크 데이터를 수신하여 임시 파일에 추가"""
    chunk_data = await chunk.read()
    await container.downloader.append_chunk(identifier, chunk_data)
    return {"status": "success"}


@router.post("/api/upload/complete")
async def complete_upload(
    req: ChunkCompleteRequest,
    container: AppContainer = Depends(get_container)
):
    """모든 청크 수신 완료 후 임시 파일을 최종 파일로 변환"""
    try:
        SecurityManager.validate_filename(req.filename)
    except HTTPException as error:
        print(f"--- [Upload Complete Rejected] Reason: {error.detail} ---")
        raise error
    
    result = await container.downloader.finalize_upload(req.identifier, req.filename)
    if result.get("status") == "error":
        print(f"--- [Upload Complete Error] {result['message']} ---")
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/api/transcribe")
async def start_transcription(req: TranscriptionRequest, container: AppContainer = Depends(get_container)):
    """1단계: 영상 다운로드 및 자막 생성 요청."""
    if not req.url and req.filename:
        SecurityManager.validate_filename(req.filename)

    task_id = str(uuid.uuid4())
    target_name = req.url if req.url else req.filename

    container.task_manager.add_task(task_id, target_name, task_type="transcription")
    await container.job_queue.put((task_id, req))

    return {
        "task_id": task_id,
        "message": f"Transcription queued. Position: {container.job_queue.qsize()}",
    }
