# 🎬 티키타카(Banter) 쇼츠 프롬프트 및 끝맺음 개선 계획서 (Prompt Optimization Plan)

---

## 1. 📌 현상 및 문제 정의 (Problem Definition)

티키타카(`Banter`) 및 리액션 하이라이트(`Reaction_Highlight`) 장르의 쇼츠 생성 시 다음과 같은 한계가 존재함:
1. 초반 훅과 대화 내용은 흥미로우나 **마무리 끝맺음(Punchline/Resolution)이 어색하고 뚝 끊기는 현상** 발생.
2. `STREAMING_PROFILE` 내 프롬프트 및 시스템 지침의 어휘 특성으로 인해 모델이 라이브 방송 대화 맥락을 고려하지 않고 **단순히 매우 짧은 연속 클립으로 강제 세그먼팅**함.
3. 대화 중간에 껴있는 딴소리/정적을 쳐내려고 LLM에 비연속 점프컷(Jump Cut) 계산까지 일괄 전임시킬 경우, 타임스탬프 계산 오류 및 환각(Hallucination) 위험이 증가함.

---

## 2. 🔍 장르별 특성 및 원인 분석 (Genre-specific Analysis)

### ① 대화형 콘텐츠 (스트리밍 / 티키타카)
- **원인**: 기존 프롬프트는 오프닝의 시선 끌기(`첫 3초 억울함/폭소/티키타카 순간을 훅으로 잡으세요`)에만 가이드가 집중되어 대화의 최종 결말(Punchline / Resolution) 지침이 부재함.
- **특성**: 2인 이상의 대화 턴(Turn-taking) 구조이므로, 대화 중간의 정적/잡담을 안전하게 걸러내는 하이브리드 접근법이 필수적임.

### ② 1인 화자 콘텐츠 (설교 / 강연·세미나)
- **기존 프로필의 우수성**:  
  - 설교(`SERMON_PROFILE`): `[고난/시련] → [영적 원리] → [은혜와 결단]`의 연속적 감동 서사가 이미 잘 기획되어 있음.
  - 세미나(`SEMINAR_PROFILE`): `[Problem] → [Agitate] → [Solve]`의 지식 전달 3단계 프레임워크가 이미 최적화되어 있음.
- **전략**: 1인 화자 영상은 중간을 점프컷 하면 오히려 감동과 논리의 흐름이 깨지므로 **기존의 뛰어난 연속 서사 프로필 지침을 100% 유지**함.

---

## 3. 💡 스트리밍 전용 하이브리드 편집 아키텍처 (Hybrid Interactive Architecture)

티키타카/스트리밍 장르의 끝맺음 및 잡담 문제를 해결하기 위해 **"AI 통맥락 선별 + UI 스마트 스킵 제안(Human-in-the-Loop)"** 2단계 아키텍처를 도입함.

```
[ 1단계: AI 통맥락 추출 (스트리밍 프로필 전용) ]
  - 앞부분(Hook/드립)과 뒷부분(Punchline/팩폭)을 이어 붙였을 때 유쾌함이 완성되는 전체 범위(Parent Window)를 통째로 선별.
  - 중간에 3~10초간 관련 없는 딴소리가 포함되어 있더라도 서사의 완결성을 우선하여 통째 구간으로 1차 확정.
        │
        ▼
[ 2단계: AI 내부 스킵(Skip) 지점 추천 ]
  - 통째 구간 내부에서 텐션을 해치는 불필요 구간(정적, 세팅 멘트, 딴소리)을 탐지하여 recommended_skips 목록 생성.
        │
        ▼
[ 3단계: 사용자 UI 인터랙티브 조작 ]
  - 타임라인 상에 "✂️ 15s ~ 18s 스킵 추천 (3초 절약)" 뱃지를 토글(ON/OFF) 가능하도록 제시.
  - AI 환각 위험 제로화 및 사용자 편집 자율성 보장.
```

---

## 4. 📝 세부 수정 및 데이터 스키마 가이드 (Backend Implementation)

### 4.1. 컨텐츠 프로필(`services/content_profiles.py`) 개정 방향

1. **스트리밍 프로필 (`STREAMING_PROFILE`)**: 하이라이트 맥락 완결성 및 펀치라인 강조로 지침 개정.
2. **설교/세미나 프로필 (`SERMON_PROFILE`, `SEMINAR_PROFILE`)**: 기존의 우수한 서사 추출 프롬프트 **100% 보수 유지**.

```python
# [services/content_profiles.py - STREAMING_PROFILE 수정안]
shorts_system_instruction=(
    "당신은 시청자 몰입도를 극대화하는 스트리밍 하이라이트 전문 편집자입니다.\n"
    "제공된 스트리밍 스크립트에서 반응이 강하고, 대화의 시작부터 결말 펀치라인(Punchline)까지 맥락이 유기적으로 연결된 통구간을 선별하세요."
)
```

### 4.2. `services/shorts_maker.py` 프롬프트 지침 수정

```python
# [services/shorts_maker.py 수정안]
"- 챕터 성격별 편집 지침:\n"
"  * Reaction_Highlight / Banter: [Hook-Development-Punchline 3단계 통맥락 준수]\n"
"    1) Hook(첫 3초): 강한 억울함/폭소/티키타카 시작 지점으로 시선 집중.\n"
"    2) Development: 중간에 불필요 대화가 일부 섞이더라도 앞뒤 맥락이 자연스럽게 연결되도록 대화 턴(Turn)을 통째로 포함.\n"
"    3) Punchline(마무리): 반드시 한쪽의 확실한 팩트 폭격, 당황한 침묵, 최종 인정, 혹은 함박웃음으로 대화가 유쾌하게 완결되는 턴(Turn)까지 포함하세요. 대화 상대방의 발언 시작 직후나 문장 중간 자르기 절대 금지.\n"
"  * Illustration / Application: 기존의 감동적인 묵직한 문장 및 은혜 결단 중심 선별 유지.\n"
"  * Core_Explanation / Key_Takeaway: 기존의 핵심 수치/꿀팁 명확 전개 구간 선별 유지.\n"
```

### 4.3. Response Schema 확장 (스트리밍용 추천 스킵 데이터 추가)

AI가 통맥락 구간과 내부 추천 스킵 지점을 동시에 반환할 수 있도록 JSON Schema 확장:

```json
{
  "title": "서버 렉 핑계 대는 스트리머",
  "reason": "보스전 패배 후 게스트와의 남탓 티키타카 하이라이트",
  "overall_segment": {
    "start": 102.5,
    "end": 148.0
  },
  "recommended_skips": [
    {
      "start": 115.0,
      "end": 120.2,
      "reason": "✂️ 음료수 마시는 정적 및 딴소리 구간 (스킵 추천)"
    }
  ]
}
```

---

## 5. 🎨 프론트엔드 UI/UX 확장 명세 (Frontend UI/UX Specification)

새로운 추천 스킵(Jump-cut) 기능을 사용자가 조작하고 미리보기 할 수 있도록 `static/js/app.js` 카드 뷰 및 플레이어 파이프라인에 UI 요소를 추가함.

### 5.1. AI 숏츠 카드 내 스킵 제안 컴포넌트 (`SkipRecommendationBadge`)
- **위치**: 숏츠 아이템 카드 하단 자막 대본 위 영역.
- **구성**:
  - `✂️ 스마트 스킵 추천 (N개 구간)` 토글 아코디언.
  - 각 스킵 지점별 `[ON/OFF]` 스위치 칩(Chip): 사용자가 클릭하여 특정 스킵 적용 여부 지정.
  - 예: `[ ✂️ 115s~120s 딴소리 제거 (5.2초 절약) - ON ]`

### 5.2. 플레이어 자동 점프 컷 연동 (Interactive Player Skip Sync)
- **미리보기 시**: 비디오 플레이어의 `onTimeUpdate` 이벤트 발생 시, active 스킵 구간의 `start` 지점에 도달하면 `video.currentTime = skip.end`로 자동 점프시켜 스킵 반영 미리보기 제공.
- **스크립트 하이라이트**: 스킵 적용된 구간은 대본 영역에서 사선(취소선) 및 취결색(Light Gray)으로 시각적 구분 처리.

### 5.3. 렌더링 / 다운로드 파이프라인 선택 (Export Options)
- 숏츠 비디오 다운로드 또는 클립 합성 요청 시 `use_recommended_skips: true` 플래그를 전달하여 ffmpeg 렌더링 엔진이 자른 영상들만 이어 붙여 합성하도록 지원.

---

## 6. 🎯 기대 효과 (Expected Outcomes)

1. **장르별 최적화 전략 수립**: 스트리밍(티키타카)은 하이브리드 점프컷으로 텐션 극대화, 설교/지식은 기존 서사 유지로 은혜/정보 전달력 극대화.
2. **AI 추론 신뢰성 확보**: LLM의 타임스탬프 환각 오류 및 무작위 자르기 현상 완전 방지.
3. **편집 자율성 및 UX 향상**: 사용자가 UI 상에서 1클릭 토글만으로 군더더기 구간을 선택적으로 제외 및 실시간 미리보기 가능.
