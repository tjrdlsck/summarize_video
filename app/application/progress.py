"""Progress translation helpers."""


class TaskProgressWrapper:
    """하위 모듈 진행률을 전체 파이프라인 진행률로 변환합니다."""

    def __init__(self, real_task_manager, task_id: str, start_offset: int, scale_factor: float):
        self.tm = real_task_manager
        self.task_id = task_id
        self.offset = start_offset
        self.scale = scale_factor

    def update_progress(self, task_id: str, progress: int, message: str = None) -> None:
        del task_id  # Wrapper 생성 시 받은 task_id를 사용합니다.
        scaled_progress = self.offset + int(progress * self.scale)
        self.tm.update_progress(self.task_id, scaled_progress, message)

    def is_cancelled(self, task_id: str) -> bool:
        del task_id
        return self.tm.is_cancelled(self.task_id)

    def complete_task(self, task_id: str, result_data: dict) -> None:
        """체이닝 실행 중 하위 단계 완료 시 부모 태스크가 조기 완료 처리되지 않도록 차단합니다."""
        pass

    def fail_task(self, task_id: str, error_msg: str, exception: Exception = None) -> None:
        """하위 단계 실패 시 즉각 부모 태스크에 전파하여 전체 태스크를 실패 처리합니다."""
        self.tm.fail_task(self.task_id, error_msg, exception)
