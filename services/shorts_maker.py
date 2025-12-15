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

    # [수정] 기존 make_shorts_candidates 메서드를 아래 코드로 교체하세요.
    def make_shorts_candidates(self, transcripts, video_title):
        """
        [Update] 숏츠 길이를 최대 3분(180초)으로 확장하고, 
        생성된 후보군의 총 길이가 제한을 넘지 않는지 검증하는 로직을 추가했습니다.
        """
        if not self.api_key:
            print("[ShortsMaker] Error: API Key missing")
            return []

        # 1. 입력 데이터 준비
        input_data = "\n".join([f"[{t['id']}] {t['start']:.2f}~{t['end']:.2f}: {t['text']}" for t in transcripts])
        
        # 2. Output Schema 정의
        candidates_schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "시선을 끄는 숏츠 제목"},
                    "reason": {"type": "STRING", "description": "바이럴 소구점 설명"},
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

        # 3. 프롬프트 수정 (60초 -> 180초)
        prompt = f"""
        You are an expert video editor specializing in viral Shorts/Reels.
        Your task is to identify the **top 3 most engaging segments** from the provided transcript.
        Video Title: {video_title}

        ### Requirements:
        1. **Format**: Vertical Short-form video (Reels/Shorts/TikTok).
        2. **Duration**: Each candidate must be between **15 seconds and 180 seconds (3 minutes)**.
        3. **Flow**: Combine non-adjacent segments if they are logically connected (Jump Cuts), but ensure the audio flows naturally.
        4. **Hook**: The beginning must be attention-grabbing.

        ### Input Transcript:
        {input_data}
        """

        try:
            client = genai.Client(api_key=self.api_key)
            
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    response_mime_type="application/json",
                    response_schema=candidates_schema
                )
            )
            
            candidates = json.loads(response.text)
            
            # 4. 논리적 유효성 검증 및 길이 트리밍 (Hard Limit: 180s)
            valid_candidates = []
            MAX_DURATION = 180.0  # 최대 3분

            for item in candidates:
                if not item.get('segments'): continue
                
                validated_segments = []
                current_total_duration = 0.0
                
                for seg in item['segments']:
                    s, e = float(seg['start']), float(seg['end'])
                    
                    # 역행하거나 너무 짧은 구간 제외
                    if e <= s or (e - s) < 0.5: continue
                    
                    # 현재 세그먼트의 길이
                    seg_duration = e - s
                    
                    # 최대 길이를 초과하는지 확인
                    if current_total_duration + seg_duration > MAX_DURATION:
                        # 남은 시간만큼만 자르고 루프 종료
                        remaining = MAX_DURATION - current_total_duration
                        if remaining > 1.0: # 최소 1초 이상 남았을 때만 추가
                            validated_segments.append({"start": s, "end": s + remaining})
                            current_total_duration += remaining
                        break
                    else:
                        validated_segments.append({"start": s, "end": e})
                        current_total_duration += seg_duration
                
                if validated_segments and current_total_duration >= 10.0: # 최소 10초 이상인 것만
                    item['segments'] = validated_segments
                    item['total_duration'] = current_total_duration
                    valid_candidates.append(item)
            
            print(f"[ShortsMaker] Generated {len(valid_candidates)} candidates (Max 3 min).")
            return valid_candidates

        except Exception as e:
            print(f"[ShortsMaker Error] {e}")
            return []