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

        # 프롬프트 엔지니어링: 설교 특화 블로그 포스팅 엔진 (Sermon-to-Blog Engine)
        prompt = f"""
        You are an expert AI blog editor and theologian specializing in Christian sermon analysis.
        Your goal is to transform a raw sermon transcript into a spiritually deep, well-structured, and readable Korean blog post.

        ### [CORE MISSIONS]
        1. **Fact-Based Refining (사실 기반 윤문)**: Your output must be strictly based on the provided [INPUT DATA]. Do NOT invent stories, theological theories, or names (e.g., Calvin, Luther) unless they are explicitly mentioned in the input.
        2. **Spoken to Written (문어체 변환)**: Convert casual spoken language into professional, respectful Korean (문어체). Use "~입니다", "~하십시오" style.
        3. **Bible Verse Enrichment (성경 본문 보강)**: Whenever a Bible verse is mentioned (e.g., "John 3:16"), you MUST provide the full text of that verse in a blockquote format (`>`).
        4. **Timestamp Integration**: Start major paragraphs with the corresponding timestamp `[MM:SS]` from the input to maintain the link with the video.

        ### [STRICT DATA RULES - CRITICAL]
        1. **NO HALLUCINATION**: Do not add any information not present in the source text.
        2. **TIMESTAMP FIDELITY**: **ONLY** use timestamps that appear in the [INPUT DATA]. Do NOT create fake timestamps like [00:00] if they are not in the input.
        3. **CHRONOLOGICAL ORDER**: Do not reorder the content. Follow the flow of the input script.

        ### [CONSTRAINTS]
        - **Readability**: Use double newlines between paragraphs.
        - **Structure**: Use `####` headers for main points (e.g., "First", "Second").
        - **Timestamp Placement**: Place the timestamp at the very beginning of the line.
          - Right: `[01:23] **Subheading**: Content...`
          - Wrong: `**[01:23] Subheading**...`

        ### [EXAMPLE]
        Input: 
        [00:10] 자 오늘 말씀은 창세기 1장 1절입니다
        [00:15] 태초에 하나님이 천지를 창조하시니라
        [00:20] 이 말씀이 얼마나 놀랍습니까
        [05:30] 첫째로 생각할 건 창조의 목적입니다
        [05:35] 바로 사랑 때문이죠

        Output: 
        ### 천지 창조의 신비

        [00:10] **성경 본문 선포**: 오늘 우리가 함께 나눌 말씀은 창세기의 시작입니다.
        
        [00:15] **성경 읽기**:
        > [성경 본문] 창세기 1:1: "태초에 하나님이 천지를 창조하시니라"
        
        [00:20] **말씀의 경이로움**: 이 선포는 우리에게 큰 놀라움을 줍니다. 하나님께서 세상을 만드셨다는 사실이 믿음의 기초가 됩니다.

        #### 1. 창조의 목적: 사랑

        [05:30] **첫 번째 대지**: 설교자는 창조의 가장 중요한 목적을 탐구합니다.
        
        [05:35] **사랑의 동기**: 하나님께서 세상을 지으신 이유는 바로 사랑 때문입니다.

        ### [INPUT DATA]
        - Chapter Title: {chapter_title}
        - Raw Script (Timestamped):
        {raw_text}

        ### [OUTPUT]
        (Write the refined blog post in Korean. Adhere strictly to the timestamps provided above.)
        """

        try:
            # Gemma 모델 호출
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1, # 사실 기반 유지를 위해 낮음
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
            refined_text = re.sub(r'\s*(\[\d{2}:\d{2}\])', r'\n\n\1', refined_text)

            # 4. 리스트 기호(-) 바로 뒤에 타임스탬프가 붙어 있는 경우 분리
            refined_text = re.sub(r'-\s*(\[\d{2}:\d{2}\])', r'\n\1', refined_text)

            # 5. [New] 글머리 기호(Bullet Points) 및 환각 라인 제거
            final_lines = []
            for line in refined_text.split('\n'):
                stripped = line.strip()
                # 불렛 기호로 시작하고, 라인 내에 타임스탬프가 없는 경우 -> 스킵 (환각 가능성 높음)
                if re.match(r'^\s*[-*•]', stripped) and not re.search(r'\[\d{2}:\d{2}\]', stripped):
                    continue
                final_lines.append(line)
            refined_text = '\n'.join(final_lines)

            # 6. 중복된 타임스탬프가 한 줄에 있는 경우 첫 번째만 유지
            def remove_duplicate_ts(line: str) -> str:
                ts_list = re.findall(r'\[\d{2}:\d{2}\]', line)
                if len(ts_list) > 1:
                    first_ts = ts_list[0]
                    content = re.sub(r'\[\d{2}:\d{2}\]', '', line).strip()
                    return f"{first_ts} {content}"
                return line

            lines = [remove_duplicate_ts(line) for line in refined_text.split('\n')]
            refined_text = '\n'.join(lines)

            # 7. 최종 공백 및 과도한 줄바꿈 정리
            refined_text = re.sub(r'\n{3,}', '\n\n', refined_text)

            return refined_text.strip()

        except Exception as e:
            print(f"[Refiner Error] {e}")
            # 에러 발생 시 원본 텍스트라도 반환하여 데이터 손실 방지
            return f"### {chapter_title}\n\n(AI 윤문 중 오류가 발생하여 원본을 표시합니다.)\n\n{raw_text}"