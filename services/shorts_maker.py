import os
import json
import re  # [필수] 정규표현식 모듈 추가
from dotenv import load_dotenv
from google import genai
from google.genai import types

class ShortsMaker:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY")
        # JSON 포맷 준수율이 높은 최신 모델 사용
        self.model_name = "gemini-2.5-flash"

    def _clean_json_text(self, text):
        """
        LLM이 반환한 텍스트에서 Markdown 코드 블록(```json ... ```)을 제거하고
        순수 JSON 문자열만 추출합니다.
        """
        # 1. ```json ... ``` 패턴 제거
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        return text.strip()

    def make_shorts_candidates(self, master_data, video_title):
        """
        [Strategic Multimodal Selection] 
        마스터 데이터를 분석하여 AIDA 모델과 Hook-Retention-Payoff 공식에 기반한 쇼츠 후보를 추출합니다.
        """
        if not self.api_key:
            print("[ShortsMaker] Error: API Key missing")
            return []

        # 1. 멀티모달 컨텍스트 데이터 정제
        refined_context = []
        for chap in master_data.get('chapters', []):
            chap_text = (
                f"### [구간: {chap['time']['start']:.1f}s ~ {chap['time']['end']:.1f}s]\n"
                f"- 요약: {chap['summary']}\n"
            )
            if chap.get('visual_context'):
                visuals = " | ".join([
                    f"화면({v['action']}), 자막({v['text']}), 분위기({v['mood']})" 
                    for v in chap['visual_context']
                ])
                chap_text += f"- 시각 정보: {visuals}\n"
            
            refined_context.append(chap_text)
        
        context_body = "\n".join(refined_context)
        
        # 2. 구조화된 출력 스키마 정의
        candidates_schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "시청자를 유혹하는 숏츠 제목"},
                    "reason": {"type": "STRING", "description": "바이럴 전략적 근거"},
                    "segments": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "start": {"type": "NUMBER"},
                                "end": {"type": "NUMBER"}
                            },
                            "required": ["start", "end"]
                        }
                    }
                },
                "required": ["title", "reason", "segments"]
            }
        }

        # 3. 전략적 쇼츠 기획 지시문 (Updated with Constraints)
        system_instruction = (
            "당신은 유튜브 쇼츠(Shorts) 전문 전략가이자 에디터입니다.\n"
            "제공된 [멀티모달 분석 데이터]를 심층 분석하여, '킬러 콘텐츠' 구간 3개를 발굴하세요.\n\n"
            "### [필수 분석 프레임워크]:\n"
            "1. **The Hook (0~3초)**: 시각적 임팩트나 호기심 자극이 강한 구간.\n"
            "2. **AIDA 모델**: Attention -> Interest -> Desire -> Action의 흐름.\n"
            "3. **Visual Reward**: 말이 많은 구간보다 시각 정보(Visual Scenes)가 풍부한 구간 우대.\n\n"
            "### [CRITICAL CONSTRAINTS - 절대 준수]:\n"
            "1. **Audio Continuity (오디오 완결성)**: 구간의 시작(Start)과 끝(End)은 반드시 **문장이 온전히 끝나는 시점**이어야 합니다. 말이 중간에 뚝 끊기지 않도록 앞뒤로 1~2초의 여유(Buffer)를 두고 잡으세요.\n"
            "2. **No Context Cuts**: 대화의 맥락이 이해될 수 있도록 충분한 길이를 확보하세요 (최소 15초 이상 권장)."
        )

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model_name,
                contents=f"{system_instruction}\n\n### [영상 제목: {video_title}]\n### [멀티모달 분석 데이터]:\n{context_body}",
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    response_mime_type="application/json",
                    response_schema=candidates_schema
                )
            )
            
            candidates = json.loads(response.text)
            
            # 4. 유효성 검증 및 구간 트리밍 (Max 3min Limit)
            valid_candidates = []
            MAX_DURATION = 180.0

            for item in candidates:
                if not item.get('segments'): continue
                
                validated_segments = []
                current_total_duration = 0.0
                
                for seg in item['segments']:
                    s, e = float(seg['start']), float(seg['end'])
                    if e <= s or (e - s) < 0.5: continue
                    
                    seg_duration = e - s
                    if current_total_duration + seg_duration > MAX_DURATION:
                        remaining = MAX_DURATION - current_total_duration
                        if remaining > 1.0:
                            validated_segments.append({"start": s, "end": s + remaining})
                            current_total_duration += remaining
                        break
                    else:
                        validated_segments.append({"start": s, "end": e})
                        current_total_duration += seg_duration
                
                if validated_segments and current_total_duration >= 10.0:
                    item['segments'] = validated_segments
                    item['total_duration'] = current_total_duration
                    valid_candidates.append(item)
            
            print(f"[ShortsMaker] Strategic Multimodal Planning Complete. Generated {len(valid_candidates)} candidates.")
            return valid_candidates

        except Exception as e:
            print(f"[ShortsMaker Error] AI Planning Failed: {e}")
            return []