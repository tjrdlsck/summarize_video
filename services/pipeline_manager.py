import os
import uuid
import asyncio
import json
import shutil
import re
import multiprocessing
from functools import partial
from datetime import datetime

# [Custom Services]
from services.downloader import VideoDownloader
from services.transcriber import VideoTranscriber, TaskCancelledError
from services.summarizer import VideoSummarizer
from services.task_manager import TaskManager
from services.clipper import VideoClipper
from services.refiner import TextRefiner
from services.shorts_maker import ShortsMaker
from services.premiere_exporter import PremiereExporter
from services.system_manager import ConfigManager

class TaskProgressWrapper:
    """
    하위 모듈(Transcriber 등)이 보고하는 0~100% 진행률을
    전체 파이프라인의 특정 구간으로 스케일링하여 TaskManager에 전달하는 래퍼
    """
    def __init__(self, real_task_manager, task_id, start_offset, scale_factor):
        self.tm = real_task_manager
        self.task_id = task_id
        self.offset = start_offset
        self.scale = scale_factor

    def update_progress(self, task_id, progress, message=None):
        scaled_progress = self.offset + int(progress * self.scale)
        self.tm.update_progress(self.task_id, scaled_progress, message)

    def is_cancelled(self, task_id):
        return self.tm.is_cancelled(self.task_id)

class PipelineManager:
    def __init__(self):
        # 서비스 인스턴스 초기화
        self.downloader = VideoDownloader(download_dir="static/videos")
        self.transcriber = VideoTranscriber(output_dir="static/results")
        self.summarizer = VideoSummarizer(output_dir="static/results")
        self.refiner = TextRefiner()
        self.task_manager = TaskManager()
        self.clipper = VideoClipper(temp_dir="static/temp")
        self.shorts_maker = ShortsMaker()
        self.premiere_exporter = PremiereExporter(output_dir="static/temp")
        
        # 작업 큐 및 리소스 제어
        self.job_queue = asyncio.Queue()
        self.resource_semaphore = asyncio.Semaphore(1)
        self.worker_task = None

    async def start_worker(self):
        """백그라운드 워커 시작"""
        print("--- [PipelineManager] Starting Background Worker... ---")
        self.worker_task = asyncio.create_task(self._worker_loop())

    async def stop_worker(self):
        """백그라운드 워커 중지 및 리소스 정리"""
        print("--- [PipelineManager] Shutting down... ---")
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        
        # 자식 프로세스 정리
        active_children = multiprocessing.active_children()
        if active_children:
            print(f"--- [PipelineManager] Cleaning up {len(active_children)} child processes... ---")
            for child in active_children:
                child.terminate()
                child.join(timeout=1)
                if child.is_alive():
                    child.kill()

    async def enqueue_task(self, task_id: str, req_data, target_name: str, task_type: str):
        """작업을 큐에 추가"""
        self.task_manager.add_task(task_id, target_name, task_type=task_type)
        await self.job_queue.put((task_id, req_data))

    async def _worker_loop(self):
        print("--- [PipelineManager] Worker Loop Started ---")
        while True:
            task_id, req = await self.job_queue.get()
            try:
                if self.task_manager.is_cancelled(task_id):
                    print(f"[{task_id}] Task cancelled before start.")
                    self.task_manager.fail_task(task_id, "대기 중 취소됨")
                else:
                    async with self.resource_semaphore:
                        await self._run_pipeline(task_id, req)
            except Exception as e:
                print(f"[Worker Error] {e}")
            finally:
                self.job_queue.task_done()

    async def _run_pipeline(self, task_id: str, req):
        """요청 타입에 따른 파이프라인 실행 분기"""
        from main import TranscriptionRequest, SummaryRequest, BlogGenerationRequest, ClipRequest, ShortsGenerateRequest
        
        if isinstance(req, TranscriptionRequest):
            await self.run_transcription_pipeline(task_id, req)
        elif isinstance(req, SummaryRequest):
            await self.run_summary_pipeline(task_id, req)
        elif isinstance(req, BlogGenerationRequest):
            await self.run_blog_pipeline(task_id, req)
        elif isinstance(req, ClipRequest):
            await self.run_clip_pipeline(task_id, req)
        elif isinstance(req, ShortsGenerateRequest):
            await self.run_shorts_pipeline(task_id, req)

    # --- [Pipelines 이관] ---

    async def run_transcription_pipeline(self, task_id: str, req):
        video_filename = req.filename 
        display_title = req.custom_title
        
        def cleanup_files(filename):
            if not filename: return
            try:
                base_name = os.path.splitext(filename)[0]
                targets = [
                    os.path.join("static/videos", filename),           
                    os.path.join("static/results", f"{base_name}.srt"),      
                    os.path.join("static/results", f"{base_name}.vtt"),      
                    os.path.join("static/results", f"{base_name}_transcript.json"), 
                    os.path.join("static/results", f"{base_name}_temp.wav")
                ]
                for path in targets:
                    if os.path.exists(path): os.remove(path)

                video_dir = "static/videos"
                if os.path.exists(video_dir):
                    for f in os.listdir(video_dir):
                        if f == filename or (base_name in f and (".part" in f or ".ytdl" in f or ".temp" in f)):
                            try: os.remove(os.path.join(video_dir, f))
                            except: pass
            except Exception as e:
                print(f"[Cleanup Error] {e}")

        try:
            loop = asyncio.get_running_loop()
            if self.task_manager.is_cancelled(task_id): raise TaskCancelledError()
            self.task_manager.update_progress(task_id, 0, "작업 시작...")
            
            if req.url:
                self.task_manager.update_progress(task_id, 1, "영상 다운로드 중...")
                def dl_callback(percent, msg):
                    scaled = 1 + int(percent * 0.19)
                    loop.call_soon_threadsafe(self.task_manager.update_progress, task_id, scaled, msg)

                result = await loop.run_in_executor(
                    None, 
                    partial(self.downloader.download_from_url, req.url, progress_callback=dl_callback, task_manager=self.task_manager, task_id=task_id)
                )
                if result["status"] == "error":
                    if result.get("filename"): video_filename = result["filename"]
                    raise Exception(result["message"])
                video_filename = result["filename"]
                if not display_title and result.get("meta") and result["meta"].get("title"):
                    display_title = result["meta"]["title"]

            if self.task_manager.is_cancelled(task_id): raise TaskCancelledError()

            video_path = os.path.join("static/videos", video_filename)
            if not os.path.exists(video_path): raise FileNotFoundError(f"File not found: {video_filename}")
            
            if not display_title:
                raw_name = video_filename
                clean_name = re.sub(r'^[0-9a-fA-F]{8}_', '', raw_name)
                display_title = os.path.splitext(clean_name)[0].replace("_", " ").strip()

            self.task_manager.update_progress(task_id, 20, "오디오 변환 및 자막 생성 중...")
            progress_wrapper = TaskProgressWrapper(self.task_manager, task_id, start_offset=20, scale_factor=0.8)
            
            def transcriber_callback(local_percent, msg):
                loop.call_soon_threadsafe(progress_wrapper.update_progress, task_id, local_percent, msg)

            transcribe_result = await loop.run_in_executor(
                None,
                partial(self.transcriber.transcribe, video_path, progress_callback=transcriber_callback, task_manager=progress_wrapper, task_id=task_id)
            )
            
            if self.task_manager.is_cancelled(task_id): raise TaskCancelledError()
            if transcribe_result.get("status") == "error": raise Exception("Transcription failed")
            
            base_name = os.path.splitext(video_filename)[0]
            summary_path = os.path.join("static/results", f"{base_name}_summary.json")
            initial_data = {
                "video_source": video_filename,
                "video_title": display_title,
                "total_chapters": 0,
                "chapters": [],
                "status": "transcribed_only"
            }
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump(initial_data, f, ensure_ascii=False, indent=2)

            self.task_manager.complete_task(task_id, {"status": "success", "message": "자막 생성 완료", "video_title": display_title})
        except TaskCancelledError:
            cleanup_files(video_filename)
            self.task_manager.fail_task(task_id, "취소됨")
        except Exception as e:
            cleanup_files(video_filename)
            self.task_manager.fail_task(task_id, str(e))

    async def run_summary_pipeline(self, task_id: str, req):
        base_name = os.path.splitext(req.filename)[0]
        transcript_path = os.path.join("static/results", f"{base_name}_transcript.json")
        try:
            self.task_manager.update_progress(task_id, 0, "AI 분석 시작...")
            if not os.path.exists(transcript_path): raise FileNotFoundError("자막 데이터가 없습니다.")
            with open(transcript_path, 'r', encoding='utf-8') as f: segments = json.load(f)

            loop = asyncio.get_running_loop()
            self.task_manager.update_progress(task_id, 10, "Gemini가 내용을 분석하고 있습니다...")
            summary_result = await loop.run_in_executor(
                None,
                partial(self.summarizer.summarize, segments, req.filename, custom_title=req.custom_title, status_callback=lambda msg: loop.call_soon_threadsafe(self.task_manager.update_progress, task_id, 50, msg))
            )
            if summary_result.get("error"): raise Exception(summary_result["error"])
            if self.task_manager.is_cancelled(task_id): raise TaskCancelledError()
            self.task_manager.complete_task(task_id, summary_result)
        except TaskCancelledError:
            self.task_manager.fail_task(task_id, "취소됨")
        except Exception as e:
            self.task_manager.fail_task(task_id, str(e))

    async def run_blog_pipeline(self, task_id: str, req):
        base_name = os.path.splitext(req.filename)[0]
        transcript_path = os.path.join("static/results", f"{base_name}_transcript.json")
        output_path = os.path.join("static/results", f"{base_name}_blog_view.json")
        try:
            self.task_manager.update_progress(task_id, 0, "블로그 구조 설계 중...")
            if not os.path.exists(transcript_path): raise FileNotFoundError("자막 데이터가 없습니다.")
            with open(transcript_path, 'r', encoding='utf-8') as f: segments = json.load(f)
            
            loop = asyncio.get_running_loop()
            blog_plan = await loop.run_in_executor(
                None,
                partial(self.summarizer.plan_blog_structure, segments, req.filename, status_callback=lambda msg: loop.call_soon_threadsafe(self.task_manager.update_progress, task_id, 10, msg))
            )
            if "error" in blog_plan: raise Exception(blog_plan["error"])
            
            temp_chapters = blog_plan.get("chapters", [])
            total_chaps = len(temp_chapters)
            sorted_segments = sorted(segments, key=lambda x: x['start'])
            final_chapters = []

            for i, chap in enumerate(temp_chapters):
                if self.task_manager.is_cancelled(task_id): raise TaskCancelledError()
                self.task_manager.update_progress(task_id, 20 + int((i / total_chaps) * 80), f"섹션 작성 중... ({i+1}/{total_chaps})")
                chapter_segments = [s for s in sorted_segments if chap['start_id'] <= s['id'] <= chap['end_id']]
                if not chapter_segments: continue
                
                refined_md = await loop.run_in_executor(
                    None,
                    partial(self.refiner.refine_chapter, raw_text="", chapter_title=chap['title'], segments=chapter_segments)
                )
                final_chapters.append({
                    "title": chap['title'], "content": refined_md, "focus_point": chap.get("focus_point", ""),
                    "time": {"start": chapter_segments[0]['start'], "end": chapter_segments[-1]['end'], 
                             "start_formatted": self.summarizer._format_time(chapter_segments[0]['start']),
                             "end_formatted": self.summarizer._format_time(chapter_segments[-1]['end'])}
                })

            result_data = {"video_source": req.filename, "blog_title": blog_plan.get("blog_title", "Untitled"), "chapters": final_chapters, "generated_at": datetime.now().isoformat()}
            with open(output_path, 'w', encoding='utf-8') as f: json.dump(result_data, f, ensure_ascii=False, indent=2)
            self.task_manager.complete_task(task_id, result_data)
        except TaskCancelledError:
            self.task_manager.fail_task(task_id, "취소됨")
        except Exception as e:
            self.task_manager.fail_task(task_id, str(e))

    async def run_clip_pipeline(self, task_id: str, req):
        temp_files = [] 
        try:
            self.task_manager.update_progress(task_id, 0, "클립 생성 준비...")
            video_path = os.path.join("static/videos", req.filename)
            if not os.path.exists(video_path): raise FileNotFoundError(f"Video file not found: {req.filename}")
            if req.end_time <= req.start_time: raise ValueError("잘못된 구간 설정")

            base_name = os.path.splitext(req.filename)[0]
            self.task_manager.update_progress(task_id, 10, "영상 자르는 중...")
            cut_video_path = await self.clipper.cut_video(video_path, req.start_time, req.end_time, output_filename=f"clip_{base_name}_{task_id[:8]}.mp4", task_manager=self.task_manager, task_id=task_id)
            temp_files.append(cut_video_path)
            
            self.task_manager.update_progress(task_id, 60, "자막 동기화 중...")
            srt_path = os.path.join("static/results", f"{base_name}.srt")
            vtt_path = os.path.join("static/results", f"{base_name}.vtt")
            sub_source_path = srt_path if os.path.exists(srt_path) else (vtt_path if os.path.exists(vtt_path) else None)
            
            if sub_source_path:
                sub_ext = os.path.splitext(sub_source_path)[1]
                loop = asyncio.get_running_loop()
                cut_sub_path = await loop.run_in_executor(None, partial(self.clipper.cut_subtitle, sub_source_path, req.start_time, req.end_time, output_filename=f"clip_{base_name}_{task_id[:8]}{sub_ext}"))
                if cut_sub_path: temp_files.append(cut_sub_path)

            self.task_manager.update_progress(task_id, 80, "클립 패키징 중...")
            clip_uuid = str(uuid.uuid4())
            safe_zip_name = f"clip_{base_name}_{clip_uuid[:8]}.zip"
            zip_path = await asyncio.get_running_loop().run_in_executor(None, partial(self.clipper.create_zip, temp_files, safe_zip_name, "static/clips"))
            
            meta_path = os.path.join("static/results", f"{base_name}_clips.json")
            new_clip_info = {"clip_id": clip_uuid, "title": req.title or "Untitled", "filename": safe_zip_name, "start_time": req.start_time, "end_time": req.end_time, "created_at": str(datetime.now()), "download_url": f"/static/clips/{safe_zip_name}"}
            clips_data = []
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f: clips_data = json.load(f)
            clips_data.insert(0, new_clip_info)
            with open(meta_path, 'w', encoding='utf-8') as f: json.dump(clips_data, f, ensure_ascii=False, indent=2)

            self.task_manager.complete_task(task_id, {"message": "Saved to library", "download_url": new_clip_info["download_url"]})
        except Exception as e:
            self.task_manager.fail_task(task_id, str(e))
        finally:
            for f in temp_files:
                if f and os.path.exists(f): 
                    try: os.remove(f)
                    except: pass

    async def run_shorts_pipeline(self, task_id: str, req):
        temp_files = [] 
        base_name = os.path.splitext(req.filename)[0]
        try:
            self.task_manager.update_progress(task_id, 0, "AI 숏츠 기획 시작...")
            transcript_path = os.path.join("static/results", f"{base_name}_transcript.json")
            srt_path = os.path.join("static/results", f"{base_name}.srt") 
            summary_path = os.path.join("static/results", f"{base_name}_summary.json")

            if not os.path.exists(transcript_path): raise FileNotFoundError("분석 데이터가 없습니다.")
            with open(transcript_path, 'r', encoding='utf-8') as f: transcripts = json.load(f)
            
            video_title = req.filename
            chapters = None
            if os.path.exists(summary_path):
                with open(summary_path, 'r', encoding='utf-8') as f:
                    summary_data = json.load(f)
                    video_title = summary_data.get("video_title", req.filename)
                    chapters = summary_data.get("chapters")

            self.task_manager.update_progress(task_id, 10, "AI가 기획 중...")
            loop = asyncio.get_running_loop()
            candidates = await loop.run_in_executor(None, partial(self.shorts_maker.make_shorts_candidates, transcripts, video_title, chapters=chapters, focus_topic=req.focus_topic))
            if not candidates: raise Exception("숏츠 구간을 찾지 못했습니다.")

            results = []
            video_path = os.path.join("static/videos", req.filename)
            PHASE_START, PHASE_END = 30, 90
            slot_weight = (PHASE_END - PHASE_START) / len(candidates)
            
            for idx, cand in enumerate(candidates):
                if self.task_manager.is_cancelled(task_id): raise Exception("Task cancelled")
                def ffmpeg_callback(local_percent):
                    global_progress = int(PHASE_START + (idx * slot_weight) + (local_percent / 100.0) * slot_weight)
                    self.task_manager.update_progress(task_id, global_progress, f"숏츠 {idx+1}/{len(candidates)} 제작 중...")

                safe_title = re.sub(r'[\\/*?:"<>|]', "", cand['title']).replace(" ", "_")
                video_filename = f"AI_Shorts_{idx+1}_{safe_title}.mp4"
                merge_result = await self.clipper.merge_segments(video_path, cand['segments'], output_filename=video_filename, sub_input_path=srt_path, progress_callback=ffmpeg_callback, task_manager=self.task_manager, task_id=task_id)
                
                if merge_result['video'] and os.path.exists(merge_result['video']):
                    final_video_path = os.path.join("static/clips", video_filename)
                    shutil.move(merge_result['video'], final_video_path)
                    
                    final_sub_path = None
                    if merge_result['subtitle'] and os.path.exists(merge_result['subtitle']):
                        final_sub_path = os.path.join("static/clips", video_filename.replace(".mp4", ".srt"))
                        shutil.move(merge_result['subtitle'], final_sub_path)
                    
                    final_vtt_filename = None
                    if merge_result['subtitle_vtt'] and os.path.exists(merge_result['subtitle_vtt']):
                        final_vtt_path = os.path.join("static/clips", video_filename.replace(".mp4", ".vtt"))
                        shutil.move(merge_result['subtitle_vtt'], final_vtt_path)
                        final_vtt_filename = video_filename.replace(".mp4", ".vtt")

                    zip_filename = video_filename.replace(".mp4", ".zip")
                    files_to_zip = [final_video_path]
                    if final_sub_path: files_to_zip.append(final_sub_path)
                    await loop.run_in_executor(None, partial(self.clipper.create_zip, files_to_zip, zip_filename, "static/clips"))

                    results.append({
                        "clip_id": str(uuid.uuid4()), "title": cand['title'], "reason": cand['reason'],
                        "filename_video": video_filename, "filename_zip": zip_filename, "filename_vtt": final_vtt_filename,
                        "duration": cand['total_duration'], "segments": cand['segments'], "created_at": datetime.now().isoformat(),
                        "download_url": f"/static/clips/{zip_filename}", "preview_url": f"/static/clips/{video_filename}"
                    })

            meta_path = os.path.join("static/results", f"{base_name}_clips.json")
            existing_data = []
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f: existing_data = json.load(f)
            for res in reversed(results):
                res["is_ai_generated"] = True
                existing_data.insert(0, res)
            with open(meta_path, 'w', encoding='utf-8') as f: json.dump(existing_data, f, ensure_ascii=False, indent=2)

            self.task_manager.complete_task(task_id, {"count": len(results), "message": "완료"})
        except Exception as e:
            self.task_manager.fail_task(task_id, str(e))