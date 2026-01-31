import os
import sys
import subprocess
import time
import json

class ConfigManager:
    """
    사용자 정의 설정을 관리하는 매니저.
    data/config.json 파일을 사용하여 개인화된 설정을 유지합니다.
    """
    CONFIG_PATH = "data/config.json"
    DEFAULT_CONFIG = {
        "models": {
            "summarizer": "gemini-2.5-flash",
            "planner": "gemini-2.5-flash-lite",
            "refiner": "gemma-3-27b-it",
            "shorts": "gemini-2.5-flash",
            "whisper": "mlx-community/whisper-large-v3-mlx-4bit"
        }
    }

    @classmethod
    def load_config(cls):
        """설정 파일을 로드합니다. 파일이 없으면 기본값을 생성합니다."""
        if not os.path.exists(cls.CONFIG_PATH):
            cls.save_config(cls.DEFAULT_CONFIG)
            return cls.DEFAULT_CONFIG
        
        try:
            with open(cls.CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ConfigManager] Error loading config: {e}")
            return cls.DEFAULT_CONFIG

    @classmethod
    def save_config(cls, config):
        """설정 파일을 저장합니다."""
        try:
            os.makedirs(os.path.dirname(cls.CONFIG_PATH), exist_ok=True)
            with open(cls.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"[ConfigManager] Successfully saved config to {os.path.abspath(cls.CONFIG_PATH)}")
            return True
        except Exception as e:
            print(f"[ConfigManager] Error saving config: {e}")
            raise e # 에러를 상위로 전파하여 API에서 확인 가능하게 함

    @classmethod
    def get_model(cls, task_type):
        """특정 작업에 설정된 모델명을 가져옵니다."""
        config = cls.load_config()
        model_name = config.get("models", {}).get(task_type, cls.DEFAULT_CONFIG["models"].get(task_type))
        
        # [OS 분기] Whisper 모델의 경우, OS에 따라 다른 기본 모델을 반환해야 함
        if task_type == "whisper":
            # 사용자가 config.json에 명시적으로 모델을 바꿨다면 그 값을 존중하되,
            # 기본값인 경우 OS에 맞춰 스위칭
            default_mlx = cls.DEFAULT_CONFIG["models"]["whisper"]
            
            # Mac이 아닌 경우(Windows/Linux)이고, 모델명이 MLX 전용이라면 -> Faster-Whisper용 표준 모델명으로 변경
            if sys.platform != "darwin" and "mlx-community" in model_name:
                return "large-v3" # Faster-Whisper 표준 모델명
                
        return model_name

class SystemManager:
    @staticmethod
    def check_for_updates():
        """
        Check if the local git repo is behind origin/main.
        Returns dict with status and version hashes.
        """
        try:
            # 1. Fetch latest changes from remote
            subprocess.run(["git", "fetch", "origin", "main"], check=True, capture_output=True, timeout=30)
            
            # 2. Get current HEAD hash
            current_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
            
            # 3. Get remote HEAD hash
            remote_hash = subprocess.check_output(["git", "rev-parse", "origin/main"]).decode().strip()
            
            return {
                "update_available": current_hash != remote_hash,
                "current_version": current_hash[:7],
                "latest_version": remote_hash[:7]
            }
        except Exception as e:
            return {"update_available": False, "error": str(e)}

    @staticmethod
    def perform_update():
        """
        Signals the guardian process (run.py) to perform update and restart.
        Exits current process with code 5.
        """
        print("--- [System] Signaling Update to Guardian in 1s... ---")
        # Exit code 5 is our custom signal defined in run.py
        # We use a short delay and os._exit to bypass FastAPI's exception handling
        time.sleep(1)
        os._exit(5)

    @staticmethod
    def restart_server():
        """
        Signals the guardian process to just restart.
        """
        print("--- [System] Signaling Restart to Guardian in 1s... ---")
        time.sleep(1)
        os._exit(5)
