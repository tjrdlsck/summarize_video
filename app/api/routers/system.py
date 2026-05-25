"""System maintenance routes."""

import os
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse

from services.system_manager import SystemManager
from services.logger import LOG_DIR

router = APIRouter()


@router.get("/api/system/check-update")
async def check_update():
    """원격 저장소와 비교하여 업데이트 필요 여부를 확인합니다."""
    return SystemManager.check_for_updates()


@router.post("/api/system/update")
async def update_system(background_tasks: BackgroundTasks):
    """업데이트 수행 후 서버 재시작 신호를 보냅니다."""
    try:
        background_tasks.add_task(SystemManager.perform_update)
        return {"status": "success", "message": "Update initiated. Server will restart shortly."}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/api/system/restart-status")
async def restart_status():
    """자동 재시작 예약 상태를 반환합니다."""
    return SystemManager.get_restart_status()


@router.post("/api/system/restart-now")
async def restart_now(background_tasks: BackgroundTasks):
    """예약된 재시작이 있으면 즉시 재시작을 수행합니다."""
    try:
        background_tasks.add_task(SystemManager.restart_now)
        return {"status": "success", "message": "Restart requested. Server will restart shortly."}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))

@router.get("/api/system/logs")
async def get_logs_list():
    """서버 및 태스크 로그 파일 목록을 반환합니다."""
    try:
        if not os.path.exists(LOG_DIR):
            return {"logs": []}
            
        log_files = []
        for filename in os.listdir(LOG_DIR):
            if filename.endswith(".log"):
                filepath = os.path.join(LOG_DIR, filename)
                stat = os.stat(filepath)
                log_files.append({
                    "filename": filename,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        # 최신 수정순 정렬
        log_files.sort(key=lambda x: x["modified"], reverse=True)
        return {"logs": log_files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/system/logs/{filename}")
async def get_log_content(filename: str):
    """특정 로그 파일의 내용을 반환합니다."""
    try:
        # 경로 이탈 방지 (Path Traversal 방어)
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
            
        filepath = os.path.join(LOG_DIR, filename)
        if not os.path.exists(filepath):
            raise HTTPException(status_code=404, detail="Log file not found")
            
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        return PlainTextResponse(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
