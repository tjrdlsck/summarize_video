"""Router registration utilities."""

from fastapi import FastAPI

from app.api.routers.analysis import router as analysis_router
from app.api.routers.clips import router as clips_router
from app.api.routers.export import router as export_router
from app.api.routers.history import router as history_router
from app.api.routers.media import router as media_router
from app.api.routers.root import router as root_router
from app.api.routers.settings import router as settings_router
from app.api.routers.system import router as system_router
from app.api.routers.tasks import router as tasks_router
from app.api.routers.transcription import router as transcription_router
from app.api.routers.folder import router as folder_router


def include_routers(app: FastAPI) -> None:
    """Register all API routers."""
    app.include_router(root_router)
    app.include_router(settings_router)
    app.include_router(transcription_router)
    app.include_router(analysis_router)
    app.include_router(tasks_router)
    app.include_router(history_router)
    app.include_router(clips_router)
    app.include_router(media_router)
    app.include_router(export_router)
    app.include_router(system_router)
    app.include_router(folder_router)
