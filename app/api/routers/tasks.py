"""Task status and cancellation routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.container import AppContainer
from app.core.dependencies import get_container

router = APIRouter()


@router.get("/api/tasks")
async def get_active_tasks(container: AppContainer = Depends(get_container)):
    """현재 실행 중인 작업 목록 조회 (Polling)."""
    return container.task_manager.get_active_tasks()


@router.delete("/api/tasks/{task_id}")
async def cancel_task(task_id: str, container: AppContainer = Depends(get_container)):
    """진행 중이거나 대기 중인 작업을 취소합니다."""
    task = container.task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    container.task_manager.request_cancel(task_id)
    return {"status": "success", "message": "Cancel requested"}
