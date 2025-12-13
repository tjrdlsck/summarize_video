import asyncio

class TaskManager:
    """
    비동기 작업의 상태(Status), 진행률(Progress), 메시지(Message)를 관리하는 클래스.
    메모리 내 딕셔너리를 사용하여 데이터를 관리합니다.
    """
    def __init__(self):
        # 구조: { "task_id": { "status": "...", "progress": 0, "message": "...", ... } }
        self.tasks = {}

    def add_task(self, task_id: str, filename: str, task_type: str = "analysis"):
        """
        새로운 작업을 등록합니다.
        
        Args:
            task_id (str): 작업 고유 ID
            filename (str): 관련 파일명 (표시용)
            task_type (str): 'analysis' (분석) 또는 'clip_export' (클립 내보내기) 등 작업 구분
        """
        self.tasks[task_id] = {
            "task_id": task_id,
            "filename": filename,
            "type": task_type,       # [New] UI에서 처리 방식을 구분하기 위한 필드
            "status": "pending",     # pending, processing, completed, failed
            "progress": 0,           # 0 ~ 100 (int)
            "message": "대기 중...",  # 사용자에게 보여줄 상태 메시지
            "result": None,          # 완료 시 결과 데이터 (다운로드 링크 등)
            "error": None            # 실패 시 에러 메시지
        }

    def update_progress(self, task_id: str, progress: int, message: str = None):
        """
        작업의 진행률과 상태 메시지를 업데이트합니다.
        progress: 0~100 사이의 정수
        message: (선택) 상태 설명 텍스트
        """
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "processing"
            self.tasks[task_id]["progress"] = progress
            if message:
                self.tasks[task_id]["message"] = message

    def complete_task(self, task_id: str, result: dict):
        """작업을 완료 상태로 변경하고 결과를 저장합니다."""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "completed"
            self.tasks[task_id]["progress"] = 100
            self.tasks[task_id]["message"] = "분석 완료!"
            self.tasks[task_id]["result"] = result

    def fail_task(self, task_id: str, error_message: str):
        """작업을 실패 상태로 변경하고 에러를 기록합니다."""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "failed"
            self.tasks[task_id]["progress"] = 0
            self.tasks[task_id]["message"] = "오류 발생"
            self.tasks[task_id]["error"] = error_message

    def get_task(self, task_id: str):
        """특정 작업의 정보를 반환합니다."""
        return self.tasks.get(task_id)

    def get_active_tasks(self):
        """
        현재 진행 중인 작업(pending, processing) 목록을 반환합니다.
        UI의 'Task Monitor'에서 폴링할 때 사용됩니다.
        """
        active_list = []
        for tid, info in self.tasks.items():
            if info["status"] in ["pending", "processing"]:
                active_list.append(info)
        # 최신 작업이 위로 오도록 정렬 (선택 사항)
        return sorted(active_list, key=lambda x: x['progress'], reverse=True)

    def delete_task(self, task_id: str):
        """메모리에서 작업 정보를 삭제합니다."""
        if task_id in self.tasks:
            del self.tasks[task_id]