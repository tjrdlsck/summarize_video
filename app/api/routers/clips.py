"""Clip export and library routes."""

import json
import os
import unicodedata
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.core.container import AppContainer
from app.core.dependencies import get_container
from app.core.paths import CLIPS_DIR, RESULTS_DIR, VIDEOS_DIR
from app.schemas.requests import ClipRequest, ShortsGenerateRequest

router = APIRouter()


@router.post("/api/export/clip")
async def export_clip(req: ClipRequest, container: AppContainer = Depends(get_container)):
    """클립 내보내기 요청을 큐에 등록합니다."""
    task_id = str(uuid.uuid4())
    container.task_manager.add_task(task_id, req.filename, task_type="clip_export")
    await container.job_queue.put((task_id, req))
    return {"task_id": task_id, "message": "Clip generation queued"}


@router.post("/api/shorts/auto-generate")
async def auto_generate_shorts(
    req: ShortsGenerateRequest,
    background_tasks: BackgroundTasks,
    container: AppContainer = Depends(get_container),
):
    """AI 숏츠 자동 생성 요청."""
    del background_tasks

    video_path = os.path.join(VIDEOS_DIR, req.filename)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    task_id = str(uuid.uuid4())
    container.task_manager.add_task(task_id, req.filename, task_type="shorts_generation")
    await container.job_queue.put((task_id, req))

    return {"task_id": task_id, "message": "AI Shorts generation queued"}


@router.get("/api/clips/{video_filename}")
async def get_clips_library(video_filename: str):
    """특정 원본 영상에 연결된 클립 목록을 조회합니다."""
    base_name = os.path.splitext(video_filename)[0]
    meta_path = os.path.join(RESULTS_DIR, f"{base_name}_clips.json")

    if not os.path.exists(meta_path):
        return []

    try:
        with open(meta_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        print(f"[Error] Failed to load clips json: {error}")
        return []


@router.delete("/api/clips/{video_filename}/{clip_id}")
async def delete_clip(video_filename: str, clip_id: str):
    """클립 삭제: Zip, MP4, SRT, VTT 파일을 모두 정리합니다."""
    try:
        base_name = os.path.splitext(video_filename)[0]
        meta_path = os.path.join(RESULTS_DIR, f"{base_name}_clips.json")

        if not os.path.exists(meta_path):
            raise HTTPException(status_code=404, detail="Clips metadata not found")

        with open(meta_path, "r", encoding="utf-8") as file:
            clips = json.load(file)

        target_clip = next((clip for clip in clips if clip.get("clip_id") == clip_id), None)
        if not target_clip:
            raise HTTPException(status_code=404, detail="Clip not found")

        files_to_delete = []
        if target_clip.get("filename"):
            files_to_delete.append(target_clip["filename"])
        if target_clip.get("filename_video"):
            files_to_delete.append(target_clip["filename_video"])
        if target_clip.get("filename_zip"):
            files_to_delete.append(target_clip["filename_zip"])
        if target_clip.get("filename_vtt"):
            files_to_delete.append(target_clip["filename_vtt"])

        if target_clip.get("filename_video"):
            srt_name = target_clip["filename_video"].replace(".mp4", ".srt")
            files_to_delete.append(srt_name)
            vtt_name = target_clip["filename_video"].replace(".mp4", ".vtt")
            files_to_delete.append(vtt_name)

        deleted_count = 0
        if os.path.exists(CLIPS_DIR):
            for filename in files_to_delete:
                if not filename:
                    continue
                try:
                    path = os.path.join(CLIPS_DIR, filename)
                    if os.path.exists(path):
                        os.remove(path)
                        deleted_count += 1
                        continue

                    target_nfc = unicodedata.normalize("NFC", filename)
                    for clip_file in os.listdir(CLIPS_DIR):
                        if unicodedata.normalize("NFC", clip_file) == target_nfc:
                            os.remove(os.path.join(CLIPS_DIR, clip_file))
                            deleted_count += 1
                            break
                except Exception as error:
                    print(f"[Warning] Failed to delete file {filename}: {error}")

        clips = [clip for clip in clips if clip.get("clip_id") != clip_id]
        with open(meta_path, "w", encoding="utf-8") as file:
            json.dump(clips, file, ensure_ascii=False, indent=2)

        return {"status": "success", "message": f"Clip deleted ({deleted_count} files removed)"}

    except HTTPException as http_error:
        raise http_error
    except Exception as error:
        print(f"[Delete Clip Error] {error}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(error)}")
