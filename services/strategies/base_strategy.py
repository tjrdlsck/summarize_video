from abc import ABC, abstractmethod
from typing import List, Dict, Any

class AnalysisStrategy(ABC):
    """
    영상 분석을 위한 추상 전략 인터페이스
    """
    
    @property
    @abstractmethod
    def mode_name(self) -> str:
        """전략의 이름 (e.g., 'sermon', 'entertainment')"""
        pass

    @abstractmethod
    def get_analysis_prompt(self, video_title: str, transcripts_text: str) -> str:
        """분석을 위한 메인 시스템 프롬프트 반환"""
        pass

    @abstractmethod
    def get_blog_structure_prompt(self, video_title: str, transcripts_text: str) -> str:
        """블로그 구조 설계를 위한 프롬프트 반환"""
        pass

    @abstractmethod
    def get_category_definitions(self) -> List[Dict[str, str]]:
        """챕터 분류를 위한 카테고리 정의 반환"""
        pass
