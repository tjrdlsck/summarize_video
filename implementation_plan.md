# [Implementation Plan] 실패/취소 작업 자동 정돈(Auto-dismiss) 및 상태 관리 버그 수정

작업이 오류 발생(`failed`) 또는 취소(`canceled`)되었을 때 서버를 재시작하기 전까지 작업 대기열 모니터에서 계속 남아있는 버그를 해결하기 위한 기술 구현 계획입니다.

## User Review Required

> [!NOTE]
> 이번 수정을 통해 실패하거나 취소된 작업은 사용자가 수동으로 '닫기' 버튼을 누르거나, **10초가 지나면 백엔드 및 프론트엔드 작업 모니터에서 자동으로 매끈하게 퇴장(Auto-dismiss)** 처리됩니다.

> [!IMPORTANT]
> 1. **취소 상태 보존**: 기존에는 사용자 취소 시 `TaskCancelledError` 내부에서 `fail_task`를 호출하여 상태가 `"failed"` (오류 발생)로 잘못 덮어씌워지는 문제가 있었습니다. 이를 개선하여 `"canceled"` (취소됨) 상태를 정확히 유지합니다.
> 2. **백엔드 TTL(Time-To-Live) 자동 청소**: 백엔드 `get_active_tasks()`에서 실패/취소된 작업이 발생한 지 10초가 지나면 `GET /api/tasks` 활성 목록 반환에서 자동으로 제외합니다.

## Proposed Changes

### 1. `TaskManager` TTL 타임스탬프 기록 및 자동 제외 로직
#### [MODIFY] [`services/task_manager.py`](file:///home/radi/cli/summarize_video/services/task_manager.py)

* **완료/실패/취소 시점 타임스탬프 기록 및 TTL 검증**:
  ```python
  def get_active_tasks(self):
      active_list = []
      now = time.time()
      TTL_SECONDS = 10.0  # 완료/실패/취소 후 활성 목록 노출 시간 (10초)

      with self._lock:
          for tid, info in self.tasks.items():
              status = info.get("status")
              finished_at = info.get("finished_at", 0.0)

              if status in ["queued", "pending", "processing", "canceling"]:
                  active_list.append(info)
              elif status in ["failed", "canceled", "completed"]:
                  # clip_export 완료 건은 다운로드 링크 제공을 위해 유지하되, 나머지는 10초 이내만 반환
                  if info.get("type") == "clip_export" and status == "completed":
                      active_list.append(info)
                  elif finished_at > 0 and (now - finished_at) < TTL_SECONDS:
                      active_list.append(info)

      return sorted(active_list, key=lambda x: x['progress'], reverse=True)
  ```

* **`fail_task`, `request_cancel`, `complete_task`에 `finished_at` 타임스탬프 기록**:
  ```python
  info["finished_at"] = time.time()
  ```

---

### 2. 파이프라인 취소 시 상태 덮어쓰기 방지
#### [MODIFY] [`app/application/pipeline_runner.py`](file:///home/radi/cli/summarize_video/app/application/pipeline_runner.py)

* **`TaskCancelledError` 예외 핸들러 상태 보존**:
  ```python
  except TaskCancelledError:
      print(f"[{task_id}] Task Cancelled by User.")
      cleanup_files(str(video_filename) if video_filename else None)
      # fail_task 대신 status를 'canceled'로 확정
      task_manager.request_cancel(task_id)
  ```

---

### 3. 프론트엔드 작업 모니터 10초 자동 닫기 (Auto-dismiss)
#### [MODIFY] [`static/js/components.js`](file:///home/radi/cli/summarize_video/static/js/components.js)

* **`TaskMonitor` 컴포넌트 자동 타이머 닫기 구현**:
  ```javascript
  React.useEffect(() => {
      const dismissible = tasks.filter(t => (t.status === 'failed' || t.status === 'canceled') && t.finished_at);
      dismissible.forEach(t => {
          const elapsed = Date.now() - (t.finished_at * 1000);
          const remaining = Math.max(0, 10000 - elapsed);
          setTimeout(() => {
              onCancel(t.task_id, true);
          }, remaining);
      });
  }, [tasks]);
  ```

---

## Verification Plan

### Automated Tests
1. **신규 단위 테스트 작성 및 실행**: `tests/test_task_auto_cleanup.py`
   - `test_task_manager_ttl_cleanup()`: 10초 경과 시 `get_active_tasks()`에서 실패/취소 작업 자동 제외 검증
   - `test_pipeline_cancel_preserves_canceled_status()`: 취소 시 `status`가 `canceled`로 보존되는지 검증
   - **실행 명령**: `pytest tests/test_task_auto_cleanup.py -v`

2. **전체 단위/통합 테스트 회귀 검증**:
   - **실행 명령**: `pytest tests/`

### Manual Verification
1. 작업을 시작한 후 '취소' 버튼을 눌렀을 때 상태가 `"오류 발생"`이 아닌 `"취소됨"`으로 표시되는지 확인.
2. 취소 또는 실패한 작업이 발생 후 10초 지나면 화면 우측 하단 작업 모니터에서 깔끔하게 사라지는지 확인.
