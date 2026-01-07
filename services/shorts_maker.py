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

    def make_shorts_candidates(self, transcripts, video_title, chapters=None):
        """
        [Advanced] 챕터 메타데이터를 활용하여 성경 봉독 구간의 원자성을 보호하며 숏츠 후보를 생성합니다.
        """
        if not self.api_key:
            print("[ShortsMaker] Error: API Key missing")
            return []

        input_data = "\n".join([f"[{t['id']}] {t['start']:.2f}~{t['end']:.2f}: {t['text']}" for t in transcripts])
        
        chapter_context = ""
        if chapters:
            bible_segments = [c for c in chapters if c.get('type') == 'Scripture_Reading']
            if bible_segments:
                chapter_context = "\n### Special Constraints (Scripture Reading):\n"
                for b in bible_segments:
                    chapter_context += f"- ID {b.get('start_id')} to {b.get('end_id')} is a Scripture Reading section.\n"
                chapter_context += "Rule: Do NOT cut in the middle of these sections. Include the WHOLE section or NOTHING from it.\n"

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

        prompt = f"""
        You are an expert video editor specializing in viral Shorts/Reels for Christian content.
        Your task is to identify the **top 3 most engaging candidates** for Shorts from the provided transcript.
        Video Title: {video_title}

        ### Core Strategy: Multi-cut Editing
        - **DO NOT** just pick one long continuous block. It's often boring.
        - **DO** identify multiple key moments (e.g., a powerful opening statement, a core message, and a concluding impact) and **combine them** into one Short.
        - **Skip** filler words, long pauses, or redundant explanations between the core points to keep the pace high and the duration optimal.
        - Each candidate in the JSON should ideally have **2 to 4 segments** in the `segments` array to create a dynamic 'multi-cut' effect.

        ### Core Requirements:
        1. **Format**: Vertical Short-form video (Reels/Shorts/TikTok).
        2. **Duration**: Each final Short must be between **15 seconds and 180 seconds** in total duration.
        3. **Flow**: Ensure the transition between non-adjacent segments feels logical and the audio flows naturally without cutting mid-sentence.
        4. **Hook**: The very first segment MUST be an attention-grabbing 'hook'.

        {chapter_context}

        ### Crucial Rule for Scripture Reading:
        - If a segment belongs to a 'Scripture_Reading' section, you MUST NOT fragment it. 
        - These sections are sacred and must be presented as a whole unit to maintain context. 
        - If the scripture is too long for a Short, focus on the speaker's explanation (Sermon) instead.

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
            valid_candidates = []
            MAX_DURATION = 180.0

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

                if validated_segments and current_total_duration >= 10.0:
                    item['segments'] = validated_segments
                    item['total_duration'] = current_total_duration
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