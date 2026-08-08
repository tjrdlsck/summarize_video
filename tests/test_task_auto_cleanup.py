import time
import pytest
from services.task_manager import TaskManager


def test_task_manager_ttl_cleanup(tmp_path):
    """완료/실패/취소된 태스크가 10초(TTL) 경과 시 get_active_tasks() 반환 결과에서 자동 제외되는지 검증."""
    db_file = tmp_path / "test_tasks.json"
    tm = TaskManager(persistence_file=str(db_file))

    # 1. 활성 작업 및 실패/취소 작업 등록
    tm.add_task("task_active", "video1.mp4", "transcription")
    tm.add_task("task_failed", "video2.mp4", "analysis")
    tm.add_task("task_canceled", "video3.mp4", "shorts_generation")

    tm.fail_task("task_failed", "테스트 오류 발생")
    tm.request_cancel("task_canceled")

    # 방금 실패/취소 처리 직후에는 10초 미만이므로 활성 목록에 3개 모두 포함되어야 함 (TTL < 10)
    active_now = tm.get_active_tasks(ttl_seconds=10.0)
    task_ids_now = [t["task_id"] for t in active_now]
    assert "task_active" in task_ids_now
    assert "task_failed" in task_ids_now
    assert "task_canceled" in task_ids_now

    # 2. 강제로 finished_at 타임스탬프를 15초 전으로 변경하여 TTL 초과 시뮬레이션
    tm.tasks["task_failed"]["finished_at"] = time.time() - 15.0
    tm.tasks["task_canceled"]["finished_at"] = time.time() - 15.0

    active_after = tm.get_active_tasks(ttl_seconds=10.0)
    task_ids_after = [t["task_id"] for t in active_after]

    # TTL(10초)이 지난 failed/canceled 작업은 get_active_tasks() 결과에서 자동으로 제거되어야 함
    assert "task_active" in task_ids_after
    assert "task_failed" not in task_ids_after
    assert "task_canceled" not in task_ids_after


def test_pipeline_cancel_preserves_canceled_status(tmp_path):
    """request_cancel 호출 시 상태가 'canceled'로 정확히 유지되는지 검증."""
    db_file = tmp_path / "test_tasks.json"
    tm = TaskManager(persistence_file=str(db_file))

    task_id = "cancel_test_1"
    tm.add_task(task_id, "test_video.mp4", "transcription")
    tm.request_cancel(task_id)

    task_info = tm.get_task(task_id)
    assert task_info["status"] == "canceled"
    assert task_info["finished_at"] > 0
