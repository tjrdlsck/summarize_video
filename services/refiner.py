import os
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
        # gemma-3-27b-it 모델 사용 (만약 할당량 문제 발생 시 gemini-2.0-flash 등으로 대체 가능)
        self.model_name = "gemma-3-27b-it" 
        self.client = None
        
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    def refine_chapter(self, raw_text, chapter_title=""):
        """
        챕터별 텍스트를 입력받아 구조화된 Markdown 형식으로 반환합니다.
        """
        if not self.client:
            return "API Key missing."

        if not raw_text or len(raw_text.strip()) < 10:
            return "내용이 너무 짧아 요약할 수 없습니다."

        # 프롬프트 엔지니어링: 전문 에디터 페르소나 부여
        prompt = f"""
        You are a professional blog editor. 
        Your task is to refine the following raw spoken text into a highly readable, structured Markdown format.

        ### Guidelines:
        1. **Title**: Start with a level 3 header (`###`) using the provided chapter title: "{chapter_title}".
        2. **Structure**: Break down the text into logical paragraphs. Use bullet points (`-`) for lists.
        3. **Highlight**: Use bold (`**`) for key terms or important sentences.
        4. **Quote**: If there is a key message or insight, use a Blockquote (`>`).
        5. **Tone**: Polite, engaging, and professional (maintain the original meaning but fix speech errors).
        6. **Language**: **Korean (한국어)** only.

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
            return response.text.strip()

        except Exception as e:
            print(f"[Refiner Error] {e}")
            # 에러 발생 시 원본 텍스트라도 반환하여 데이터 손실 방지
            return f"### {chapter_title}\n\n(AI 윤문 중 오류가 발생하여 원본을 표시합니다.)\n\n{raw_text}"