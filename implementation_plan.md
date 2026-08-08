# [Implementation Plan] 업로드 100% 대기 해소 및 청크 파일 병합 고속화 구현

파일 업로드 진행률이 100%에 채워진 후 멈춰 서 있는 것처럼 보이는 사용자 경험(UX) 문제를 완전히 해결하고, 대용량 파일 병합 시 발생하는 백엔드 I/O 병목을 해소하기 위한 기술 구현 계획서입니다.

## User Review Required

> [!NOTE]
> 1. **실시간 단계별 상태 문구 제공**: 파일 전송 100% 완료 직후 **`"📦 서버 파일 병합 완료 중..."` ➔ `"⚙️ 분석 작업 대기열(Queue) 등록 중..."`** 상태가 실시간으로 안내되어 무한 멈춤 느낌을 즉시 차단합니다.
> 2. **비동기 청크 병합 최적화**: 대용량 비디오 파일(수GB 이상) 업로드 시 백엔드 병합 작업을 비동기 스레드 풀(`run_in_executor`)로 격리하여 타임아웃을 완전 예방합니다.

## Proposed Changes

### 1. `Downloader` 비동기 청크 병합 고속화
#### [MODIFY] [`services/downloader.py`](file:///home/radi/cli/summarize_video/services/downloader.py)

* **`finalize_upload` 비동기 스레드 실행 격리**:
  ```python
  async def finalize_upload(self, identifier: str, original_filename: str):
      """임시 청크 파트 파일을 비동기 스레드 풀에서 안전하게 최종 파일로 결합합니다."""
      loop = asyncio.get_running_loop()
      return await loop.run_in_executor(
          None,
          self._sync_finalize_upload,
          identifier,
          original_filename
      )
  ```

---

### 2. 프론트엔드 단계별 상태 문구 업데이트
#### [MODIFY] [`static/js/app.js`](file:///home/radi/cli/summarize_video/static/js/app.js) & [`static/js/components.js`](file:///home/radi/cli/summarize_video/static/js/components.js)

* **`app.js` 상태 관리 및 문구 갱신**:
  ```javascript
  const [uploadStatusText, setUploadStatusText] = useState("");

  // 100% 도달 후 단계별 상태 변경
  setUploadProgress(100);
  setUploadStatusText("📦 서버 파일 병합 처리 중...");
  const completeRes = await axios.post('/api/upload/complete', { ... });

  setUploadStatusText("⚙️ 분석 작업 대기열(Queue) 등록 중...");
  await axios.post('/api/transcribe', { ... });
  ```

* **`VideoUploadModal` UI에 상태 문구 렌더링**:
  버튼 및 프로그레스 바 영역에 `uploadStatusText` (예: `"📦 100% - 서버 파일 병합 처리 중..."`)가 명확히 렌더링되도록 구현.

---

## Verification Plan

### Automated Tests
1. **신규 단위 테스트 작성 및 실행**: `tests/test_chunked_upload_finalizer.py`
   - `test_finalize_upload_success()`: 비동기 스레드 풀 기반 청크 파일 최종 결합 검증
   - `test_finalize_upload_missing_part()`: 파트 미존재 시 에러 반환 검증
   - **실행 명령**: `pytest tests/test_chunked_upload_finalizer.py -v`

2. **전체 회귀 테스트**:
   - **실행 명령**: `pytest tests/`

### Manual Verification
1. 파일 업로드 테스트 시 100% 도달 즉시 `"📦 서버 파일 병합 처리 중..."` ➔ `"⚙️ 분석 작업 대기열 등록 중..."` 문구가 실시간 표기되는지 확인.
2. 완료 후 모달이 닫히며 하단 TaskMonitor로 자연스럽게 이동하는지 확인.
