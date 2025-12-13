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

    def _create_prompt(self, segments):
        """LLM에게 던질 경량화된 스크립트(ID | Text) 생성"""
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

    def summarize(self, segments, video_filename, custom_title=None, status_callback=None):
        """
        Args:
            segments (list): [{'id':1, 'start':0.0, 'end':2.0, 'text':'...'}, ...]
            video_filename (str): 원본 파일명 (JSON 저장용 ID 역할)
            custom_title (str, optional): 사용자가 지정한 영상 제목 (없으면 파일명 사용)
            status_callback (func, optional): 상태 메시지 콜백
        
        Returns:
            dict: 최종 챕터 데이터 (타임스탬프 포함)
        """
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        total_lines = len(segments)
        if total_lines == 0:
            return {"error": "Empty segments"}

        print(f"--- [Summarizer] Analyzing {total_lines} lines with Gemini ---")
        
        # 상태 메시지 전송
        if status_callback:
            status_callback("Gemini가 내용을 분석하고 요약하는 중...")

        tracker = UsageTracker()
        
        try:
            client = genai.Client(api_key=self.api_key)
            prompt = self._create_prompt(segments)
            
            # API Call
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=8192
                )
            )
            tracker.update(response)
            
            # Parsing & Healing
            if status_callback:
                status_callback("요약 데이터 후처리 중...")

            raw_text = response.text
            parsed_chapters = ChapterHealer.parse_markdown(raw_text)
            
            if not parsed_chapters:
                print("[Warning] Parsing failed. Using fallback.")
                final_chapters = [{
                    "title": "전체 요약",
                    "summary": "챕터 자동 구분 실패 (전체 영상)",
                    "start_id": 1, 
                    "end_id": total_lines
                }]
            else:
                final_chapters = ChapterHealer.heal_chapters(parsed_chapters, total_lines)

            # ID -> Time Mapping
            mapped_result = []
            for chap in final_chapters:
                # 1-based index to 0-based list index
                s_idx = chap['start_id'] - 1
                e_idx = chap['end_id'] - 1
                
                # Safe indexing
                s_idx = max(0, min(s_idx, total_lines - 1))
                e_idx = max(0, min(e_idx, total_lines - 1))
                
                start_time = segments[s_idx]['start']
                end_time = segments[e_idx]['end']
                
                mapped_result.append({
                    "title": chap['title'],
                    "summary": chap['summary'],
                    "time": {
                        "start": start_time,
                        "end": end_time,
                        "start_formatted": self._format_time(start_time),
                        "end_formatted": self._format_time(end_time)
                    }
                })

            # [New] 결정된 제목 (사용자 지정 제목이 있으면 우선 사용)
            display_title = custom_title if custom_title and custom_title.strip() else video_filename

            # Final JSON Construction
            result_data = {
                "video_source": video_filename,   # 물리적 파일명 (ID)
                "video_title": display_title,     # [New] 논리적 제목 (Display용)
                "total_chapters": len(mapped_result),
                "token_usage": tracker.get_report(),
                "chapters": mapped_result
            }

            # Save to Disk
            base_name = os.path.splitext(video_filename)[0]
            output_path = os.path.join(self.output_dir, f"{base_name}_summary.json")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
                
            print(f"--- [Summarizer] Done. Saved to {output_path} ---")
            return result_data

        except Exception as e:
            print(f"[Error] Summarization failed: {e}")
            return {"error": str(e)}
        
    def _format_time(self, seconds):
        """초(seconds)를 HH:MM:SS 형식의 문자열로 변환"""
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