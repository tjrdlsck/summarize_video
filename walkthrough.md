# 🎥 동영상 구간 자르기 중간 구간 오디오 유실 결함 디버깅 완료 보고서 (Walkthrough)

## 1. 디버깅 관점의 문제 분석 (Debugging & Problem Analysis)

### 1.1 발견된 결함 (Symptom)
* 프론트엔드(Front-end)에서 구간 잘라내기(Export) 버튼을 통해 비디오 클립을 생성할 때, 영상의 시작점(0.0초 부근)을 포함하여 자를 때는 소리가 정상적으로 출력되지만, 영상의 중간 구간(예: 5초 이후 구간)을 잘라내면 오디오 스트림(Audio Stream) 정보는 파일 내에 존재함에도 불구하고 소리가 완전히 재생되지 않는 무음(Silent, 최대 볼륨 $-91.0\text{ dB}$) 상태가 되는 결함이 식별되었습니다.

### 1.2 근본 원인 분석 (Root Cause)
* **FFmpeg 옵션 배치 위치에 따른 타임스탬프 보존 현상**:
  기존 `services/clipper.py`의 `cut_video` 메서드는 FFmpeg 명령어를 구성할 때 시간 탐색 옵션(`-ss`, `-to`)을 입력 파일 지정 옵션(`-i`) 뒤에 배치하였습니다.
  ```bash
  ffmpeg -nostdin -i <input_path> -ss <start_sec> -to <end_sec> ...
  ```
  이 구성은 FFmpeg에서 **출력 옵션(Output Option)**으로 작동합니다. 출력 옵션 방식은 디코더가 입력 파일 전체를 읽어가면서 구간에 도달했을 때 비로소 인코딩을 시작하도록 프레임을 선택하므로, 디코더를 빠져나온 오디오 프레임들의 타임스탬프(PTS, Presentation Timestamp)가 0으로 리셋되지 않고 **원본 영상의 타임스탬프(예: 5.0초 ~ 10.0초)를 그대로 유지**합니다.
  
* **오디오 페이드 필터의 입력 타임라인 일치 실패**:
  동영상 컷팅 시 적용되는 오디오 필터는 시작/종료 시점의 오디오 노이즈 및 끊김을 방지하기 위해 다음과 같이 페이드 인/아웃 필터(`afade`)를 지정하고 있었습니다:
  `afade=t=in:st=0:d=0.1,afade=t=out:st={duration - 0.2}:d=0.2`
  
  예를 들어, 5.0초~10.0초 구간을 자르고자 하는 경우 잘라낸 클립의 길이는 5초이므로 페이드 아웃 시작 시간은 `st=4.8`이 됩니다. 하지만 디코딩된 오디오 데이터의 PTS는 5.0초에서 시작합니다. 
  `afade=t=out:st=4.8` 필터 입장에서 들어오는 모든 오디오 프레임들의 타임스탬프($\ge 5.0\text{초}$)가 페이드 아웃 임계값인 $4.8\text{초} + 0.2\text{초} = 5.0\text{초}$ 이상에 속하므로, 필터가 **모든 프레임 데이터를 완전히 감쇄(Mute, 볼륨 0)하여 출력**해 버렸던 것입니다. 0초 부근을 자를 때는 타임스탬프가 0부터 시작했기에 0~4.8초 구간의 소리가 정상 노출되었으나, 중간 구간은 항상 임계값을 넘어 소리가 유실되는 부작용이 발생했습니다.

---

## 2. 해결 메커니즘 (Resolution Mechanics)

이 문제를 최소한의 코드 수정으로 견고하게 극복하기 위해 FFmpeg 옵션 처리 프로세스를 리팩토링하였습니다.

### 2.1 주요 해결 방법
1. **FFmpeg 옵션 배치 순서 변경 (입력 옵션으로 전환)**:
   - `-ss` 옵션을 입력 파일 지정 옵션(`-i`) 앞으로 이동시켰습니다.
   - `-to` 옵션 대신 잘라낼 절대적 크기(길이)를 나타내는 `-t` 옵션을 신규 도입하여 `-i` 앞으로 함께 배치하였습니다.
   ```bash
   ffmpeg -nostdin -ss <start_sec> -t <duration> -i <input_path> ...
   ```
2. **타임스탬프 리셋 효과**:
   - `-ss`와 `-t`가 입력 파일옵션 앞에 위치하게 됨에 따라 FFmpeg는 인코딩 전 단계에서 해당 위치로 키프레임 시크를 수행하고, 지정한 길이만큼만 프레임을 디코딩합니다.
   - 이 과정을 통해 디코더에서 나오는 비디오/오디오 프레임의 타임스탬프(PTS)가 항상 **0부터 다시 시작**하도록 보정됩니다.
   - 결과적으로 오디오 필터 체인으로 들어오는 입력 타임라인이 오프셋 0으로 동기화되어 `afade` 필터가 정상 범위(0초 ~ duration초) 내에서 페이드 효과를 정확히 수행하게 되었으며, 오디오 유실 결함이 완전히 복구되었습니다.

### 2.2 코드 변경 요약

#### [services/clipper.py](file:///home/radi/cli/summarize_video/services/clipper.py)
* `cut_video` 내의 FFmpeg 명령어 매개변수 생성 로직을 변경하였습니다.
```python
        # [FFmpeg Command Configuration]
        cmd = [
            "ffmpeg", 
            "-nostdin",
            "-ss", str(start_sec),
            "-t", str(duration),
            "-i", input_path,
            "-filter_complex", f"[0:a]{audio_filter}[af]", # 오디오 필터 적용
            "-map", "0:v", "-map", "[af]",                 # 비디오는 그대로, 오디오는 필터 거친 것 사용
            "-c:v", encoder,                               # 자동 선택된 인코더
        ]
```

---

## 3. 검증 결과 (Verification Results)

### 3.1 회귀 테스트 통과 (`tests/test_clipper.py`)
* 모킹(Mocking)된 인코더 선택 로직 테스트 3개 모두 정상 통과를 완료하였습니다.
```bash
$ ./venv/bin/pytest tests/test_clipper.py
============================== 3 passed in 0.03s ===============================
```

### 3.2 신규 통합 테스트 수행 및 실제 소리 검증 (`tests/test_clipper_audio_leak.py`)
* 실제 비디오 파일을 타깃으로 삼아 처음 잘라내기(0.0초~5.0초)와 중간 구간 잘라내기(5.0초~10.0초) 시나리오를 연달아 진행하고, 생성된 클립의 소리 존재 및 최대 볼륨 상태를 FFmpeg `volumedetect` 필터로 추출 및 검증하였습니다.
```bash
$ ./venv/bin/pytest tests/test_clipper_audio_leak.py -s
tests/test_clipper_audio_leak.py 테스트 타깃 비디오: static/videos/자폭드론·방공포까지…튀르키예,_대규모_합동훈련서_화력_과시__연합뉴스_(Yonhapnews).mp4
--- [Clipper] Starting Async Cut (High Quality + Fade): clip_test_start.mp4 ---
--- [Clipper] Cut Success: static/temp_test/clip_test_start.mp4 ---
--- [Clipper] Starting Async Cut (High Quality + Fade): clip_test_middle.mp4 ---
--- [Clipper] Cut Success: static/temp_test/clip_test_middle.mp4 ---
[검증 결과] 처음 구간 클립 오디오 스트림 존재: True, 최대 볼륨: -6.8 dB
[검증 결과] 중간 구간 클립 오디오 스트림 존재: True, 최대 볼륨: -2.9 dB
.
============================== 1 passed in 1.72s ===============================
```
* **결과 분석**: 두 결과 클립 모두 오디오 스트림이 유효하며 최대 볼륨이 무음 임계점($-60.0\text{ dB}$)보다 큰 $-6.8\text{ dB}$ 및 $-2.9\text{ dB}$로 안정적으로 인코딩 및 소리 출력이 보존됨을 성공적으로 확인하였습니다.

---

## 4. 교훈 및 예방 조치 (Lessons Learned)

* **FFmpeg 타임스탬프와 필터 상호작용의 관계**:
  시간적 오프셋을 매개변수로 취하는 멀티미디어 필터(예: `afade`, `overlay`, `drawtext` 등)를 설계할 때는 입력 스트림의 타임스탬프(PTS) 기준점을 명확히 알아야 합니다. 가급적 입력 옵션 방식(`-ss` / `-t`를 `-i` 앞단에 배치)을 활용하여 타임라인을 0으로 강제 리셋시키는 것이 안전합니다.
* **실제 멀티미디어 수치 검증 자동화**:
  단순히 파일의 존재나 스트림 헤더(Header)의 존재만 체크하는 테스트는 무음 현상과 같은 데이터 논리 오류를 잡지 못합니다. FFmpeg의 `volumedetect` 필터 등 볼륨 분석 툴을 통합 테스트에 도입해 데시벨 수치를 파싱 검증하는 기법은 향후 유사 오디오 유실 회귀를 완벽히 막아내는 견고한 장치입니다.

---

# 🎥 리눅스 비디오 인코더 호환성 문제 해결 및 클립 내보내기 기능 검증 완료 보고서 (Walkthrough)

프론트엔드에서 영상의 구간 잘라내기(Export) 및 AI 숏츠(Shorts) 생성 요청 시 백그라운드 태스크가 실패하거나 멈추던 문제를 분석하고 해결한 상세 내용을 디버깅 관점에서 보고합니다.

---

## 1. 디버깅 관점의 문제 분석 (Debugging & Problem Analysis)

### 1.1 최초 발견된 문제 (Symptom)
* **현상 A (클립 생성 실패)**: 프론트엔드(Front-end) UI 상에서 시작/종료 지점을 잡고 내보내기(Export)를 실행했을 때, 작업은 정상 등록되었으나 보관함 목록에 아무런 클립(Clip)도 추가되지 않았습니다.
* **현상 B (숏츠 생성 중 행(Hang) 현상)**: AI 숏츠 생성 중 1단계 숏츠 제작은 완료되었으나, 2단계 숏츠 제작 진행률이 99%에 도달한 후 더 이상 프로세스(Process)가 진행되지 않고 대기 상태로 멈추어 있었습니다.

### 1.2 근본 원인 분석 (Root Cause)
* **원인 A**: 기존 `services/clipper.py`는 윈도우(Windows) 환경을 제외한 모든 환경(`else`)에서 macOS의 하드웨어 가속기(Hardware Accelerator)인 `h264_videotoolbox` 인코더를 강제(Hard-coded)로 사용하고 있었습니다. 현재 실행 환경인 **Linux (Ubuntu)**에서는 해당 전용 코덱을 지원하지 않으므로 FFmpeg 실행이 즉시 에러로 중단되었습니다.
* **원인 B**: 백그라운드 비동기 태스크(Async Task)로 FFmpeg 프로세스를 실행할 때, **표준 입력(stdin)의 차단 및 상호작용 모드 비활성화** 처리가 생략되어 있었습니다. FFmpeg는 백그라운드 구동 시 터미널 상호작용을 처리하거나 입력 버퍼를 확인하기 위해 대기하는 경향이 있어, 인코딩이 거의 끝난 시점(99%)에 행(Hang) 현상이 일어나 무한정 대기하게 되었습니다.

---

## 2. 해결 메커니즘 (Resolution Mechanics)

이 문제를 해결하기 위해 시스템의 운영체제 및 그래픽 리소스를 유연하고 동적으로 판단하고, 백그라운드 서브프로세스 행 현상을 철저히 제어하도록 코드를 리팩토링(Refactoring) 하였습니다.

### 2.1 주요 해결 방법
1. **NVIDIA 가속기 (NVENC) 동적 감지 헬퍼 추가**:
   - `_is_nvenc_available` 메소드를 구현하여 `nvidia-smi` 명령어의 존재 여부 및 `ffmpeg -encoders` 출력 결과를 검사하여 하드웨어 가속 인코더(`h264_nvenc`)의 유효성을 실시간 판별합니다.
2. **최적의 인코더 분기 처리**:
   - **1순위 (NVIDIA NVENC 가속 가능 환경 - Windows/Linux 공통)**: 가속을 위해 `h264_nvenc` 코덱 및 VBR 인코딩 옵션을 적용합니다.
   - **2순위 (macOS 환경 - sys.platform == 'darwin')**: 기존과 동일하게 Apple 가속 인코더인 `h264_videotoolbox`를 사용합니다.
   - **3순위 (일반 Linux 등 기타 환경)**: 하드웨어 가속기가 없으므로 CPU 기반 범용 인코더인 `libx264` 및 품질 지향 CRF 옵션(`-crf 23 -preset medium`)을 활용하여 안전하게 백업합니다.
3. **FFmpeg 백그라운드 행(Hang) 현상 방지**:
   - FFmpeg 명령어 매개변수 구성 리스트에 `-nostdin` 플래그(Flag)를 명시적으로 삽입하여 상호작용형 터미널 명령 대기 모드를 완전 차단하였습니다.
   - `asyncio.create_subprocess_exec`를 통해 FFmpeg 서브프로세스를 생성하는 모든 호출부에 `stdin=asyncio.subprocess.DEVNULL` 옵션을 적용하여 표준 입력을 강제로 null 장치로 라우팅시켰습니다.

### 2.2 코드 변경 요약

#### [services/clipper.py](file:///home/radi/cli/summarize_video/services/clipper.py)
* `sys` 모듈을 가져와 환경 판별을 지원합니다.
* `_is_nvenc_available` 함수를 구현하여 하드웨어 상태를 런타임에 체크하도록 보완하였습니다.
* `cut_video` 및 `merge_segments` 내부의 인코더 선택 코드를 삼항 분기(`NVENC` -> `Darwin` -> `libx264`) 구조로 안전하게 마이그레이션(Migration) 하였습니다.
* 모든 `ffmpeg` 명령어 및 `create_subprocess_exec` 파라미터에 `-nostdin` 및 `stdin=asyncio.subprocess.DEVNULL` 처리를 완료하였습니다.

---

## 3. 검증 결과 (Verification Results)

### 3.1 유닛 테스트 수행 (`tests/test_clipper.py`)
운영체제 및 가속 장치 가용 환경을 모킹(Mocking)한 3개의 핵심 유닛 테스트를 신규 작성하여 검증하였습니다.
* **`test_encoder_selection_nvenc`**: NVIDIA 장치가 활성화된 경우 `h264_nvenc` 사용 여부 검증 (통과)
* **`test_encoder_selection_darwin_no_nvenc`**: Darwin 환경에서 `h264_videotoolbox` 사용 여부 검증 (통과)
* **`test_encoder_selection_linux_no_nvenc`**: 일반 리눅스 환경에서 `libx264` 사용 여부 검증 (통과)

```bash
$ ./venv/bin/pytest tests/test_clipper.py
============================== 3 passed in 0.03s ===============================
```

### 3.2 전체 테스트 회귀 검사 (`pytest`)
* 기존 설교 요약, 청크 정리, 자막 처리 로직 등 총 34개의 전체 테스트 스위트를 수행하여 아무런 부작용(Side Effect)이 발생하지 않았음을 확인하였습니다.

```bash
$ ./venv/bin/pytest
======================== 34 passed, 2 warnings in 9.30s ========================
```

---

## 4. 교훈 및 예방 조치 (Lessons Learned)

* **하드웨어 디펜던시의 유연한 바인딩**: 특정 하드웨어 벤더(Apple, NVIDIA)의 전용 API 및 코덱을 이용할 때는 환경 판별(`sys.platform` 또는 기능 가용성 테스트)을 선행하여 범용 소프트웨어 대체(Fallback) 로직을 갖추는 것이 강력한 크로스플랫폼(Cross-platform) 설계임을 재확인하였습니다.
* **서브프로세스 표준 입력 관리의 중요성**: 백그라운드 워커 환경에서 외부 실행 파일(CLI)을 호출할 때는 행(Hang) 현상이 일어나지 않도록 `stdin` 및 TTY 상호작용 대기 상태에 대해 예외 처리를 명시적(예: `-nostdin`, `stdin=DEVNULL`)으로 해 주어야 장애(Deadlock)를 방지할 수 있습니다.

---

# ⚙️ 프론트엔드 모델 설정 UI 크로스 플랫폼 동적화 및 최신 Gemini API 연동 완료 보고서

## 1. 디버깅 관점의 문제 분석 (Debugging & Problem Analysis)

### 1.1 최초 발견된 문제 (Symptom)
* 프론트엔드 시스템 설정 창을 열었을 때, 윈도우(Windows)나 리눅스(Linux) 운영체제임에도 불구하고 Whisper STT 모델 선택 드롭다운(Dropdown)에 맥 전용 `mlx-community/...` 모델명만 표시되었으며, 안내 문구 역시 `(MLX 최적화 모델 권장)`으로 하드코딩(Hard-coded)되어 있었습니다.
* Gemini 모델 리스트 또한 수동으로 관리되는 배열(`GEMINI_MODELS`)로 고정되어 있어, Google에서 새로운 모델 버전이 출시될 경우 사용자가 즉각 설정에서 선택할 수 없는 제한적인 상황이었습니다.

### 1.2 근본 원인 분석 (Root Cause)
* **프론트엔드의 정적인 데이터 바인딩**: `static/js/components.js` 파일 내에 `WHISPER_MODELS` 및 `GEMINI_MODELS`가 프론트엔드 코드 내 고정 변수로 선언되어 있었고, 서버 환경의 동적(OS, API) 정보가 주입되지 않았습니다.
* **설정 저장 로직 결합도**: 백엔드의 `GET /api/settings` 라우터가 설정 파일(`config.json`) 데이터만 그대로 반환하고 있었으며, `POST /api/settings` 시 프론트엔드가 상태 객체 전체를 날리므로 응답 포맷을 확장하기 까다로운 구조적 한계(Pydantic 스키마 제약)가 존재했습니다.

---

## 2. 해결 메커니즘 (Resolution Mechanics)

이 문제를 해결하기 위해 백엔드 API에서 서버 측 구동 환경 및 모델 가용성을 파악하여 프론트엔드로 전달하고, 프론트엔드에서는 이를 동적으로 렌더링하도록 완전 분리 구조(Decoupling) 기반으로 리팩토링(Refactoring) 하였습니다.

### 2.1 주요 해결 방법
1. **Google GenAI 기반 동적 Gemini 모델 로딩 (캐싱 포함)**:
   - `services/system_manager.py`의 `ConfigManager` 내에 `get_gemini_models()` 클래스 메서드를 추가하여 Google GenAI SDK를 통해 실시간 가용 모델 리스트를 조회합니다.
   - 불필요한 API 비용 및 지연율(Latency) 증가를 방지하기 위해 조회 결과를 `_cached_gemini_models` 변수에 인메모리 캐싱(In-memory Caching) 하였습니다. API Key 누락이나 네트워크 연결 오류 시 기본(Fallback) 리스트를 즉각 제공하여 안정성을 보장합니다.
2. **OS 기반 크로스 플랫폼 모델 추천**:
   - `sys.platform`을 확인하여 macOS(`darwin`) 환경인 경우 기존처럼 MLX 모델 리스트를, Linux/Windows 등에서는 Faster-Whisper(`large-v3-turbo` 등) 가속 기반 리스트를 분기하여 `get_settings` 라우터 응답 스키마에 포함시킵니다.
3. **프론트엔드 동적 렌더링 도입**:
   - `fetchSettings` 시 추가적인 메타 데이터(`platform`, `whisper_models`, `gemini_models`)를 React 상태로 할당하고 렌더링 컴포넌트에 바인딩하였습니다.
   - 저장(`handleSave`) 시 프론트엔드는 불필요한 메타 데이터를 뺀 순수 환경설정 `{ models: settings.models }` 객체만 `POST`하도록 통신 레이어를 재설계하였습니다.

---

## 3. 검증 결과 (Verification Results)

### 3.1 유닛 테스트 수행 (`tests/test_cross_platform.py`)
운영체제와 환경 변수를 모킹(Mocking)하여 API가 정상적으로 메타 데이터와 함께 안전하게 처리되는지 검증하였습니다.
* **`test_api_settings_cross_platform`**: `sys.platform` 모킹에 따라 알맞은 `platform` 문자열과 `whisper_models` 구성이 내려오는지 검증 (통과)
* **`test_gemini_models_fallback`**: `GOOGLE_API_KEY` 환경변수가 누락된 오프라인 상황에서 예외 처리 후 폴백 배열이 정상 반환되는지 검증 (통과)

---

## 4. 교훈 및 예방 조치 (Lessons Learned)
* **데이터와 뷰의 완전한 분리(Decoupling)**: 뷰(View, 프론트엔드) 내에 고정 상수를 두는 하드코딩 방식은 유지 보수성을 악화시키므로, 설정 리스트나 메타 정보는 항상 컨트롤러(Controller, 백엔드 라우터)로부터 동적으로 주입받도록 통일해야 함을 확인할 수 있었습니다.
* **외부 의존성 결합 시 방어 코드 체계화**: 외부 API(Google GenAI) 연동 로직에는 네트워크 실패나 인증 오류 등을 항시 상정하여 폴백(Fallback)이나 기본값, 메모리 캐시를 결합하여 UI 장애를 차단하는 프랙티스를 정립하였습니다.

---

# 🔀 Git Flow 이력 꼬임 오류 복구 및 develop -> main 배포 병합 완료 보고서

## 1. 디버깅 관점의 문제 분석 (Debugging & Problem Analysis)

### 1.1 최초 발견된 문제 (Symptom)
* 로컬의 배포 브랜치(Branch)인 `main` 브랜치가 원격 저장소(Remote Repository)의 `origin/main` 브랜치보다 20개의 커밋(Commit)만큼 앞선(`ahead`) 상태로 표시되며 이력이 오염되어 있었습니다.
* 이로 인해 사용자가 `develop` 브랜치의 변경 사항(특히 `feat/#85` 관련 수정본)을 `main` 브랜치에 풀 리퀘스트(Pull Request, PR)를 통하여 안전하게 병합하려 했으나, 로컬 `main` 상태 불일치 및 꼬임 현상으로 정상적인 PR 배포 파이프라인 흐름을 진행하기 어려운 상황이었습니다.

### 1.2 근본 원인 분석 (Root Cause)
* **로컬에서의 임의 직접 병합(Direct Merge)**: 로컬 `main` 브랜치에서 `develop` 브랜치(머지 커밋 `b2de946`)를 직접 머지(Merge)하는 작업이 사전에 오동작했거나 오입력되었습니다.
* 원래 Git Flow 표준 규격에 따르면, 모든 통합 브랜치(`develop`) 변경 사항은 GitHub과 같은 원격 호스팅 서비스에서 풀 리퀘스트를 생성 및 승인(Approve)받고 병합한 후, 로컬에서는 단순 `pull`을 받아 동기화해야 합니다. 로컬에서 직접 `main` 브랜치를 강제로 업데이트한 후 `push`를 시도하려고 하면 PR 없이 병합이 진행되는 문제와 원격 브랜치와의 싱크 오류가 수반됩니다.

---

## 2. 해결 메커니즘 (Resolution Mechanics)

로컬 `main` 브랜치를 안전하게 원래의 표준 릴리즈 시점으로 되돌린 뒤, GitHub CLI 도구인 `gh`를 활용하여 원격 릴리즈 PR을 생성 및 병합하고 최종 동기화하는 로드맵을 적용하여 복구했습니다.

### 2.1 주요 해결 방법
1. **로컬 `main` 이력 강제 초기화**:
   - `main` 브랜치로 전환한 후, 원격의 정상적인 최종 릴리즈 커밋(`0f6df95`)을 가리키는 `origin/main` 상태로 완전히 강제 재설정(Hard Reset)을 수행하였습니다.
   ```bash
   git checkout main
   git reset --hard origin/main
   ```
   - 이를 통해 로컬의 꼬인 20개 커밋을 취소하고 원격 `main` 브랜치와 동일한 상태(`Your branch is up to date with 'origin/main'`)로 복구하였습니다.

2. **GitHub CLI (`gh`) 기반 `develop` -> `main` 풀 리퀘스트 생성**:
   - `develop` 브랜치(최신 `feat/#85`이 포함된 통합 브랜치)의 코드를 최종 배포하기 위해 릴리즈 PR #91을 생성하였습니다.
   ```bash
   gh pr create --base main --head develop --title "[Release] develop 브랜치 변경사항 main 병합" --body "feat/#85을 포함한 develop 브랜치 변경사항을 main 브랜치에 병합합니다."
   ```

3. **풀 리퀘스트 병합 및 브랜치 유지**:
   - 생성된 PR #91을 병합하는 과정에서 `develop` 브랜치가 삭제되지 않도록 `--delete-branch=false` 및 일반 머지 방식(`--merge`)을 강제하여 병합을 자동 수행하였습니다.
   ```bash
   gh pr merge 91 --merge --delete-branch=false
   ```

4. **로컬 및 원격 브랜치 동기화**:
   - 병합 완료 후 로컬 `main` 브랜치에서 `pull`을 받아 원격 `origin/main`의 최신 배포 내역(PR 병합 커밋 `51c8e05`)을 성공적으로 가리키도록 설정했습니다.
   - 로컬 `develop` 브랜치 역시 로컬 작업 추적 문서(`task.md`, `implementation_plan.md`)를 커밋하고 원격과 정상 동기화하였습니다.

---

## 3. 검증 결과 (Verification Results)

### 3.1 로컬 및 원격 Git Log 검증
`git log --oneline -n 15 --graph --all` 조회를 통해 최종 그래프가 다음과 같이 깔끔하게 정렬되었음을 확인하였습니다.
```text
* 435c0bb (HEAD -> develop, origin/develop) [Docs]: 태스크 완료 상태 반영
* 24897fa [Docs]: develop -> main 병합용 기획서 및 작업 목록 반영
| *   51c8e05 (origin/main, origin/HEAD, main) Merge pull request #91 from tjrdlsck/develop
| |\
| |/
|/|
* |   b2de946 Merge branch 'feat/#85' into develop
```
- `main` 브랜치는 PR #91 병합 결과물(`51c8e05`)을 정확히 가리키고 있습니다.
- `develop` 브랜치는 `feat/#85` 통합 커밋(`b2de946`)에 아티팩트(문서) 반영 커밋 2개가 추가로 얹어진 안전한 상태로 원격과 일치합니다.
- `feat/#85`에서 수행된 Whisper API 모델 보정 및 macOS/Linux 분기 처리를 포함한 19개의 커밋이 누락 없이 모두 `main`에 통합 완료되었습니다.

---

## 4. 교훈 및 예방 조치 (Lessons Learned)

* **배포 및 통합 브랜치 보호**: `main`과 `develop` 브랜치는 로컬에서 직접 수동 머지하지 않고, 반드시 원격 PR을 통과한 후 로컬에서 가져오는(Pull) 습관을 들이는 것이 이력 꼬임을 원천 차단하는 지름길입니다.
* **로컬 꼬임 발생 시 `git reset --hard` 활용**: 로컬의 커밋 상태가 원격 브랜치와 방향을 잃고 꼬였을 경우, 당황하여 추가 커밋을 생성하기보다, 정상 상태인 원격 브랜치를 기준으로 `reset --hard`를 사용해 로컬 상태를 복원하고 원격 파이프라인(GitHub PR)을 타는 것이 가장 안전하고 빠른 복구 메커니즘(Mechanism)입니다.

---
### 📚 참고 자료 (References)
* [Google GenAI SDK Models List Documentation](https://github.com/google/generative-ai-python)
* [FastAPI Response Models & Pydantic Schemas](https://fastapi.tiangolo.com/tutorial/response-model/)
* [React Hooks API Reference](https://react.dev/reference/react)
* [FFmpeg NVIDIA NVENC Encoding Guide](https://trac.ffmpeg.org/wiki/HWAccelIntro#NVENC)
* [FFmpeg H.264 Video Encoding Guide](https://trac.ffmpeg.org/wiki/Encode/H.264)
* [Python sys Module Documentation](https://docs.python.org/3/library/sys.html)
* [GitHub CLI gh pr command reference](https://cli.github.com/manual/gh_pr)
