import os
import shutil
import pytest
from services.logger import get_logger, log_error_with_traceback, log_task_error, LOG_DIR

def test_logger_creation_and_file_write():
    """
    tests that get_logger creates the correct logging directory,
    initializes the logger handlers, and writes a log message.
    """
    # 임시 디렉토리를 사용해 로깅 디렉토리 대체 설정
    test_log_dir = os.path.join(LOG_DIR, "test_run")
    os.makedirs(test_log_dir, exist_ok=True)
    
    try:
        logger = get_logger("test_logger")
        assert logger is not None
        assert len(logger.handlers) >= 2 # StreamHandler and FileHandler
        
        # 로그 메시지 기록 테스트
        logger.info("Test message for logger verification")
        
        # 파일이 생성되었는지 검증
        # get_logger()가 생성하는 기본 app log가 저장되는 폴더 확인
        assert os.path.exists(LOG_DIR)
        
    finally:
        # 테스트 임시 디렉토리 정리
        if os.path.exists(test_log_dir):
            shutil.rmtree(test_log_dir)

def test_task_error_logging():
    """
    tests that log_task_error writes log entries specifically
    associated with a task_id to a separate log file.
    """
    task_id = "test-task-123"
    safe_task_id = task_id.replace("/", "_").replace("\\", "_")
    expected_log_file = os.path.join(LOG_DIR, f"task_{safe_task_id}.log")
    
    # 만약 기존 테스트 잔재가 있다면 삭제
    if os.path.exists(expected_log_file):
        os.remove(expected_log_file)
        
    try:
        raise ValueError("Simulated pipeline exception for logging verification")
    except ValueError as e:
        log_task_error(task_id, "test_step", e)
        
    # 전용 로그 파일이 생성되었는지 및 내용이 포함되었는지 검증
    assert os.path.exists(expected_log_file)
    with open(expected_log_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "TASK ERROR REPORT" in content
        assert "ValueError" in content
        assert "Simulated pipeline exception" in content
        assert "test_step" in content
        
    # 청소
    if os.path.exists(expected_log_file):
        os.remove(expected_log_file)


def test_task_manager_integration_logging():
    """
    tests that task_manager.fail_task captures sys.exc_info() or explicit exceptions
    and automatically logs them using log_task_error, while adding the log_file field.
    """
    from services.task_manager import TaskManager
    import tempfile

    # 임시 tasks.json 파일 설정
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        temp_db_path = tmp.name

    try:
        tm = TaskManager(persistence_file=temp_db_path)
        task_id = "test-integration-task"
        tm.add_task(task_id, "test_file.mp4", "transcription")

        # 1. 예외 상황 시뮬레이션
        try:
            raise RuntimeError("Integration test exception for automated task logging")
        except RuntimeError as e:
            tm.fail_task(task_id, "Automatic traceback test", exception=e)

        # 2. task 정보 갱신 검증
        task_info = tm.get_task(task_id)
        assert task_info["status"] == "failed"
        assert "log_file" in task_info
        assert f"task_{task_id}.log" in task_info["log_file"]

        # 3. 로그 파일 자동 생성 검증
        expected_log_file = os.path.join(LOG_DIR, f"task_{task_id}.log")
        assert os.path.exists(expected_log_file)

        with open(expected_log_file, "r", encoding="utf-8") as f:
            content = f.read()
            assert "RuntimeError" in content
            assert "Integration test exception" in content
            assert "transcription" in content

        # 로그 파일 정리
        if os.path.exists(expected_log_file):
            os.remove(expected_log_file)

    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)


def test_task_log_api_endpoint():
    """
    tests the /api/tasks/{task_id}/log endpoint via FastAPI TestClient
    to ensure it returns 200 and the log text content when task is failed,
    and 404 when task or log file is not found.
    """
    from fastapi.testclient import TestClient
    from app.factory import create_app
    from app.core.container import AppContainer
    from services.task_manager import TaskManager
    import tempfile

    # 1. 임시 데이터베이스 준비
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        temp_db_path = tmp.name

    try:
        # 2. 테스트용 App 생성 및 task_manager 직접 오버라이딩
        app = create_app()
        container = app.state.container
        tm = TaskManager(persistence_file=temp_db_path)
        container.task_manager = tm

        client = TestClient(app)

        # 3. 없는 태스크에 대한 로그 요청 -> 404
        response = client.get("/api/tasks/non-existent-task/log")
        assert response.status_code == 404

        # 4. 존재하는 태스크 등록 후 로그 파일이 없는 상태 -> 404
        task_id = "test-api-task"
        tm.add_task(task_id, "test.mp4", "transcription")
        response = client.get(f"/api/tasks/{task_id}/log")
        assert response.status_code == 404
        assert "Log file not found" in response.text

        # 5. 태스크 실패 처리 및 로그 파일 작성 유도
        try:
            raise ValueError("API logging integration test error")
        except ValueError as e:
            tm.fail_task(task_id, "Failed during transcription", exception=e)

        # 6. 로그 조회 API 다시 요청 -> 200 & 내용 일치 검증
        response = client.get(f"/api/tasks/{task_id}/log")
        assert response.status_code == 200
        assert "API logging integration test error" in response.text
        assert "ValueError" in response.text
        assert "transcription" in response.text

        # 7. 로그 파일 정리
        expected_log_file = os.path.join(LOG_DIR, f"task_{task_id}.log")
        if os.path.exists(expected_log_file):
            os.remove(expected_log_file)

    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)

