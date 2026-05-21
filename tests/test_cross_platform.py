import sys
import pytest
from services.system_manager import ConfigManager

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
