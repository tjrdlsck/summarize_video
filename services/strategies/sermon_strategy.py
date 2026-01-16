from typing import List, Dict, Any
from services.strategies.base_strategy import AnalysisStrategy

class SermonStrategy(AnalysisStrategy):
    """
    기독교 설교 영상 분석을 위한 구체적 전략
    """

    @property
    def mode_name(self) -> str:
        return "sermon"

    def get_analysis_prompt(self, video_title: str, transcripts_text: str) -> str:
        return (
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
            "- 모든 텍스트는 한국어로 작성하세요.\n\n"
            f"[Video Title]: {video_title}\n\n"
            f"[Script Data]:\n{transcripts_text}"
        )

    def get_blog_structure_prompt(self, video_title: str, transcripts_text: str) -> str:
        return (
            "당신은 설교 콘텐츠를 고품질 블로그 포스트로 변환하는 기독교 전문 에디터입니다.\n"
            "제공된 전체 스크립트를 분석하여 성도들이 몰입할 수 있는 논리적인 설교 요약 블로그 구조를 설계하세요.\n"
            "영상의 처음(ID:1)부터 끝까지 빈틈없이 챕터를 나누어야 합니다.\n"
            "각 챕터는 단순 요약이 아닌, 설교의 영성과 메시지를 담은 완결된 이야기를 구성할 수 있도록 ID 범위를 지정하세요.\n\n"
            f"[Video Title]: {video_title}\n\n"
            f"[Full Script]:\n{transcripts_text}"
        )

    def get_category_definitions(self) -> List[Dict[str, str]]:
        return [
            {"name": "Intro_Icebreak", "description": "인사 및 도입부"},
            {"name": "Scripture", "description": "성경 봉독"},
            {"name": "Preaching_Main", "description": "설교 본론"},
            {"name": "Illustration", "description": "예화 및 에피소드"},
            {"name": "Application", "description": "적용 및 결단"},
            {"name": "Announcement", "description": "광고 및 안내"},
            {"name": "Prayer", "description": "기도 및 축도"}
        ]
