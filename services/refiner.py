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

    def refine_chapter(self, raw_text, chapter_title=""):
        """
        챕터별 텍스트를 입력받아 구조화된 Markdown 형식으로 반환합니다.
        [Update] 타임스탬프 보존 + 리스트/인용구/강조 효과 전량 복구
        """
        if not self.client:
            return "API Key missing."

        if not raw_text or len(raw_text.strip()) < 10:
            return "내용이 너무 짧아 요약할 수 없습니다."

        # 프롬프트 엔지니어링: 전문 에디터 페르소나 + 시각적 효과 + 타임스탬프 규칙
        prompt = f"""
        You are a professional blog editor. 
        Your task is to refine the following raw spoken text into a highly readable, structured Markdown format.

        ### Guidelines:
        1. **Title**: Start with a level 3 header (`###`) using the provided chapter title: "{chapter_title}".
        2. **Structure**: Break down the text into logical paragraphs. Use **bullet points (`-`)** for lists or step-by-step explanations.
        3. **Timestamps**: Keep timestamps (e.g., [00:12]) from the raw text. 
           - Place them at the very beginning of a sentence or paragraph.
           - Format: `[MM:SS]`.
           - **CRITICAL**: Timestamps must be OUTSIDE of any bold (`**`) or quote (`>`) markers.
        4. **Highlight**: Use **bold (`**`)** for key terms or important sentences.
        5. **Insight**: Use **Blockquotes (`>`)** for key messages, quotes, or deep insights.
        6. **Tone**: Polite, engaging, and professional Korean.
        
        ### Formatting Rules:
        - **NEVER** put spaces inside bold markers. 
        - Right: `[01:23] **중요한 문장입니다.**`
        - Wrong: `** [01:23] 중요한 문장입니다. **`

        ### Raw Text with Timestamps:
        {raw_text}
        """

        try:
            # Gemma 모델 호출
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                )
            )
            
            refined_text = response.text.strip()
            
            # --- [Regex Healing] 마크다운 문법 및 타임스탬프 교정 ---
            
            # 1. 굵은 글씨 내부 공백 제거
            refined_text = re.sub(r'\*\*\s+(.+?)\s+\*\*', r'**\1**', refined_text)
            
            # 2. 굵은 글씨 내부의 따옴표 공백 제거
            refined_text = re.sub(r"\*\*\s*['\"](.+?)['\"]\s*\*\*", r"**'\1'**", refined_text)

            # 3. 타임스탬프 형식 표준화
            refined_text = re.sub(r'\[(\d):(\d+)\]', r'[0\1:\2]', refined_text)
            refined_text = re.sub(r'\[(\d+):(\d)\]', r'[\1:0\2]', refined_text)
            
            # 4. 강조 표시 안으로 잘못 들어간 타임스탬프를 밖으로 꺼내기
            refined_text = re.sub(r'\*\*(\[\d{2}:\d{2}\])\s*(.*?)\*\*', r'\1 **\2**', refined_text)

            return refined_text

        except Exception as e:
            print(f"[Refiner Error] {e}")
            # 에러 발생 시 원본 텍스트라도 반환하여 데이터 손실 방지
            return f"### {chapter_title}\n\n(AI 윤문 중 오류가 발생하여 원본을 표시합니다.)\n\n{raw_text}"