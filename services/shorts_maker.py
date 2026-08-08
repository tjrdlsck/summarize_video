import os
import json
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types
from services.content_profiles import get_content_profile
from services.system_manager import ConfigManager

class ShortsMaker:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY")

    def _get_model(self):
        """실시간 설정을 가져옵니다."""
        return ConfigManager.get_model("shorts")

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

    def _clamp(self, value, lo=0.0, hi=1.0):
        return max(lo, min(hi, value))

    def _resolve_duration_bounds(self, min_duration, max_duration):
        try:
            min_d = float(min_duration)
        except Exception:
            min_d = 40.0

        try:
            max_d = float(max_duration)
        except Exception:
            max_d = 90.0

        min_d = max(20.0, min_d)
        max_d = min(180.0, max_d)
        if max_d <= min_d:
            max_d = min_d + 10.0
        return min_d, max_d

    def _attach_turn_ids(self, transcripts, speaker_mode="pseudo"):
        if not transcripts:
            return []

        sorted_transcripts = sorted(transcripts, key=lambda x: float(x.get("start", 0.0)))
        has_real_speaker = (
            speaker_mode == "full"
            and any(segment.get("speaker_id") is not None for segment in sorted_transcripts)
        )

        annotated = []
        turn_id = 1
        prev = None
        for segment in sorted_transcripts:
            current = dict(segment)
            if prev is not None:
                gap = max(0.0, float(current.get("start", 0.0)) - float(prev.get("end", 0.0)))
                if speaker_mode == "none":
                    pass
                elif has_real_speaker:
                    if current.get("speaker_id") != prev.get("speaker_id") or gap > 1.2:
                        turn_id += 1
                else:
                    prev_text = str(prev.get("text", "")).strip()
                    curr_text = str(current.get("text", "")).strip()
                    short_exchange = len(prev_text) <= 14 or len(curr_text) <= 14
                    punctuation_trigger = prev_text.endswith(("?", "？", "!", "！"))
                    if gap > 1.1 or punctuation_trigger or (gap > 0.25 and short_exchange):
                        turn_id += 1

            current["pseudo_turn_id"] = 1 if speaker_mode == "none" else turn_id
            annotated.append(current)
            prev = current

        return annotated

    def _collect_candidate_transcripts(self, transcripts, ranges):
        if not transcripts or not ranges:
            return []

        matched = []
        for segment in transcripts:
            s_start = float(segment.get("start", 0.0))
            s_end = float(segment.get("end", 0.0))
            for target in ranges:
                r_start = float(target.get("start", 0.0))
                r_end = float(target.get("end", 0.0))
                if s_end > r_start and s_start < r_end:
                    matched.append(segment)
                    break
        return sorted(matched, key=lambda x: float(x.get("start", 0.0)))

    def _candidate_span(self, segments):
        if not segments:
            return 0.0, 0.0
        return float(segments[0]["start"]), float(segments[-1]["end"])

    def _span_overlap_ratio(self, a_segments, b_segments):
        a_start, a_end = self._candidate_span(a_segments)
        b_start, b_end = self._candidate_span(b_segments)

        a_len = max(0.001, a_end - a_start)
        overlap_start = max(a_start, b_start)
        overlap_end = min(a_end, b_end)
        overlap = max(0.0, overlap_end - overlap_start)
        return overlap / a_len

    def _estimate_funniness_score(self, title, reason, overlap_segments):
        transcript_snippet = " ".join(str(seg.get("text", "")) for seg in overlap_segments[:16])
        source = f"{title} {reason} {transcript_snippet}"
        humor_keywords = [
            "웃긴", "웃음", "폭소", "빵터", "터짐", "개웃", "드립", "농담", "미친", "레전드",
            "당황", "실화", "미쳤", "대환장", "킹받", "헛웃", "ㅋㅋ", "ㅎㅎ",
        ]
        hit_count = sum(1 for keyword in humor_keywords if keyword in source)

        score = 0.2 + min(0.55, hit_count * 0.08)
        if "ㅋㅋ" in source or "ㅎㅎ" in source:
            score += 0.15
        if "!" in source or "?" in source:
            score += 0.06
        return self._clamp(score)

    def _estimate_hook_score(self, overlap_segments, candidate_start):
        if not overlap_segments:
            return 0.0

        first_window_end = candidate_start + 3.0
        early_lines = [
            str(seg.get("text", ""))
            for seg in overlap_segments
            if float(seg.get("start", 0.0)) < first_window_end
        ]
        early_text = " ".join(early_lines).strip()
        if not early_text:
            return 0.2

        hook_keywords = ["뭐야", "진짜", "와", "헉", "잠깐", "레전드", "미쳤", "실화"]
        score = 0.25
        if any(keyword in early_text for keyword in hook_keywords):
            score += 0.35
        if "!" in early_text or "?" in early_text:
            score += 0.2
        if len(early_text) <= 40:
            score += 0.1
        if "ㅋㅋ" in early_text or "ㅎㅎ" in early_text:
            score += 0.1
        return self._clamp(score)

    def _estimate_tikkitaka_score(self, overlap_segments, duration):
        if len(overlap_segments) < 2:
            return 0.0, 0

        switches = 0
        short_lines = 0
        prev_turn = overlap_segments[0].get("pseudo_turn_id", 1)
        prev_end = float(overlap_segments[0].get("end", 0.0))

        for segment in overlap_segments:
            if len(str(segment.get("text", "")).strip()) <= 14:
                short_lines += 1

        for segment in overlap_segments[1:]:
            turn = segment.get("pseudo_turn_id", prev_turn)
            gap = max(0.0, float(segment.get("start", 0.0)) - prev_end)
            if turn != prev_turn and gap <= 2.0:
                switches += 1
            prev_turn = turn
            prev_end = float(segment.get("end", prev_end))

        density = switches / max(1.0, duration)
        score = min(1.0, density * 3.5)
        score += min(0.25, (short_lines / max(1, len(overlap_segments))) * 0.25)
        if switches >= 3:
            score += 0.15
        return self._clamp(score), switches

    def _estimate_context_score(self, validated_segments, overlap_segments, duration):
        score = 0.55
        if 40.0 <= duration <= 75.0:
            score += 0.15
        if len(validated_segments) == 1:
            score += 0.15

        if len(validated_segments) > 1:
            gaps = []
            for idx in range(1, len(validated_segments)):
                prev_end = float(validated_segments[idx - 1]["end"])
                cur_start = float(validated_segments[idx]["start"])
                gaps.append(max(0.0, cur_start - prev_end))
            if gaps:
                if max(gaps) <= 1.5:
                    score += 0.1
                elif max(gaps) > 5.0:
                    score -= 0.2

        if overlap_segments:
            ending_text = str(overlap_segments[-1].get("text", "")).strip()
            if ending_text.endswith(("!", "?", ".", "다", "요")):
                score += 0.1
        else:
            score -= 0.2

        return self._clamp(score)

    def _estimate_topic_match(self, focus_topic, title, reason, overlap_segments):
        if not focus_topic or not focus_topic.strip():
            return 0.5

        source = f"{title} {reason} {' '.join(str(seg.get('text', '')) for seg in overlap_segments)}"
        tokens = [token for token in re.split(r"\s+", focus_topic.strip()) if token]
        if not tokens:
            return 0.5

        matches = sum(1 for token in tokens if token in source)
        if matches == 0:
            return 0.2
        return self._clamp(0.2 + (0.8 * matches / len(tokens)))

    def _build_weights(self, humor_weight):
        try:
            humor_int = int(humor_weight)
        except Exception:
            humor_int = 50

        humor_ratio = self._clamp(humor_int / 100.0, 0.0, 0.8)
        remaining = 1.0 - humor_ratio
        return {
            "funniness": humor_ratio,
            "tikkitaka": remaining * 0.4,
            "hook": remaining * 0.3,
            "context": remaining * 0.2,
            "topic": remaining * 0.1,
        }

    def make_shorts_candidates(
        self,
        transcripts,
        video_title,
        chapters=None,
        focus_topic=None,
        content_type="sermon",
        style="funny",
        min_duration=40.0,
        max_duration=90.0,
        humor_weight=50,
        keep_original_tone=True,
        speaker_mode="pseudo",
        map_notes=None,
    ):
        """
        [Advanced] 챕터 메타데이터, Stage 1 정밀 노트, 사용자 주제(Topic)를 활용하여 최적의 숏츠 후보를 생성합니다.
        
        Args:
            transcripts: 전체 자막 데이터 리스트
            video_title: 영상 제목
            chapters: 분석된 챕터 정보 (Filtering용)
            focus_topic: 사용자가 요청한 주제/키워드 (Optional)
            map_notes: Stage 1 (Map Phase)에서 추출된 정밀 노트 리스트 (Optional)
        """
        if not self.api_key:
            print("[ShortsMaker] Error: API Key missing")
            return []

        profile = get_content_profile(content_type)
        min_duration, max_duration = self._resolve_duration_bounds(min_duration, max_duration)

        if style == "balanced":
            try:
                humor_weight = min(int(humor_weight), 35)
            except Exception:
                humor_weight = 35
        else:
            try:
                humor_weight = int(humor_weight)
            except Exception:
                humor_weight = 50

        weights = self._build_weights(humor_weight)
        annotated_transcripts = self._attach_turn_ids(transcripts, speaker_mode=speaker_mode)

        # 1. 챕터 기반 데이터 필터링 (Whitelist 방식)
        filtered_script = ""
        TARGET_TYPES = profile.shorts_target_types
        total_filtered_duration = 0.0

        if chapters:
            print(f"[ShortsMaker] Filtering chapters... (Target: {TARGET_TYPES})")
            for chap in chapters:
                if chap.get("type") in TARGET_TYPES:
                    start_t = chap["time"]["start"]
                    end_t = chap["time"]["end"]
                    
                    filtered_script += f"\n\n## Section: {chap['title']} ({chap.get('type')})\n"
                    
                    in_range_segments = [
                        s for s in transcripts 
                        if s['start'] >= start_t and s['start'] < end_t
                    ]
                    for seg in in_range_segments:
                        filtered_script += f"[{seg['id']}] {seg['start']:.2f}~{seg['end']:.2f}: {seg['text']}\n"
                        total_filtered_duration += (seg['end'] - seg['start'])
        else:
            print("[ShortsMaker] No chapters provided. Using full script.")

        # 챕터 매칭된 스크립트가 없거나, 총 세그먼트 합산 기간이 min_duration보다 작은 경우 스마트 Fallback
        if not filtered_script.strip() or total_filtered_duration < min_duration:
            if filtered_script.strip():
                print(f"[ShortsMaker] Warning: Filtered chapters total duration ({total_filtered_duration:.1f}s) < min_duration ({min_duration:.1f}s). Falling back to FULL script.")
            else:
                print("[ShortsMaker] Warning: No chapters matched target types. Falling back to FULL script.")
            
            filtered_script = ""
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

        tone_guide = (
            "원문 말투/감탄/밈을 유지하세요."
            if keep_original_tone
            else "욕설/비속어는 과도하지 않게 완화하세요."
        )
        runtime_rules = (
            f"- 길이는 반드시 {int(min_duration)}초~{int(max_duration)}초 사이로 맞추세요.\n"
            f"- 웃긴 장면 우선순위를 {int(humor_weight)}%로 두고 후보를 제안하세요.\n"
            f"- {tone_guide}"
        )
        system_instruction = f"{profile.shorts_system_instruction}\n{runtime_rules}\n{user_intent_guide}\n"

        prompt = f"{system_instruction}\n\n[Selected Script Data]:\n{filtered_script}"

        try:
            print(f"[ShortsMaker] Requesting AI Plan... (Topic: {focus_topic})")
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self._get_model(),
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    response_mime_type="application/json",
                    response_schema=candidates_schema
                )
            )
            candidates = json.loads(response.text)
            scored_candidates = []

            for item in candidates:
                if not item.get('segments'):
                    continue

                refined_segments = self._refine_segments_with_word_data(item['segments'], transcripts)
                validated_segments = []
                current_total_duration = 0.0

                for seg in refined_segments:
                    try:
                        s, e = float(seg['start']), float(seg['end'])
                    except (ValueError, TypeError, KeyError):
                        continue
                    s = self._deduplicate_stuttering(s, e, transcripts)

                    if e <= s or (e - s) < 0.5:
                        continue

                    seg_duration = e - s
                    if current_total_duration + seg_duration > max_duration:
                        remaining = max_duration - current_total_duration
                        if remaining > 1.0:
                            validated_segments.append({"start": s, "end": s + remaining})
                            current_total_duration += remaining
                        break
                    else:
                        validated_segments.append({"start": s, "end": e})
                        current_total_duration += seg_duration

                if not validated_segments:
                    continue

                validated_segments = sorted(validated_segments, key=lambda x: x["start"])
                if current_total_duration < min_duration:
                    continue

                overlap_segments = self._collect_candidate_transcripts(annotated_transcripts, validated_segments)
                funniness = self._estimate_funniness_score(
                    item.get("title", ""),
                    item.get("reason", ""),
                    overlap_segments,
                )
                tikkitaka, turn_switch_count = self._estimate_tikkitaka_score(overlap_segments, current_total_duration)
                hook = self._estimate_hook_score(overlap_segments, validated_segments[0]["start"])
                context = self._estimate_context_score(validated_segments, overlap_segments, current_total_duration)
                topic = self._estimate_topic_match(focus_topic, item.get("title", ""), item.get("reason", ""), overlap_segments)

                score_base = (
                    (weights["funniness"] * funniness)
                    + (weights["tikkitaka"] * tikkitaka)
                    + (weights["hook"] * hook)
                    + (weights["context"] * context)
                    + (weights["topic"] * topic)
                )

                item["segments"] = validated_segments
                item["total_duration"] = round(current_total_duration, 3)
                item["score_base"] = round(score_base, 3)
                item["score_breakdown"] = {
                    "funniness": round(funniness, 3),
                    "tikkitaka": round(tikkitaka, 3),
                    "hook": round(hook, 3),
                    "context": round(context, 3),
                    "topic_match": round(topic, 3),
                }
                item["diagnostics"] = {
                    "duration_sec": round(current_total_duration, 3),
                    "turn_switch_count": int(turn_switch_count),
                    "speaker_mode": speaker_mode,
                }
                scored_candidates.append(item)

            scored_candidates.sort(key=lambda x: x.get("score_base", 0.0), reverse=True)

            selected = []
            for item in scored_candidates:
                overlap_penalty = 0.0
                for existing in selected:
                    overlap_penalty = max(
                        overlap_penalty,
                        self._span_overlap_ratio(item["segments"], existing["segments"]),
                    )

                final_score = self._clamp(float(item.get("score_base", 0.0)) - (0.2 * overlap_penalty))
                item["score_breakdown"]["overlap_penalty"] = round(overlap_penalty, 3)
                item["score_total"] = round(final_score, 3)

                if overlap_penalty >= 0.65:
                    continue

                selected.append(item)

            selected.sort(key=lambda x: x.get("score_total", 0.0), reverse=True)
            print(f"[ShortsMaker] Generated {len(selected)} candidates.")
            return selected

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
