"""History management routes."""

import json
import os

from fastapi import APIRouter, HTTPException

from app.core.paths import CLIPS_DIR, RESULTS_DIR, VIDEOS_DIR
from app.schemas.requests import UpdateTitleRequest
from services.security import SecurityManager

router = APIRouter()


@router.delete("/api/history/{filename}")
async def delete_history(filename: str):
    """지정된 파일과 관련된 모든 데이터(영상/결과/클립)를 삭제합니다."""
    SecurityManager.validate_filename(filename)

    try:
        base_name = os.path.splitext(filename)[0]

        result_targets = [
            f"{base_name}_summary.json",
            f"{base_name}_transcript.json",
            f"{base_name}_blog_view.json",
            f"{base_name}_blog.json",
            f"{base_name}_clips.json",
            f"{base_name}.srt",
            f"{base_name}.vtt",
        ]

        deleted_count = 0
        for target in result_targets:
            path = os.path.join(RESULTS_DIR, target)
            if os.path.exists(path):
                os.remove(path)
                deleted_count += 1

        if os.path.exists(VIDEOS_DIR):
            for video_name in os.listdir(VIDEOS_DIR):
                has_temp_suffix = ".part" in video_name or ".ytdl" in video_name or ".temp" in video_name
                if video_name == filename or (base_name in video_name and has_temp_suffix):
                    try:
                        os.remove(os.path.join(VIDEOS_DIR, video_name))
                        deleted_count += 1
                    except Exception:
                        pass

        if os.path.exists(CLIPS_DIR):
            for clip_name in os.listdir(CLIPS_DIR):
                if base_name in clip_name:
                    try:
                        os.remove(os.path.join(CLIPS_DIR, clip_name))
                        deleted_count += 1
                    except Exception:
                        pass

        return {"status": "success", "message": f"Deleted {deleted_count} files related to {filename}"}

    except Exception as error:
        print(f"[Delete History Error] {error}")
        raise HTTPException(status_code=500, detail=str(error))


@router.patch("/api/history/{filename}")
async def update_history_title(filename: str, req: UpdateTitleRequest):
    """이미 분석된 영상의 제목(메타데이터)만 수정합니다."""
    SecurityManager.validate_filename(filename)

    base_name = os.path.splitext(filename)[0]
    json_path = os.path.join(RESULTS_DIR, f"{base_name}_summary.json")

    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="Analysis result not found")

    try:
        with open(json_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        data["video_title"] = req.title

        with open(json_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

        return {"status": "success", "title": req.title}

    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to update title: {str(error)}")


@router.get("/api/history")
async def get_history():
    """분석 완료된 목록 조회."""
    history = []

    if not os.path.exists(RESULTS_DIR):
        return history

    for filename in os.listdir(RESULTS_DIR):
        if not filename.endswith("_summary.json"):
            continue

        json_path = os.path.join(RESULTS_DIR, filename)
        try:
            with open(json_path, "r", encoding="utf-8") as file:
                data = json.load(file)

            video_source = data.get("video_source")
            if not video_source:
                continue

            video_full_path = os.path.join(VIDEOS_DIR, video_source)
            if not os.path.exists(video_full_path):
                continue

            base_name = os.path.splitext(video_source)[0]
            transcript_filename = f"{base_name}_transcript.json"
            has_transcript = os.path.exists(os.path.join(RESULTS_DIR, transcript_filename))

            vtt_filename = f"{base_name}.vtt"
            has_vtt = os.path.exists(os.path.join(RESULTS_DIR, vtt_filename))

            display_title = data.get("video_title")
            if not display_title:
                display_title = data.get("chapters", [{}])[0].get("title", video_source)

            history.append(
                {
                    "filename": video_source,
                    "title": display_title,
                    "total_chapters": data.get("total_chapters", 0),
                    "timestamp": os.path.getmtime(json_path),
                    "folder_id": data.get("folder_id"),
                    "result_data": {
                        "video_filename": video_source,
                        "video_title": display_title,
                        "content_type": data.get("content_type", "sermon"),
                        "total_chapters": data.get("total_chapters", 0),
                        "chapters": data.get("chapters"),
                        "transcripts": [],
                        "has_transcript_file": has_transcript,
                        "transcript_json_filename": transcript_filename,
                        "vtt_filename": vtt_filename if has_vtt else None,
                    },
                }
            )
        except Exception:
            continue

    history.sort(key=lambda item: item["timestamp"], reverse=True)
    return history
