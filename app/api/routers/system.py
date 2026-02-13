"""System maintenance routes."""

from fastapi import APIRouter, BackgroundTasks, HTTPException

from services.system_manager import SystemManager

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
