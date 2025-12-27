import os
import re
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

# --- [Helper Class] Resource Usage Tracker ---
class UsageTracker:
    """API 호출 비용 및 토큰 사용량을 추적하는 유틸리티"""
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    def update(self, response):
        if hasattr(response, 'usage_metadata'):
            usage = response.usage_metadata
            self.input_tokens += getattr(usage, 'prompt_token_count', 0)
            self.output_tokens += getattr(usage, 'candidates_token_count', 0)

    def get_report(self):
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens
        }

# --- [Helper Class] Logic Healer ---
class ChapterHealer:
    """
    LLM의 불안정한 출력(Markdown)을 파싱하고, 
    누락된 구간(Gap) 없이 전체 타임라인을 채우는 로직.
    """
    @staticmethod
    def parse_markdown(llm_output):
        # Regex: ## Title -> - 요약: ... -> - 구간: [Start - End]
        regex = re.compile(
            r'##\s*(.+?)\n'
            r'\s*-\s*요약:\s*(.+?)(?=\n\s*-\s*구간:)'
            r'\s*-\s*구간:\s*\[(\d+)\s*-\s*(\d+)\]',
            re.DOTALL
        )
        chapters = []
        for m in regex.findall(llm_output):
            chapters.append({
                "title": m[0].strip(),
                "summary": m[1].strip(),
                "start_id": int(m[2]),
                "end_id": int(m[3])
            })
        return chapters

    @staticmethod
    def heal_chapters(raw_chapters, total_lines):
        """챕터 간 빈틈이 없도록 ID 범위를 강제로 조정(Healing)"""
        if not raw_chapters: return []
        
        # 시작 ID 기준으로 정렬
        raw_chapters.sort(key=lambda x: x['start_id'])
        healed = []
        current_start = 1
        
        for i, chap in enumerate(raw_chapters):
            title = chap['title']
            summary = chap['summary']
            
            # 마지막 챕터면 끝까지, 아니면 다음 챕터 시작 전까지
            if i == len(raw_chapters) - 1:
                final_end = total_lines
            else:
                next_start = raw_chapters[i+1]['start_id']
                final_end = max(current_start, next_start - 1)

            # 범위 보정
            if current_start > final_end: final_end = current_start
            final_end = min(final_end, total_lines)

            healed.append({
                "title": title,
                "summary": summary,
                "start_id": current_start,
                "end_id": final_end
            })
            current_start = final_end + 1
            
        return healed

# --- [Main Class] Video Summarizer ---
class VideoSummarizer:
    """
    Transcribed Segments -> Prompt -> Gemini API -> JSON Structure
    """
    def __init__(self, output_dir="static/results"):
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.output_dir = output_dir
        self.model_name = "gemini-2.5-flash"  # Cost-effective high performance model
        os.makedirs(self.output_dir, exist_ok=True)

    def _create_prompt(self, segments: list[dict]) -> str:
        """LLM에게 전달할 경량화된 스크립트 데이터를 생성합니다.

        Args:
            segments: 분석된 자막 세그먼트 리스트.

        Returns:
            ID와 텍스트가 결합된 문자열 형태의 스크립트 데이터.
        """
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_text = "\n".join(lines)
        
        system_instruction = (
            "당신은 영상 콘텐츠 분석가입니다. 대본(Script)을 정밀 분석하여 논리적인 '챕터(Chapter)'로 구분하세요.\n"
            "반드시 아래 **Markdown 형식**으로만 출력해야 합니다.\n"
            "## 챕터 제목\n"
            "- 요약: (상세 서술)\n"
            "- 구간: [시작ID - 종료ID]\n\n"
            "조건 1: 영상의 처음(ID:1)부터 끝까지 빈틈없이 나누세요.\n"
            "조건 2: 요약은 구체적인 행동과 상황을 포함하여 서술하세요."
        )
        return f"{system_instruction}\n\n[Script Data]:\n{script_text}"

    def _create_blog_prompt(self, segments: list[dict]) -> str:
        """블로그 포스트 생성을 위한 프롬프트를 생성합니다.

        Args:
            segments: 분석된 자막 세그먼트 리스트.

        Returns:
            블로그 작성 지시사항과 스크립트 데이터가 포함된 프롬프트 문자열.
        """
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_text = "\n".join(lines)
        
        system_instruction = (
            "당신은 전문 지식을 독자에게 친절하고 논리적으로 가르치는 **세계 최고의 블로그 에디터**입니다.\n"
            "제공된 스크립트를 바탕으로 독자가 몰입할 수 있는 **스토리텔링형 블로그 포스트**를 작성하세요.\n"
            "**절대 시간 순서대로 단순히 나열하지 마세요.** 주제별로 내용을 재구성하여 독자의 지적 호기심을 충족시켜야 합니다.\n\n"
            "**[필수 작성 및 강조 규칙]**\n"
            "1. **정형화된 서사 구조**: 모든 주제 섹션은 아래 구성을 따라야 합니다.\n"
            "   - **도입부 (Introduction)**: 독자의 호기심을 자극하고 본문에서 다룰 핵심 질문을 던지는 문장으로 시작.\n"
            "   - **본문 (Body)**: 매력적인 소제목과 함께 내용을 논리적으로 상세히 설명.\n"
            "   - **맺음말 (Conclusion)**: 내용을 갈무리하며 독자에게 깊은 통찰이나 제언을 던지는 문장으로 마무리.\n"
            "2. **시각적 강조 (Highlighting)**:\n"
            "   - **핵심 키워드**: 문맥상 중요한 단어나 고유 명사는 반드시 `**굵게**` 표시하세요. (섹션당 5개 이상)\n"
            "   - **핵심 메시지**: 각 챕터나 섹션의 결론이 담긴 가장 중요한 문장 1~2개는 반드시 `<mark>핵심 문장</mark>` 태그로 감싸세요.\n"
            "3. **인용(Citation)**: 본문의 내용이 스크립트의 특정 부분에 기반할 때, 문장 끝에 반드시 `[[ID:숫자]]` 형식으로 출처를 남기세요.\n"
            "   - **주의**: 여러 개의 출처를 인용할 경우 반드시 `[[ID:1]][[ID:2]]`와 같이 개별적으로 작성하세요. `[[ID:1, 2]]`와 같이 쉼표로 연결하지 마세요.\n"
            "4. **어조**: 친절하고 전문적인 블로거의 말투(해요체)를 사용하세요."
        )
        return f"{system_instruction}\n\n[Script Data]:\n{script_text}"

    def generate_blog_post(
        self, 
        segments: list[dict], 
        video_filename: str, 
        status_callback: callable = None
    ) -> dict:
        """Gemini를 사용하여 주제 중심의 블로그 포스트를 생성합니다.

        타임스탬프를 인용(`[[ID:숫자]]`) 형태로 받아 실제 시간으로 치환합니다.

        Args:
            segments: 분석된 자막 세그먼트 리스트.
            video_filename: 원본 영상 파일명.
            status_callback: 진행 상태 콜백.

        Returns:
            블로그 포스트 내용과 메타데이터가 포함된 딕셔너리.
        """
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        if not segments:
            return {"error": "Empty segments"}

        print(f"--- [Summarizer] Generating Blog Post for {video_filename} ---")
        if status_callback: status_callback("Gemini가 블로그 포스트를 작성 중입니다...")

        tracker = UsageTracker()
        prompt = self._create_blog_prompt(segments)

        try:
            client = genai.Client(api_key=self.api_key)
            
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3, # 창의성 약간 부여
                )
            )
            tracker.update(response)
            
            blog_content = response.text
            
            # --- Post-Processing: 인용 ID를 타임스탬프로 치환 ---
            def replace_match(match):
                try:
                    seg_id = int(match.group(1))
                    idx = seg_id - 1
                    if 0 <= idx < len(segments):
                        start_time = segments[idx]['start']
                        time_str = self._format_time(start_time)
                        return f" `({time_str})`" 
                except:
                    pass
                return ""

            # 1. 다양한 형태의 ID 인용구 치환
            inter_content = re.sub(r'\[*ID:\s*(\d+)\s*\]*', replace_match, blog_content)
            
            # 2. 잔여물 제거 (Heuristic Cleanup)
            refined_content = re.sub(r'[, \d]*\]+', '', inter_content)
            refined_content = refined_content.replace("[[", "").replace("]]", "").strip()
            
            result_data = {
                "video_source": video_filename,
                "type": "blog_post",
                "token_usage": tracker.get_report(),
                "content": refined_content
            }

            # 저장
            base_name = os.path.splitext(video_filename)[0]
            output_path = os.path.join(self.output_dir, f"{base_name}_blog.json")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
                
            return result_data

        except Exception as e:
            print(f"[Error] Blog generation failed: {e}")
            return {"error": str(e)}

    def summarize(
        self, 
        segments: list[dict], 
        video_filename: str, 
        custom_title: str = None, 
        status_callback: callable = None
    ) -> dict:
        """Gemini API의 JSON Mode를 사용하여 자막을 분석하고 챕터 정보를 생성합니다.

        Args:
            segments: 분석된 자막 세그먼트 리스트.
            video_filename: 원본 영상 파일명.
            custom_title: 사용자가 지정한 영상 제목 (선택 사항).
            status_callback: 진행 상태를 보고할 콜백 함수 (선택 사항).

        Returns:
            요약 결과, 챕터 리스트, 토큰 사용량 등이 포함된 결과 딕셔너리.
        """
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        total_lines = len(segments)
        if total_lines == 0: return {"error": "Empty segments"}

        print(f"--- [Summarizer] Analyzing {total_lines} lines with Gemini (JSON Mode) ---")
        if status_callback: status_callback("Gemini가 내용을 정밀 분석 중 (JSON Mode)...")

        tracker = UsageTracker()
        
        # 프롬프트 구성
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_text = "\n".join(lines)
        
        # JSON 스키마 정의
        response_schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "챕터 제목"},
                    "summary": {"type": "STRING", "description": "상세 내용 요약"},
                    "start_id": {"type": "INTEGER", "description": "시작 세그먼트 ID"},
                    "end_id": {"type": "INTEGER", "description": "종료 세그먼트 ID"}
                },
                "required": ["title", "summary", "start_id", "end_id"]
            }
        }

        system_instruction = (
            "당신은 영상 콘텐츠 분석 AI입니다. 대본을 읽고 논리적인 '챕터'로 나누어 JSON으로 출력하세요.\n"
            "규칙 1: 영상의 시작(ID:1)부터 끝까지 빈틈없이 커버해야 합니다.\n"
            "규칙 2: start_id와 end_id는 제공된 스크립트의 ID를 참조합니다.\n"
            "규칙 3: 한국어로 작성하세요."
        )

        try:
            client = genai.Client(api_key=self.api_key)
            
            response = client.models.generate_content(
                model=self.model_name,
                contents=f"{system_instruction}\n\n[Script]:\n{script_text}",
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json", 
                    response_schema=response_schema       
                )
            )
            tracker.update(response)
            
            # JSON 파싱
            final_chapters = json.loads(response.text)
            
            # ID -> Time 매핑 & 챕터 제목 정제
            mapped_result = []
            for chap in final_chapters:
                s_idx = max(0, min(chap['start_id'] - 1, total_lines - 1))
                e_idx = max(0, min(chap['end_id'] - 1, total_lines - 1))
                
                start_time = segments[s_idx]['start']
                end_time = segments[e_idx]['end']
                
                # 챕터 제목 내 불필요한 마크다운(**, __) 제거
                clean_chapter_title = re.sub(r'\*\*|__', '', chap['title']).strip()
                
                mapped_result.append({
                    "title": clean_chapter_title,
                    "summary": chap['summary'],
                    "time": {
                        "start": start_time,
                        "end": end_time,
                        "start_formatted": self._format_time(start_time),
                        "end_formatted": self._format_time(end_time)
                    }
                })

            display_title = custom_title if custom_title and custom_title.strip() else video_filename

            result_data = {
                "video_source": video_filename,
                "video_title": display_title,
                "total_chapters": len(mapped_result),
                "token_usage": tracker.get_report(),
                "chapters": mapped_result
            }

            # 저장
            base_name = os.path.splitext(video_filename)[0]
            output_path = os.path.join(self.output_dir, f"{base_name}_summary.json")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
                
            return result_data

        except Exception as e:
            print(f"[Error] Summarization failed: {e}")
            return {"error": str(e)}
        
    def _format_time(self, seconds: float) -> str:
        """초(seconds)를 HH:MM:SS 형식의 문자열로 변환합니다.

        Args:
            seconds: 변환할 초 단위 시간.

        Returns:
            HH:MM:SS 형식의 시간 문자열.
        """
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02}:{m:02}:{s:02}"

# --- [Module Test] ---
if __name__ == "__main__":
    # Test with dummy data
    dummy_segments = [
        {"id": 1, "start": 0.0, "end": 5.0, "text": "안녕하세요, 오늘 영상은 게임입니다."},
        {"id": 2, "start": 5.0, "end": 10.0, "text": "캐릭터를 선택하고 시작해보겠습니다."},
        {"id": 3, "start": 10.0, "end": 15.0, "text": "와, 이 보스 정말 어렵네요."},
        {"id": 4, "start": 15.0, "end": 20.0, "text": "결국 클리어했습니다. 구독 좋아요 부탁해요."}
    ]
    
    # .env 파일이 있어야 작동합니다.
    summ = VideoSummarizer(output_dir="../static/results")
    if os.getenv("GOOGLE_API_KEY"):
        res = summ.summarize(dummy_segments, "test_video.mp4")
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("Need GOOGLE_API_KEY in .env to test")