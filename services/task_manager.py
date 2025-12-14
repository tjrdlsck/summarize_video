import json
import os
import asyncio  # [Add] 비동기 이벤트 처리를 위해 추가

class TaskManager:
    """
    작업 상태를 'tasks.json' 파일에 저장하여 서버가 재시작되어도 상태를 유지합니다.
    """
    def __init__(self, persistence_file="tasks.json"):
        self.persistence_file = persistence_file
        self.tasks = self._load_tasks() 
        # [Add] 런타임 취소 이벤트를 관리할 딕셔너리 (JSON 저장 불가하므로 별도 관리)
        self.cancel_events = {}

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
        """
        작업을 등록하고 대기열(queued) 상태로 초기화합니다.
        동시에 해당 작업에 대한 취소 이벤트 제어권을 생성합니다.
        """
        # 1. 런타임용 취소 이벤트 생성 (기본값: Set=False)
        self.cancel_events[task_id] = asyncio.Event()

        # 2. 작업 정보 등록
        self.tasks[task_id] = {
            "task_id": task_id,
            "filename": filename,
            "type": task_type,
            "status": "queued",  # [Modify] 초기 상태를 pending -> queued로 변경
            "progress": 0,
            "message": "대기열 진입...",
            "result": None,
            "error": None
        }
        self._save_tasks()

    def update_progress(self, task_id: str, progress: int, message: str = None):
        """
        작업의 진행률을 업데이트합니다.
        [수정] 이미 취소되거나 실패한 작업은 업데이트를 무시하는 '방어 로직' 추가
        """
        if task_id not in self.tasks:
            return

        # [Guard Logic] 좀비 프로세스 방어
        # 작업이 이미 취소되었거나 실패했다면, 더 이상의 진행 보고를 받지 않음
        current_status = self.tasks[task_id]["status"]
        if current_status in ["canceled", "failed"]:
            return

        # 정상 상태일 때만 업데이트 수행
        self.tasks[task_id]["status"] = "processing"
        self.tasks[task_id]["progress"] = progress
        if message:
            self.tasks[task_id]["message"] = message
            
        # (선택 사항) I/O 부하가 걱정된다면 저장 주기를 조절할 수 있습니다.
        # 여기서는 데이터 일관성을 위해 매번 저장합니다.
        self._save_tasks()

    def request_cancel(self, task_id: str):
        """
        [New] 특정 작업에 취소 요청을 보냅니다.
        """
        if task_id in self.tasks:
            # 1. 상태 업데이트
            self.tasks[task_id]["status"] = "canceled"
            self.tasks[task_id]["message"] = "취소 요청됨..."
            self._save_tasks()
            
            # 2. 실행 중인 스레드/코루틴에 신호 전송
            if task_id in self.cancel_events:
                self.cancel_events[task_id].set()  # Flag를 True로 설정
                print(f"[TaskManager] Cancel signal sent to {task_id}")

    def is_cancelled(self, task_id: str) -> bool:
        """
        [New] 작업이 취소되었는지 확인합니다. (Worker나 Transcriber가 호출)
        """
        # 1. 이벤트 객체 확인 (가장 빠름)
        if task_id in self.cancel_events and self.cancel_events[task_id].is_set():
            return True
            
        # 2. (재시작 등의 이유로 이벤트가 날아갔을 경우) DB 상태 확인
        task = self.tasks.get(task_id)
        if task and task.get("status") == "canceled":
            return True
            
        return False

    def complete_task(self, task_id: str, result: dict):
        """
        작업을 완료 상태로 마킹합니다.
        [수정] 취소된 작업이 완료로 덮어씌워지는 것을 방지
        """
        if task_id not in self.tasks:
            return

        # [Guard Logic] 취소된 작업은 완료 처리 거부
        current_status = self.tasks[task_id]["status"]
        if current_status in ["canceled", "failed"]:
            print(f"[TaskManager] Ignored completion for cancelled task: {task_id}")
            return

        self.tasks[task_id]["status"] = "completed"
        self.tasks[task_id]["progress"] = 100
        self.tasks[task_id]["message"] = "완료!"
        self.tasks[task_id]["result"] = result
        self._save_tasks()

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
        """
        [Modify] UI에 표시할 작업 목록을 반환합니다.
        기존에는 'processing'만 반환했으나, 이제 'queued'(대기중)와 'canceling'(취소중)도 포함해야 합니다.
        """
        active_list = []
        for tid, info in self.tasks.items():
            # [수정된 부분] 필터링 조건에 'queued'와 'canceling'을 추가합니다.
            # 'pending'은 레거시 호환성을 위해 남겨둡니다.
            if info["status"] in ["queued", "pending", "processing", "canceling"]:
                active_list.append(info)
        
        # 정렬 로직:
        # 1순위: 처리 중인 것 (progress > 0)
        # 2순위: 먼저 들어온 순서 (딕셔너리는 Python 3.7+부터 입력 순서 보장됨)
        # 단순히 progress 역순으로 하면 0%인 대기열들이 뒤로 가서 자연스럽게 정렬됩니다.
        return sorted(active_list, key=lambda x: x['progress'], reverse=True)

    def delete_task(self, task_id: str):
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._save_tasks()