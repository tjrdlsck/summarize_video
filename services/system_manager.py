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
        return config.get("models", {}).get(task_type, cls.DEFAULT_CONFIG["models"].get(task_type))

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
