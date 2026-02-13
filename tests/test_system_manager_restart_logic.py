"""SystemManager restart scheduling logic tests."""

from services.system_manager import SystemManager


class DummyTaskManager:
    def __init__(self, tasks):
        self.tasks = tasks


class DummyTimer:
    def __init__(self, interval, target):
        self.interval = interval
        self.target = target
        self.started = False
        self.cancelled = False
        self.daemon = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def _reset_system_manager_state():
    SystemManager._restart_requested = False
    SystemManager._restart_timer = None
    SystemManager._restart_deadline = None
    SystemManager._restart_reason = None
    SystemManager._restart_delay_seconds = 60


def test_restart_is_scheduled_only_when_active_tasks_are_gone(monkeypatch):
    _reset_system_manager_state()
    created_timers = []

    def fake_timer(interval, target):
        timer = DummyTimer(interval, target)
        created_timers.append(timer)
        return timer

    monkeypatch.setattr("services.system_manager.threading.Timer", fake_timer)

    active_tasks = {"a": {"status": "processing"}}
    failed_tasks = {"a": {"status": "failed"}, "b": {"status": "completed"}}

    SystemManager.request_restart_after_failures("yt-dlp updated", delay_seconds=60)

    assert SystemManager.maybe_schedule_restart(DummyTaskManager(active_tasks), queue_size=0) is False
    assert SystemManager.maybe_schedule_restart(DummyTaskManager(failed_tasks), queue_size=1) is False
    assert SystemManager.maybe_schedule_restart(DummyTaskManager(failed_tasks), queue_size=0) is True
    assert len(created_timers) == 1
    assert created_timers[0].started is True


def test_restart_now_cancels_timer_and_calls_restart(monkeypatch):
    _reset_system_manager_state()
    timer = DummyTimer(60, lambda: None)
    SystemManager._restart_timer = timer
    SystemManager._restart_requested = True

    called = {"restart": False}

    def fake_restart():
        called["restart"] = True

    monkeypatch.setattr(SystemManager, "restart_server", staticmethod(fake_restart))

    SystemManager.restart_now()

    assert timer.cancelled is True
    assert called["restart"] is True
    assert SystemManager._restart_timer is None
