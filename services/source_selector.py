import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

class SourceSelector:
    """
    [New] 전문 편집자 페르소나를 가진 AI가 Transcript를 분석하여
    Hook, Story, Insight, B-Roll 4가지 카테고리로 핵심 소스를 선별합니다.
    """
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY")
        # 복잡한 지시를 잘 따르는 고성능 모델 사용
        self.model_name = "gemini-2.5-flash" 

    def select_sources(self, transcripts, video_duration, task_manager=None, task_id=None):
        """
        메인 파이프라인 (Updated):
        - TaskManager와 연동하여 진행률 보고 및 취소 감지 기능 추가
        """
        if not self.api_key:
            return {"error": "API Key missing"}

        # [1] 시작 (0~10%)
        if task_manager and task_id:
            if task_manager.is_cancelled(task_id): return {"error": "Cancelled"}
            task_manager.update_progress(task_id, 5, "편집 소스 분석 준비 중...")

        # [2] LLM 분석 요청 (10~80%)
        # 가장 시간이 오래 걸리는 작업입니다.
        if task_manager and task_id:
            task_manager.update_progress(task_id, 10, "AI가 영상의 맥락을 분석 중입니다 (LLM)...")

        candidates = self._analyze_with_llm(transcripts)
        
        # LLM 호출 후 취소 확인 (긴 작업 직후 확인 필수)
        if task_manager and task_id and task_manager.is_cancelled(task_id):
            return {"error": "Cancelled by user"}

        if not candidates:
            return {"error": "AI analysis failed or returned empty result"}

        # [3] 후처리 및 병합 (80~95%)
        if task_manager and task_id:
            task_manager.update_progress(task_id, 80, "선별된 소스를 최적화(Merge/Padding) 중...")
            
        # LLM은 ID만 반환하므로, 시간 계산을 위해 transcripts 원본 데이터가 필요합니다.
        processed_groups = self._process_candidates(candidates, video_duration, transcripts)
        
        # [4] 완료 임박
        if task_manager and task_id:
            task_manager.update_progress(task_id, 95, "결과 저장 중...")

        return {
            "status": "success",
            "total_groups": len(processed_groups),
            "results": processed_groups
        }

    def _analyze_with_llm(self, transcripts):
        """
        Gemini에게 스크립트를 주고 구간 선별을 요청합니다.
        (프롬프트 최적화 유지)
        """
        # 입력 데이터 포맷팅 (ID | Time | Text)
        script_lines = [
            f"[{t['id']}] {t['start']:.1f}s ~ {t['end']:.1f}s: {t['text']}" 
            for t in transcripts
        ]
        input_text = "\n".join(script_lines)

        # JSON 스키마 정의
        response_schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "category": {
                        "type": "STRING", 
                        "enum": ["Hook", "Story", "Insight", "B-Roll"],
                        "description": "편집 용도 분류"
                    },
                    "title": {"type": "STRING", "description": "구간 제목 (5단어 이내)"},
                    "reason": {"type": "STRING", "description": "선정 이유"},
                    "start_id": {"type": "INTEGER", "description": "시작 세그먼트 ID"},
                    "end_id": {"type": "INTEGER", "description": "종료 세그먼트 ID"}
                },
                "required": ["category", "title", "reason", "start_id", "end_id"]
            }
        }

        # 프롬프트 설계
        prompt = f"""
        You are a professional Video Editor assistant. 
        Analyze the transcript below and select key segments for a 'Rough Cut'.
        
        ### Categories (Select based on these types):
        1. **Hook**: Highly engaging moments within the first 20% of the video or climax teasers. (Label Color: Rose)
        2. **Story**: Main narrative arcs or episodes. (Label Color: Iris)
        3. **Insight**: Key information, lessons, or clear messages. (Label Color: Mango)
        4. **B-Roll**: Reactions, funny moments, or mood setters suitable for inserts. (Label Color: Lavender)

        ### Rules:
        - Select continuous chunks using `start_id` and `end_id`.
        - Do NOT select everything. Pick only the usable parts (Top 30-40%).
        - Ignore filler words or silence.

        ### Input Transcript:
        {input_text}
        """

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                    response_schema=response_schema
                )
            )
            return json.loads(response.text)

        except Exception as e:
            print(f"[SourceSelector] LLM Error: {e}")
            return []

    def _process_candidates(self, candidates, video_duration, transcripts):
        """
        [핵심 알고리즘]
        1. ID를 실제 시간(Time)으로 변환
        2. 앞뒤 패딩(+5초) 추가
        3. 겹치거나 인접한(2초 이내) 구간 병합
        """
        raw_segments = []
        
        # ID로 transcript 조회 최적화를 위한 딕셔너리 생성
        trans_map = {t['id']: t for t in transcripts}

        for cand in candidates:
            s_id = cand.get('start_id')
            e_id = cand.get('end_id')
            
            if s_id not in trans_map or e_id not in trans_map:
                continue
                
            start_time = trans_map[s_id]['start']
            end_time = trans_map[e_id]['end']
            
            # 패딩 적용 (앞뒤 5초)
            padded_start = max(0, start_time - 5.0)
            padded_end = min(video_duration, end_time + 5.0)
            
            raw_segments.append({
                "category": cand['category'],
                "title": cand['title'],
                "reason": cand['reason'],
                "start": padded_start,
                "end": padded_end
            })

        if not raw_segments: return []

        # 2. 시간순 정렬 (병합을 위해 필수)
        raw_segments.sort(key=lambda x: x['start'])

        # 3. 병합 (Merge) 알고리즘
        merged = []
        
        for current in raw_segments:
            if not merged:
                merged.append(current)
                continue
            
            last = merged[-1]
            
            # 병합 조건: 
            # 1. 같은 카테고리 (Hook끼리, Story끼리 등)
            # 2. 인접성: (이전 구간 끝 + 2초 여유) >= 현재 구간 시작
            #    즉, 두 구간 사이의 갭이 2초 이내라면 붙여버림
            is_same_category = (last['category'] == current['category'])
            is_adjacent = (last['end'] + 2.0 >= current['start'])
            
            if is_same_category and is_adjacent:
                # 병합 수행: 끝나는 시간을 더 긴 쪽으로 연장
                last['end'] = max(last['end'], current['end'])
                # (선택) 이유는 합치거나, 첫 번째 이유를 대표로 사용
            else:
                merged.append(current)

        return merged