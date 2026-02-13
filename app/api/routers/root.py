"""Root page route."""

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.paths import INDEX_TEMPLATE_PATH

router = APIRouter()


@router.get("/")
async def read_root():
    """메인 페이지 서빙."""
    if os.path.exists(INDEX_TEMPLATE_PATH):
        return FileResponse(INDEX_TEMPLATE_PATH)
    return {"message": "Please create templates/index.html"}
