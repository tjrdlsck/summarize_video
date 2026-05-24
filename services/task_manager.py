import json
import os
import asyncio  # [Add] 비동기 이벤트 처리를 위해 추가
import threading # [Add] 데이터 무결성을 위한 락 도입

class TaskManager:
    """
    작업 상태를 'tasks.json' 파일에 저장하여 서버가 재시작되어도 상태를 유지합니다.
    """
    def __init__(self, persistence_file="tasks.json"):
        self.persistence_file = persistence_file
        # [Add] 데이터 보호를 위한 스레드 잠금 객체 생성
        self._lock = threading.Lock()
        self.tasks = self._load_tasks() 
        # [Add] 런타임 취소 이벤트를 관리할 딕셔너리 (JSON 저장 불가하므로 별도 관리)
        self.cancel_events = {}

    def _load_tasks(self):
        """파일에서 작업 목록을 불러옵니다."""
        # 로드 시에도 락을 사용하여 읽기-쓰기 충돌 방지
        with self._lock:
            if os.path.exists(self.persistence_file):
                try:
                    with open(self.persistence_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    return {}
            return {}

    def _save_tasks(self):
        """
        작업 목록을 파일에 저장합니다.
        [Guarded] 락을 사용하여 한 번에 하나의 프로세스만 파일에 접근하도록 보장합니다.
        """
        temp_file = f"{self.persistence_file}.tmp"
        with self._lock:
            try:
                # 1. 임시 파일에 쓰기
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(self.tasks, f, ensure_ascii=False, indent=2)
                
                # 2. 파일 교체 (Atomic operation)
                os.replace(temp_file, self.persistence_file)
            except Exception as e:
                print(f"[TaskManager Error] Failed to save tasks: {e}")
                if os.path.exists(temp_file):
                    try: os.remove(temp_file)
                    except: pass

    def add_task(self, task_id: str, filename: str, task_type: str = "analysis"):
        """
        작업을 등록하고 대기열(queued) 상태로 초기화합니다.
        """
        # 1. 런타임용 취소 이벤트 생성
        self.cancel_events[task_id] = asyncio.Event()

        # 2. 작업 정보 등록
        with self._lock:
            self.tasks[task_id] = {
                "task_id": task_id,
                "filename": filename,
                "type": task_type,
                "status": "queued",
                "progress": 0,
                "message": "대기열 진입...",
                "result": None,
                "error": None
            }
        self._save_tasks()

    def update_progress(self, task_id: str, progress: int, message: str = None):
        """
        작업의 진행률을 업데이트합니다.
        """
        with self._lock:
            if task_id not in self.tasks:
                return

            current_status = self.tasks[task_id]["status"]
            if current_status in ["canceled", "failed"]:
                return

            self.tasks[task_id]["status"] = "processing"
            self.tasks[task_id]["progress"] = progress
            if message:
                self.tasks[task_id]["message"] = message
            
        self._save_tasks()

    def request_cancel(self, task_id: str):
        """
        특정 작업에 취소 요청을 보냅니다.
        """
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]["status"] = "canceled"
                self.tasks[task_id]["message"] = "취소 요청됨..."
            
        if task_id in self.cancel_events:
            self.cancel_events[task_id].set()
            
        self._save_tasks()

    def is_cancelled(self, task_id: str) -> bool:
        """
        작업이 취소되었는지 확인합니다.
        """
        # 이벤트 객체 확인
        if task_id in self.cancel_events and self.cancel_events[task_id].is_set():
            return True
            
        # DB 상태 확인
        with self._lock:
            task = self.tasks.get(task_id)
            if task and task.get("status") == "canceled":
                return True
            
        return False

    def complete_task(self, task_id: str, result: dict):
        """
        작업을 완료 상태로 마킹합니다.
        """
        with self._lock:
            if task_id not in self.tasks:
                return

            current_status = self.tasks[task_id]["status"]
            if current_status in ["canceled", "failed"]:
                return

            self.tasks[task_id]["status"] = "completed"
            self.tasks[task_id]["progress"] = 100
            self.tasks[task_id]["message"] = "완료!"
            self.tasks[task_id]["result"] = result
            
        self._save_tasks()

    def fail_task(self, task_id: str, error_message: str, exception: Exception = None):
        import sys
        safe_task_id = str(task_id).replace("/", "_").replace("\\", "_")
        log_filename = f"task_{safe_task_id}.log"

        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]["status"] = "failed"
                self.tasks[task_id]["progress"] = 0
                self.tasks[task_id]["message"] = "오류 발생"
                self.tasks[task_id]["error"] = error_message
                self.tasks[task_id]["log_file"] = f"/static/logs/{log_filename}"
        self._save_tasks()

        # 예외(exception) 객체 자동 캡처
        exc = exception
        if exc is None:
            _, exc_val, _ = sys.exc_info()
            if exc_val is not None:
                exc = exc_val

        if exc is not None:
            try:
                from services.logger import log_task_error
                step_name = self.tasks.get(task_id, {}).get("type", "pipeline")
                log_task_error(task_id, step_name, exc)
            except Exception as log_err:
                print(f"[Backup Warning] Failed to log task error: {log_err}")

    def get_task(self, task_id: str):
        with self._lock:
            return self.tasks.get(task_id)

    def get_active_tasks(self):
        active_list = []
        with self._lock:
            for tid, info in self.tasks.items():
                if info["status"] in ["queued", "pending", "processing", "canceling", "failed", "canceled"]:
                    active_list.append(info)
                elif info["status"] == "completed" and info.get("type") == "clip_export":
                    active_list.append(info)
        
        return sorted(active_list, key=lambda x: x['progress'], reverse=True)

    def delete_task(self, task_id: str):
        with self._lock:
            if task_id in self.tasks:
                del self.tasks[task_id]
        self._save_tasks()