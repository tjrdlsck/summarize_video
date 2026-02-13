"""Regression tests for progress conversion wrapper."""

from app.application.progress import TaskProgressWrapper


class DummyTaskManager:
    def __init__(self) -> None:
        self.calls = []
        self.cancelled = False

    def update_progress(self, task_id, progress, message=None):
        self.calls.append((task_id, progress, message))

    def is_cancelled(self, task_id):
        del task_id
        return self.cancelled


def test_progress_wrapper_scales_local_percent_to_global_range():
    manager = DummyTaskManager()
    wrapper = TaskProgressWrapper(manager, "task-1", start_offset=20, scale_factor=0.8)

    wrapper.update_progress("ignored", 50, "processing")

    assert manager.calls == [("task-1", 60, "processing")]


def test_progress_wrapper_delegates_cancellation_check():
    manager = DummyTaskManager()
    manager.cancelled = True
    wrapper = TaskProgressWrapper(manager, "task-2", start_offset=10, scale_factor=0.5)

    assert wrapper.is_cancelled("ignored") is True
