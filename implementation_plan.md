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

#### [MODIFY] [transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py)
- `run_whisper_worker` 내부의 Faster-Whisper 디바이스 및 컴파일 파라미터를 2060 Super에 최적화합니다.
  - `compute_type` 결정을 `int8_float16`로 기본 설정.
  - deprecated된 `transcribe_stable` 메서드를 최신 권장 API인 `transcribe`로 변경하여 경고 메시지 제거.
  - `transcribe` 호출 시 `condition_on_previous_text=False`, `temperature=0.0`, `no_speech_threshold=0.6`, `log_prob_threshold=-1.0` 추가.

### 테스트 스크립트 (Test Suite)

#### [MODIFY] [test_cross_platform.py](file:///home/radi/cli/summarize_video/tests/test_cross_platform.py)
- `test_whisper_model_selection_non_darwin` 테스트의 단언(Assertion) 값을 `large-v3-turbo`에 맞도록 변경합니다.

---

## 검증 계획

### 자동화 테스트 (Automated Tests)
- `tests/test_transcriber.py` 테스트 코드를 재실행하여 바뀐 파라미터 및 모델 옵션이 에러 없이 정상적으로 파싱되고 로드되는지 확인합니다.

### 수동 검증 (Manual Verification)
- 실제 짧은 한국어 영상을 자막 변환하여 이전 대비 환각 현상(문장 반복, 무음 구간 낙서)이 개선되었는지 테스트합니다.

---
## 참고 문헌 (Official Docs)
- [Faster-Whisper Model list & Quantization](https://github.com/SYSTRAN/faster-whisper)
- [Stable-ts generation parameters](https://github.com/jianfch/stable-ts)
