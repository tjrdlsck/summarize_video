import os
import json
import re
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
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        return text.strip()

    def _deduplicate_stuttering(self, segment_start, segment_end, original_transcripts):
        """
        [Advanced] 단어 간격과 성격을 분석하여 중복 단어를 정밀하게 처리합니다.
        """
        target_seg = None
        for seg in original_transcripts:
            if seg['start'] <= segment_start < seg['end']:
                target_seg = seg
                break
        
        if not target_seg or 'words' not in target_seg:
            return segment_start

        words = target_seg['words']
        start_idx = 0
        for i, w in enumerate(words):
            if w['start'] >= segment_start - 0.1:
                start_idx = i
                break
        
        check_range = words[start_idx : start_idx + 4]
        if len(check_range) < 2:
            return segment_start

        def clean(t): return re.sub(r'[^\w]', '', t)
        
        fillers = ["어", "음", "아", "저", "이제", "막", "어음"]
        w1 = check_range[0]
        w2 = check_range[1]
        
        word1_text = clean(w1['word'])
        word2_text = clean(w2['word'])
        gap = w2['start'] - w1['end']

        if word1_text in fillers and gap < 0.8:
            return w2['start']

        if word1_text == word2_text:
            if gap < 1.0:
                return w2['start']

        return segment_start

    def make_shorts_candidates(self, transcripts, video_title, chapters=None, focus_topic=None):
        """
        [Advanced] 챕터 메타데이터와 사용자 주제(Topic)를 활용하여 최적의 숏츠 후보를 생성합니다.
        
        Args:
            transcripts: 전체 자막 데이터 리스트
            video_title: 영상 제목
            chapters: 분석된 챕터 정보 (Filtering용)
            focus_topic: 사용자가 요청한 주제/키워드 (Optional)
        """
        if not self.api_key:
            print("[ShortsMaker] Error: API Key missing")
            return []

        # 1. 챕터 기반 데이터 필터링 (Whitelist 방식)
        filtered_script = ""
        # 숏츠로 쓰기에 적합한 챕터 타입
        TARGET_TYPES = ["Illustration", "Preaching_Main", "Application"]
        
        if chapters:
            print(f"[ShortsMaker] Filtering chapters... (Target: {TARGET_TYPES})")
            for chap in chapters:
                # 챕터 타입이 타겟에 포함되는 경우만 추출
                if chap.get("type") in TARGET_TYPES:
                    start_t = chap["time"]["start"]
                    end_t = chap["time"]["end"]
                    
                    # 챕터 정보를 헤더로 넣어 문맥 파악 도움
                    filtered_script += f"\n\n## Section: {chap['title']} ({chap.get('type')})\n"
                    
                    # 시간 범위에 맞는 세그먼트 추출
                    in_range_segments = [
                        s for s in transcripts 
                        if s['start'] >= start_t and s['start'] < end_t
                    ]
                    for seg in in_range_segments:
                        filtered_script += f"[{seg['id']}] {seg['start']:.2f}~{seg['end']:.2f}: {seg['text']}\n"
        else:
            # 챕터 정보가 없으면 전체 사용 (Fallback)
            print("[ShortsMaker] No chapters provided. Using full script.")
            for seg in transcripts:
                filtered_script += f"[{seg['id']}] {seg['start']:.2f}~{seg['end']:.2f}: {seg['text']}\n"

        if not filtered_script.strip():
            print("[ShortsMaker] Warning: No chapters matched target types. Falling back to FULL script.")
            # 필터링된 게 없으면 전체 스크립트를 다 넣음 (구버전 데이터 호환성 or 챕터가 제대로 안 잡힌 경우 대비)
            for seg in transcripts:
                filtered_script += f"[{seg['id']}] {seg['start']:.2f}~{seg['end']:.2f}: {seg['text']}\n"

        if not filtered_script.strip():
            print("[ShortsMaker] No valid script found even after fallback.")
            return []

        # 2. 프롬프트 구성
        user_intent_guide = ""
        if focus_topic:
            user_intent_guide = (
                f"\n**[사용자 특별 요청]**\n"
                f"사용자는 **'{focus_topic}'**에 관한 내용을 원합니다.\n"
                f"제공된 스크립트에서 이 주제와 관련된 에피소드나 메시지를 **최우선**으로 찾으세요.\n"
                f"만약 주제와 정확히 일치하는 내용이 없다면, 가장 유사하거나 흥미로운 대안을 제시하세요.\n"
            )

        candidates_schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "시선을 끄는 숏츠 제목"},
                    "reason": {"type": "STRING", "description": "선정 이유 및 사용자 주제와의 연관성"},
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

        system_instruction = (
            "당신은 수백만 조회수를 기록하는 **유튜브 쇼츠 전문 PD**입니다.\n"
            "제공된 설교 대본(Script)에서 시청자의 이목을 사로잡을 수 있는 '알짜배기' 구간을 발굴하여 기획안을 작성하세요.\n\n"
            "**[편집 원칙]**\n"
            "1. **Viral Selection**: 지루한 서론은 버리고, **'Hook(도입)-Body(전개)-Climax(결말)'**가 확실한 구간을 선택하세요.\n"
            "2. **Time Constraint**: 길이는 **최소 40초 ~ 최대 120초(2분)**로 제한합니다. 문맥이 끊기지 않고 완결성을 갖추는 것이 60초 제한보다 더 중요합니다.\n"
            "3. **Contextual Integrity**: 문장이 중간에 잘리거나, 앞뒤 맥락 없이 대명사(그, 저기 등)로 시작하지 않도록 주의하세요.\n"
            "4. **Priority**: '예화(Illustration)'나 '강렬한 메시지(Application)' 위주로 선정하세요. (광고나 성경 봉독은 절대 금지)\n"
            f"{user_intent_guide}\n"
        )

        prompt = f"{system_instruction}\n\n[Selected Script Data]:\n{filtered_script}"

        try:
            print(f"[ShortsMaker] Requesting AI Plan... (Topic: {focus_topic})")
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
            valid_candidates = []
            MAX_DURATION = 130.0 # 여유 있게 130초

            for item in candidates:
                if not item.get('segments'):
                    continue

                refined_segments = self._refine_segments_with_word_data(item['segments'], transcripts)
                validated_segments = []
                current_total_duration = 0.0

                for seg in refined_segments:
                    s, e = float(seg['start']), float(seg['end'])
                    s = self._deduplicate_stuttering(s, e, transcripts)

                    if e <= s or (e - s) < 0.5:
                        continue

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

                # 40초 이상 120초 이하 조건 체크 (약간의 오차 허용)
                if validated_segments and current_total_duration >= 35.0:
                    item['segments'] = validated_segments
                    item['total_duration'] = current_total_duration
                    
                    # 중복 필터링 (Overlap Filtering)
                    is_duplicate = False
                    for existing in valid_candidates:
                        # 교집합 계산 (첫 번째 세그먼트 기준)
                        # *주의: 멀티 컷일 경우 전체 범위를 단순 비교하기 어려우나, 
                        # 보통 전체 범위(Total Span)를 기준으로 판단
                        
                        my_start = validated_segments[0]['start']
                        my_end = validated_segments[-1]['end']
                        ex_start = existing['segments'][0]['start']
                        ex_end = existing['segments'][-1]['end']
                        
                        overlap_start = max(my_start, ex_start)
                        overlap_end = min(my_end, ex_end)
                        overlap_len = max(0, overlap_end - overlap_start)
                        
                        # 기존 구간 대비 50% 이상 겹치면 중복
                        if overlap_len > (existing['total_duration'] * 0.5):
                            is_duplicate = True
                            break
                    
                    if not is_duplicate:
                        valid_candidates.append(item)

            print(f"[ShortsMaker] Generated {len(valid_candidates)} candidates.")
            return valid_candidates

        except Exception as e:
            print(f"[ShortsMaker Error] {e}")
            return []

    def _refine_segments_with_word_data(self, segments, original_transcripts):
        """
        [Advanced Refinement]
        Gemini가 제안한 시간을 단어 단위 데이터와 대조하여 최적의 커팅 포인트를 찾습니다.
        """
        refined = []
        all_words = []
        for seg in original_transcripts:
            if 'words' in seg:
                all_words.extend(seg['words'])
        
        if not all_words:
            return segments

        for i, target in enumerate(segments):
            s_target, e_target = target['start'], target['end']
            
            closest_start_word = min(all_words, key=lambda w: abs(w['start'] - s_target))
            new_start = max(0, closest_start_word['start'] - 0.15)
            
            closest_end_word = min(all_words, key=lambda w: abs(w['end'] - e_target))
            new_end = closest_end_word['end'] + 0.3
            
            if refined and new_start < refined[-1]['end']:
                new_start = refined[-1]['end'] + 0.05
            
            if new_end > new_start + 0.5:
                refined.append({"start": round(new_start, 3), "end": round(new_end, 3)})
            else:
                refined.append({"start": round(s_target, 3), "end": round(e_target, 3)})

        return refined