"""Request body schemas."""

from typing import Literal, Optional

from pydantic import BaseModel


class TranscriptionRequest(BaseModel):
    """1단계: 다운로드/자막 생성 요청."""

    url: Optional[str] = None
    filename: Optional[str] = None
    custom_title: Optional[str] = None
    content_type: Literal["sermon", "streaming", "informational"] = "sermon"


class SettingsUpdateRequest(BaseModel):
    """설정 업데이트 요청."""

    models: dict


class SummaryRequest(BaseModel):
    """2단계: 요약 분석 요청."""

    filename: str
    custom_title: Optional[str] = None
    content_type: Literal["sermon", "streaming", "informational"] = "sermon"


class BlogGenerationRequest(BaseModel):
    """3단계: 블로그 생성 요청."""

    filename: str


class UpdateTitleRequest(BaseModel):
    """히스토리 제목 수정 요청."""

    title: str


class ClipRequest(BaseModel):
    """클립 생성 요청."""

    filename: str
    start_time: float
    end_time: float
    title: Optional[str] = "Untitled Clip"


class ShortsGenerateRequest(BaseModel):
    """AI 숏츠 자동 생성 요청."""

    filename: str
    focus_topic: Optional[str] = None
    content_type: Literal["sermon", "streaming", "informational"] = "sermon"
    style: Literal["funny", "balanced"] = "funny"
    min_duration: float = 40.0
    max_duration: float = 90.0
    humor_weight: int = 50
    keep_original_tone: bool = True
    speaker_mode: Literal["none", "pseudo", "full"] = "pseudo"


class PremiereExportRequest(BaseModel):
    """프리미어 XML 내보내기 요청."""

    video_filename: str
    clip_id: str
    custom_video_filename: Optional[str] = None
    max_chars: Optional[int] = 10
    max_lines: Optional[int] = 2
