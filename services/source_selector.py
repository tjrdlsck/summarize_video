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

    def select_sources(self, master_data, video_duration, task_manager=None, task_id=None):
        """
        [Professional Source Selection] 
        마스터 데이터를 정량 평가하여 고가치 편집 소스(Hook, Story, Insight, B-Roll)를 선별합니다.
        
        입력:
        - master_data: Summarizer가 생성한 멀티모달 통합 JSON
        """
        if not self.api_key:
            return {"error": "API Key missing"}

        # 1. 상태 보고 및 준비 (0~10%)
        if task_manager and task_id:
            if task_manager.is_cancelled(task_id): return {"error": "Cancelled"}
            task_manager.update_progress(task_id, 5, "멀티모달 소스 정밀 평가 준비 중...")

        # 2. LLM 절대 점수제 분석 (10~80%)
        if task_manager and task_id:
            task_manager.update_progress(task_id, 15, "수석 편집자 AI가 각 구간의 편집 가치를 채점 중입니다...")

        # [핵심] 마스터 데이터를 기반으로 한 정밀 추론 호출
        candidates = self._analyze_with_llm(master_data)
        
        if task_manager and task_id and task_manager.is_cancelled(task_id):
            return {"error": "Cancelled by user"}

        if not candidates:
            return {"error": "AI analysis failed or returned empty result"}

        # 3. 고가치 소스 최적화 및 필터링 (80~100%)
        if task_manager and task_id:
            task_manager.update_progress(task_id, 85, "7점 이상의 고가치 소스 구간 확정 중...")
            
        # [Fix] LLM이 이미 초(seconds) 단위를 반환하므로 transcripts 인자 없이 처리
        processed_groups = self._process_candidates(candidates, video_duration)
        
        if task_manager and task_id:
            task_manager.update_progress(task_id, 100, "편집 소스 선별 및 채점 완료")

        return {
            "status": "success",
            "total_groups": len(processed_groups),
            "results": processed_groups
        }

    def _analyze_with_llm(self, master_data):
        """
        [Chief Editor Reasoning] 
        영상과 내용을 1-10점 척도로 절대 평가하여 최적의 소스를 선별합니다.
        """
        # 마스터 데이터로부터 멀티모달 컨텍스트 구성
        source_context = []
        for chap in master_data.get('chapters', []):
            info = (
                f"### [시간: {chap['time']['start']:.1f}s ~ {chap['time']['end']:.1f}s]\n"
                f"- 내용: {chap['summary']}\n"
            )
            if chap.get('visual_context'):
                visuals = " | ".join([f"동작({v['action']}), 자막({v['text']})" for v in chap['visual_context']])
                info += f"- 시각: {visuals}\n"
            
            source_context.append(info)

        input_text = "\n---\n".join(source_context)

        # JSON 스키마 (채점 결과 포함)
        response_schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "category": {
                        "type": "STRING", 
                        "enum": ["Hook", "Story", "Insight", "B-Roll"],
                        "description": "Footage type"
                    },
                    "score": {"type": "INTEGER", "description": "편집 가치 점수 (1-10)"},
                    "title": {"type": "STRING", "description": "소체 제목"},
                    "reason": {"type": "STRING", "description": "선정 이유 (시각적/내용적 강점)"},
                    "start": {"type": "NUMBER", "description": "시작 시간(초)"},
                    "end": {"type": "NUMBER", "description": "종료 시간(초)"}
                },
                "required": ["category", "score", "title", "reason", "start", "end"]
            }
        }

        # 수석 편집자 페르소나 및 점수제 지시문 (Updated with Anchor Examples)
        prompt = f"""
        당신은 다큐멘터리 및 예능 전문 수석 편집자(Chief Editor)입니다. 
        제공된 '멀티모달 분석 데이터'의 각 구간을 전문적 관점에서 평가하여 **7점 이상**인 고가치 소스만 추출하세요.

        ### [전문 편집자 평가 지표]:
        1. **Hook (오프닝)**: 시각적으로 시선을 끌거나, 첫 3초 안에 시청자를 사로잡을 수 있는가?
        2. **Story (내러티브)**: 정보 전달이 명확하고 문맥의 흐름이 자연스러운가?
        3. **Insight (정보)**: 핵심 통찰을 담고 있으며, 화면에 중요한 자막/데이터가 나타나는가?
        4. **B-Roll (인서트 가치)**: 오디오보다 시각적 묘사(Visual)가 훌륭하여 인서트 컷으로 쓰기 좋은가?

        ### [채점 기준표 (Anchor Examples) - 필독]:
        - **10점 (Perfect)**: 도파민이 터지는 강력한 액션 장면, 또는 핵심 반전이 드러나는 결정적 순간. (무조건 씀)
        - **7~8점 (Great)**: 내용이 알차고 화면 구도가 안정적임. 컷 편집에 필수적인 구간.
        - **5점 (Average)**: 평범한 대화나 설명. 특별한 매력은 없지만 흐름상 필요할 수 있음.
        - **3점 이하 (Bad)**: 화면 변화가 거의 없고, 의미 없는 추임새나 반복 어구만 가득한 구간. (버림)

        ### [선별 규칙]:
        - 반드시 위 '채점 기준표'에 근거하여 냉정하게 평가하세요.
        - **오직 7점 이상인 구간만** 결과에 포함시키세요.

        ### 분석 데이터:
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
            # 7점 이상 필터링은 프롬프트에서도 지시했지만, 코드 레벨에서 한 번 더 보장합니다.
            results = json.loads(response.text)
            return [res for res in results if res.get('score', 0) >= 7]

        except Exception as e:
            print(f"[SourceSelector Error] Chief Editor Reasoning Failed: {e}")
            return []

    def _process_candidates(self, candidates, video_duration):
        """
        [핵심 알고리즘]
        1. LLM이 반환한 초(seconds) 단위를 기반으로 처리
        2. 앞뒤 패딩(+5초) 추가
        3. 겹치거나 인접한(2초 이내) 구간 병합
        """
        raw_segments = []
        
        for cand in candidates:
            # LLM은 이미 초(seconds) 단위를 반환함
            start_time = cand.get('start')
            end_time = cand.get('end')
            
            if start_time is None or end_time is None:
                continue
            
            # 패딩 적용 (앞뒤 5초)
            padded_start = max(0, start_time - 5.0)
            padded_end = min(video_duration, end_time + 5.0)
            
            raw_segments.append({
                "category": cand['category'],
                "score": cand.get('score', 7),
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
                # 이유는 첫 번째 이유를 유지하거나 병합 가능
            else:
                merged.append(current)

        return merged