# 🚀 Gemini 3.5/3.1 Flash-Lite 기반 비디오 요약 시스템 대개편 아키텍처 명세서

> **문서 버전**: v1.1  
> **최종 수정일**: 2026-08-08  
> **목적**: 바이브 코딩(Vibe Coding) 시 즉시 구현에 착수할 수 있도록 모델 라우팅, 전단 자막 정제 파이프라인 보존 사양, 지능형 Chunking Engine, 3단계 멀티 에이전트 파이프라인의 구체적 구현 사양을 명시함.

---

## 1. 개편 배경 및 모델 할당 전략 (Model Quota Strategy)

### 1.1 개편 배경
- 기존 방식은 API 비용 아끼기를 위해 단 1회 호출에 요약, 챕터 생성, 블로그 작성을 억지로 몰아넣어 **문맥 정보 손실(Lost in the Middle)** 및 **환각(Hallucination)**이 발생함.
- Google AI Studio는 **모델 ID별로 독립적인 Free Quota($500 \text{ RPD}$)**를 제공함.
- **Gemini 2.5 Flash 및 Gemini 자막 정제 단계는 완전 배제**하되, **Whisper & VAD 전단 정제 파이프라인(`services/transcriber.py`)은 100% 보존**하여 고품질 전사 데이터를 그대로 활용함.

### 1.2 모델 역할 분담 및 성능 지표

| 분류 | 대상 모델 | 제공 Quota | 역할 및 할당 작업 | 벤치마크 핵심 지표 |
| :--- | :--- | :--- | :--- | :--- |
| **메인 브레인** | `gemini-3.5-flash-lite` | $500 \text{ RPD}$ | - Stage 2: 전체 목차/챕터 설계 및 고품질 블로그 포스팅 작성<br>- Stage 3: 바이럴 숏폼 후보 정밀 선별 및 대본 작성 | SWE-Bench Pro $54.2\%$<br>Terminal-bench $54.0\%$<br>GDPVal-AA $1140 \text{ pts}$ |
| **서브 보조** | `gemini-3.1-flash-lite` | $500 \text{ RPD}$ | - Stage 1: 자막 Chunk별 1차 정밀 노트 추출 ($N$회 병렬 호출) | 고속 처리 throughput<br>단순 Extraction 고성능 |
| **총 활용 가능 Quota** | **합계 $1,000 \text{ RPD}$** | **하루 비디오 100~150개 이상 정밀 처리 가능** | | |

### 1.3 보존 대상: Whisper STT 전단 환각 방지 파이프라인 (`services/transcriber.py`)
개편된 파이프라인의 전단(Front-end) 입력 안정성을 보장하기 위해 기존의 아래 4가지 환각 방지 로직을 손상 없이 **100% 그대로 유지(계승)**함:
1. **FFmpeg 음향 정제 (`_convert_to_16k_wav`)**:
   - `highpass=f=200` (웅웅거림 제거), `lowpass=f=8000` (고주파 노이즈 필터링), `afftdn=nf=-25` (FFT 노이즈 감소), `loudnorm` (-16 LUFS 방송 표준 음량 정규화).
2. **Silero VAD 기반 1차 환각 제거 (`_filter_hallucinations`)**:
   - Whisper 무음/배경음 환각 방지를 위해 VAD 음성 구간과 중복 비율 20% 미만 및 음성 길이 2.0초 미만 세그먼트 강제 차단.
3. **`Sanitizer v3` 세그먼트 조율 (`_sanitize_segments`)**:
   - 띄어쓰기 정규화 기반 중복 세그먼트 제거 및 단조성`(Monotonicity)` 강제로 타임스탬프 역행 오차 $100\%$ 방지.
4. **LLM 전달용 문장 부호(`., ?, !`) 유지**:
   - 자막용 SRT/VTT와 달리, LLM 전달용 JSON 스크립트에는 문장 부호를 그대로 보존하여 `Smart Chunking Engine`의 `Semantic Cut Point`로 직결시킴.

---

## 2. 지능형 Chunking Engine 설계 (Smart Chunking Engine)

### 2.1 분할 기본 규칙 (Splitting Rules)
1. **목표 크기**: 한글 기준 **$1,500 \sim 2,500\text{자}$** (토큰 기준 약 $1,000 \sim 1,800\text{ tokens}$, 약 $3 \sim 5\text{분}$ 분량).
2. **문맥 오버랩 (Sliding Window Overlap)**:
   - Chunk 경계 부분의 문맥 잘림을 $100\%$ 방지하기 위해 **앞 Chunk의 마지막 세그먼트 $200 \sim 300\text{자}$ ($2 \sim 3$개 문장)**를 다음 Chunk의 시작 부분에 중복 포함함.
3. **의미적 경계 절단 (Semantic Cut Point)**:
   - 글자 수가 $1,800\text{자}$에 도달한 시점 이후:
     - 1순위: 세그먼트 간 무음 공백 타임스탬프 차이 $\text{Gap} \ge 1.5\text{초}$인 지점
     - 2순위: 마침표(`.`, `?`, `!`)로 끝나는 세그먼트 지점

### 2.2 파이프라인 알고리즘 구조 (`build_smart_chunks`)
```python
def build_smart_chunks(segments: list[dict], target_chars=2000, overlap_chars=250) -> list[list[dict]]:
    """
    Whisper 세그먼트 배열을 기반으로 문맥 오버랩 및 무음 타임스탬프 경계를 적용한 Chunk 생성기
    """
    chunks = []
    current_chunk = []
    current_length = 0

    for i, seg in enumerate(segments):
        current_chunk.append(seg)
        current_length += len(seg.get("text", ""))

        if current_length >= target_chars - overlap_chars:
            next_seg = segments[i + 1] if i + 1 < len(segments) else None
            gap_to_next = (float(next_seg["start"]) - float(seg["end"])) if next_seg else 999.0
            is_sentence_end = str(seg.get("text", "")).strip().endswith((".", "?", "!"))

            if gap_to_next >= 1.5 or is_sentence_end or not next_seg:
                chunks.append(current_chunk)
                
                # Overlap 추출 (뒤에서부터 overlap_chars 만큼 보존)
                overlap_buffer = []
                overlap_len = 0
                for prev_seg in reversed(current_chunk):
                    overlap_buffer.insert(0, prev_seg)
                    overlap_len += len(prev_seg.get("text", ""))
                    if overlap_len >= overlap_chars:
                        break
                
                current_chunk = overlap_buffer
                current_length = overlap_len

    if current_chunk and current_chunk not in chunks:
        chunks.append(current_chunk)

    return chunks
```

---

## 3. 3단계 멀티 에이전트 파이프라인 명세 (Multi-Stage Pipeline)

```
[ Whisper 자막 ]
       │
       ▼
[ Smart Chunking Engine ] (글자 수 + Overlap + 무음 갭 적용)
       │
       ├─────────────── Stage 1 (gemini-3.1-flash-lite) ───────────────┐
       ▼                                                               ▼
 [Chunk 1 추출 노트]                                             [Chunk N 추출 노트]
       │                                                               │
       └───────────────────────────────┬───────────────────────────────┘
                                       │ (정밀 요약 노트 융합)
                                       ▼
                       Stage 2 (gemini-3.5-flash-lite)
                       └── 전체 타임라인 챕터 생성 + 완성형 블로그 포스팅 집필
                                       │
                                       ▼
                       Stage 3 (gemini-3.5-flash-lite)
                       └── 바이럴 숏폼 3개 후보 랭킹 및 스크립트 작성
```

### 3.1 Stage 1: Map Phase (정밀 노트 추출)
- **사용 모델**: `gemini-3.1-flash-lite`
- **입력**: 쪼개진 단일 Chunk (발화 세그먼트 배열 및 타임스탬프)
- **출력**: 마크다운 형식의 세부 노트
- **System Prompt 지시사항**:
  - 해당 구간의 주제, 구체적 언급 사실, 데이터/숫자, 핵심 인용구 추출
  - 구간 시작(`start`) 및 종료(`end`) 타임스탬프 기록
  - 불필요한 서론/결론 제외, 불릿 포인트 기반 정리

### 3.2 Stage 2: Reduce Phase (통합 챕터 & 블로그 작성)
- **사용 모델**: `gemini-3.5-flash-lite`
- **입력**: Stage 1에서 수집된 모든 정밀 노트 융합본 (원본 자막 대비 $1/5$ 수준으로 압축된 알짜 정보)
- **출력**: `JSON` 포맷 (`{ "chapters": [...], "blog_post": "..." }`)
- **System Prompt 지시사항**:
  - Overlap 구간으로 인해 중복된 문장은 자동으로 **중복 제거(Deduplication)** 처리
  - 전체 영상 흐름을 꿰뚫는 타임라인 챕터 범위 설정
  - 가독성 뛰어난 1,500자 이상의 고품질 블로그 원고 집필

### 3.3 Stage 3: Shorts Discovery Phase (바이럴 숏폼 선별)
- **사용 모델**: `gemini-3.5-flash-lite`
- **입력**: Stage 1 정밀 노트 및 Stage 2 챕터 데이터
- **출력**: 숏폼 후보 구간 3개 리스트 (`start_time`, `end_time`, `viral_score`, `hook_text`, `script`)
- **System Prompt 지시사항**:
  - 가장 몰입도가 높고 시청자 유입(Hook)이 뛰어난 3개 구간 선별

---

## 4. Codebase 수정 대상 파일 및 변경 지침 (Code Blueprint)

### 4.1 `services/system_manager.py`
- `DEFAULT_CONFIG` 및 `ConfigManager` 내 작업별 최적 모델 자동 라우팅 매핑 업데이트:
  ```python
  DEFAULT_CONFIG = {
      "models": {
          "summarizer_map": "gemini-3.1-flash-lite",
          "summarizer_reduce": "gemini-3.5-flash-lite",
          "planner": "gemini-3.5-flash-lite",
          "shorts": "gemini-3.5-flash-lite",
          "whisper": "large-v3-turbo"
      }
  }
  ```

### 4.2 `services/summarizer.py`
- 기존 `_build_coarse_segments` 및 단순 압축 방식 폐지.
- `build_smart_chunks` 유틸리티 함수 구현.
- `VideoSummarizer` 클래스 내 `summarize_map_reduce()` 메서드 신설하여 1단계 Map 호출 loop 및 2단계 Reduce 호출을 연쇄 실행.

### 4.3 `services/shorts_maker.py`
- `_get_model()`을 `gemini-3.5-flash-lite`로 지정.
- Stage 1에서 뽑힌 정밀 노트를 수신하여 숏폼 선별 랭킹 프롬프트를 실행하도록 수정.

### 4.4 `app/application/pipeline_runner.py`
- 파이프라인 단계를 `[자막 생성] -> [지능형 Chunking] -> [Map 노트 추출 (3.1)] -> [Reduce 블로그/챕터 (3.5)] -> [Shorts 추출 (3.5)]` 순서로 스트리밍 상태 업데이트 UI 노출.

---

## 5. 검증 및 테스트 계획 (Testing Protocol)

1. **단단한 테스트 케이스 작성 (`tests/test_smart_chunker.py`)**:
   - `build_smart_chunks`가 글자 수($1,500 \sim 2,500\text{자}$)와 Overlap($200\text{자}$)을 올바르게 반영하는지 테스트.
   - 무음 시간 공백(Gap $\ge 1.5\text{초}$) 위치에서 끊기는지 검증.
2. **Map-Reduce 파이프라인 통합 테스트 (`tests/test_map_reduce_summarizer.py`)**:
   - Gemini API Mocking을 통해 Map 단계 $N$회 호출 및 Reduce 단계 1회 호출이 정상 동작하는지 테스트.

---

*본 설계서는 바이브 코딩 세션 진입 시 바로 참조하여 파일 수정을 시작할 수 있도록 완벽히 작성되었습니다.*
