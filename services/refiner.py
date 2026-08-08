import os
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential # [Add] 재시도 로직 추가
from services.system_manager import ConfigManager
from services.content_profiles import get_content_profile

class TextRefiner:
    """
    Gemini 3.1 Flash-Lite 모델을 사용하여 Raw Transcript 또는 챕터를 읽기 좋은 블로그 포스트 형태(Markdown)로 윤문하는 클래스
    """
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.client = None
        
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    def _get_model(self):
        """실시간 설정을 가져옵니다."""
        return ConfigManager.get_model("refiner")

    def _format_time(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02}:{m:02}:{s:02}"

    @retry(
        stop=stop_after_attempt(5), 
        wait=wait_exponential(multiplier=2, min=4, max=20),
        reraise=True
    )
    def _call_gemini_with_retry(self, client, model, contents, config):
        """개별 API 호출 레벨의 재시도 유틸리티"""
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

    def refine_chapter(
        self, 
        raw_text: str, 
        chapter_title: str, 
        segments: list[dict] = None, 
        content_type: str = None
    ) -> str:
        """챕터별 텍스트를 입력받아 가독성이 극대화된 Markdown 형식으로 윤문합니다."""
        if not self.client:
            return "API Key missing."

        if not segments:
             return f"### {chapter_title}\n\n(상세 세그먼트 데이터가 없어 인용 모드를 실행할 수 없습니다.)\n\n{raw_text}"

        profile = get_content_profile(content_type)
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_block = "\n".join(lines)

        prompt = f"""
        {profile.refine_system_instruction}

        제공된 스크립트를 바탕으로 "{chapter_title}" 챕터에 대한 상세하고 몰입감 있는 블로그 섹션을 작성하세요.

        ### [필수 작성 및 강조 규칙 (Technical Guardrails)]
        1. **정형화된 서사 구조**: 반드시 아래 순서로 작성하세요.
           - **도입부 (Introduction)**: 단순 요약이나 나열이 아닌, 독자의 호기심을 자극하고 본문에서 다룰 핵심 질문을 던지는 문장으로 시작하세요.
           - **본문 (Body)**: 내용을 논리적인 흐름에 따라 상세히 설명하세요. 필요시 소제목을 활용하세요.
           - **맺음말 (Conclusion)**: 내용을 갈무리하며 독자에게 깊은 통찰이나 생각할 거리를 던지는 문장으로 마무리하세요.
        
        2. **시각적 강조 (Highlighting)**:
           - **키워드**: 문맥상 중요한 핵심 단어나 고유 명사는 반드시 `**굵게**` 표시하세요. (섹션당 5~7개 권장)
           - **핵심 메시지**: 해당 섹션의 결론이나 가장 중요한 문장 1~2개는 반드시 <mark>핵심 문장</mark> 처럼 순수 HTML 태그로 감싸세요. (절대로 태그 앞뒤에 백틱(`) 기호를 붙이지 마세요)

        3. **인용 규칙 (Citation)**: 사실, 의견, 인용구 뒤에는 반드시 출처 ID를 `[[ID:number]]` 형식으로 남기세요.
           - 예: 이 현상은 과학적으로 증명되었습니다 [[ID:12]].
           - 여러 개 인용 시: [[ID:12]][[ID:13]] (쉼표 사용 절대 금지)

        4. **근거 준수 (Grounding)**: 제공된 스크립트 데이터에 근거하여 작성하되, 없는 사실을 자의적으로 왜곡하거나 지어내지 마세요.

        ### [입력 스크립트 데이터]
        {script_block}

        ### [출력 마크다운]
        """

        try:
            model_name = self._get_model()
            response = self._call_gemini_with_retry(
                client=self.client,
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2, 
                    top_p=0.95,
                )
            )
            
            refined_text = response.text.strip()
            
            # --- [Post-Processing: ID -> Timestamp] ---
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

            inter_text = re.sub(r'\[*ID:\s*(\d+)\s*\]*', replace_match, refined_text)
            final_text = re.sub(r'[, \d]*\]+', '', inter_text)
            final_text = final_text.replace("[[", "").replace("]]", "").strip()

            return final_text

        except Exception as e:
            print(f"[Refiner Error] {e}")
            raise e