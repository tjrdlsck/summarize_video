# Whisper Worker 자원 최적화 및 환각 방지 구현 계획

## 현재 상태 분석
- **설정 모델:** Linux 환경에서 `mlx-community/whisper-large-v3-mlx-4bit` 설정 시, 시스템 매니저(`ConfigManager`)에 의해 실시간으로 Faster-Whisper 표준 모델인 **`large-v3`**로 변환되어 실행 중이었습니다.
- **2060 Super 하드웨어 제약:**
  - VRAM 용량: $8\text{ GB}$
  - `large-v3` 모델은 약 15억 개의 매개변수(Parameter)를 가져 `float16` 정밀도 로드 시 가중치와 활성화 함수 점유로 인해 VRAM 사용량이 $6\text{ GB} \sim 8\text{ GB}$에 달합니다. 이는 VRAM 부족(Out of Memory, OOM)이나 가상 메모리 페이징으로 인한 급격한 속도 저하 및 동작 불안정을 야기합니다.
- **환각(Hallucination) 및 무음 처리 유발 원인:**
  1. **오디오 과적합 전처리 필터:** FFmpeg 오디오 변환 시 `highpass`, `lowpass`, `afftdn=nf=-25` 등이 결합되어 실제 대화 목소리 성분까지 노이즈로 처리하여 음성을 무음(Silent)으로 지워버렸습니다. 그 결과 Whisper는 무음 구간에서 `initial_prompt`에 적힌 시스템 유도 지시문(`"화자 전환과 감탄사를 자연스럽게 인식하세요."`)만 그대로 환각으로 뱉고 인식을 끝내버렸습니다.
  2. **`condition_on_previous_text` 옵션 누락:** 이전 청크의 예측 결과를 다음 청크의 컨텍스트로 전달하면서 특정 단어가 무한 반복되는 반복 루프 환각이 발생하기 쉬운 상태였습니다.
  3. **다중 온도 테스트(`temperature=(0.0, 0.2, 0.4)`):** 첫 시도 실패 시 온도를 높여 재시도하는 과정에서 텍스트 창작 및 환각 현상이 가속화되었습니다.
- **VAD 및 환각 방지 로직 결함:**
  1. **텐서 차원 붕괴 현상:** `soundfile.read`를 통해 로드된 다채널 오디오 데이터는 `(samples, channels)`의 형태를 가집니다. 기존 코드의 `wav = wav.mean(dim=0, keepdim=True)`는 시간축인 샘플 차원($\text{dim}=0$) 전체를 평균 내어 결국 $1\text{ sample}$ 크기(즉 $\frac{1}{16000}\text{초}$)의 극단적으로 찌그러진 오디오 텐서를 유발했습니다. 이로 인해 음성 구간 탐지(Voice Activity Detection, VAD) 모델에 비어있거나 다름없는 데이터가 입력되어 `Detected 0 speech segments` 현상이 발생했습니다.
  2. **`_filter_hallucinations`의 예외 처리 결함:** VAD 결과가 비어있을(`[]`) 때, 환각 문장들을 모두 걸러내야 함에도 불구하고 `if not vad_segments: return whisper_segments`로 인해 필터링을 전혀 거치지 않고 Whisper가 내뱉은 생짜 환각 문장("다음 영상에서 만나요", "이 영상은 라이브 스트리밍...")들이 고스란히 최종 자막 파일로 노출되었습니다.

## 제안하는 최적화 및 환각 억제 대책

### 1. 기본 모델 변경
- **`large-v3-turbo`** 모델 적용:
  - 디코더 레이어 수가 32개에서 4개로 대폭 축소되어 속도가 $3 \sim 4$배 빠르며 VRAM 사용량이 매우 적습니다.
  - 한국어 음성 인식률 또한 `large-v3`와 견줄 만큼 우수하며 환각 발생 확률이 현저히 적습니다.

### 2. 추론 파라미터 최적화
- **`condition_on_previous_text=False` 명시:** 이전 청크의 문맥 의존성을 차단하여 동일 문장 무한 반복 루프를 원천 차단합니다.
- **단일 온도 설정 (`temperature=0.0`):** 일관되고 결정론적인 결과를 반환하여 랜덤한 환각 억제.
- **VAD(Voice Activity Detection) 파라미터 및 임계치 보완:** 
  - `no_speech_threshold=0.6` 및 `logprob_threshold=-1.0` 설정을 통해 무음 구간에서 텍스트를 인위적으로 생성해내는 환각 차단.
- **VAD 텐서 차원 보정 및 환각 필터링 로직 강화:**
  - `_get_vad_timestamps` 내에서 오디오 텐서 축을 채널축($\text{dim}=1$) 기준으로 평균 내어 `(samples,)` 형태로 만든 후, `unsqueeze(0)`를 수행하여 Silero VAD가 요구하는 정상적인 $2$차원 배치 형태 `(1, samples)`의 오디오 데이터를 전달하도록 복원합니다.
  - VAD 실행 오류(Exception) 발생 시 `None`을 반환하도록 하고, VAD가 정상적으로 동작했으나 음성 구간이 전혀 감지되지 않은 경우 `[]`를 반환하도록 리턴 타입을 분기합니다.
  - `_filter_hallucinations`에서 `vad_segments`가 `None`(실행 에러)일 때는 예외적으로 Whisper 자막을 유지(Fallback)하되, `[]`(정상 수행 결과 음성 구간 없음)일 때는 모든 Whisper 세그먼트를 환각으로 판단하여 `[]`를 반환하도록 강화하여 빈 자막을 생성하게 유도합니다.

### 3. 연산 정밀도 최적화 (2060 Super 맞춤형)
- **`compute_type="int8_float16"` 도입:**
  - RTX 2060 Super(Turing 아키텍처)의 텐서 코어(Tensor Core)를 활용합니다.
  - 가중치는 8비트 정수(Int8)로 양자화하여 로드하고 연산은 16비트 부동소수점(Float16)으로 수행합니다.
  - 이를 통해 **VRAM 사용량을 약 $50\%$ 절감**하면서도 성능 하락은 거의 없이 동작 속도를 유지할 수 있습니다.

### 4. FFmpeg 오디오 전처리 전면 간소화
- 노이즈 게이팅 성격인 `afftdn`, `highpass`, `lowpass`를 걷어내어 음성 왜곡 및 묵음 처리를 원천 방지하고, 오직 기본적인 음량 정규화를 위한 `loudnorm`만 유지합니다.

---

## 변경 제안 (Proposed Changes)

### 설정 매니저 (Config Manager)

#### [MODIFY] [system_manager.py](file:///home/radi/cli/summarize_video/services/system_manager.py)
- `get_model` 메서드에서 Linux/Windows 환경의 기본 모델을 `large-v3` 대신 `large-v3-turbo`로 변경합니다.

### 서비스 레이어 (Service Layer)

#### [NEW] [logger.py](file:///home/radi/cli/summarize_video/services/logger.py)
- 공통 파이썬 `logging` 설정을 구축하여 콘솔(`StreamHandler`)과 일별 로그 파일(`FileHandler`) 출력을 지원합니다.
- `log_task_error`를 통해 개별 태스크(Task) ID 단위로 격리된 예외 보고서(`task_<task_id>.log`)를 상세 기록하는 기능을 구현합니다.

#### [MODIFY] [task_manager.py](file:///home/radi/cli/summarize_video/services/task_manager.py)
- `fail_task` 메서드에 `exception` 매개변수를 추가하고, `sys.exc_info()` 또는 직접 넘겨진 `exception` 객체를 감지하여 자동으로 `log_task_error`를 통해 상세 트레이스백(Traceback) 에러 보고서를 파일로 생성하도록 결합합니다.
- 태스크 데이터 구조에 `log_file` 필드를 추가하여, 실패 시 저장된 디버그 로그 파일명을 `tasks.json`에 기록해 프론트엔드가 접근하기 쉽도록 설계합니다.

#### [MODIFY] [transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py)
- `_get_vad_timestamps` 내 오디오 텐서 Mono 변환 시 `mean(dim=1)` 및 `unsqueeze(0)`를 활용한 `(1, samples)` 형태로 차원 보정 로직을 전면 수정합니다.
- `_get_vad_timestamps`에서 Exception 발생 시 `None`을 반환하도록 리턴 형식을 변경합니다.
- `_filter_hallucinations` 메서드에서 `vad_segments is None`일 때와 `not vad_segments`일 때를 엄격히 분기하여, 정상적으로 분석되어 음성이 없다고 판단한 경우에는 빈 리스트(`[]`)를 반환해 환각 자막을 원천 차단합니다.
- `run_whisper_worker` 내부의 Faster-Whisper 디바이스 및 컴파일 파라미터를 2060 Super에 최적화합니다.
  - `compute_type` 결정을 `int8_float16`로 기본 설정.
  - deprecated된 `transcribe_stable` 메서드를 최신 권장 API인 `transcribe`로 변경하여 경고 메시지 제거.
  - `transcribe` 호출 시 `condition_on_previous_text=False`, `temperature=0.0`, `no_speech_threshold=0.6`, `log_prob_threshold=-1.0` 추가.
- 예외 발생 시 호출 스택(Traceback) 상세 분석 및 로깅 기능을 추가합니다.
  - Whisper Worker 자식 프로세스 crash 시 예외 객체 및 Traceback 정보를 로그 디렉토리(`static/logs/`)에 기록합니다.
  - 부모 프로세스 파이프라인 상의 에러 및 취소 여부를 감지해 상세 Task 로그를 기록합니다.

#### [MODIFY] [pipeline_runner.py](file:///home/radi/cli/summarize_video/app/application/pipeline_runner.py)
- 각 파이프라인의 `except Exception as error` 블록에서 `fail_task` 호출 시 `exception=error`를 넘겨주도록 변경하여, 보다 명확하고 디버깅하기 쉬운 예외 포착(Exception trapping)이 일어나도록 합니다.

#### [MODIFY] [worker.py](file:///home/radi/cli/summarize_video/app/application/worker.py)
- `QueueWorker.run` 루프 외부 및 예기치 못한 태스크 예외 블록에서 로깅 시스템(`log_error_with_traceback`) 및 `fail_task`를 활용해 트레이스백이 완전 소실되지 않도록 보강합니다.

#### [MODIFY] [tasks.py](file:///home/radi/cli/summarize_video/app/api/routers/tasks.py)
- `/api/tasks/{task_id}/log` GET 엔드포인트를 추가하여 특정 태스크 실패 시 축적된 `task_<task_id>.log` 디버그 로그 파일의 텍스트 내용을 직접 반환합니다. 이를 통해 버그 발생 시 신속히 복기할 수 있게 지원합니다.

### 테스트 스크립트 (Test Suite)

#### [MODIFY] [test_cross_platform.py](file:///home/radi/cli/summarize_video/tests/test_cross_platform.py)
- `test_whisper_model_selection_non_darwin` 테스트의 단언(Assertion) 값을 `large-v3-turbo`에 맞도록 변경합니다.

#### [NEW] [test_logger.py](file:///home/radi/cli/summarize_video/tests/test_logger.py)
- 공통 로깅 객체 생성 확인 및 태스크별 에러 보고서 파일 생성/내용 일치성 검증 단위 테스트를 작성합니다.
- `task_manager.fail_task` 와의 결합 및 로그 파일 생성 무결성 검증 케이스를 추가합니다.

---

## 검증 계획

### 자동화 테스트 (Automated Tests)
- `tests/test_transcriber.py`에 VAD 동작을 검증하기 위한 단위 테스트(`test_transcriber_vad_correction`)를 신규 추가하여, 오디오 데이터를 VAD에 전달할 때 텐서 차원 및 채널 평균이 정상적으로 `(1, samples)` 구조로 형성되는지와 `_filter_hallucinations` 로직의 빈 리스트 반환을 검증합니다.
- `tests/test_transcriber.py` 및 `tests/test_logger.py` 테스트 코드를 재실행하여 바뀐 파라미터, 자동 로깅, 예외 캡처 API가 에러 없이 작동하는지 확인합니다.

### 수동 검증 (Manual Verification)
- 음성이 들어있지 않고 굉음 및 배경음만 존재하는 `자폭드론·방공포까지…튀르키예,_대규모_합동훈련서_화력_과시__연합뉴스_(Yonhapnews).mp4` 비디오에 대해 자막 생성을 수행하여, VAD가 정상적으로 `Detected 0 speech segments.`로 로깅되는지 확인하고 최종 결과물이 환각 자막 없이 비어있는 올바른 파일로 생성되는지 검증합니다.
- 고의로 비정상적인 입력값(예: 존재하지 않는 비디오)을 입력하여 태스크를 실패시키고, `/api/tasks/{task_id}/log` 엔드포인트를 통해 에러 로그가 깔끔하게 노출되는지 실시간 확인합니다.

---
## 참고 문헌 (Official Docs)
- [Faster-Whisper Model list & Quantization](https://github.com/SYSTRAN/faster-whisper)
- [Stable-ts generation parameters](https://github.com/jianfch/stable-ts)
