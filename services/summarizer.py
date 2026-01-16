import os
import re
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential 

# [Strategy Imports]
from services.strategies.base_strategy import AnalysisStrategy
from services.strategies.sermon_strategy import SermonStrategy
from services.system_manager import ConfigManager

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

# --- [Main Class] Video Summarizer ---
class VideoSummarizer:
    """
    Transcribed Segments -> AnalysisStrategy -> Gemini API -> JSON Structure
    """
    def __init__(self, output_dir="static/results", strategy: AnalysisStrategy = None):
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.output_dir = output_dir
        # 기본 전략으로 설교 모드 설정
        self.strategy = strategy or SermonStrategy()
        os.makedirs(self.output_dir, exist_ok=True)

    def set_strategy(self, strategy: AnalysisStrategy):
        """실행 중 전략을 변경할 수 있도록 지원"""
        self.strategy = strategy

    def _get_model(self, task_type):
        """설정 매니저를 통해 실시간으로 모델명을 가져옵니다."""
        return ConfigManager.get_model(task_type)

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def plan_blog_structure(
        self, 
        segments: list[dict], 
        video_filename: str, 
        status_callback: callable = None
    ) -> dict:
        """분석 전략에 따라 영상 전체의 블로그 구조를 설계합니다."""
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        total_lines = len(segments)
        if total_lines == 0: return {"error": "Empty segments"}

        print(f"--- [Summarizer] Planning Blog Structure (Mode: {self.strategy.mode_name}) ---")
        if status_callback: status_callback(f"블로그 구조를 설계 중입니다 ({self.strategy.mode_name})...")

        # 스크립트 텍스트 생성
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_text = "\n".join(lines)
        
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "blog_title": {"type": "STRING", "description": "영상의 핵심 내용을 관통하는 매력적인 블로그 제목"},
                "chapters": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "title": {"type": "STRING", "description": "해당 섹션의 소제목"},
                            "start_id": {"type": "INTEGER", "description": "시작 세그먼트 ID"},
                            "end_id": {"type": "INTEGER", "description": "종료 세그먼트 ID"},
                            "focus_point": {"type": "STRING", "description": "이 섹션에서 강조해야 할 핵심 논거 및 스토리텔링 포인트"}
                        },
                        "required": ["title", "start_id", "end_id", "focus_point"]
                    }
                }
            },
            "required": ["blog_title", "chapters"]
        }

        # 전략으로부터 프롬프트 획득
        system_prompt = self.strategy.get_blog_structure_prompt(video_filename, script_text)

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self._get_model("planner"),
                contents=system_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=response_schema
                )
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"[Error] Blog planning failed: {e}")
            raise e

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def summarize(
        self, 
        segments: list[dict], 
        video_filename: str, 
        custom_title: str = None, 
        status_callback: callable = None
    ) -> dict:
        """분석 전략에 따라 자막을 분석하고 챕터 정보를 생성합니다."""
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        total_lines = len(segments)
        if total_lines == 0: return {"error": "Empty segments"}

        print(f"--- [Summarizer] Analyzing with Mode: {self.strategy.mode_name} ---")
        if status_callback: status_callback(f"내용을 정밀 분석 중 ({self.strategy.mode_name})...")

        tracker = UsageTracker()
        
        # 스크립트 텍스트 생성
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_text = "\n".join(lines)
        
        # 전략으로부터 카테고리 획득하여 스키마 동적 생성
        categories = [cat['name'] for cat in self.strategy.get_category_definitions()]
        
        response_schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "내용을 직관적으로 알 수 있는 챕터 제목"},
                    "type": {
                        "type": "STRING", 
                        "enum": categories,
                        "description": "구간 성격 분류"
                    },
                    "summary": {"type": "STRING", "description": "핵심 내용 요약"},
                    "start_id": {"type": "INTEGER", "description": "시작 세그먼트 ID"},
                    "end_id": {"type": "INTEGER", "description": "종료 세그먼트 ID"}
                },
                "required": ["title", "type", "summary", "start_id", "end_id"]
            }
        }

        # 전략으로부터 프롬프트 획득
        display_title = custom_title if custom_title and custom_title.strip() else video_filename
        system_prompt = self.strategy.get_analysis_prompt(display_title, script_text)

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self._get_model("summarizer"),
                contents=system_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json", 
                    response_schema=response_schema       
                )
            )
            tracker.update(response)
            
            final_chapters = json.loads(response.text)
            
            # ID -> Time 매핑
            mapped_result = []
            for chap in final_chapters:
                s_idx = max(0, min(chap['start_id'] - 1, total_lines - 1))
                e_idx = max(0, min(chap['end_id'] - 1, total_lines - 1))
                
                start_time = segments[s_idx]['start']
                end_time = segments[e_idx]['end']
                
                mapped_result.append({
                    "title": re.sub(r'\*\*|__', '', chap['title']).strip(),
                    "type": chap['type'],
                    "summary": chap['summary'],
                    "time": {
                        "start": start_time,
                        "end": end_time,
                        "start_formatted": self._format_time(start_time),
                        "end_formatted": self._format_time(end_time)
                    }
                })

            result_data = {
                "video_source": video_filename,
                "video_title": display_title,
                "mode": self.strategy.mode_name, # 분석 모드 기록
                "total_chapters": len(mapped_result),
                "token_usage": tracker.get_report(),
                "chapters": mapped_result
            }

            base_name = os.path.splitext(video_filename)[0]
            output_path = os.path.join(self.output_dir, f"{base_name}_summary.json")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
                
            return result_data

        except Exception as e:
            print(f"[Error] Summarization failed: {e}")
            raise e
        
    def _format_time(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02}:{m:02}:{s:02}"