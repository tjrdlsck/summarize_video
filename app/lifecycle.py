"""Application lifespan orchestration."""

import asyncio
import multiprocessing
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.application.cleanup import cleanup_orphaned_files
from app.application.worker import QueueWorker
from app.core.container import AppContainer


def create_lifespan(container: AppContainer):
    """Creates a FastAPI lifespan handler bound to the provided container."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        print("--- [Lifespan] Starting Background Worker... ---")

        cleanup_orphaned_files()

        worker = QueueWorker(container)
        worker_task = asyncio.create_task(worker.run())
        container.worker = worker
        container.worker_task = worker_task

        yield

        print("--- [Lifespan] Shutting down... ---")

        active_children = multiprocessing.active_children()
        if active_children:
            print(f"--- [Lifespan] Cleaning up {len(active_children)} child processes... ---")
            for child in active_children:
                child.terminate()
                child.join(timeout=1)
                if child.is_alive():
                    child.kill()

        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    return lifespan
