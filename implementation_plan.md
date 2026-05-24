# 영상 업로드 모달 내 Whisper 사용자 정의 설정 도입

영상 업로드 시 사용자가 Whisper 엔진의 세부 파라미터를 제어할 수 있도록 고급 설정(Advanced Settings) 토글 기능을 추가합니다. 코드베이스 전반의 최소 수정 원칙을 준수하여 구현합니다.

## User Review Required

> [!IMPORTANT]
> - **적용 범위**: 현재는 "영상 업로드 모달"에만 해당 토글을 추가할 계획입니다. 혹시 "AI 재생성 모달"에도 동일한 옵션을 넣기를 원하시는지 피드백 부탁드립니다. (요청하신 대로 일단 업로드 모달에만 적용합니다.)

## Proposed Changes

### Frontend (UI)

#### [MODIFY] [components.js](file:///home/radi/cli/summarize_video/static/js/components.js)
- `VideoUploadModal` 컴포넌트에 상태 변수 추가 (`showAdvancedSettings`, `whisperLang`, `whisperPrompt`, `whisperCondition`, `whisperTemp`, `whisperVad`).
- 기존 옵션 하단에 **"⚙️ 사용자 정의 (Advanced Settings)"** 토글 버튼 추가.
- 토글 시 나타나는 패널 영역 구현:
  - 언어 선택 (select: 자동감지, 한국어, 영어, 일본어)
  - 초기 프롬프트 (input text)
  - 이전 문맥 참조 (checkbox)
  - 창의성/온도 (range slider 0.0 ~ 1.0)
  - 묵음 필터링 (checkbox)
- `onSubmit` 이벤트 호출 시 위 파라미터 묶음을 함께 전달.

#### [MODIFY] [app.js](file:///home/radi/cli/summarize_video/static/js/app.js)
- `isUploadModalOpen` 처리부(`handleFileUpload` 및 `axios.post('/api/transcribe')`)에서 전달받은 Whisper 옵션 데이터를 API 바디에 포함시켜 전송.

---

### Backend (API & Schema)

#### [MODIFY] [requests.py](file:///home/radi/cli/summarize_video/app/schemas/requests.py)
- `TranscriptionRequest` 데이터 클래스에 Whisper 오버라이드용 필드 추가.
  - `whisper_lang: str = "ko"`
  - `whisper_prompt: Optional[str] = None`
  - `whisper_condition: bool = False`
  - `whisper_temp: float = 0.0`
  - `whisper_vad: bool = True`

#### [MODIFY] [pipeline_runner.py](file:///home/radi/cli/summarize_video/app/application/pipeline_runner.py)
- `run_transcription_pipeline` 메서드 내에서 `transcriber.transcribe` 호출 시, `req` 객체에 포함된 Whisper 파라미터를 추출하여 인자로 넘김.

#### [MODIFY] [transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py)
- `transcribe` 및 `run_whisper_worker` 함수의 시그니처를 수정하여 커스텀 파라미터를 수용.
- 하드코딩 되어 있던 `language`, `initial_prompt`, `condition_on_previous_text`, `temperature`, `vad` 설정 부분을 사용자의 입력값으로 덮어쓰도록(override) 분기 처리. (MLX와 Faster-Whisper 양쪽 모두 호환되도록 처리)

## Verification Plan

### Manual Verification
1. 프론트엔드 모달을 열고 "사용자 정의" 토글이 부드럽게 열리고 닫히는지 확인.
2. 각 입력값(예: 영어 언어, 온도 0.5)을 설정하고 업로드를 진행하여 브라우저 네트워크 탭(Network Tab)의 페이로드(Payload)가 올바른지 확인.
3. 백엔드 콘솔 로그 및 `tasks.json`을 통해 커스텀 파라미터가 Worker Process에 정상적으로 전달되어 적용되었는지 검증.
