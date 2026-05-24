# 시스템 업데이트 다운그레이드 기능 추가

현재 시스템은 최신 버전이 있을 때만 감지하여 업데이트를 수행합니다. 사용자가 원하는 이전 버전(Commit)으로 다운그레이드(롤백)할 수 있도록 시스템 전반(UI, API, 구동 스크립트)을 수정합니다.

## User Review Required

> [!WARNING]
> 이 기능은 `git reset --hard` 또는 `git checkout`을 사용하여 소스 코드를 강제로 과거 시점으로 되돌립니다.
> 과거 시점으로 이동하면 로컬에서 수정한 커밋되지 않은 코드가 유실될 수 있습니다. 
> 또한 과거 버전에서는 데이터베이스나 기타 설정 파일의 포맷이 달라 오류가 발생할 가능성도 있습니다.
> 
> 버전 목록을 보여줄 때 몇 개까지 보여주는 것이 좋을까요? 기본적으로 **최근 20개의 커밋**을 보여주도록 구현할 예정입니다.

## Proposed Changes

---

### Backend API & System Manager

#### [MODIFY] [system_manager.py](file:///home/radi/cli/summarize_video/services/system_manager.py)
- `get_versions(limit=20)` 메서드 추가: `git log` 명령어를 사용하여 최근 커밋 목록(해시, 날짜, 커밋 메시지)을 조회하여 반환.
- `perform_update(target_version: str = "latest")` 수정: 타겟 버전 정보를 `.target_version` 파일에 저장하여 `run.py` 프로세스가 읽을 수 있도록 전달.

#### [MODIFY] [requests.py](file:///home/radi/cli/summarize_video/app/schemas/requests.py)
- `SystemUpdateRequest` 스키마 추가: `target_version` 문자열을 포함하도록 정의.

#### [MODIFY] [system.py](file:///home/radi/cli/summarize_video/app/api/routers/system.py)
- `GET /api/system/versions` 엔드포인트 추가.
- `POST /api/system/update` 엔드포인트에서 `SystemUpdateRequest` 객체를 받아 `SystemManager.perform_update`를 호출할 때 타겟 버전을 넘기도록 수정.

---

### Guardian Process

#### [MODIFY] [run.py](file:///home/radi/cli/summarize_video/run.py)
- `UPDATE_SIGNAL (5)` 수신 시 로직 변경:
  - `.target_version` 파일이 존재하면 읽고 삭제.
  - 타겟 버전이 "latest" 이면 기존과 동일하게 `git checkout -B main origin/main` 실행.
  - 특정 커밋 해시가 타겟이면 `git reset --hard <target_version>`을 사용하여 해당 버전으로 롤백.

---

### Frontend UI

#### [MODIFY] [app.js](file:///home/radi/cli/summarize_video/static/js/app.js)
- 상단 배너 혹은 설정 영역에 **"버전 관리(Version History)"** 모달 버튼 추가.
- 모달 내부에서 `GET /api/system/versions` API를 호출하여 최근 업데이트 내역을 목록(리스트) 형태로 표시.
- 각 버전 아이템 옆에 **[이 버전으로 롤백]** 버튼을 배치.
- 롤백 진행 시 `POST /api/system/update`에 선택된 해시값을 전송하고 시스템을 재시작.

## Verification Plan

### Manual Verification
1. 프론트엔드에서 "버전 관리" 메뉴가 나타나는지 확인.
2. 버전 목록이 정상적으로 과거 커밋 내역(해시, 메시지)을 표시하는지 확인.
3. 과거의 특정 버전을 선택하고 롤백을 실행했을 때 서버가 재시작되며 해당 커밋으로 소스코드가 변경되는지 확인.
4. "최신 버전으로 업데이트" 기능을 통해 다시 원래 상태(최신화)로 복구 가능한지 확인.
