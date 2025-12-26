import os
import re  # [Add] 정규표현식 모듈 추가
from dotenv import load_dotenv
from google import genai
from google.genai import types

class TextRefiner:
    """
    Gemma 모델을 사용하여 Raw Transcript를 읽기 좋은 블로그 포스트 형태(Markdown)로 윤문하는 클래스
    """
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY")
        # gemma-3-27b-it 모델 사용
        self.model_name = "gemma-3-27b-it" 
        self.client = None
        
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    def refine_chapter(self, raw_text: str, chapter_title: str = "") -> str:
        """챕터별 텍스트를 입력받아 가독성이 극대화된 Markdown 형식으로 윤문합니다.

        Args:
            raw_text (str): 윤문할 원본 텍스트(타임스탬프 포함).
            chapter_title (str): 해당 챕터의 제목.

        Returns:
            str: 타임스탬프별로 문단이 명확히 분리된 구조화된 Markdown 텍스트.
        """
        if not self.client:
            return "API Key missing."

        if not raw_text or len(raw_text.strip()) < 10:
            return "내용이 너무 짧아 요약할 수 없습니다."

        # 프롬프트 엔지니어링: 타임스탬프 기반 문단 분리 및 수직 나열 강제
        prompt = f"""
        You are an expert AI blog editor specializing in video content analysis.
        Convert the following raw script into a professional, engaging Korean blog post.

        ### [TASK]
        Refine the raw text into a structured Markdown format. 
        The most important goal is **READABILITY** and **VERTICAL LISTING** of information.

        ### [CONSTRAINTS - CRITICAL]
        1. **Paragraph per Timestamp**: Every single timestamp `[MM:SS]` MUST start a NEW paragraph.
        2. **No Inline Timestamps**: NEVER place a timestamp in the middle of a sentence. 
        3. **No Hallucination**: NEVER place timestamps inside bold (`**`), blockquotes (`>`), or bullet points (`-`). 
           - Right: `[01:23] **Key Point**: Description sentence.`
           - Wrong: `**[01:23] Key Point**: Description.**`
           - Wrong: `- [01:23] Detail.`
        4. **Structure**: Each timestamped entry should stand alone. Use bullet points (`-`) only for minor sub-details *below* a timestamped paragraph.
        5. **Style**: Use level 3 header (`###`) for the chapter title. Use bold (`**`) for emphasis on key terms.

        ### [EXAMPLE]
        Input: [00:12] 안녕하세요 [00:15] 오늘은 파이썬에 대해 [00:18] 알아보겠습니다.
        Output: 
        ### 파이썬 코딩 강의
        
        [00:12] **인사 및 소개**: 영상 분석 전문가와 함께하는 파이썬 강의에 오신 것을 환영합니다.
        
        [00:15] **주제 선정**: 오늘은 프로그래밍의 기초인 파이썬의 핵심 개념을 다룹니다.
        
        [00:18] **강의 목표**: 이 영상을 통해 기본적인 문법과 환경 설정을 마스터할 수 있습니다.

        ### [INPUT DATA]
        - Chapter Title: {chapter_title}
        - Raw Script:
        {raw_text}

        ### [OUTPUT]
        (Write the refined blog post in Korean, ensuring double newlines between timestamped paragraphs)
        """

        try:
            # Gemma 모델 호출
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    top_p=0.95,
                )
            )
            
            refined_text = response.text.strip()
            
            # --- [Advanced Regex Healing for Maximum Readability] ---
            
            # 1. 강조(**) 내부의 불필요한 공백 제거
            refined_text = re.sub(r'\*\*\s+(.+?)\s+\*\*', r'**\1**', refined_text)
            
            # 2. 강조 표시 내부로 잘못 들어간 타임스탬프를 밖(왼쪽)으로 추출
            refined_text = re.sub(r'(\*\*|>)\s*(\[\d{2}:\d{2}\])', r'\2 \1', refined_text)

            # 3. 모든 타임스탬프 앞에 강제로 두 줄의 줄바꿈(\n\n)을 삽입하여 문단을 분리
            # 가독성을 위해 타임스탬프가 나오는 즉시 이전 문맥과 단절시킵니다.
            refined_text = re.sub(r'\s*(\[\d{2}:\d{2}\])', r'\n\n\1', refined_text)

            # 4. 리스트 기호(-) 바로 뒤에 타임스탬프가 붙어 있는 경우 분리
            refined_text = re.sub(r'-\s*(\[\d{2}:\d{2}\])', r'\n\1', refined_text)

            # 5. 중복된 타임스탬프가 한 줄에 있는 경우 첫 번째만 유지
            def remove_duplicate_ts(line: str) -> str:
                """한 줄에 여러 타임스탬프가 있을 경우 첫 번째만 남기고 정리합니다."""
                ts_list = re.findall(r'\[\d{2}:\d{2}\]', line)
                if len(ts_list) > 1:
                    first_ts = ts_list[0]
                    # 모든 타임스탬프를 제거한 후 순수 텍스트만 추출
                    content = re.sub(r'\[\d{2}:\d{2}\]', '', line).strip()
                    # 첫 번째 타임스탬프와 텍스트 결합
                    return f"{first_ts} {content}"
                return line

            # 각 줄별로 중복 타임스탬프 제거 처리
            lines = [remove_duplicate_ts(line) for line in refined_text.split('\n')]
            refined_text = '\n'.join(lines)

            # 6. 최종 공백 및 과도한 줄바꿈 정리 (3개 이상 -> 2개)
            refined_text = re.sub(r'\n{3,}', '\n\n', refined_text)

            return refined_text.strip()

        except Exception as e:
            print(f"[Refiner Error] {e}")
            # 에러 발생 시 원본 텍스트라도 반환하여 데이터 손실 방지
            return f"### {chapter_title}\n\n(AI 윤문 중 오류가 발생하여 원본을 표시합니다.)\n\n{raw_text}"