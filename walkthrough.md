# 🚀 Walkthrough: 실패/취소 작업 자동 정돈(Auto-dismiss) 및 상태 관리 버그 수정

오류가 발생하거나 취소된 작업이 서버를 재시작하기 전까지 작업 대기열 모니터 화면에서 영구히 사라지지 않던 버그를 분석 및 해결하고, 전체 회귀 테스트를 완료한 보고서입니다.

---

## 💡 변경 사항 요약 (Changes Made)

### 1. `TaskManager` TTL 타임스탬프 기반 자동 스크리닝
* **파일**: [`services/task_manager.py`](file:///home/radi/cli/summarize_video/services/task_manager.py)
* **내용**:
  * `request_cancel`, `complete_task`, `fail_task` 호출 시 작업 완료/종료 시점의 UNIX 타임스탬프(`finished_at`)를 기록합니다.
  * `get_active_tasks(ttl_seconds=10.0)` 메서드에서 실패(`failed`), 취소(`canceled`), 완료(`completed`, 클립 생성을 제외한 일반 태스크) 건이 10초(TTL) 경과 시 `active_list` 반환 결과에서 **자동 제외**되도록 조치했습니다.

### 2. 파이프라인 취소 시 상태 덮어쓰기 방지
* **파일**: [`app/application/pipeline_runner.py`](file:///home/radi/cli/summarize_video/app/application/pipeline_runner.py)
* **내용**:
  * 사용자가 작업을 취소하여 `TaskCancelledError` 예외가 발생했을 때, `fail_task(...)` 대신 `request_cancel(...)`을 부르도록 교체하여 작업 상태가 `"failed"`(오류 발생)로 덮어씌워지는 버그를 차단하고 `"canceled"`(취소됨) 상태를 보존했습니다.

### 3. 프론트엔드 작업 모니터 위젯 10초 자동 닫기 (Auto-dismiss)
* **파일**: [`static/js/components.js`](file:///home/radi/cli/summarize_video/static/js/components.js)
* **내용**:
  * `TaskMonitor` 컴포넌트 내부 `React.useEffect` 훅을 이용하여 실패 또는 취소된 태스크가 존재할 때, 10초 후 프론트엔드에서 자동으로 `onCancel(t.task_id, true)` (즉 `DELETE /api/tasks/{task_id}`)를 호출하여 화면 우측 하단에서 매끄럽게 자동 퇴장(Auto-dismiss) 처리되도록 보완했습니다.

---

## 🧪 테스트 및 검증 결과 (Validation Results)

### 1. 신규 단위 테스트 (`tests/test_task_auto_cleanup.py`)
```bash
./venv/bin/pytest tests/test_task_auto_cleanup.py -v
```
* `test_task_manager_ttl_cleanup` **PASSED**: 10초(TTL) 경과 시 `get_active_tasks()`에서 실패/취소 태스크 자동 제외 검증 완료
* `test_pipeline_cancel_preserves_canceled_status` **PASSED**: 사용자 취소 시 상태가 `failed`가 아닌 `canceled`로 보존됨을 검증 완료

### 2. 전체 회귀 테스트 (Full Test Suite)
```bash
./venv/bin/pytest tests/ -v
```
* **결과**: `50 passed, 2 warnings in 12.34s` (전체 50개 테스트 100% PASSED 통과)
