"""Analysis and blog queue routes."""

import uuid

from fastapi import APIRouter, Depends

from app.core.container import AppContainer
from app.core.dependencies import get_container
from app.schemas.requests import BlogGenerationRequest, SummaryRequest

router = APIRouter()


@router.post("/api/analyze")
async def start_analysis(req: SummaryRequest, container: AppContainer = Depends(get_container)):
    """2단계: AI 챕터 분석 및 요약 요청."""
    task_id = str(uuid.uuid4())
    container.task_manager.add_task(task_id, req.filename, task_type="analysis")
    await container.job_queue.put((task_id, req))
    return {"task_id": task_id, "message": "Analysis queued"}


@router.post("/api/blog/generate")
async def generate_blog(req: BlogGenerationRequest, container: AppContainer = Depends(get_container)):
    """3단계: 블로그 포스트 생성 요청."""
    task_id = str(uuid.uuid4())
    container.task_manager.add_task(task_id, req.filename, task_type="blog_generation")
    await container.job_queue.put((task_id, req))
    return {"task_id": task_id, "message": "Blog generation queued"}
