import os
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types
from services.system_manager import ConfigManager

class TextRefiner:
    """
    Gemma 모델을 사용하여 Raw Transcript를 읽기 좋은 블로그 포스트 형태(Markdown)로 윤문하는 클래스
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
        당신은 전문 지식을 독자에게 친절하고 논리적으로 가르치는 **세계 최고의 블로그 에디터**입니다.
        제공된 스크립트를 바탕으로 "{chapter_title}" 챕터에 대한 상세하고 몰입감 있는 블로그 섹션을 작성하세요.

        ### [작성 규칙]
        1. **정형화된 서사 구조**: 반드시 아래 순서로 작성하세요.
           - **도입부 (Introduction)**: 단순 요약이 아닌, 독자의 호기심을 자극하고 본문에서 다룰 핵심 질문을 던지는 문장으로 시작하세요.
           - **본문 (Body)**: 내용을 논리적인 흐름에 따라 상세히 설명하세요. 필요시 소제목을 활용하세요.
           - **맺음말 (Conclusion)**: 내용을 갈무리하며 독자에게 깊은 통찰이나 생각할 거리를 던지는 문장으로 마무리하세요.
        
        2. **시각적 강조 (Highlighting)**:
           - **키워드**: 문맥상 중요한 핵심 단어나 고유 명사는 반드시 `**굵게**` 표시하세요. (섹션당 5~7개 권장)
           - **핵심 메시지**: 해당 섹션의 결론이나 가장 중요한 문장 1~2개는 반드시 `<mark>핵심 문장</mark>` 태그로 감싸세요.

        3. **인용 규칙 (Citation)**: 사실, 의견, 인용구 뒤에는 반드시 출처 ID를 `[[ID:number]]` 형식으로 남기세요.
           - 예: 이 현상은 과학적으로 증명되었습니다 [[ID:12]].
           - 여러 개 인용 시: [[ID:12]][[ID:13]] (쉼표 사용 금지)

        4. **문체 및 언어**: 한국어로 작성하며, 전문적이면서도 친절한 '해요체'를 사용하세요.

        ### [입력 스크립트 데이터]
        {script_block}

        ### [출력 마크다운]
        """

        try:
            # Gemma 모델 호출
            response = self.client.models.generate_content(
                model=self._get_model(),
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