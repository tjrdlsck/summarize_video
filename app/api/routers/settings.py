"""Settings routes."""

from fastapi import APIRouter, HTTPException

from app.schemas.requests import SettingsUpdateRequest
from services.system_manager import ConfigManager

router = APIRouter()


@router.get("/api/settings")
async def get_settings():
    """현재 AI 모델 설정을 조회합니다."""
    return ConfigManager.load_config()


@router.post("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    """AI 모델 설정을 업데이트합니다."""
    if ConfigManager.save_config(req.model_dump()):
        return {"status": "success", "message": "Settings applied successfully"}
    raise HTTPException(status_code=500, detail="Failed to save settings")
