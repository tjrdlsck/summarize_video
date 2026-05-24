"""Background queue worker."""

from app.application.pipeline_runner import PipelineRunner
from app.core.container import AppContainer
from app.schemas.requests import (
    BlogGenerationRequest,
    ClipRequest,
    ShortsGenerateRequest,
    SummaryRequest,
    TranscriptionRequest,
)
from services.system_manager import SystemManager


class QueueWorker:
    """Single-consumer worker that runs queued tasks sequentially."""

    def __init__(self, container: AppContainer, runner: PipelineRunner | None = None) -> None:
        self.container = container
        self.runner = runner or PipelineRunner(container)

    async def run(self) -> None:
        """Consumes job queue forever and dispatches request types to pipelines."""
        print("--- [Worker] Analysis Worker Started ---")
        task_manager = self.container.task_manager

        while True:
            task_id, req = await self.container.job_queue.get()
            try:
                if task_manager.is_cancelled(task_id):
                    print(f"[{task_id}] Task cancelled before start.")
                    task_manager.fail_task(task_id, "대기 중 취소됨")
                else:
                    async with self.container.resource_semaphore:
                        if isinstance(req, TranscriptionRequest):
                            await self.runner.run_transcription_pipeline(task_id, req)
                        elif isinstance(req, SummaryRequest):
                            await self.runner.run_summary_pipeline(task_id, req)
                        elif isinstance(req, BlogGenerationRequest):
                            await self.runner.run_blog_pipeline(task_id, req)
                        elif isinstance(req, ClipRequest):
                            await self.runner.run_clip_pipeline(task_id, req)
                        elif isinstance(req, ShortsGenerateRequest):
                            await self.runner.run_shorts_pipeline(task_id, req)
            except Exception as error:
                print(f"[Worker Error] {error}")
                try:
                    from services.logger import get_logger, log_error_with_traceback
                    logger = get_logger()
                    log_error_with_traceback(logger, f"[Worker] Exception in task {task_id}", error)
                except Exception as log_err:
                    print(f"[Backup Warning] Failed to log worker exception: {log_err}")
                
                # 대기열 실행 실패 시 태스크를 실패 처리
                try:
                    task_manager.fail_task(task_id, f"Worker Error: {str(error)}", exception=error)
                except Exception as fail_err:
                    print(f"[Backup Warning] Failed to fail task {task_id}: {fail_err}")
            finally:
                self.container.job_queue.task_done()
                SystemManager.maybe_schedule_restart(
                    task_manager=task_manager,
                    queue_size=self.container.job_queue.qsize(),
                )
