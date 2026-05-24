import os
import sys
import subprocess
import time
import json
import threading

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
            "refiner": "gemma-4-26b-a4b-it",
            "shorts": "gemini-2.5-flash-lite",
            "whisper": "mlx-community/whisper-large-v3-turbo-q4"
        }
    }

    # macOS (darwin) 추천 모델 목록
    DARWIN_WHISPER_MODELS = [
        "mlx-community/whisper-large-v3-turbo-q4",
        "mlx-community/whisper-large-v3-mlx-4bit"
    ]
    # Windows/Linux (Faster-Whisper) 추천 모델 목록
    OTHER_WHISPER_MODELS = [
        "large-v3-turbo",
        "large-v3",
        "medium",
        "small"
    ]

    _cached_gemini_models = None

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
        
        # [OS 분기 및 상호 매핑] Whisper 모델의 경우 OS 호환성을 위해 모델명을 보정합니다.
        if task_type == "whisper":
            if sys.platform == "darwin":
                # macOS 환경: Faster-Whisper 모델명이 들어온 경우 최적화된 MLX 모델로 매핑
                if model_name == "large-v3":
                    return "mlx-community/whisper-large-v3-mlx-4bit"
                elif model_name == "large-v3-turbo":
                    return "mlx-community/whisper-large-v3-turbo-q4"
                # 기본 설정이 mlx-community/whisper-large-v3-turbo 인 경우(구버전 호환)
                elif model_name == "mlx-community/whisper-large-v3-turbo":
                    return "mlx-community/whisper-large-v3-turbo-q4"
            else:
                # macOS가 아닌 환경(Linux/Windows): MLX 전용 모델명이 들어온 경우 Faster-Whisper 표준 모델명으로 폴백
                if "whisper-large-v3-turbo-q4" in model_name:
                    return "large-v3-turbo"
                elif "whisper-large-v3-mlx-4bit" in model_name or "whisper-large-v3-q4" in model_name:
                    return "large-v3"
                elif "mlx-community" in model_name:
                    # 그 외의 MLX 모델명인 경우 안전한 폴백
                    return "large-v3-turbo"
                
        return model_name

    @classmethod
    def get_gemini_models(cls):
        """
        Google GenAI API를 호출하여 gemini 또는 gemma 모델 목록을 동적으로 가져옵니다.
        실패하거나 API 키가 없는 경우 기본 폴백(Fallback) 리스트를 반환합니다.
        지연 시간을 줄이기 위해 클래스 변수를 통해 인메모리 캐싱을 제공합니다.
        """
        if cls._cached_gemini_models:
            return cls._cached_gemini_models
            
        default_models = [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-3-flash",
            "gemini-3-pro",
            "gemini-3-deep-think",
            "gemma-3-27b-it",
            "gemma-3-4b-it",
            "gemma-3-12b-it"
        ]
        
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return default_models
            
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            models_list = client.models.list()
            
            gemini_gemma = []
            for m in models_list:
                name = m.name
                if name.startswith("models/"):
                    name = name[len("models/"):]
                
                name_lower = name.lower()
                if "gemini" in name_lower or "gemma" in name_lower:
                    if name not in gemini_gemma:
                        gemini_gemma.append(name)
            
            if gemini_gemma:
                cls._cached_gemini_models = gemini_gemma
                return gemini_gemma
        except Exception as e:
            print(f"[ConfigManager] Failed to fetch dynamic Gemini models: {e}")
            
        return default_models

class SystemManager:
    _state_lock = threading.Lock()
    _restart_requested = False
    _restart_timer = None
    _restart_deadline = None
    _restart_reason = None
    _restart_delay_seconds = 60
    _active_statuses = {"queued", "pending", "processing", "canceling"}

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

    @classmethod
    def request_restart_after_failures(cls, reason: str, delay_seconds: int = 60):
        """yt-dlp 자동 복구 이후, 조건이 맞으면 지연 재시작하도록 예약 의도를 등록합니다."""
        with cls._state_lock:
            cls._restart_requested = True
            cls._restart_reason = reason
            cls._restart_delay_seconds = max(1, int(delay_seconds))

    @classmethod
    def maybe_schedule_restart(cls, task_manager, queue_size: int = 0):
        """활성 작업이 없고 실패 작업만 남은 경우에만 지연 재시작을 실제 스케줄링합니다."""
        with cls._state_lock:
            if not cls._restart_requested:
                return False
            if cls._restart_timer is not None:
                return True
            if queue_size > 0:
                return False

            tasks = getattr(task_manager, "tasks", {})
            statuses = [task.get("status") for task in tasks.values()]
            if any(status in cls._active_statuses for status in statuses):
                return False
            if not any(status == "failed" for status in statuses):
                return False

            cls._restart_deadline = time.time() + cls._restart_delay_seconds
            timer = threading.Timer(cls._restart_delay_seconds, cls.restart_server)
            timer.daemon = True
            timer.start()
            cls._restart_timer = timer
            return True

    @classmethod
    def get_restart_status(cls):
        with cls._state_lock:
            pending = cls._restart_timer is not None
            remaining = None
            deadline = None
            if pending and cls._restart_deadline is not None:
                remaining = max(0, int(cls._restart_deadline - time.time()))
                deadline = int(cls._restart_deadline)
            return {
                "pending": pending,
                "reason": cls._restart_reason,
                "remaining_seconds": remaining,
                "deadline_unix": deadline,
            }

    @classmethod
    def restart_now(cls):
        """예약된 재시작을 즉시 수행합니다."""
        with cls._state_lock:
            timer = cls._restart_timer
            cls._restart_timer = None
            cls._restart_deadline = None
            cls._restart_requested = False
        if timer is not None:
            timer.cancel()
        cls.restart_server()

    @staticmethod
    def restart_server():
        """
        Signals the guardian process to just restart.
        """
        print("--- [System] Signaling Restart to Guardian in 1s... ---")
        time.sleep(1)
        os._exit(6)
