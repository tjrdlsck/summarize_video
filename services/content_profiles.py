"""Content-type specific profile registry for prompt and schema strategy."""

from dataclasses import dataclass

SUPPORTED_CONTENT_TYPES = ("sermon", "streaming", "informational")
DEFAULT_CONTENT_TYPE = "sermon"


@dataclass(frozen=True)
class ContentProfile:
    """도메인별 분석/생성 정책 묶음."""

    content_type: str
    profile_version: str
    asr_initial_prompt: str
    summary_type_enum: list[str]
    summary_system_instruction: str
    refine_system_instruction: str
    shorts_target_types: list[str]
    shorts_system_instruction: str
    cot_thinking_guide: str
    blog_few_shot_example: str
    impact_criteria: str


SERMON_PROFILE = ContentProfile(
    content_type="sermon",
    profile_version="v1",
    asr_initial_prompt=(
        "이 영상은 한국 교회의 기독교 목사님 설교 영상입니다. 성경 말씀, 기도, 하나님, 예수님, "
        "은혜, 아멘, 할렐루야 등의 기독교 용어가 포함되어 있습니다."
    ),
    summary_type_enum=[
        "Intro_Icebreak",
        "Scripture",
        "Preaching_Main",
        "Illustration",
        "Application",
        "Announcement",
        "Prayer",
    ],
    summary_system_instruction=(
        "당신은 설교 영상 전문 미디어 팀장입니다. 제공된 대본을 분석하여 '1차 컷편집(Rough Cut)'을 위한 기획안을 JSON으로 출력하세요.\n"
        "목표: 편집자가 불필요한 구간을 빠르게 제거하고, 핵심 구간(예화, 강조점)을 찾아낼 수 있도록 돕는 것.\n\n"
        "**[분류 규칙]**\n"
        "1. Intro_Icebreak: 설교 전 인사, 가벼운 대화, 날씨 이야기 등.\n"
        "2. Scripture: 성경 본문 봉독 구간. (정확한 시작과 끝 지점 포착 필수)\n"
        "3. Preaching_Main: 본문 해석, 교리 설명 등 설교의 메인 흐름.\n"
        "4. Illustration: 시청자의 몰입을 돕는 예화, 에피소드, 유머 구간. (중요: 별도 챕터로 분리하여 하이라이트화)\n"
        "5. Application: 성도들을 향한 삶의 권면, 핵심 메시지 선포, 결단.\n"
        "6. Announcement: 교회 광고, 캠페인, 내빈 소개 등. (편집 시 삭제 1순위 후보)\n"
        "7. Prayer: 마무리 기도, 축도.\n\n"
        "**[작성 가이드라인]**\n"
        "- 영상의 처음(ID:1)부터 끝까지 빈틈없이 나누세요.\n"
        "- 'Announcement' 구간을 아주 정밀하게 분리하세요. 유튜브 업로드 시 이 구간을 잘라내는 것이 편집자의 주된 업무입니다.\n"
        "- 모든 텍스트는 한국어로 작성하세요."
    ),
    refine_system_instruction=(
        "당신은 영성 깊은 기독교 문서 선교사이자 설교 요약 전문 칼럼니스트입니다.\n"
        "제공된 설교 스크립트를 바탕으로 성도들에게 깊은 은혜와 영적 통찰을 전하는 정갈한 묵상 칼럼 섹션을 작성하세요."
    ),
    shorts_target_types=["Illustration", "Preaching_Main", "Application"],
    shorts_system_instruction=(
        "당신은 수백만 조회수를 기록하는 기독교 은혜 숏츠 전문 PD입니다.\n"
        "제공된 설교 대본(Script)에서 시청자의 이목을 사로잡을 수 있는 '알짜배기' 구간을 발굴하여 기획안을 작성하세요."
    ),
    cot_thinking_guide=(
        "1. 설교 대본에서 목사님이 강조하시는 핵심 영적 메시지와 본문 원리를 추출하세요.\n"
        "2. 성도들이 일상 삶의 현장에서 마주하는 고난 극복 간증(Testimony) 및 실천적 적용점(Application Point)을 파악하세요.\n"
        "3. 은혜와 결단을 전하는 감동적인 묵상 칼럼 개요를 작성하고, 문단별 대본 출처 ID([[ID:숫자]]) 매핑을 수립하세요."
    ),
    blog_few_shot_example=(
        "<example>\n"
        "<input>\n"
        "15 | 사랑하는 성도 여러분, 인생의 풍랑을 만났을 때 우리가 해야 할 첫 번째 일은 두려워하는 것이 아니라 주님을 바라보는 것입니다.\n"
        "16 | 마가복음 4장에서 제자들은 풍랑 속에서 주님을 깨웠습니다. 여러분의 삶의 풍랑 속에서도 주님은 항상 여러분과 함께 배에 타고 계십니다.\n"
        "17 | 이번 한 주간 문제보다 크신 하나님을 신뢰하며 담대하게 나아가시기를 축원합니다.\n"
        "</input>\n"
        "<output>\n"
        "### 🌊 인생의 풍랑 속에서 우리가 주님을 바라보아야 하는 이유\n\n"
        "인생을 살아가다 보면 예고 없이 닥쳐오는 고난과 두려움의 풍랑을 만날 때가 있습니다.[[ID:15]] 하지만 그 순간 우리가 기억해야 할 핵심 진리는 주님께서 이미 우리 삶이라는 배에 함께 타고 계신다는 사실입니다.[[ID:16]]\n\n"
        "> **\"문제보다 크신 하나님을 신뢰하며 담대히 나아가십시오.\"**[[ID:17]]\n\n"
        "이번 한 주간, 눈앞의 풍랑 때문에 침몰할 것 같은 두려움이 엄습할 때 기도함으로 주님을 깨우십시오. 주님께서 여러분의 삶을 명하여 평안케 하실 것입니다.\n"
        "</output>\n"
        "</example>"
    ),
    impact_criteria=(
        "목사님의 강렬한 영적 메시지 선포/결단 문장, 삶의 고난과 위기를 기도로 극복한 감동적인 은혜의 간증(Testimony) 클라이맥스, 실천적 삶의 권면"
    ),
)


STREAMING_PROFILE = ContentProfile(
    content_type="streaming",
    profile_version="v1",
    asr_initial_prompt=(
        "이 영상은 한국어 라이브 스트리밍입니다. 여러 화자 간 대화, 즉흥 반응, 게임/토크 맥락, "
        "밈이나 구어체 표현이 포함될 수 있습니다. 화자 전환과 감탄사를 자연스럽게 인식하세요."
    ),
    summary_type_enum=[
        "Opening",
        "Banter",
        "Main_Content",
        "Reaction_Highlight",
        "QnA",
        "Ad_Promo",
        "Closing",
    ],
    summary_system_instruction=(
        "당신은 라이브 스트리밍 편집 팀장입니다. 대본을 분석하여 하이라이트 편집에 바로 사용할 JSON 기획안을 만드세요.\n"
        "목표: 흐름을 유지하면서 웃음 포인트, 리액션, 핵심 발언을 빠르게 찾는 것.\n\n"
        "**[분류 규칙]**\n"
        "1. Opening: 방송 시작 안내, 인사, 세팅 멘트.\n"
        "2. Banter: 티키타카, 잡담, 드립, 캐주얼한 대화.\n"
        "3. Main_Content: 방송의 핵심 진행 구간(게임, 토론, 리뷰 등).\n"
        "4. Reaction_Highlight: 감정 반응이 강한 순간, 웃음/놀람/환호 포인트.\n"
        "5. QnA: 시청자 질문 답변, 채팅 상호작용.\n"
        "6. Ad_Promo: 광고, 후원 멘션, 홍보 안내.\n"
        "7. Closing: 마무리 멘트, 다음 방송 예고.\n\n"
        "**[작성 가이드라인]**\n"
        "- 영상의 처음(ID:1)부터 끝까지 빈틈없이 나누세요.\n"
        "- Ad_Promo를 정밀하게 분리하세요.\n"
        "- 모든 텍스트는 한국어로 작성하세요."
    ),
    refine_system_instruction=(
        "당신은 인기 인플루언서 미디어 리뷰어이자 커뮤니티 에디터입니다.\n"
        "제공된 라이브 스트리밍 스크립트를 바탕으로 생동감 넘치고 유쾌한 하이라이트 리포트 섹션을 작성하세요."
    ),
    shorts_target_types=["Reaction_Highlight", "Banter", "Main_Content", "QnA"],
    shorts_system_instruction=(
        "당신은 조회수를 만드는 스트리밍 숏폼 전문 편집자입니다.\n"
        "제공된 스트리밍 스크립트에서 반응이 강하고 맥락이 완결된 구간을 선별하세요."
    ),
    cot_thinking_guide=(
        "1. 방송 스크립트 중 가장 리액션이 컸거나, 유쾌한 디스/팩트폭격/억울함이 폭발한 핵심 밈 하이라이트 순간을 포착하세요.\n"
        "2. 출연진 간에 오간 찰떡같은 남탓 티키타카 드립 및 시청자 반응 포인트를 정리하세요.\n"
        "3. 생동감 넘치는 현장감이 느껴지도록 시청자 관점의 유쾌한 에피소드 개요를 작성하고 출처 ID([[ID:숫자]])를 매핑하세요."
    ),
    blog_few_shot_example=(
        "<example>\n"
        "<input>\n"
        "42 | 스트리머: 아니 이걸 보스한테 패배한다고? 말도 안 돼!\n"
        "43 | 게스트: 그러니까 제가 거기서 힐을 넣으라고 했잖아요! 난 몰라요 이제~\n"
        "44 | 스트리머: 아 레전드 억울하네 진짜... 여러분 이건 제 컨트롤 미스가 아니라 서버 렉입니다. 아무튼 렉임!\n"
        "</input>\n"
        "<output>\n"
        "### 🎮 보스전 패배 후 '서버 렉' 남탓 시전하는 억울함 레전드 장면\n\n"
        "다 잡은 보스전에서 허무하게 패배하자 스트리머와 게스트의 찰떡같은 남탓 티키타카가 터졌습니다.[[ID:42, ID:43]]\n\n"
        "게스트의 팩트 폭격에 당황한 스트리머는 결국 현란한 남탓 핑계를 대기 시작했습니다.\n\n"
        "> **\"이건 제 컨트롤 미스가 아니라 서버 렉입니다. 아무튼 렉임!\"**[[ID:44]]\n\n"
        "억울함으로 얼룩진 레전드 패배 현장, 스트리머의 당황한 표정이 관전 포인트였습니다!\n"
        "</output>\n"
        "</example>"
    ),
    impact_criteria=(
        "출연진 간 유쾌한 디스(Roasting)/팩트폭격/돌려까기, 억울한 남탓(서버 렉, 팀원 탓) 시전, 당황/킹받음/폭소 텐션 폭발 순간"
    ),
)


INFORMATIONAL_PROFILE = ContentProfile(
    content_type="informational",
    profile_version="v1",
    asr_initial_prompt=(
        "이 영상은 한국어 정보성 콘텐츠입니다. 설명 중심 문장, 용어 정의, 예시, 결론 요약이 포함될 수 있습니다. "
        "전문 용어와 숫자 정보를 정확하게 인식하세요."
    ),
    summary_type_enum=[
        "Intro",
        "Problem_Definition",
        "Core_Explanation",
        "Example_Case",
        "Key_Takeaway",
        "CTA",
    ],
    summary_system_instruction=(
        "당신은 정보성 영상 편집 팀장입니다. 대본을 분석해 학습 효율이 높은 챕터 기획안을 JSON으로 출력하세요.\n"
        "목표: 핵심 개념과 결론을 빠르게 재사용 가능한 단위로 분리하는 것.\n\n"
        "**[분류 규칙]**\n"
        "1. Intro: 주제 소개와 문제 제기.\n"
        "2. Problem_Definition: 해결하려는 문제/배경 정의.\n"
        "3. Core_Explanation: 핵심 이론/절차 설명.\n"
        "4. Example_Case: 예시, 사례, 데모.\n"
        "5. Key_Takeaway: 핵심 요약, 실무 적용 포인트.\n"
        "6. CTA: 구독 유도, 다음 영상 안내, 링크 안내.\n\n"
        "**[작성 가이드라인]**\n"
        "- 영상의 처음(ID:1)부터 끝까지 빈틈없이 나누세요.\n"
        "- CTA 구간은 별도로 정확히 분리하세요.\n"
        "- 모든 텍스트는 한국어로 작성하세요."
    ),
    refine_system_instruction=(
        "당신은 테크/지식 전문 IT 테크니컬 라이터이자 인포그래픽 에디터입니다.\n"
        "제공된 정보성 스크립트를 바탕으로 독자가 빠르고 정확하게 학습할 수 있는 명료한 기술 가이드 섹션을 작성하세요."
    ),
    shorts_target_types=["Core_Explanation", "Example_Case", "Key_Takeaway"],
    shorts_system_instruction=(
        "당신은 1분 지식/꿀팁 전문 숏폼 기획자입니다.\n"
        "제공된 스크립트에서 한 번에 이해되는 핵심 지식 구간을 골라 숏츠로 재구성하세요."
    ),
    cot_thinking_guide=(
        "1. 대본 내 객관적 핵심 지식/데이터 및 해결 기술(Solutions)을 추출하세요.\n"
        "2. 독자가 겪는 대표적인 문제 상황(Pain Point)과 얻을 정보적 가치를 정의하세요.\n"
        "3. Problem(문제)-Agitate(심화)-Solve(해결) 서사 구조의 마크다운 요약 개요를 설계하고 출처 ID([[ID:숫자]])를 매핑하세요."
    ),
    blog_few_shot_example=(
        "<example>\n"
        "<input>\n"
        "8 | 많은 초보 개발자분들이 프롬프트를 길게 쓰면 지시를 더 잘 따를 것이라고 오해합니다.\n"
        "9 | 하지만 프롬프트가 길어질수록 모델의 주의력이 분산되어 지시사항을 무시하는 현상이 일어납니다.\n"
        "10 | 이를 해결하기 위해 XML 태그를 써서 구획을 명확히 구분하고 핵심 규칙은 맨 마지막에 배치해야 합니다.\n"
        "</input>\n"
        "<output>\n"
        "### 💡 프롬프트가 길어질수록 AI가 말을 안 듣는 이유와 해결책\n\n"
        "많은 개발자들이 원하는 결과를 얻기 위해 프롬프트를 무작정 길게 작성하곤 합니다.[[ID:8]] 그러나 지시문이 길어질수록 AI 모델의 어텐션이 분산되어 오히려 지시사항을 무시하는 현상이 발생합니다.[[ID:9]]\n\n"
        "#### 🛠️ 프롬프트 밀도를 높이는 2가지 핵심 기술\n"
        "1. **XML 태그로 영역 구분**: 지시문과 입력 데이터를 `<rules>`, `<script_data>` 등으로 완벽히 격리합니다.[[ID:10]]\n"
        "2. **핵심 규칙 후방 배치**: 가장 중요한 제약 조건은 프롬프트 맨 마지막에 한 번 더 고정합니다.[[ID:10]]\n"
        "</output>\n"
        "</example>"
    ),
    impact_criteria=(
        "시청자의 오해/페인포인트를 해결하는 통찰 문장, 핵심 데이터/수치가 집약된 결론 솔루션 발언"
    ),
)


_PROFILES = {
    "sermon": SERMON_PROFILE,
    "streaming": STREAMING_PROFILE,
    "informational": INFORMATIONAL_PROFILE,
}


def normalize_content_type(content_type: str | None) -> str:
    """입력 콘텐츠 타입을 정규화하고 미지원 값은 기본값으로 대체."""

    if not content_type:
        return DEFAULT_CONTENT_TYPE
    normalized = str(content_type).strip().lower()
    if normalized in _PROFILES:
        return normalized
    return DEFAULT_CONTENT_TYPE


def get_content_profile(content_type: str | None) -> ContentProfile:
    """콘텐츠 타입에 맞는 프로파일을 반환."""

    return _PROFILES[normalize_content_type(content_type)]
