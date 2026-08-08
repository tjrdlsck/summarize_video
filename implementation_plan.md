# [Implementation Plan] 스마트 비디오 탐색 및 파일 부재 시 즉시 오류 알림 구현

동영상 파일명이 다소 다르게 전달되더라도 보관 중인 실물 동영상을 자동 탐지(Smart Video Matching)하고, 동영상 파일이 최종적으로 없을 경우 무기한 대기(Infinite Pending) 대신 즉시 명확한 오류 발생 및 프론트엔드 알림을 제공하기 위한 기술 구현 계획입니다.

## User Review Required

> [!NOTE]
> 1. **스마트 동영상 탐색**: `_summary.json`의 `video_source` 정보와 해시가 포함된 파일명(`28cf4da5_...mp4`)을 자동으로 감지하여, 사용자가 **영상을 다시 업로드하지 않아도** 즉시 숏츠가 정상 렌더링됩니다.
> 2. **무기한 대기 완전 차단**: 실물 비디오 파일이 서버에 존재하지 않으면 작업을 즉시 실패(`failed`) 처리하고 사용자에게 `"원본 영상 파일이 없습니다. 영상을 다시 업로드해주세요."` 안내 팝업을 제공합니다.

## Proposed Changes

### 1. `PipelineRunner` 스마트 동영상 파일 매칭 & 예외 명확화
#### [MODIFY] [`app/application/pipeline_runner.py`](file:///home/radi/cli/summarize_video/app/application/pipeline_runner.py)

* **스마트 동영상 탐색 헬퍼 및 `run_shorts_pipeline` 적용**:
  ```python
  def _resolve_video_path(self, req_filename: str, summary_data: dict = None) -> str:
      """보관 중인 동영상 경로를 스마트하게 탐색합니다."""
      candidates = [os.path.join(VIDEOS_DIR, req_filename)]
      if summary_data and summary_data.get("video_source"):
          candidates.insert(0, os.path.join(VIDEOS_DIR, summary_data["video_source"]))

      for path in candidates:
          if os.path.exists(path):
              return path

      if os.path.exists(VIDEOS_DIR):
          clean_name = re.sub(r"^[0-9a-fA-F]{8}_", "", req_filename)
          for fname in os.listdir(VIDEOS_DIR):
              if fname == req_filename or clean_name in fname:
                  return os.path.join(VIDEOS_DIR, fname)

      raise FileNotFoundError(f"원본 영상 파일('{req_filename}')을 찾을 수 없습니다. 대시보드에서 영상을 다시 업로드해 주세요.")
  ```

* **`run_shorts_pipeline`에서 렌더링 전 동영상 검증**:
  ```python
  video_path = self._resolve_video_path(req.filename, summary_data if 'summary_data' in locals() else None)
  ```

---

### 2. 프론트엔드 실패 작업 알림 및 무기한 대기 차단
#### [MODIFY] [`static/js/app.js`](file:///home/radi/cli/summarize_video/static/js/app.js)

* **`fetchActiveTasks` 폴링 시 실패 태스크 감지 알림**:
  ```javascript
  const fetchActiveTasks = async () => {
      try {
          const res = await axios.get(`/api/tasks?t=${Date.now()}`);
          const newTasks = res.data;

          // 신규 실패 건 감지 시 사용자 안내
          newTasks.forEach(task => {
              if (task.status === 'failed' && !notifiedFailedTasks.current.has(task.task_id)) {
                  notifiedFailedTasks.current.add(task.task_id);
                  alert(`⚠️ 작업 실패 안내 (${task.filename}):\n${task.error || task.message}`);
              }
          });

          setActiveTasks(newTasks);
      } catch (err) { console.error(err); }
  };
  ```

---

## Verification Plan

### Automated Tests
1. **신규 단위 테스트 작성 및 실행**: `tests/test_video_path_smart_matching.py`
   - `test_resolve_video_path_matches_hashed_filename()`: 해시가 달린 실물 파일 자동 감지 검증
   - `test_resolve_video_path_raises_filenotfounderror()`: 파일 미존재 시 `FileNotFoundError` 발생 검증
   - **실행 명령**: `pytest tests/test_video_path_smart_matching.py -v`

2. **전체 회귀 테스트**:
   - **실행 명령**: `pytest tests/`

### Manual Verification
1. 숏츠 생성 클릭 시 영상이 다르게 저장되어 있어도 숏츠가 즉시 생성되는지 확인.
2. 비디오 파일이 완전히 없는 상태에서 숏츠 요청 시 팝업으로 실패 메시지가 명확히 전달되는지 확인.
