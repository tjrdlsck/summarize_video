"""Media download, streaming, and subtitle generation routes."""

import os
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.application.cleanup import remove_temp_files
from app.core.paths import CLIPS_DIR, RESULTS_DIR, TEMP_DIR, VIDEOS_DIR
from services.subtitle_builder import SubtitleBuilder

router = APIRouter()


@router.get("/api/download/temp/{filename}")
async def download_temp_file(filename: str, background_tasks: BackgroundTasks):
    """생성된 임시 파일(Zip)을 다운로드하고, 전송 후 삭제합니다."""
    file_path = os.path.join(TEMP_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found or expired")

    background_tasks.add_task(remove_temp_files, [file_path])
    return FileResponse(file_path, media_type="application/zip", filename=filename)


@router.get("/api/stream/video/{filename}")
async def stream_video(filename: str, request: Request, range: str = Header(None)):
    """Range 요청을 처리하는 비디오 스트리밍 엔드포인트."""
    video_path = os.path.join(VIDEOS_DIR, filename)

    if not os.path.exists(video_path):
        video_path = os.path.join(CLIPS_DIR, filename)
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
        except Exception:
            pass

    chunk_length = byte_end - byte_start + 1
    is_download_request = request.query_params.get("download") == "true"

    def iterfile():
        with open(video_path, "rb") as file:
            file.seek(byte_start)
            remaining = chunk_length
            while remaining > 0:
                chunk_size = min(64 * 1024, remaining)
                data = file.read(chunk_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_length),
        "Content-Type": "video/mp4",
    }

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


@router.get("/api/download/subtitle/{filename}")
async def download_custom_subtitle(
    filename: str,
    format: str = "srt",
    max_chars: Optional[int] = 20,
    max_lines: Optional[int] = 2,
    remove_punctuation: Optional[bool] = True,
    background_tasks: BackgroundTasks = None,
):
    """transcript.json 기반으로 사용자 옵션 자막 파일을 동적 생성합니다."""
    base_name = os.path.splitext(filename)[0]
    json_path = os.path.join(RESULTS_DIR, f"{base_name}_transcript.json")

    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="Transcript data not found. Please transcribe the video first.")

    try:
        builder = SubtitleBuilder(json_path=json_path)

        ext = format.lower()
        if ext == "srt":
            content = builder.to_srt(max_chars=max_chars, max_lines=max_lines, remove_punctuation=remove_punctuation)
        elif ext == "vtt":
            content = builder.to_vtt(max_chars=max_chars, max_lines=max_lines, remove_punctuation=remove_punctuation)
        elif ext == "txt":
            content = builder.to_txt()
        else:
            raise HTTPException(status_code=400, detail="Unsupported format. Use srt, vtt, or txt.")

        punc_tag = "_nopunc" if remove_punctuation else ""
        temp_filename = f"custom_{base_name}_{uuid.uuid4().hex[:8]}.{ext}"
        temp_path = os.path.join(TEMP_DIR, temp_filename)

        with open(temp_path, "w", encoding="utf-8") as file:
            file.write(content)

        if background_tasks:
            background_tasks.add_task(remove_temp_files, [temp_path])

        return FileResponse(
            temp_path,
            media_type="text/plain" if ext == "txt" else "application/octet-stream",
            filename=f"{base_name}_custom{punc_tag}.{ext}",
        )

    except Exception as error:
        print(f"[Subtitle Gen Error] {error}")
        raise HTTPException(status_code=500, detail=str(error))
