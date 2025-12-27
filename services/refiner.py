import os
import re
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

    def _format_time(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{m:02}:{s:02}"

    def refine_chapter(self, raw_text: str, chapter_title: str, segments: list[dict] = None) -> str:
        """챕터별 텍스트를 입력받아 가독성이 극대화된 Markdown 형식으로 윤문합니다.
        
        [Updated] 인용(Citation) 방식을 적용하여 근거 타임스탬프를 표시합니다.

        Args:
            raw_text (str): (Legacy) 윤문할 원본 텍스트. segments가 제공되면 무시될 수 있음.
            chapter_title (str): 해당 챕터의 제목.
            segments (list[dict]): 해당 챕터에 속하는 자막 세그먼트 리스트. (ID 매핑용)

        Returns:
            str: 인용 타임스탬프가 포함된 구조화된 Markdown 텍스트.
        """
        if not self.client:
            return "API Key missing."

        # 세그먼트 데이터가 없으면 기존 방식(Legacy)으로 처리하거나 텍스트 기반으로 진행
        # 하지만 인용 기능을 위해선 segments가 필수적임.
        if not segments:
             # Fallback to simple text (기존 로직과 유사하게 처리하거나 에러 메시지)
             return f"### {chapter_title}\n\n(상세 세그먼트 데이터가 없어 인용 모드를 실행할 수 없습니다.)\n\n{raw_text}"

        # 프롬프트용 스크립트 텍스트 생성 (ID | Text 형식)
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_block = "\n".join(lines)

        prompt = f"""
        You are an expert AI blog editor specializing in video content analysis.
        Your task is to write a detailed, engaging blog section based on the provided video script for the chapter: "{chapter_title}".

        ### [CORE INSTRUCTIONS]
        1. **Structured Writing**: Write a cohesive, well-structured blog post section. Do not just summarize; explain the content as if you are teaching it.
        2. **Citation Rule (CRITICAL)**: Whenever you state a fact, opinion, or quote from the script, **YOU MUST** cite the source ID using the format `[[ID:number]]` at the end of the sentence.
           - **Multiple Citations**: If you cite multiple sources, use separate brackets for each ID: `[[ID:12]][[ID:13]]`. **NEVER** combine them like `[[ID:12, 13]]`.
           - **Format**: Always use the exact format `[[ID:number]]`.
        3. **Tone**: Professional yet accessible (polite Korean '해요체').
        4. **Formatting**:
           - Use `**Bold**` for key terms.
           - Use `> Blockquote` for direct quotes or important emphasis.
           - NO timestamps at the beginning of lines. Use citations instead.

        ### [INPUT SCRIPT]
        {script_block}

        ### [OUTPUT]
        (Write the blog section in Korean with citations)
        """

        try:
            # Gemma 모델 호출
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3, 
                    top_p=0.95,
                )
            )
            
            refined_text = response.text.strip()
            
            # --- [Post-Processing: ID -> Timestamp] ---
            # [[ID:123]] -> (05:32) 형태로 변환
            
            # 빠른 조회를 위한 ID 맵
            id_map = {seg['id']: seg['start'] for seg in segments}

            def replace_match(match):
                try:
                    seg_id = int(match.group(1))
                    if seg_id in id_map:
                        time_str = self._format_time(id_map[seg_id])
                        return f" ({time_str})"
                except:
                    pass
                return ""

            # 1. 표준 및 변형된 ID 패턴 치환 (ID:숫자 형태를 모두 찾아 타임스탬프로 변경)
            inter_text = re.sub(r'\[*ID:\s*(\d+)\s*\]*', replace_match, refined_text)
            
            # 2. 잔여 오물 제거 (Heuristic Cleanup)
            # LLM이 [[ID:68, 69]] 처럼 쉼표로 연결했을 경우 남게 되는 ", 69]]" 등을 청소합니다.
            final_text = re.sub(r'[, \d]*\]+', '', inter_text)
            
            # 3. 혹시 모를 빈 괄호나 깨진 인용구 최종 정리
            final_text = final_text.replace("[[", "").replace("]]", "").strip()

            return final_text

        except Exception as e:
            print(f"[Refiner Error] {e}")
            return f"### {chapter_title}\n\n(AI 작성 중 오류 발생: {e})\n\n{raw_text}"