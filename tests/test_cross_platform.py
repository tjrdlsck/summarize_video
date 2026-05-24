import sys
import os
import pytest
from services.system_manager import ConfigManager
from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.api.routers.settings import router as settings_router

app = FastAPI()
app.include_router(settings_router)
client = TestClient(app)

def test_whisper_model_selection_non_darwin(monkeypatch):
    """
    비-Darwin(Windows, Linux) 환경에서 Whisper 모델명이 MLX 전용 명칭이 아닌
    Faster-Whisper 표준 모델명('large-v3')으로 자동 전환되는지 검증합니다.
    """
    # sys.platform을 'linux'로 강제 설정하여 운영체제 분기를 시뮬레이션
    monkeypatch.setattr(sys, "platform", "linux")
    
    # 모델명 가져오기
    model_name = ConfigManager.get_model("whisper")
    
    # 기본 구성상 MLX 모델명이 지정되어 있다면 'large-v3-turbo'가 반환되어야 함
    default_whisper_model = ConfigManager.DEFAULT_CONFIG["models"]["whisper"]
    if "mlx-community" in default_whisper_model:
        assert model_name == "large-v3-turbo"
    else:
        assert model_name == default_whisper_model

def test_api_settings_cross_platform(monkeypatch):
    """
    /api/settings API가 플랫폼에 따라 올바른 메타데이터를 반환하는지 테스트합니다.
    """
    # 1. Linux 플랫폼 모킹
    monkeypatch.setattr(sys, "platform", "linux")
    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "linux"
    assert "large-v3-turbo" in data["whisper_models"]
    assert "models" in data
    assert "gemini_models" in data
    
    # 2. Darwin 플랫폼 모킹
    monkeypatch.setattr(sys, "platform", "darwin")
    response = client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "darwin"
    assert any("mlx-community" in model for model in data["whisper_models"])

def test_gemini_models_fallback(monkeypatch):
    """
    API 키가 없을 때 get_gemini_models가 기본값을 반환하는지 확인합니다.
    """
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # 캐시 초기화
    ConfigManager._cached_gemini_models = None
    
    models = ConfigManager.get_gemini_models()
    assert "gemini-2.5-flash" in models

def test_whisper_model_mapping_by_platform(monkeypatch):
    """
    sys.platform 환경에 맞춰 Whisper 모델명이 알맞은 하드웨어 가속 최적화 모델명으로 상호 맵핑되는지 검증합니다.
    """
    # 1. macOS (darwin) 환경에서의 맵핑 테스트
    monkeypatch.setattr(sys, "platform", "darwin")
    
    # 1.1 config.json 모킹 (대체값을 설정 파일에 주입하여 테스트)
    monkeypatch.setattr(ConfigManager, "load_config", lambda: {"models": {"whisper": "large-v3"}})
    assert ConfigManager.get_model("whisper") == "mlx-community/whisper-large-v3-mlx-4bit"
    
    monkeypatch.setattr(ConfigManager, "load_config", lambda: {"models": {"whisper": "large-v3-turbo"}})
    assert ConfigManager.get_model("whisper") == "mlx-community/whisper-large-v3-turbo-q4"

    monkeypatch.setattr(ConfigManager, "load_config", lambda: {"models": {"whisper": "mlx-community/whisper-large-v3-turbo"}})
    assert ConfigManager.get_model("whisper") == "mlx-community/whisper-large-v3-turbo-q4"

    # 2. Linux/Windows 환경에서의 맵핑 테스트
    monkeypatch.setattr(sys, "platform", "linux")
    
    monkeypatch.setattr(ConfigManager, "load_config", lambda: {"models": {"whisper": "mlx-community/whisper-large-v3-turbo-q4"}})
    assert ConfigManager.get_model("whisper") == "large-v3-turbo"
    
    monkeypatch.setattr(ConfigManager, "load_config", lambda: {"models": {"whisper": "mlx-community/whisper-large-v3-mlx-4bit"}})
    assert ConfigManager.get_model("whisper") == "large-v3"

    monkeypatch.setattr(ConfigManager, "load_config", lambda: {"models": {"whisper": "mlx-community/whisper-large-v3-q4"}})
    assert ConfigManager.get_model("whisper") == "large-v3"

