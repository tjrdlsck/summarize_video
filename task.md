# 작업 목록 (Task List)

- [x] [transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py) 수정
  - [x] `run_whisper_worker` 함수 시그니처에 `parent_sys_path` 매개변수 추가 및 경로 복구 로직 구현
  - [x] `VideoTranscriber.transcribe` 메서드에서 `multiprocessing.Process` 호출 시 `sys.path` 인자 전달 추가
- [x] Whisper Worker 리소스 및 환각 최적화
  - [x] [system_manager.py](file:///home/radi/cli/summarize_video/services/system_manager.py) 수정하여 리눅스 기본 모델을 `large-v3-turbo`로 변경
  - [x] [transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py) 내 FFmpeg 전처리 필터 간소화 (`afftdn`, `highpass`, `lowpass` 제거)
  - [x] `run_whisper_worker`에서 `compute_type="int8_float16"` 적용 및 환각 제어 파라미터(`condition_on_previous_text=False`, `temperature=0.0`, `no_speech_threshold=0.6`, `log_prob_threshold=-1.0` 주입 완료)
- [x] Whisper API 및 파라미터 표준화
  - [x] `logprob_threshold`를 `log_prob_threshold` 매개변수로 수정하여 `faster-whisper` 에러 해결
  - [x] `transcribe_stable` 대신 `transcribe`를 사용하여 deprecation 경고 제거
- [x] 검증 및 테스트 수정
  - [x] [test_cross_platform.py](file:///home/radi/cli/summarize_video/tests/test_cross_platform.py) 테스트 코드 assertion 수정 (`large-v3-turbo` 대응)
  - [x] `transcribe` 변경 후 pytest 실행 및 모든 테스트 통과 확인
