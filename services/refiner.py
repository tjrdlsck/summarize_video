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
        [Update] 마크다운 문법 오류(공백 등)를 정규식으로 자동 교정하는 로직 추가
        """
        if not self.client:
            return "API Key missing."

        if not raw_text or len(raw_text.strip()) < 10:
            return "내용이 너무 짧아 요약할 수 없습니다."

        # 프롬프트 엔지니어링: 스타일 가이드라인 대폭 강화
        prompt = f"""
        You are a professional blog editor specializing in high-engagement web content.
        Your task is to refine the following raw spoken text into a highly readable, structured Markdown format.

        ### [Style Guidelines - STRICT]:
        1. **Conciseness**: Keep sentences short (under 60 characters where possible). Avoid excessive conjunctions.
        2. **Active Voice**: Use active voice. Avoid passive or translation-style phrasing (e.g., 'It is done by...' -> 'I did...').
        3. **Structure**: 
           - Start with a level 3 header (`###`) for the title: "{chapter_title}".
           - Use bullet points (`-`) for lists to improve readability.
           - Use **bold** for key concepts, but NEVER put spaces inside bold markers (e.g., `**Word**`, not `** Word **`).
           - Use Blockquotes (`>`) for key insights or summary sentences.
        4. **Tone**: Polite, engaging, and professional Korean (Friendly '해요체').
        
        ### Raw Text:
        {raw_text}
        """

        try:
            # Gemma 모델 호출
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3, # 사실 기반 유지를 위해 온도를 낮춤
                )
            )
            
            refined_text = response.text.strip()
            
            # --- [Regex Healing] 마크다운 문법 강제 교정 ---
            
            # 1. 굵은 글씨 내부 공백 제거: "** 텍스트 **" -> "**텍스트**"
            # (?<=...) 등의 룩비하인드 대신 안전한 그룹 치환 사용
            refined_text = re.sub(r'\*\*\s+(.+?)\s+\*\*', r'**\1**', refined_text)
            
            # 2. 굵은 글씨 내부의 따옴표 공백 제거: "** ' 텍스트 ' **" -> "**'텍스트'**"
            refined_text = re.sub(r"\*\*\s*['\"](.+?)['\"]\s*\*\*", r"**'\1'**", refined_text)
            
            # 3. 불필요한 이중 별표 제거 (가끔 ****텍스트**** 형태로 나올 때)
            refined_text = re.sub(r'\*{4,}(.+?)\*{4,}', r'**\1**', refined_text)

            return refined_text

        except Exception as e:
            print(f"[Refiner Error] {e}")
            # 에러 발생 시 원본 텍스트라도 반환하여 데이터 손실 방지
            return f"### {chapter_title}\n\n(AI 윤문 중 오류가 발생하여 원본을 표시합니다.)\n\n{raw_text}"