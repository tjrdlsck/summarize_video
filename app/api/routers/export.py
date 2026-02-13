"""Premiere export route."""

import json
import os
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse

from app.application.cleanup import remove_temp_files
from app.core.container import AppContainer
from app.core.dependencies import get_container
from app.core.paths import RESULTS_DIR, TEMP_DIR, VIDEOS_DIR
from app.schemas.requests import PremiereExportRequest
from services.subtitle_builder import SubtitleBuilder

router = APIRouter()


@router.post("/api/export/premiere")
async def export_premiere_xml(
    req: PremiereExportRequest,
    background_tasks: BackgroundTasks,
    container: AppContainer = Depends(get_container),
):
    """클립 메타데이터를 프리미어 XML(또는 ZIP)로 내보냅니다."""
    try:
        clipper = container.clipper
        premiere_exporter = container.premiere_exporter

        base_name = os.path.splitext(req.video_filename)[0]
        meta_path = os.path.join(RESULTS_DIR, f"{base_name}_clips.json")

        if not os.path.exists(meta_path):
            raise HTTPException(status_code=404, detail="Clips metadata not found")

        with open(meta_path, "r", encoding="utf-8") as file:
            clips_data = json.load(file)

        target_clip = next(
            (clip for clip in clips_data if clip.get("clip_id") == req.clip_id or clip.get("shorts_id") == req.clip_id),
            None,
        )
        if not target_clip:
            raise HTTPException(status_code=404, detail="Clip not found")

        summary_path = os.path.join(RESULTS_DIR, f"{base_name}_summary.json")
        video_display_title = None
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as file:
                    summary_data = json.load(file)
                    video_display_title = summary_data.get("video_title")
            except Exception:
                pass

        if target_clip.get("segments"):
            segments = target_clip["segments"]
        elif "start_time" in target_clip and "end_time" in target_clip:
            segments = [{"start": target_clip["start_time"], "end": target_clip["end_time"]}]
        else:
            raise HTTPException(status_code=400, detail="Invalid clip data: No time segments found")

        video_path = os.path.join(VIDEOS_DIR, req.video_filename)
        if not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="Source video file not found")

        safe_title = re.sub(r"[\\/*?:\"<>|]", "", target_clip.get("title", "Untitled")).replace(" ", "_")
        xml_filename = f"Premiere_Seq_{safe_title}.xml"
        target_video_name_for_xml = req.custom_video_filename if req.custom_video_filename else video_display_title

        xml_path = premiere_exporter.create_xml(
            video_path=video_path,
            segments=segments,
            output_filename=xml_filename,
            video_name=target_video_name_for_xml,
        )

        is_ai_shorts = target_clip.get("is_ai_generated") is True

        if is_ai_shorts:
            transcript_path = os.path.join(RESULTS_DIR, f"{base_name}_transcript.json")
            if os.path.exists(transcript_path):
                try:
                    with open(transcript_path, "r", encoding="utf-8") as file:
                        full_transcript = json.load(file)

                    accumulated_offset = 0.0
                    shorts_transcript_data = []

                    for segment in segments:
                        seg_start, seg_end = segment["start"], segment["end"]

                        for transcript_segment in full_transcript:
                            if transcript_segment["end"] <= seg_start or transcript_segment["start"] >= seg_end:
                                continue

                            new_segment = json.loads(json.dumps(transcript_segment))

                            if "words" in new_segment:
                                filtered_words = []
                                for word in new_segment["words"]:
                                    if word["start"] < seg_end and word["end"] > seg_start:
                                        word["start"] = max(0, word["start"] - seg_start + accumulated_offset)
                                        word["end"] = max(0, word["end"] - seg_start + accumulated_offset)
                                        filtered_words.append(word)
                                new_segment["words"] = filtered_words

                            new_segment["start"] = max(0, transcript_segment["start"] - seg_start + accumulated_offset)
                            new_segment["end"] = min(
                                (seg_end - seg_start) + accumulated_offset,
                                transcript_segment["end"] - seg_start + accumulated_offset,
                            )

                            shorts_transcript_data.append(new_segment)

                        accumulated_offset += seg_end - seg_start

                    builder = SubtitleBuilder(data=shorts_transcript_data)
                    srt_content = builder.to_srt(
                        max_chars=req.max_chars,
                        max_lines=req.max_lines,
                        remove_punctuation=True,
                    )

                    custom_srt_filename = f"Custom_Subs_{uuid.uuid4().hex[:8]}.srt"
                    custom_srt_path = os.path.join(TEMP_DIR, custom_srt_filename)
                    with open(custom_srt_path, "w", encoding="utf-8") as subtitle_file:
                        subtitle_file.write(srt_content)

                    zip_filename = f"Premiere_Pack_{safe_title}.zip"
                    zip_path = clipper.create_zip(
                        [xml_path, custom_srt_path],
                        zip_filename=zip_filename,
                        destination_dir=TEMP_DIR,
                    )

                    background_tasks.add_task(remove_temp_files, [xml_path, custom_srt_path, zip_path])
                    return FileResponse(zip_path, media_type="application/zip", filename=zip_filename)
                except Exception as error:
                    print(f"[Export Error] Failed to generate custom SRT: {error}")

        background_tasks.add_task(remove_temp_files, [xml_path])
        return FileResponse(xml_path, media_type="application/xml", filename=xml_filename)

    except HTTPException as http_error:
        raise http_error
    except Exception as error:
        print(f"[Export XML Error] {error}")
        raise HTTPException(status_code=500, detail=str(error))
