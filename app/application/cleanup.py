"""File cleanup routines used by lifecycle and download responses."""

import json
import os
import shutil
from typing import Iterable

from app.core.paths import CLIPS_DIR, RESULTS_DIR, TEMP_DIR, VIDEOS_DIR


def cleanup_orphaned_files() -> None:
    """서버 시작 시 불필요한 임시/좀비 파일을 정리합니다."""
    print("--- [Cleanup] Scanning for orphaned and zombie files... ---")
    cleanup_count = 0

    if os.path.exists(TEMP_DIR):
        for filename in os.listdir(TEMP_DIR):
            if filename == ".gitkeep":
                continue
            file_path = os.path.join(TEMP_DIR, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                    cleanup_count += 1
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    cleanup_count += 1
            except Exception as error:
                print(f"[Cleanup Error] Failed to delete {file_path}: {error}")

    for target_dir in [VIDEOS_DIR, CLIPS_DIR]:
        if os.path.exists(target_dir):
            for filename in os.listdir(target_dir):
                if filename.endswith(".part") or filename.endswith(".ytdl") or filename.endswith(".temp") or ".tmp" in filename:
                    file_path = os.path.join(target_dir, filename)
                    try:
                        os.remove(file_path)
                        cleanup_count += 1
                    except Exception:
                        pass

    if os.path.exists(RESULTS_DIR):
        for filename in os.listdir(RESULTS_DIR):
            if not filename.endswith("_summary.json"):
                continue

            summary_path = os.path.join(RESULTS_DIR, filename)
            try:
                with open(summary_path, "r", encoding="utf-8") as file:
                    data = json.load(file)

                video_source = data.get("video_source")
                if not video_source:
                    continue

                video_path = os.path.join(VIDEOS_DIR, video_source)
                if os.path.exists(video_path):
                    continue

                print(f"[Cleanup] Found zombie record: {video_source} (Source missing)")
                base_name = os.path.splitext(video_source)[0]
                
                clips_json_path = os.path.join(RESULTS_DIR, f"{base_name}_clips.json")
                if os.path.exists(clips_json_path):
                    try:
                        with open(clips_json_path, "r", encoding="utf-8") as file:
                            clips_data = json.load(file)
                        for clip in clips_data:
                            files_to_delete = []
                            if clip.get("filename"):
                                files_to_delete.append(clip["filename"])
                            if clip.get("filename_video"):
                                files_to_delete.append(clip["filename_video"])
                                files_to_delete.append(clip["filename_video"].replace(".mp4", ".srt"))
                                files_to_delete.append(clip["filename_video"].replace(".mp4", ".vtt"))
                            if clip.get("filename_zip"):
                                files_to_delete.append(clip["filename_zip"])
                            if clip.get("filename_vtt"):
                                files_to_delete.append(clip["filename_vtt"])
                            
                            for f_name in files_to_delete:
                                if f_name:
                                    p = os.path.join(CLIPS_DIR, f_name)
                                    if os.path.exists(p):
                                        try:
                                            os.remove(p)
                                            cleanup_count += 1
                                        except Exception:
                                            pass
                    except Exception:
                        pass

                zombie_targets = [
                    f"{base_name}_summary.json",
                    f"{base_name}_transcript.json",
                    f"{base_name}_blog_view.json",
                    f"{base_name}_blog.json",
                    f"{base_name}_clips.json",
                    f"{base_name}.srt",
                    f"{base_name}.vtt",
                ]
                for target in zombie_targets:
                    target_path = os.path.join(RESULTS_DIR, target)
                    if os.path.exists(target_path):
                        os.remove(target_path)
                        cleanup_count += 1
            except Exception:
                continue

        for filename in os.listdir(RESULTS_DIR):
            if not filename.endswith((".json", ".srt", ".vtt")):
                continue

            file_path = os.path.join(RESULTS_DIR, filename)
            parts = filename.split("_")
            if len(parts) <= 1:
                continue

            base_candidate = parts[0]
            found_video = False
            for video in os.listdir(VIDEOS_DIR):
                if video.startswith(base_candidate):
                    found_video = True
                    break

            if found_video or filename.startswith("."):
                continue

            try:
                os.remove(file_path)
                cleanup_count += 1
                print(f"[Cleanup] Removed orphaned result: {filename}")
            except Exception:
                pass

    if os.path.exists(CLIPS_DIR):
        valid_clip_files = set()
        if os.path.exists(RESULTS_DIR):
            for filename in os.listdir(RESULTS_DIR):
                if filename.endswith("_clips.json"):
                    clips_json_path = os.path.join(RESULTS_DIR, filename)
                    try:
                        with open(clips_json_path, "r", encoding="utf-8") as file:
                            clips_data = json.load(file)
                        for clip in clips_data:
                            if clip.get("filename"):
                                valid_clip_files.add(clip["filename"])
                            if clip.get("filename_video"):
                                valid_clip_files.add(clip["filename_video"])
                                valid_clip_files.add(clip["filename_video"].replace(".mp4", ".srt"))
                                valid_clip_files.add(clip["filename_video"].replace(".mp4", ".vtt"))
                            if clip.get("filename_zip"):
                                valid_clip_files.add(clip["filename_zip"])
                            if clip.get("filename_vtt"):
                                valid_clip_files.add(clip["filename_vtt"])
                    except Exception:
                        pass
        
        valid_base_names = set()
        if os.path.exists(VIDEOS_DIR):
            for video in os.listdir(VIDEOS_DIR):
                valid_base_names.add(os.path.splitext(video)[0])

        for clip_file in os.listdir(CLIPS_DIR):
            if clip_file in valid_clip_files:
                continue
            
            has_valid_base = any(base in clip_file for base in valid_base_names)
            if has_valid_base:
                continue
            
            try:
                os.remove(os.path.join(CLIPS_DIR, clip_file))
                cleanup_count += 1
                print(f"[Cleanup] Removed orphaned clip: {clip_file}")
            except Exception:
                pass

    if cleanup_count > 0:
        print(f"--- [Cleanup] Removed {cleanup_count} orphaned/zombie files in total. ---")
    else:
        print("--- [Cleanup] System is clean. ---")


def remove_temp_files(file_paths: Iterable[str]) -> None:
    """다운로드 응답 후 임시 파일을 삭제합니다."""
    for path in file_paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                print(f"[Cleanup] Deleted temp file: {path}")
            except Exception as error:
                print(f"[Cleanup Error] Failed to delete {path}: {error}")
