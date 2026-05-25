import os
import logging
import traceback
import re
from datetime import datetime

# 로그 저장 디렉토리 정의
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "logs")

def mask_sensitive_info(text: str) -> str:
    """API 키 및 토큰과 같은 민감 정보를 마스킹 처리합니다."""
    if not isinstance(text, str):
        return str(text)
    # OpenAI API Key 패턴 마스킹 (sk-...)
    text = re.sub(r'sk-[a-zA-Z0-9]{32,}', '***MASKED_API_KEY***', text)
    # Bearer 토큰 패턴 마스킹
    text = re.sub(r'Bearer\s+[a-zA-Z0-9\-\._~+/]+=*', 'Bearer ***MASKED_TOKEN***', text)
    return text

def get_logger(name="video_summarizer"):
    """
    프로젝트 공통 로거를 반환합니다.
    콘솔 출력(StreamHandler)과 파일 출력(FileHandler)을 동시에 지원하며,
    일별/태스크별 로그 작성이 가능하도록 설계되었습니다.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    
    logger = logging.getLogger(name)
    # 이미 핸들러가 설정되어 있다면 추가 방지
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)
    
    # 1. 포맷터 정의 (시간, 로그레벨, 프로세스 ID, 코드 라인, 메시지 포함)
    log_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [PID:%(process)d] [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 2. 콘솔 핸들러 추가
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)
    
    # 3. 공통 로그 파일 핸들러 추가 (일별 로그 파일 생성)
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_file_path = os.path.join(LOG_DIR, f"app_{today_str}.log")
    
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)
    
    return logger

def log_error_with_traceback(logger, message, exception):
    """
    예외 객체와 트레이스백(Traceback) 상세 내역을 로그 파일과 콘솔에 기록합니다.
    """
    tb_lines = traceback.format_exception(type(exception), exception, exception.__traceback__)
    tb_text = "".join(tb_lines)
    
    masked_message = mask_sensitive_info(message)
    masked_exc_str = mask_sensitive_info(str(exception))
    masked_tb_text = mask_sensitive_info(tb_text)
    
    logger.error(f"{masked_message}\n[Exception Info]\nType: {type(exception).__name__}\nMessage: {masked_exc_str}\n\n[Traceback Details]\n{masked_tb_text}")

def log_task_error(task_id, step_name, exception):
    """
    개별 태스크 수행 도중 발생한 에러를 전용 태스크 로그 파일에 독립적으로 기록합니다.
    이를 통해 특정 작업 실패 시 디버깅을 신속히 수행할 수 있습니다.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = get_logger()
    
    # 태스크 전용 로그 파일 경로
    safe_task_id = str(task_id).replace("/", "_").replace("\\", "_")
    task_log_path = os.path.join(LOG_DIR, f"task_{safe_task_id}.log")
    
    # 예외 상세 정보 가공
    tb_lines = traceback.format_exception(type(exception), exception, exception.__traceback__)
    tb_text = "".join(tb_lines)
    
    masked_exc_str = mask_sensitive_info(str(exception))
    masked_tb_text = mask_sensitive_info(tb_text)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = (
        f"==================================================\n"
        f"[{timestamp}] TASK ERROR REPORT\n"
        f"==================================================\n"
        f"Task ID: {task_id}\n"
        f"Failed Step: {step_name}\n"
        f"Error Type: {type(exception).__name__}\n"
        f"Error Message: {masked_exc_str}\n"
        f"--------------------------------------------------\n"
        f"Traceback:\n{masked_tb_text}"
        f"==================================================\n\n"
    )
    
    # 태스크 로그 파일에 쓰기
    try:
        with open(task_log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
        logger.info(f"[Logger] Successfully wrote detailed task error report to {task_log_path}")
    except Exception as log_err:
        logger.error(f"[Logger] Failed to write task log file: {log_err}")
