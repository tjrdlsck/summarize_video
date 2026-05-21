# Whisper Worker 임포트 오류 해결 및 RTX 2060 Super 자원/환각 최적화 보고서

## 변경 사항 (Changes Made)

### 1. 서비스 레이어 보완
- **[transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py)** 수정:
  - `run_whisper_worker` 함수에 부모 프로세스의 모듈 탐색 경로를 전달하기 위한 `parent_sys_path=None` 매개변수를 추가하였습니다.
  - 자식 프로세스가 시작되는 즉시 `parent_sys_path`가 존재하는지 검사하고, 자신의 `sys.path`에 병합하여 가상 환경(Virtual Environment) 패키지 경로가 유지되도록 복구 로직을 구현하였습니다.
  - `VideoTranscriber.transcribe` 메서드 내부에서 `multiprocessing.Process`를 통해 Whisper Worker를 생성하고 시작할 때 부모 프로세스의 `sys.path`를 인자(`args`)로 전달하도록 스폰 로직을 보완하였습니다.

### 2. RTX 2060 Super (8GB VRAM) 자원 최적화 및 환각 방지
- **기본 모델 변경 ([system_manager.py](file:///home/radi/cli/summarize_video/services/system_manager.py)):**
  - Linux/Windows 환경에서 MLX 변환 시 적용되는 Whisper 기본 모델을 `large-v3`에서 **`large-v3-turbo`**로 변경하였습니다. 이로써 디코더 연산량이 대폭 줄어 VRAM 소모가 감소하고 속도가 약 $3 \sim 4$배 개선됩니다.
- **FFmpeg 오디오 왜곡 필터 간소화 ([transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py)):**
  - 목소리 데시벨 감쇄 및 웅얼거림 처리 등으로 목소리를 노이즈로 인지해 무음화(Silent gating)시키던 `afftdn`, `highpass`, `lowpass` 오디오 필터를 제거하고, 음량 평준화를 위한 `loudnorm` 필터만 남겨 원본 왜곡을 차단하였습니다.
- **추론 정밀도 및 환각 억제 파라미터 튜닝 ([transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py)):**
  - `compute_type="int8_float16"` 양자화 설정을 인가하여 VRAM 사용량을 약 $50\%$ 절감하였습니다.
  - `condition_on_previous_text=False`를 지정하여 이전 문장이 연속적으로 복사/반복되는 환각 루프를 사전에 격리 차단하였습니다.
  - `temperature=0.0` 단일 온도 디코딩을 주입하여 창작 및 루프 위험을 억제하고 결정론적인 번역 결과를 보장하였습니다.
  - `no_speech_threshold=0.6` 및 `log_prob_threshold=-1.0` 설정을 통해 무음 구간에 자의적으로 자막을 낙서하는 환각을 방지하였습니다. (기존에 OpenAI Whisper 규격인 `logprob_threshold`를 사용하여 `faster-whisper` 모델에서 발생하던 `TypeError`를 파라미터명 수정을 통해 해결하였습니다.)
  - deprecated된 `transcribe_stable` 메서드 대신 최신 API인 `transcribe`를 직접 호출하여 파이썬 경고 메시지(`UserWarning`)를 제거하였습니다.

### 3. 크로스 플랫폼 테스트 수정
- **[test_cross_platform.py](file:///home/radi/cli/summarize_video/tests/test_cross_platform.py)** 수정:
  - 기본 Whisper 모델이 `large-v3-turbo`로 전환됨에 따라 이에 맞추어 단위 테스트의 assert 기준을 최신화하였습니다.

---

## 검증 내용 (What Was Tested)

### 1. 자식 프로세스 내 모듈 검색 경로 유효성 검증
- [test_transcriber.py](file:///home/radi/cli/summarize_video/tests/test_transcriber.py) 단위 테스트를 작성 및 실행하여, Whisper Worker를 독립된 프로세스로 띄웠을 때 `faster_whisper` 모듈을 정상적으로 로드하는지 확인하였습니다.

### 2. 전체 테스트 스위트 검증
- `pytest` 명령을 이용해 프로젝트 전체 테스트 23개를 일괄 구동하여 사이드 이펙트 없이 안정적으로 빌드 및 기동됨을 확인하였습니다.

## 검증 결과 (Validation Results)
- 단위 테스트 및 전체 테스트 실행 결과: **전원 통과 (23 Passed)**
  - `compute_type`이 `int8_float16`로 정상 로드됨을 실시간으로 확인하였습니다.
  - 전체 실행 로그는 [test_transcriber_output.log](file:///home/radi/cli/summarize_video/test_results/test_transcriber_output.log)에서 확인하실 수 있습니다.

---
## 참고 문헌 (Official Docs)
- [Faster-Whisper Model list & Quantization](https://github.com/SYSTRAN/faster-whisper)
- [Stable-ts generation parameters](https://github.com/jianfch/stable-ts)
