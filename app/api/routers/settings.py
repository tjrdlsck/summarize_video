"""Settings routes."""

import sys
from fastapi import APIRouter, HTTPException

from app.schemas.requests import SettingsUpdateRequest
from services.system_manager import ConfigManager

router = APIRouter()


@router.get("/api/settings")
async def get_settings():
    """현재 AI 모델 설정 및 플랫폼 메타데이터를 함께 조회합니다."""
    config = ConfigManager.load_config()
    
    whisper_models = ConfigManager.DARWIN_WHISPER_MODELS if sys.platform == "darwin" else ConfigManager.OTHER_WHISPER_MODELS
    gemini_models = ConfigManager.get_gemini_models()
    
    return {
        "models": config.get("models", {}),
        "platform": sys.platform,
        "whisper_models": whisper_models,
        "gemini_models": gemini_models
    }


@router.post("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    """AI 모델 설정을 업데이트합니다."""
    if ConfigManager.save_config(req.model_dump()):
        return {"status": "success", "message": "Settings applied successfully"}
    raise HTTPException(status_code=500, detail="Failed to save settings")
