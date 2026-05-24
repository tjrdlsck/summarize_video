import json
import os
import uuid
from typing import List

from fastapi import APIRouter, HTTPException

from app.core.paths import RESULTS_DIR
from app.schemas.requests import FolderCreateRequest, FolderMoveRequest

router = APIRouter()

FOLDERS_FILE = os.path.join(RESULTS_DIR, "folders.json")


def _read_folders():
    if not os.path.exists(FOLDERS_FILE):
        return []
    try:
        with open(FOLDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _write_folders(data):
    with open(FOLDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("/api/folders")
async def get_folders():
    """전체 폴더 목록 조회."""
    return _read_folders()


@router.post("/api/folders")
async def create_folder(req: FolderCreateRequest):
    """새 폴더 생성."""
    folders = _read_folders()
    
    # 중복 이름 확인
    if any(f["name"] == req.name for f in folders):
        raise HTTPException(status_code=400, detail="이미 존재하는 폴더 이름입니다.")
        
    new_folder = {
        "id": str(uuid.uuid4()),
        "name": req.name,
        "created_at": __import__('time').time()
    }
    folders.append(new_folder)
    _write_folders(folders)
    
    return {"status": "success", "folder": new_folder}


@router.delete("/api/folders/{folder_id}")
async def delete_folder(folder_id: str):
    """폴더 삭제. (폴더 안의 영상들은 루트로 복구)"""
    folders = _read_folders()
    filtered = [f for f in folders if f["id"] != folder_id]
    
    if len(folders) == len(filtered):
        raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다.")
        
    _write_folders(filtered)
    
    # 해당 폴더에 있던 영상들의 folder_id 초기화
    if os.path.exists(RESULTS_DIR):
        for filename in os.listdir(RESULTS_DIR):
            if filename.endswith("_summary.json"):
                json_path = os.path.join(RESULTS_DIR, filename)
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    if data.get("folder_id") == folder_id:
                        data["folder_id"] = None
                        with open(json_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
                    
    return {"status": "success", "message": "폴더가 삭제되었습니다."}


@router.post("/api/folders/move")
async def move_video(req: FolderMoveRequest):
    """특정 영상을 폴더로 이동(혹은 루트로 꺼냄)."""
    if req.folder_id:
        folders = _read_folders()
        if not any(f["id"] == req.folder_id for f in folders):
            raise HTTPException(status_code=404, detail="대상 폴더를 찾을 수 없습니다.")
            
    base_name = os.path.splitext(req.filename)[0]
    json_path = os.path.join(RESULTS_DIR, f"{base_name}_summary.json")
    
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="영상 데이터 파일을 찾을 수 없습니다.")
        
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        data["folder_id"] = req.folder_id
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"이동 실패: {str(e)}")
        
    return {"status": "success", "folder_id": req.folder_id}
