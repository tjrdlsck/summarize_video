# 🎬 티키타카(Banter) 쇼츠 프롬프트 및 끝맺음 개선 계획서 (Prompt Optimization Plan)

---

## 1. 📌 현상 및 문제 정의 (Problem Definition)

티키타카(`Banter`) 및 리액션 하이라이트(`Reaction_Highlight`) 장르의 쇼츠 생성 시, 초반 훅과 대화 내용은 흥미로우나 **마무리 끝맺음(Punchline/Resolution)이 어색하고 뚝 끊기는 현상**이 발생함.

---

## 2. 🔍 원인 분석 (Root Cause Analysis)

### ① 프롬프트 지침의 '오프닝(Hook)' 편향과 '펀치라인' 지침 부재
- 기존 프롬프트(`shorts_maker.py`)는 오프닝의 시선 끌기(`첫 3초 억울함/폭소/티키타카 순간을 훅으로 잡으세요`)에만 가이드가 집중되어 있음.
- 대화의 최종 결말(Punchline / Resolution / Final Reaction)을 잡으라는 명시적 지침이 없어, 설정된 시간 범위($T_{\min} \le T \le T_{\max}$) 임계값 부근에서 무작위로 대화가 잘림.

### ② 대화 인접 쌍(Adjacency Pair) 및 턴(Turn-taking) 완결성 누락
- 티키타카는 2인 이상의 대화 인접 쌍(질문-답변, 드립-받아치기, 시비-팩폭 등) 구조를 가짐.
- 대화의 턴(Turn)이 완결되는 지점까지 자르도록 하는 프롬프트 조건이 부재하여, 상대방이 말을 받아치거나 반박하는 중간 문장에서 자막 및 영상 구간이 끊김.

### ③ 후처리 평가 로직의 단순 형태소/문장부호 의존
- `shorts_maker.py`의 `_evaluate_candidate` 내 결말 점수($S_{\text{ending}}$) 계산 시, 단순 문장 부호(`.`, `!`, `?`) 및 종결 어미(`다`, `요`) 유무만 판별함.
- 대화형 쇼츠에 필수적인 감정적/서사적 마무리(Emotional Resolution, 최종 팩폭, 당황한 침묵, 폭소 등)를 정밀히 측정하지 못함.

---

## 3. 💡 프롬프트 및 시스템 개선 방안 (Optimization Strategy)

### ① `Hook - Development - Punchline` 3단계 서사 구조 지침 도입
- 오프닝(Hook)뿐만 아니라 대화 전개(Development)와 최종 마무리 펀치라인(Punchline)을 반드시 포함하도록 프롬프트 지침 구조화.

### ② 대화 턴(Conversational Turn) 종결 조건 명시
- 대화 상대방의 발언 시작 직후나 문장 중간에서 cut이 일어나지 않도록 strict rule 적용.

---

## 4. 📝 세부 수정 내용 (Implementation Details)

### 4.1. `services/shorts_maker.py` 프롬프트 지침 수정

```python
# [services/shorts_maker.py 수정안]
"- 챕터 성격별 편집 지침:\n"
"  * Reaction_Highlight / Banter: [Hook-Development-Punchline 3단계 구조 준수]\n"
"    1) Hook(첫 3초): 강한 억울함/폭소/티키타카 시작 지점으로 시선 집중.\n"
"    2) Development: 출연진 간 티키타카 대화 턴(Turn)이 끊기지 않고 자연스럽게 오가는 구간 유지.\n"
"    3) Punchline(마무리): 반드시 한쪽의 확실한 팩트 폭격, 당황한 침묵, 최종 인정, 혹은 함박웃음으로 대화가 유쾌하게 완결되는 턴(Turn)까지 포함하세요. 대화 상대방의 발언 시작 직후나 문장 중간 자르기 절대 금지.\n"
```

### 4.2. `services/content_profiles.py` 시스템 지침 보강

```python
# [services/content_profiles.py 수정안]
shorts_system_instruction=(
    "당신은 조회수를 만드는 스트리밍 숏폼 전문 편집자입니다.\n"
    "제공된 스트리밍 스크립트에서 반응이 강하고, 대화의 시작부터 final punchline(결말 리액션)까지 맥락이 완결된 구간을 선별하세요."
)
```

---

## 5. ⚡ Gemini Flash-Lite 모델 편향 대응 및 비연속 점프컷(Jump Cut) 기획 방안

### ① '쇼츠(Shorts)' 키워드의 시맨틱 편향 (Semantic Bias)
- 프롬프트에 '쇼츠'라는 어휘가 강하게 지정되면 사전 학습 데이터 특성상 **1개의 짧은 연속된 클립(Single Continuous Block)**을 선택하려는 편향이 나타남.
- 해결: 단순 "쇼츠 자르기" 지침 대신 **"비연속 다중 타임스탬프 몽타주(Non-contiguous Segment Chain)"** 개념으로 프레이밍 보강.

### ② 라이브 대화의 불필요 구간 생략(Skip / Jump Cut) 지침 보강
- 라이브 방송 특성상 [드립 시작] $\rightarrow$ (중간 잡담/세팅/정적) $\rightarrow$ [결말 팩폭] 구조가 자주 발생함.
- 모델이 중간 불필요 대화를 적극적으로 쳐내고 비연속 타임스탬프 조각들을 연결할 수 있도록 rule 보강.

```python
# [services/shorts_maker.py - rules 추가안]
"- [점프 컷(Jump Cut) 적극 활용]: 라이브 대화 특성상 중간의 몰입을 해치는 정적, 세팅 멘트, 불필요한 잡담 구간은 적극적으로 제외(Skip)하세요.\n"
"- 하나의 후보는 연속된 1개의 클립일 필요가 없으며, 2~4개의 비연속 타임스탬프 조각(Segments)을 이어 붙여 서사를 완성할 수 있습니다.\n"
"- [구조 예시]: Hook -> (중간 잡담 생략) -> Counter-punch 형태의 다중 segments 구성 권장.\n"
```

### ③ Response Schema 다중 Segment 조각 허용
- Gemini API의 `response_schema`에 1개 후보(candidate) 내 다중 `segments` 배열(`[{"start": s1, "end": e1}, {"start": s2, "end": e2}]`) 생성을 보장하여 유연한 점프컷 조합 지원.

---

## 6. 🎯 기대 효과 (Expected Outcomes)

1. **서사적 완결성 증대**: `Hook` $\rightarrow$ `Development` $\rightarrow$ `Punchline` 서사 구조 확보로 쇼츠 끝맺음 몰입감 극대화.
2. **비연속 점프 컷 활성화**: 군더더기 대화 생략으로 전개 속도감 증대 및 몰입 유지.
3. **시청자 체류 시간 향상**: 대화 끊김 현상이 해소되어 시청자 이탈률 감소 및 재생 완수율(Completion Rate) 증가.
