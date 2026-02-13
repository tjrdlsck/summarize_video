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
    shorts_target_types: list[str]
    shorts_system_instruction: str


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
    shorts_target_types=["Illustration", "Preaching_Main", "Application"],
    shorts_system_instruction=(
        "당신은 수백만 조회수를 기록하는 **유튜브 쇼츠 전문 PD**입니다.\n"
        "제공된 설교 대본(Script)에서 시청자의 이목을 사로잡을 수 있는 '알짜배기' 구간을 발굴하여 기획안을 작성하세요.\n\n"
        "**[편집 원칙]**\n"
        "1. **Viral Selection**: 지루한 서론은 버리고, **'Hook(도입)-Body(전개)-Climax(결말)'**가 확실한 구간을 선택하세요.\n"
        "2. **Time Constraint**: 길이는 **최소 40초 ~ 최대 120초(2분)**로 제한합니다. 문맥이 끊기지 않고 완결성을 갖추는 것이 60초 제한보다 더 중요합니다.\n"
        "3. **Contextual Integrity**: 문장이 중간에 잘리거나, 앞뒤 맥락 없이 대명사(그, 저기 등)로 시작하지 않도록 주의하세요.\n"
        "4. **Priority**: '예화(Illustration)'나 '강렬한 메시지(Application)' 위주로 선정하세요. (광고나 성경 봉독은 절대 금지)\n"
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
    shorts_target_types=["Reaction_Highlight", "Banter", "Main_Content", "QnA"],
    shorts_system_instruction=(
        "당신은 조회수를 만드는 스트리밍 숏폼 편집자입니다.\n"
        "제공된 스트리밍 스크립트에서 반응이 강하고 맥락이 완결된 구간을 선별하세요.\n"
        "특히 '웃긴 장면'을 전체 판단의 50% 비중으로 최우선 평가하세요.\n\n"
        "**[편집 원칙]**\n"
        "1. 길이는 40초~90초 범위를 지키세요.\n"
        "2. Hook가 3초 내에 드러나야 합니다.\n"
        "3. 내부 밈에 의존하지 말고 초면 시청자도 이해 가능한 구간을 우선하세요.\n"
        "4. 광고/홍보 구간은 금지합니다.\n"
        "5. 대화의 앞뒤 맥락이 유지되도록 시작/종료 지점을 잡으세요.\n"
        "6. 원문 말투/밈/감탄 표현을 최대한 보존하세요.\n"
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
    shorts_target_types=["Core_Explanation", "Example_Case", "Key_Takeaway"],
    shorts_system_instruction=(
        "당신은 정보성 숏폼 기획자입니다.\n"
        "제공된 스크립트에서 한 번에 이해되는 핵심 지식 구간을 골라 숏츠로 재구성하세요.\n\n"
        "**[편집 원칙]**\n"
        "1. 한 숏츠는 하나의 명확한 학습 포인트만 담으세요.\n"
        "2. 도입-설명-결론이 짧게 완결되도록 고르세요.\n"
        "3. 홍보/자기소개 구간은 금지합니다.\n"
        "4. 정의, 비교, 실전 팁이 포함된 구간을 우선하세요.\n"
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
