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
- [x] 에러 로깅 시스템 고도화 및 견고성 확보
  - [x] [logger.py](file:///home/radi/cli/summarize_video/services/logger.py) 설계 및 구현 (공통 콘솔/파일 로깅 및 태스크 ID 단위 보고서 작성 기능 지원)
  - [x] [transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py) 내 로그 트레이서(Traceback) 및 예외 처리 연동
  - [x] [test_logger.py](file:///home/radi/cli/summarize_video/tests/test_logger.py) 작성 및 로컬 단위 테스트 검증
  - [x] pytest 실행 및 모든 테스트(25개) 통과 확인
- [x] 에러 로깅 시스템 추가 고도화 및 조회 API 연동
  - [x] [task_manager.py](file:///home/radi/cli/summarize_video/services/task_manager.py)의 `fail_task`에 자동 예외 캡처(sys.exc_info() 및 exception 전달) 결합
  - [x] [pipeline_runner.py](file:///home/radi/cli/summarize_video/app/application/pipeline_runner.py) 각 단계 실패 시 `exception=error` 인자 전달
  - [x] [worker.py](file:///home/radi/cli/summarize_video/app/application/worker.py) 예외 블록 로깅 보강
  - [x] [tasks.py](file:///home/radi/cli/summarize_video/app/api/routers/tasks.py)에 `/api/tasks/{task_id}/log` 엔드포인트 구현
  - [x] [test_logger.py](file:///home/radi/cli/summarize_video/tests/test_logger.py)에 `fail_task` 로깅 자동화 관련 단위 테스트 추가
  - [x] pytest 전체 테스트 재실행 및 검증
- [x] VAD 텐서 차원 붕괴 버그 수정 (`transcriber.py`)
- [x] `_filter_hallucinations` 환각 필터링 로직 강화 (`transcriber.py`)
- [x] 신규 VAD 및 환각 방지 단위 테스트 작성 (`test_transcriber.py`)
- [x] `자폭드론...mp4` 비디오에 대한 실무 기능 테스트 수행 및 무비 오동작 해결 검증



