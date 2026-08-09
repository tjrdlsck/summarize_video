"""Background pipeline runner implementations."""

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime
from functools import partial

from services.content_profiles import get_content_profile
from services.system_manager import ConfigManager, SystemManager
from services.transcriber import TaskCancelledError

from app.application.progress import TaskProgressWrapper
from app.core.container import AppContainer
from app.core.paths import CLIPS_DIR, RESULTS_DIR, TEMP_DIR, VIDEOS_DIR
from app.schemas.requests import (
    BlogGenerationRequest,
    ClipRequest,
    ShortsGenerateRequest,
    SummaryRequest,
    TranscriptionRequest,
)


class PipelineRunner:
    """Runs long-running processing jobs in background worker context."""

    def __init__(self, container: AppContainer) -> None:
        self.container = container

    def _resolve_video_path(self, req_filename: str, summary_data: dict = None) -> str:
        """보관 중인 동영상 파일 경로를 스마트하게 탐색하고 없으면 FileNotFoundError를 발생시킵니다."""
        candidates = [os.path.join(VIDEOS_DIR, req_filename)]
        if summary_data and summary_data.get("video_source"):
            candidates.insert(0, os.path.join(VIDEOS_DIR, summary_data["video_source"]))

        for path in candidates:
            if os.path.exists(path):
                return path

        if os.path.exists(VIDEOS_DIR):
            clean_name = re.sub(r"^[0-9a-fA-F]{8}_", "", req_filename)
            for fname in os.listdir(VIDEOS_DIR):
                if fname == req_filename or clean_name in fname:
                    return os.path.join(VIDEOS_DIR, fname)

        raise FileNotFoundError(f"원본 영상 파일('{req_filename}')을 찾을 수 없습니다. 대시보드에서 영상을 다시 업로드해 주세요.")

    async def run_transcription_pipeline(self, task_id: str, req: TranscriptionRequest) -> None:
        """영상 다운로드 및 자막 생성(STT) 파이프라인."""
        task_manager = self.container.task_manager
        downloader = self.container.downloader
        transcriber = self.container.transcriber
        profile = get_content_profile(req.content_type)

        video_filename = req.filename
        display_title = req.custom_title

        def cleanup_files(filename: str | None) -> None:
            if not filename:
                return
            try:
                base_name = os.path.splitext(filename)[0]

                targets = [
                    os.path.join(VIDEOS_DIR, filename),
                    os.path.join(RESULTS_DIR, f"{base_name}.srt"),
                    os.path.join(RESULTS_DIR, f"{base_name}.vtt"),
                    os.path.join(RESULTS_DIR, f"{base_name}_transcript.json"),
                    os.path.join(RESULTS_DIR, f"{base_name}_temp.wav"),
                ]
                for path in targets:
                    if os.path.exists(path):
                        os.remove(path)

                if os.path.exists(VIDEOS_DIR):
                    for filename_in_dir in os.listdir(VIDEOS_DIR):
                        is_target = filename_in_dir == filename
                        has_partial = ".part" in filename_in_dir or ".ytdl" in filename_in_dir or ".temp" in filename_in_dir
                        if is_target or (base_name in filename_in_dir and has_partial):
                            try:
                                os.remove(os.path.join(VIDEOS_DIR, filename_in_dir))
                                print(f"[Cleanup] Removed partial/temp file: {filename_in_dir}")
                            except Exception:
                                pass
            except Exception as error:
                print(f"[Cleanup Error] {error}")

        try:
            loop = asyncio.get_running_loop()

            if task_manager.is_cancelled(task_id):
                raise TaskCancelledError()
            task_manager.update_progress(task_id, 0, "작업 시작...")

            if req.url:
                task_manager.update_progress(task_id, 1, "영상 다운로드 중...")

                def dl_callback(percent: int, msg: str) -> None:
                    scaled = 1 + int(percent * 0.19)
                    loop.call_soon_threadsafe(task_manager.update_progress, task_id, scaled, msg)

                result = await loop.run_in_executor(
                    None,
                    partial(
                        downloader.download_from_url,
                        req.url,
                        progress_callback=dl_callback,
                        task_manager=task_manager,
                        task_id=task_id,
                    ),
                )

                if result["status"] == "error":
                    if result.get("filename"):
                        video_filename = result["filename"]
                    raise Exception(result["message"])
                if result["status"] == "restart_required":
                    fail_message = result.get("message", "yt-dlp 업데이트 후 재시작이 필요합니다.")
                    task_manager.fail_task(task_id, fail_message)
                    SystemManager.request_restart_after_failures(
                        reason=fail_message,
                        delay_seconds=60,
                    )
                    print(f"[{task_id}] {fail_message}")
                    return

                video_filename = result["filename"]

                if not display_title and result.get("meta") and result["meta"].get("title"):
                    display_title = result["meta"]["title"]

            if task_manager.is_cancelled(task_id):
                raise TaskCancelledError()

            video_path = os.path.join(VIDEOS_DIR, str(video_filename))
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"File not found: {video_filename}")

            if not display_title:
                clean_name = re.sub(r"^[0-9a-fA-F]{8}_", "", str(video_filename))
                display_title = os.path.splitext(clean_name)[0].replace("_", " ").strip()

            run_transcription = getattr(req, "run_transcription", True)
            run_summary = getattr(req, "run_summary", False)
            run_blog = getattr(req, "run_blog", False)
            if run_blog:
                run_summary = True

            trans_scale = 1.0
            if run_transcription:
                if run_blog:
                    trans_scale = 0.6
                elif run_summary:
                    trans_scale = 0.7
            else:
                trans_scale = 0.1 # Very fast if no transcription

            if run_transcription:
                task_manager.update_progress(task_id, 20, "오디오 변환 및 자막 생성 중...")
                progress_wrapper = TaskProgressWrapper(task_manager, task_id, start_offset=20, scale_factor=0.8 * trans_scale)

                def transcriber_callback(local_percent: int, msg: str) -> None:
                    loop.call_soon_threadsafe(progress_wrapper.update_progress, task_id, local_percent, msg)

                transcribe_result = await loop.run_in_executor(
                    None,
                    partial(
                        transcriber.transcribe,
                        video_path,
                        progress_callback=transcriber_callback,
                        task_manager=progress_wrapper,
                        task_id=task_id,
                        content_type=profile.content_type,
                        whisper_kwargs={
                            "language": getattr(req, "whisper_lang", "ko"),
                            "initial_prompt": getattr(req, "whisper_prompt", None),
                            "condition_on_previous_text": getattr(req, "whisper_condition", False),
                            "temperature": getattr(req, "whisper_temp", 0.0),
                            "vad": getattr(req, "whisper_vad", True),
                            "gpu_tier": ConfigManager.load_config().get("whisper_gpu_tier", "low")
                        }
                    ),
                )

                if task_manager.is_cancelled(task_id):
                    raise TaskCancelledError()
                if transcribe_result.get("status") == "error":
                    raise Exception("Transcription failed")

                base_name = os.path.splitext(str(video_filename))[0]
                summary_path = os.path.join(RESULTS_DIR, f"{base_name}_summary.json")
                initial_data = {
                    "video_source": video_filename,
                    "video_title": display_title,
                    "content_type": profile.content_type,
                    "profile_version": profile.profile_version,
                    "total_chapters": 0,
                    "chapters": [],
                    "status": "transcribed_only",
                }
                if not os.path.exists(summary_path):
                    with open(summary_path, "w", encoding="utf-8") as file:
                        json.dump(initial_data, file, ensure_ascii=False, indent=2)
            else:
                task_manager.update_progress(task_id, 20, "기존 자막 데이터 연동 완료")


            # === 체이닝 실행 ===

            if run_summary:
                task_manager.update_progress(task_id, int(100 * trans_scale), "1단계 완료. 2단계 AI 요약 분석으로 이동...")
                summary_req = SummaryRequest(
                    filename=str(video_filename),
                    custom_title=display_title,
                    content_type=req.content_type
                )
                summary_scale = 0.2 if run_blog else 0.3
                summary_offset = 60 if run_blog else 70
                summary_wrapper = TaskProgressWrapper(task_manager, task_id, start_offset=summary_offset, scale_factor=summary_scale)
                await self.run_summary_pipeline(task_id, summary_req, task_manager=summary_wrapper)

            if run_blog:
                task_manager.update_progress(task_id, 80, "2단계 완료. 3단계 블로그 초안 작성으로 이동...")
                blog_req = BlogGenerationRequest(filename=str(video_filename), content_type=req.content_type)
                blog_wrapper = TaskProgressWrapper(task_manager, task_id, start_offset=80, scale_factor=0.2)
                await self.run_blog_pipeline(task_id, blog_req, task_manager=blog_wrapper)

            task_manager.complete_task(task_id, {"status": "success", "message": "일괄 분석 완료" if run_summary else "자막 생성 완료", "video_title": display_title})
            print(f"[{task_id}] Transcription/Chaining Completed: {video_filename}")

        except TaskCancelledError:
            print(f"[{task_id}] Task Cancelled by User.")
            cleanup_files(str(video_filename) if video_filename else None)
            task_manager.request_cancel(task_id)

        except Exception as error:
            print(f"[{task_id}] Transcription Failed: {error}")
            cleanup_files(str(video_filename) if video_filename else None)
            task_manager.fail_task(task_id, str(error), exception=error)

    async def run_summary_pipeline(self, task_id: str, req: SummaryRequest, task_manager=None) -> None:
        """AI 챕터 분석 및 요약 파이프라인."""
        if task_manager is None:
            task_manager = self.container.task_manager
        summarizer = self.container.summarizer

        base_name = os.path.splitext(req.filename)[0]
        transcript_path = os.path.join(RESULTS_DIR, f"{base_name}_transcript.json")

        try:
            task_manager.update_progress(task_id, 0, "AI 분석 시작...")

            if not os.path.exists(transcript_path):
                raise FileNotFoundError("자막 데이터가 없습니다. 먼저 자막 생성을 진행해주세요.")

            with open(transcript_path, "r", encoding="utf-8") as file:
                segments = json.load(file)

            loop = asyncio.get_running_loop()
            task_manager.update_progress(task_id, 10, "Gemini가 내용을 분석하고 있습니다...")

            def summarizer_callback(msg: str) -> None:
                loop.call_soon_threadsafe(task_manager.update_progress, task_id, 50, msg)

            summary_result = await loop.run_in_executor(
                None,
                partial(
                    summarizer.summarize,
                    segments,
                    req.filename,
                    custom_title=req.custom_title,
                    status_callback=summarizer_callback,
                    content_type=req.content_type,
                ),
            )

            if summary_result.get("error"):
                raise Exception(summary_result["error"])
            if task_manager.is_cancelled(task_id):
                raise TaskCancelledError()

            task_manager.complete_task(task_id, summary_result)
            print(f"[{task_id}] Summary Completed: {req.filename}")

        except TaskCancelledError:
            print(f"[{task_id}] Summary Task Cancelled.")
            task_manager.request_cancel(task_id)
        except Exception as error:
            print(f"[{task_id}] Summary Failed: {error}")
            task_manager.fail_task(task_id, str(error), exception=error)

    async def run_blog_pipeline(self, task_id: str, req: BlogGenerationRequest, task_manager=None) -> None:
        """블로그 포스트 생성 파이프라인."""
        if task_manager is None:
            task_manager = self.container.task_manager
        summarizer = self.container.summarizer
        refiner = self.container.refiner

        base_name = os.path.splitext(req.filename)[0]
        transcript_path = os.path.join(RESULTS_DIR, f"{base_name}_transcript.json")
        output_path = os.path.join(RESULTS_DIR, f"{base_name}_blog_view.json")

        try:
            refiner_model = ConfigManager.get_model("refiner")
            task_manager.update_progress(task_id, 0, f"블로그 작성 준비 중 ({refiner_model})...")

            if not os.path.exists(transcript_path):
                raise FileNotFoundError("자막 데이터가 없습니다.")

            with open(transcript_path, "r", encoding="utf-8") as file:
                segments = json.load(file)

            loop = asyncio.get_running_loop()

            summary_path = os.path.join(RESULTS_DIR, f"{base_name}_summary.json")
            blog_title = "Untitled Blog Post"
            temp_chapters = []

            if os.path.exists(summary_path):
                with open(summary_path, "r", encoding="utf-8") as file:
                    summary_data = json.load(file)
                    blog_title = summary_data.get("blog_title") or summary_data.get("video_title") or "Untitled Blog Post"
                    raw_chaps = summary_data.get("chapters", [])
                    for chap in raw_chaps:
                        s_time = chap.get("time", {}).get("start", 0.0)
                        e_time = chap.get("time", {}).get("end", 0.0)
                        # Find start_id and end_id from segments matching timestamps
                        s_id = 1
                        e_id = len(segments)
                        for seg in segments:
                            if seg["start"] <= s_time <= seg["end"]:
                                s_id = seg["id"]
                            if seg["start"] <= e_time <= seg["end"]:
                                e_id = seg["id"]
                        temp_chapters.append({
                            "title": chap["title"],
                            "start_id": s_id,
                            "end_id": e_id,
                            "focus_point": chap.get("summary", "")
                        })

            if not temp_chapters:
                planner_model = ConfigManager.get_model("planner")
                task_manager.update_progress(task_id, 5, f"블로그 구조 설계 중 ({planner_model})...")
                blog_plan = await loop.run_in_executor(
                    None,
                    partial(
                        summarizer.plan_blog_structure,
                        segments,
                        req.filename,
                        status_callback=lambda msg: loop.call_soon_threadsafe(task_manager.update_progress, task_id, 10, msg),
                    ),
                )
                if "error" in blog_plan:
                    raise Exception(blog_plan["error"])

                blog_title = blog_plan.get("blog_title", "Untitled Blog Post")
                temp_chapters = blog_plan.get("chapters", [])

            total_chaps = len(temp_chapters)
            if not temp_chapters:
                raise ValueError("생성된 블로그 구조가 없습니다.")

            sorted_segments = sorted(segments, key=lambda item: item["start"])
            final_chapters = []

            for index, chapter in enumerate(temp_chapters):
                if task_manager.is_cancelled(task_id):
                    raise TaskCancelledError()

                progress = 20 + int((index / total_chaps) * 80)
                task_manager.update_progress(task_id, progress, f"섹션 작성 중... ({index + 1}/{total_chaps})")

                start_id = chapter["start_id"]
                end_id = chapter["end_id"]
                chapter_segments = [segment for segment in sorted_segments if start_id <= segment["id"] <= end_id]

                if not chapter_segments:
                    continue

                refined_md = await loop.run_in_executor(
                    None,
                    partial(
                        refiner.refine_chapter,
                        raw_text="",
                        chapter_title=chapter["title"],
                        segments=chapter_segments,
                        content_type=req.content_type,
                    ),
                )

                start_time = chapter_segments[0]["start"]
                end_time = chapter_segments[-1]["end"]

                final_chapters.append(
                    {
                        "title": chapter["title"],
                        "content": refined_md,
                        "focus_point": chapter.get("focus_point", ""),
                        "time": {
                            "start": start_time,
                            "end": end_time,
                            "start_formatted": summarizer._format_time(start_time),
                            "end_formatted": summarizer._format_time(end_time),
                        },
                    }
                )

            result_data = {
                "video_source": req.filename,
                "blog_title": blog_title,
                "chapters": final_chapters,
                "generated_at": datetime.now().isoformat(),
            }

            with open(output_path, "w", encoding="utf-8") as file:
                json.dump(result_data, file, ensure_ascii=False, indent=2)

            task_manager.complete_task(task_id, result_data)
            print(f"[{task_id}] Blog View Generation Completed: {req.filename}")

        except TaskCancelledError:
            print(f"[{task_id}] Blog Task Cancelled.")
            task_manager.request_cancel(task_id)
        except Exception as error:
            print(f"[{task_id}] Blog Generation Failed: {error}")
            task_manager.fail_task(task_id, str(error), exception=error)

    async def run_clip_pipeline(self, task_id: str, req: ClipRequest) -> None:
        """영상 클립 생성 파이프라인."""
        task_manager = self.container.task_manager
        clipper = self.container.clipper

        temp_files = []

        try:
            task_manager.update_progress(task_id, 0, "클립 생성 준비...")

            video_path = self._resolve_video_path(req.filename)

            if req.end_time <= req.start_time:
                raise ValueError(f"잘못된 구간 설정: 종료 시간({req.end_time})이 시작 시간({req.start_time})보다 빠르거나 같습니다.")

            if (req.end_time - req.start_time) < 0.5:
                raise ValueError("클립 길이는 최소 0.5초 이상이어야 합니다.")

            base_name = os.path.splitext(req.filename)[0]

            task_manager.update_progress(task_id, 10, "영상 자르는 중...")
            cut_video_path = await clipper.cut_video(
                video_path,
                req.start_time,
                req.end_time,
                output_filename=f"clip_{base_name}_{task_id[:8]}.mp4",
                task_manager=task_manager,
                task_id=task_id,
            )
            temp_files.append(cut_video_path)

            if task_manager.is_cancelled(task_id):
                raise Exception("Task cancelled")
            task_manager.update_progress(task_id, 60, "자막 동기화 중...")

            srt_path = os.path.join(RESULTS_DIR, f"{base_name}.srt")
            vtt_path = os.path.join(RESULTS_DIR, f"{base_name}.vtt")

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
                        output_filename=f"clip_{base_name}_{task_id[:8]}{sub_ext}",
                    ),
                )
                if cut_sub_path:
                    temp_files.append(cut_sub_path)

            if task_manager.is_cancelled(task_id):
                raise Exception("Task cancelled")
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
                    destination_dir=CLIPS_DIR,
                ),
            )

            meta_filename = f"{base_name}_clips.json"
            meta_path = os.path.join(RESULTS_DIR, meta_filename)

            final_title = req.title if req.title and req.title.strip() else f"Clip {req.start_time}-{req.end_time}"
            new_clip_info = {
                "clip_id": clip_uuid,
                "title": final_title,
                "filename": safe_zip_name,
                "start_time": req.start_time,
                "end_time": req.end_time,
                "created_at": str(asyncio.get_running_loop().time()),
                "download_url": f"/static/clips/{safe_zip_name}",
            }

            clips_data = []
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as file:
                        clips_data = json.load(file)
                except Exception:
                    pass

            clips_data.insert(0, new_clip_info)
            with open(meta_path, "w", encoding="utf-8") as file:
                json.dump(clips_data, file, ensure_ascii=False, indent=2)

            task_manager.complete_task(task_id, {"message": "Saved to library", "download_url": new_clip_info["download_url"]})
            print(f"[{task_id}] Clip Saved: {zip_path}")

        except Exception as error:
            print(f"[{task_id}] Clip Pipeline Failed: {error}")
            task_manager.fail_task(task_id, str(error), exception=error)

        finally:
            for temp_file in temp_files:
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except Exception:
                        pass

    async def run_shorts_pipeline(self, task_id: str, req: ShortsGenerateRequest) -> None:
        """AI 숏츠 생성 파이프라인."""
        task_manager = self.container.task_manager
        shorts_maker = self.container.shorts_maker
        clipper = self.container.clipper

        temp_files = []
        base_name = os.path.splitext(req.filename)[0]

        try:
            task_manager.update_progress(task_id, 0, "AI 숏츠 기획 시작...")

            transcript_path = os.path.join(RESULTS_DIR, f"{base_name}_transcript.json")
            srt_path = os.path.join(RESULTS_DIR, f"{base_name}.srt")
            vtt_path = os.path.join(RESULTS_DIR, f"{base_name}.vtt")
            effective_sub_path = srt_path if os.path.exists(srt_path) else (vtt_path if os.path.exists(vtt_path) else None)
            summary_path = os.path.join(RESULTS_DIR, f"{base_name}_summary.json")

            if not os.path.exists(transcript_path):
                raise FileNotFoundError("분석 데이터가 없습니다.")

            with open(transcript_path, "r", encoding="utf-8") as file:
                transcripts = json.load(file)

            video_title = req.filename
            chapters = None
            map_notes = None
            effective_content_type = req.content_type
            if os.path.exists(summary_path):
                with open(summary_path, "r", encoding="utf-8") as file:
                    summary_data = json.load(file)
                    video_title = summary_data.get("video_title", req.filename)
                    chapters = summary_data.get("chapters")
                    map_notes = summary_data.get("map_notes")
                    effective_content_type = summary_data.get("content_type", effective_content_type)

            if task_manager.is_cancelled(task_id):
                raise Exception("Task cancelled")
            task_manager.update_progress(task_id, 10, f"AI가 '{req.focus_topic or '자동'}' 주제로 기획 중...")

            loop = asyncio.get_running_loop()
            candidates = await loop.run_in_executor(
                None,
                partial(
                    shorts_maker.make_shorts_candidates,
                    transcripts,
                    video_title,
                    chapters=chapters,
                    focus_topic=req.focus_topic,
                    content_type=effective_content_type,
                    style=req.style,
                    min_duration=req.min_duration,
                    max_duration=req.max_duration,
                    humor_weight=req.humor_weight,
                    keep_original_tone=req.keep_original_tone,
                    speaker_mode=req.speaker_mode,
                    map_notes=map_notes,
                ),
            )

            if not candidates:
                raise Exception("AI가 숏츠 구간을 찾지 못했습니다.")
            task_manager.update_progress(task_id, 30, f"{len(candidates)}개의 숏츠 기획안 생성 완료.")

            phase_start, phase_end = 30, 90
            slot_weight = (phase_end - phase_start) / len(candidates)
            results = []
            video_path = self._resolve_video_path(req.filename, summary_data if 'summary_data' in locals() else None)

            for index, candidate in enumerate(candidates):
                if task_manager.is_cancelled(task_id):
                    raise Exception("Task cancelled")

                current_base_progress = phase_start + (index * slot_weight)
                clip_start_time = time.time()

                def ffmpeg_callback(local_percent: int) -> None:
                    global_progress = int(current_base_progress + (local_percent / 100.0) * slot_weight)
                    elapsed = time.time() - clip_start_time
                    
                    if local_percent > 3:
                        eta_seconds = int((elapsed / local_percent) * (100 - local_percent))
                        if eta_seconds > 60:
                            m, s = divmod(eta_seconds, 60)
                            eta_str = f"남은 시간 약 {m}분 {s}초"
                        else:
                            eta_str = f"남은 시간 약 {eta_seconds}초"
                    else:
                        eta_str = "예상 시간 계산 중..."

                    task_manager.update_progress(
                        task_id, 
                        global_progress, 
                        f"숏츠 {index + 1}/{len(candidates)} GPU 렌더링 중... ({local_percent}% | {eta_str})"
                    )

                safe_title = re.sub(r"[\\/*?:\"<>|]", "", candidate["title"]).replace(" ", "_")
                video_filename = f"AI_Shorts_{index + 1}_{safe_title}.mp4"

                merge_result = await clipper.merge_segments(
                    video_path,
                    candidate["segments"],
                    output_filename=video_filename,
                    sub_input_path=effective_sub_path,
                    progress_callback=ffmpeg_callback,
                    task_manager=task_manager,
                    task_id=task_id,
                )

                generated_video = merge_result["video"]
                generated_sub = merge_result["subtitle"]
                generated_vtt = merge_result["subtitle_vtt"]

                if generated_video and os.path.exists(generated_video):
                    final_video_path = os.path.join(CLIPS_DIR, video_filename)
                    shutil.move(generated_video, final_video_path)

                    final_sub_path = None
                    if generated_sub and os.path.exists(generated_sub):
                        sub_filename = video_filename.replace(".mp4", ".srt")
                        final_sub_path = os.path.join(CLIPS_DIR, sub_filename)
                        shutil.move(generated_sub, final_sub_path)

                    final_vtt_filename = None
                    if generated_vtt and os.path.exists(generated_vtt):
                        vtt_filename = video_filename.replace(".mp4", ".vtt")
                        final_vtt_path = os.path.join(CLIPS_DIR, vtt_filename)
                        shutil.move(generated_vtt, final_vtt_path)
                        final_vtt_filename = vtt_filename

                    zip_filename = video_filename.replace(".mp4", ".zip")
                    files_to_zip = [final_video_path]
                    if final_sub_path:
                        files_to_zip.append(final_sub_path)

                    await loop.run_in_executor(
                        None,
                        partial(clipper.create_zip, files_to_zip, zip_filename, CLIPS_DIR),
                    )

                    results.append(
                        {
                            "clip_id": str(uuid.uuid4()),
                            "title": candidate["title"],
                            "reason": candidate["reason"],
                            "filename_video": video_filename,
                            "filename_zip": zip_filename,
                            "filename_vtt": final_vtt_filename,
                            "duration": candidate["total_duration"],
                            "segments": candidate["segments"],
                            "recommended_skips": candidate.get("recommended_skips", []),
                            "created_at": datetime.now().isoformat(),
                            "download_url": f"/static/clips/{zip_filename}",
                            "preview_url": f"/static/clips/{video_filename}",
                        }
                    )
                else:
                    print(f"[Warning] Failed to render shorts candidate {index + 1}")

            task_manager.update_progress(task_id, 90, "메타데이터 저장 중...")
            if not results:
                raise Exception("숏츠 생성 실패")

            meta_path = os.path.join(RESULTS_DIR, f"{base_name}_clips.json")
            existing_data = []
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as file:
                        existing_data = json.load(file)
                except Exception:
                    pass

            for result in reversed(results):
                result["is_ai_generated"] = True
                existing_data.insert(0, result)

            with open(meta_path, "w", encoding="utf-8") as file:
                json.dump(existing_data, file, ensure_ascii=False, indent=2)

            task_manager.complete_task(task_id, {"count": len(results), "message": "완료"})
            print(f"[{task_id}] AI Shorts Completed: {len(results)}")

        except Exception as error:
            print(f"[{task_id}] Shorts Pipeline Failed: {error}")
            task_manager.fail_task(task_id, str(error), exception=error)
        finally:
            for temp_file in temp_files:
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except Exception:
                        pass
