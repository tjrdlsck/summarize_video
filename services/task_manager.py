import json
import os

class TaskManager:
    """
    작업 상태를 'tasks.json' 파일에 저장하여 서버가 재시작되어도 상태를 유지합니다.
    """
    def __init__(self, persistence_file="tasks.json"):
        self.persistence_file = persistence_file
        self.tasks = self._load_tasks() # 초기화 시 파일 로드

    def _load_tasks(self):
        """파일에서 작업 목록을 불러옵니다."""
        if os.path.exists(self.persistence_file):
            try:
                with open(self.persistence_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_tasks(self):
        """작업 목록을 파일에 저장합니다."""
        try:
            with open(self.persistence_file, 'w', encoding='utf-8') as f:
                json.dump(self.tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[TaskManager Error] Failed to save tasks: {e}")

    def add_task(self, task_id: str, filename: str, task_type: str = "analysis"):
        self.tasks[task_id] = {
            "task_id": task_id,
            "filename": filename,
            "type": task_type,
            "status": "pending",
            "progress": 0,
            "message": "대기 중...",
            "result": None,
            "error": None
        }
        self._save_tasks() # 상태 변경 시 저장

    def update_progress(self, task_id: str, progress: int, message: str = None):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "processing"
            self.tasks[task_id]["progress"] = progress
            if message:
                self.tasks[task_id]["message"] = message
            
            # [Optimization] 너무 잦은 I/O를 막기 위해, 10% 단위 혹은 중요 메시지일 때만 저장 가능
            # 여기서는 안정성을 위해 매번 저장하되, 실제 서비스 시에는 Throttle 필요
            # self._save_tasks() -> 빈번한 호출 방지를 위해 생략 가능 (polling 메모리 사용)
            pass 

    def complete_task(self, task_id: str, result: dict):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "completed"
            self.tasks[task_id]["progress"] = 100
            self.tasks[task_id]["message"] = "완료!"
            self.tasks[task_id]["result"] = result
            self._save_tasks() # 완료 시 반드시 저장

    def fail_task(self, task_id: str, error_message: str):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "failed"
            self.tasks[task_id]["progress"] = 0
            self.tasks[task_id]["message"] = "오류 발생"
            self.tasks[task_id]["error"] = error_message
            self._save_tasks() # 실패 시 반드시 저장

    def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    def get_active_tasks(self):
        active_list = []
        for tid, info in self.tasks.items():
            # 완료되었더라도 사용자가 아직 확인 안 했을 수 있으므로, 
            # UI 정책에 따라 보여주는 방식이 다르지만 일단 모두 반환하거나 필터링
            if info["status"] in ["pending", "processing"]:
                active_list.append(info)
        return sorted(active_list, key=lambda x: x['progress'], reverse=True)

    def delete_task(self, task_id: str):
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._save_tasks()