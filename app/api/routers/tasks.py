"""Task status and cancellation routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.container import AppContainer
from app.core.dependencies import get_container

router = APIRouter()


import os
from fastapi.responses import PlainTextResponse

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


@router.get("/api/tasks/{task_id}/log", response_class=PlainTextResponse)
async def get_task_log(task_id: str, container: AppContainer = Depends(get_container)):
    """특정 작업 실패 시 생성된 로그 파일 내용을 평문 텍스트로 반환합니다."""
    task = container.task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    from services.logger import LOG_DIR
    safe_task_id = str(task_id).replace("/", "_").replace("\\", "_")
    task_log_path = os.path.join(LOG_DIR, f"task_{safe_task_id}.log")

    if not os.path.exists(task_log_path):
        raise HTTPException(
            status_code=404,
            detail=f"Log file not found. The task may have succeeded or failed without traceback."
        )

    try:
        with open(task_log_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {str(e)}")
