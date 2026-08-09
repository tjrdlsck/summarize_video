import os
import re
import json
import time
from typing import Any
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential # [Add] 재시도 로직 추가
from services.content_profiles import get_content_profile
from services.logger import get_logger, log_error_with_traceback, log_task_error

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

def build_smart_chunks(segments: list[dict], target_chars: int = 2000, overlap_chars: int = 250) -> list[list[dict]]:
    """
    Whisper 세그먼트 배열을 기반으로 문맥 오버랩 및 무음 타임스탬프 경계를 적용한 Chunk 생성기
    """
    if not segments:
        return []

    chunks = []
    current_chunk = []
    current_length = 0

    for i, seg in enumerate(segments):
        current_chunk.append(seg)
        current_length += len(seg.get("text", ""))

        if current_length >= target_chars - overlap_chars:
            next_seg = segments[i + 1] if i + 1 < len(segments) else None
            gap_to_next = (float(next_seg["start"]) - float(seg["end"])) if next_seg else 999.0
            is_sentence_end = str(seg.get("text", "")).strip().endswith((".", "?", "!"))

            if gap_to_next >= 1.5 or is_sentence_end or not next_seg:
                chunks.append(current_chunk)
                
                # Overlap 추출 (뒤에서부터 overlap_chars 만큼 보존)
                overlap_buffer = []
                overlap_len = 0
                for prev_seg in reversed(current_chunk):
                    overlap_buffer.insert(0, prev_seg)
                    overlap_len += len(prev_seg.get("text", ""))
                    if overlap_len >= overlap_chars:
                        break
                
                current_chunk = overlap_buffer
                current_length = overlap_len

    if current_chunk and current_chunk not in chunks:
        chunks.append(current_chunk)

    return chunks

from services.system_manager import ConfigManager

# --- [Main Class] Video Summarizer ---
class VideoSummarizer:
    """
    Transcribed Segments -> Prompt -> Gemini API -> JSON Structure
    """
    def __init__(self, output_dir="static/results"):
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # 요약용 coarse 압축 전략 (입력 토큰 절감용)
        self.coarse_enabled = os.getenv("SUMMARY_COARSE_ENABLED", "1") == "1"
        self.coarse_trigger_lines = int(os.getenv("SUMMARY_COARSE_TRIGGER_LINES", "320"))
        self.coarse_target_seconds = float(os.getenv("SUMMARY_COARSE_TARGET_SECONDS", "14"))
        self.coarse_min_seconds = float(os.getenv("SUMMARY_COARSE_MIN_SECONDS", "9"))
        self.coarse_max_seconds = float(os.getenv("SUMMARY_COARSE_MAX_SECONDS", "20"))
        self.boundary_refine_enabled = os.getenv("SUMMARY_BOUNDARY_REFINE_ENABLED", "1") == "1"
        self.boundary_refine_max = int(os.getenv("SUMMARY_BOUNDARY_REFINE_MAX", "6"))
        self.boundary_refine_context_span = int(os.getenv("SUMMARY_BOUNDARY_REFINE_CONTEXT_SPAN", "12"))
        self.boundary_refine_min_score = int(os.getenv("SUMMARY_BOUNDARY_REFINE_MIN_SCORE", "2"))

    def _get_model(self, task_type):
        """설정 매니저를 통해 실시간으로 모델명을 가져옵니다."""
        return ConfigManager.get_model(task_type)

    def _build_coarse_segments(self, segments: list[dict]) -> list[dict]:
        """원본 세그먼트를 요약용 coarse 세그먼트로 병합합니다."""
        if not segments:
            return []

        sorted_segments = sorted(segments, key=lambda x: int(x.get("id", 0)))
        coarse_segments = []
        buffer = []
        coarse_id = 1

        def flush_buffer():
            nonlocal coarse_id
            if not buffer:
                return
            merged_text = " ".join(str(seg.get("text", "")).strip() for seg in buffer).strip()
            if not merged_text:
                merged_text = "(무음)"
            coarse_segments.append(
                {
                    "id": coarse_id,
                    "start": float(buffer[0]["start"]),
                    "end": float(buffer[-1]["end"]),
                    "text": merged_text,
                    "source_start_id": int(buffer[0]["id"]),
                    "source_end_id": int(buffer[-1]["id"]),
                }
            )
            coarse_id += 1
            buffer.clear()

        for index, seg in enumerate(sorted_segments):
            buffer.append(seg)

            current_duration = float(buffer[-1]["end"]) - float(buffer[0]["start"])
            seg_text = str(seg.get("text", "")).strip()
            next_seg = sorted_segments[index + 1] if index + 1 < len(sorted_segments) else None
            gap_to_next = 0.0
            if next_seg:
                gap_to_next = max(0.0, float(next_seg["start"]) - float(seg["end"]))

            end_of_sentence = seg_text.endswith((".", "!", "?", "다", "요"))
            should_flush = False

            if current_duration >= self.coarse_max_seconds:
                should_flush = True
            elif current_duration >= self.coarse_target_seconds and (end_of_sentence or gap_to_next >= 1.2):
                should_flush = True
            elif current_duration >= self.coarse_min_seconds and gap_to_next >= 2.0:
                should_flush = True
            elif not next_seg:
                should_flush = True

            if should_flush:
                flush_buffer()

        flush_buffer()
        return coarse_segments

    def _normalize_chapter_ranges(self, chapters: list[dict], total_lines: int) -> list[dict]:
        """챕터 범위를 1..total_lines에서 빈틈 없이 정규화합니다."""
        if total_lines <= 0:
            return []
        if not chapters:
            return [
                {
                    "title": "전체 요약",
                    "type": "Preaching_Main",
                    "summary": "자동 생성 챕터가 없어 전체를 하나의 구간으로 설정했습니다.",
                    "start_id": 1,
                    "end_id": total_lines,
                    "key_segment_ids": [1],
                    "focus_point": "전체 요약 구간",
                }
            ]

        sorted_chapters = sorted(chapters, key=lambda x: int(x.get("start_id", 1)))
        normalized = []
        current_start = 1

        for index, chapter in enumerate(sorted_chapters):
            raw_end = int(chapter.get("end_id", current_start))
            if index < len(sorted_chapters) - 1:
                next_start = int(sorted_chapters[index + 1].get("start_id", raw_end + 1))
                final_end = min(raw_end, next_start - 1)
            else:
                final_end = raw_end

            if final_end < current_start:
                final_end = current_start
            final_end = min(final_end, total_lines)

            raw_key_ids = chapter.get("key_segment_ids", [])
            valid_key_ids = []
            if isinstance(raw_key_ids, list):
                for k_id in raw_key_ids:
                    try:
                        ik_id = int(k_id)
                        if 1 <= ik_id <= total_lines:
                            valid_key_ids.append(ik_id)
                    except (ValueError, TypeError):
                        pass
            if not valid_key_ids:
                valid_key_ids = [current_start]

            normalized.append(
                {
                    "title": str(chapter.get("title", "")).strip() or f"챕터 {index + 1}",
                    "type": str(chapter.get("type", "")).strip() or "Preaching_Main",
                    "summary": str(chapter.get("summary", "")).strip() or "요약 정보 없음",
                    "start_id": current_start,
                    "end_id": final_end,
                    "key_segment_ids": valid_key_ids,
                    "focus_point": str(chapter.get("focus_point", "")).strip(),
                }
            )

            current_start = final_end + 1
            if current_start > total_lines:
                break

        if normalized:
            normalized[-1]["end_id"] = total_lines

        return normalized

    def _map_coarse_chapters_to_original(self, coarse_chapters: list[dict], coarse_segments: list[dict], total_lines: int) -> list[dict]:
        """coarse ID 기반 챕터를 원본 세그먼트 ID 기준으로 복원합니다."""
        if not coarse_chapters or not coarse_segments:
            return []

        max_coarse_id = len(coarse_segments)
        mapped = []
        for chapter in coarse_chapters:
            s_coarse = max(1, min(int(chapter["start_id"]), max_coarse_id))
            e_coarse = max(1, min(int(chapter["end_id"]), max_coarse_id))
            if e_coarse < s_coarse:
                e_coarse = s_coarse

            left = coarse_segments[s_coarse - 1]
            right = coarse_segments[e_coarse - 1]
            mapped.append(
                {
                    "title": chapter["title"],
                    "type": chapter["type"],
                    "summary": chapter["summary"],
                    "start_id": int(left["source_start_id"]),
                    "end_id": int(right["source_end_id"]),
                }
            )

        return self._normalize_chapter_ranges(mapped, total_lines)

    def _is_conjunction_start(self, text: str) -> bool:
        if not text:
            return False
        stripped = text.strip()
        if not stripped:
            return False
        return bool(re.match(r"^(그리고|근데|그래서|하지만|그런데|또|또한|왜냐하면|즉)\b", stripped))

    def _chapter_duration(self, chapter: dict, segments: list[dict]) -> float:
        s_idx = max(0, min(int(chapter["start_id"]) - 1, len(segments) - 1))
        e_idx = max(0, min(int(chapter["end_id"]) - 1, len(segments) - 1))
        return max(0.0, float(segments[e_idx]["end"]) - float(segments[s_idx]["start"]))

    def _find_low_confidence_boundaries(self, chapters: list[dict], segments: list[dict]) -> list[dict]:
        """애매한 경계를 찾아 선택적 정밀화 후보를 만듭니다."""
        if len(chapters) < 2:
            return []

        picked = []
        for index in range(len(chapters) - 1):
            current = chapters[index]
            nxt = chapters[index + 1]
            score = 0

            current_duration = self._chapter_duration(current, segments)
            next_duration = self._chapter_duration(nxt, segments)
            if current_duration < 45.0 or next_duration < 45.0:
                score += 1
            if current.get("type") == nxt.get("type"):
                score += 1

            boundary_end_id = max(1, min(int(current["end_id"]), len(segments)))
            boundary_start_id = max(1, min(int(nxt["start_id"]), len(segments)))
            prev_text = str(segments[boundary_end_id - 1].get("text", "")).strip()
            next_text = str(segments[boundary_start_id - 1].get("text", "")).strip()
            if not prev_text.endswith((".", "!", "?", "다", "요")):
                score += 1
            if self._is_conjunction_start(next_text):
                score += 1

            if score < self.boundary_refine_min_score:
                continue

            left_limit = max(int(current["start_id"]), boundary_end_id - self.boundary_refine_context_span)
            right_limit = min(int(nxt["end_id"]) - 1, boundary_start_id + self.boundary_refine_context_span - 1)
            if right_limit <= left_limit:
                continue

            picked.append(
                {
                    "boundary_index": index,
                    "score": score,
                    "current_end_id": boundary_end_id,
                    "min_end_id": left_limit,
                    "max_end_id": right_limit,
                }
            )

        picked.sort(key=lambda x: x["score"], reverse=True)

        # 인접 경계가 동시에 바뀌면 충돌 가능성이 커서 하나만 선택
        selected = []
        for item in picked:
            if any(abs(item["boundary_index"] - existing["boundary_index"]) <= 1 for existing in selected):
                continue
            selected.append(item)
            if len(selected) >= self.boundary_refine_max:
                break

        selected.sort(key=lambda x: x["boundary_index"])
        return selected

    def _run_boundary_refinement(
        self,
        chapters: list[dict],
        segments: list[dict],
        profile,
        tracker: UsageTracker,
        status_callback: callable = None,
    ) -> tuple[list[dict], int]:
        """저신뢰 경계를 단일 추가 호출로 보정합니다."""
        if not self.boundary_refine_enabled:
            return chapters, 0

        candidates = self._find_low_confidence_boundaries(chapters, segments)
        if not candidates:
            return chapters, 0

        if status_callback:
            status_callback("경계가 애매한 구간을 선택적으로 보정 중...")

        boundary_payload = []
        for candidate in candidates:
            idx = candidate["boundary_index"]
            left_ch = chapters[idx]
            right_ch = chapters[idx + 1]
            min_id = candidate["min_end_id"]
            max_id = candidate["max_end_id"]
            context_lines = []
            for seg_id in range(min_id, max_id + 2):
                if 1 <= seg_id <= len(segments):
                    context_lines.append(f"{seg_id} | {segments[seg_id - 1]['text']}")
            boundary_payload.append(
                {
                    "boundary_index": idx,
                    "current_end_id": candidate["current_end_id"],
                    "allowed_min_end_id": min_id,
                    "allowed_max_end_id": max_id,
                    "left_chapter_title": left_ch.get("title", ""),
                    "left_chapter_type": left_ch.get("type", ""),
                    "right_chapter_title": right_ch.get("title", ""),
                    "right_chapter_type": right_ch.get("type", ""),
                    "context_lines": context_lines,
                }
            )

        refine_schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "boundary_index": {"type": "INTEGER"},
                    "new_end_id": {"type": "INTEGER"},
                },
                "required": ["boundary_index", "new_end_id"],
            },
        }

        prompt = (
            "다음은 영상 챕터 경계 보정 요청입니다.\n"
            "각 항목에 대해 문맥이 자연스럽게 이어지도록 boundary를 조정하세요.\n"
            "반드시 allowed_min_end_id~allowed_max_end_id 범위 내에서만 new_end_id를 선택하세요.\n"
            "출력은 JSON 배열만 반환하세요.\n\n"
            f"[분류 타입 참고]: {profile.summary_type_enum}\n"
            f"[경계 후보 데이터]:\n{json.dumps(boundary_payload, ensure_ascii=False)}"
        )

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self._get_model("planner"),
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=refine_schema,
                ),
            )
            tracker.update(response)
            suggestions = json.loads(response.text)
            if not isinstance(suggestions, list):
                return chapters, 0
        except Exception as e:
            logger = get_logger("summarizer")
            log_error_with_traceback(logger, "_run_boundary_refinement failed", e)
            return chapters, 0

        suggestion_map: dict[int, int] = {}
        for item in suggestions:
            idx = int(item.get("boundary_index", -1))
            if idx < 0 or idx >= len(chapters) - 1:
                continue

            candidate = next((c for c in candidates if c["boundary_index"] == idx), None)
            if not candidate:
                continue

            raw_end = int(item.get("new_end_id", candidate["current_end_id"]))
            clamped_end = max(candidate["min_end_id"], min(raw_end, candidate["max_end_id"]))
            suggestion_map[idx] = clamped_end

        if not suggestion_map:
            return chapters, 0

        patched = [dict(chapter) for chapter in chapters]
        applied = 0
        for idx in sorted(suggestion_map.keys()):
            new_end = suggestion_map[idx]
            if new_end == int(patched[idx]["end_id"]):
                continue

            patched[idx]["end_id"] = new_end
            patched[idx + 1]["start_id"] = new_end + 1
            applied += 1

        healed = self._normalize_chapter_ranges(patched, len(segments))
        return healed, applied

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

    def _create_blog_prompt(self, segments: list[dict], content_type: str = "sermon") -> str:
        """PTCF + XML 구조를 적용하여 블로그 포스트 생성을 위한 전용 템플릿 프롬프트를 생성합니다.

        Args:
            segments: 분석된 자막 세그먼트 리스트.
            content_type: 콘텐츠 타입 프로필 (sermon, streaming, informational).

        Returns:
            XML 구조 지시사항과 스크립트 데이터가 포함된 프롬프트 문자열.
        """
        profile = get_content_profile(content_type)
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_text = "\n".join(lines)

        return (
            f"<system_instructions>\n"
            f"<persona>\n"
            f"{profile.refine_system_instruction}\n"
            f"</persona>\n\n"
            f"<task>\n"
            f"제공된 대본(<script_data>)을 기반으로 독자의 몰입도를 극대화하는 블로그 포스트를 작성하세요.\n"
            f"</task>\n\n"
            f"<reasoning_process>\n"
            f"<thinking>\n"
            f"최종 포스트 작성 전, 본 장르({profile.content_type})에 최적화된 아래 3단계를 거치세요:\n"
            f"{profile.cot_thinking_guide}\n"
            f"</thinking>\n"
            f"</reasoning_process>\n\n"
            f"<rules>\n"
            f"1. 시간 순서대로 나열하지 말고 주제별로 재구성하세요.\n"
            f"2. 모든 주요 주장 및 문단 끝에는 대본의 출처 ID를 반드시 [[ID:숫자]] 형식으로 표기하세요.\n"
            f"   - 주의: 여러 개를 인용할 경우 [[ID:1]][[ID:2]]와 같이 개별 표기하세요.\n"
            f"3. 최종 출력물에는 HTML/XML 태그를 포함하지 말고, 순수 마크다운(Markdown) 문법만 사용하세요. (핵심 키워드는 **굵게**, 인용구는 > 사용)\n"
            f"</rules>\n\n"
            f"{profile.blog_few_shot_example}\n"
            f"</system_instructions>\n\n"
            f"<script_data>\n"
            f"{script_text}\n"
            f"</script_data>\n\n"
            f"<final_instruction>\n"
            f"<script_data>를 바탕으로 <system_instructions>의 규칙을 준수하여 작성하세요.\n"
            f"</final_instruction>"
        )

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def generate_blog_post(
        self, 
        segments: list[dict], 
        video_filename: str, 
        status_callback: callable = None,
        content_type: str = "sermon",
    ) -> dict:
        """Gemini를 사용하여 주제 중심의 블로그 포스트를 생성합니다. (Retry 적용)

        타임스탬프를 인용(`[[ID:숫자]]`) 형태로 받아 실제 시간으로 치환합니다.

        Args:
            segments: 분석된 자막 세그먼트 리스트.
            video_filename: 원본 영상 파일명.
            status_callback: 진행 상태 콜백.
            content_type: 콘텐츠 타입 프로필 (sermon, streaming, informational).

        Returns:
            블로그 포스트 내용과 메타데이터가 포함된 딕셔너리.
        """
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        if not segments:
            return {"error": "Empty segments"}

        print(f"--- [Summarizer] Generating Blog Post for {video_filename} ({content_type}) ---")
        if status_callback: status_callback("Gemini가 블로그 포스트를 작성 중입니다...")

        tracker = UsageTracker()
        prompt = self._create_blog_prompt(segments, content_type=content_type)

        try:
            client = genai.Client(api_key=self.api_key)
            
            response = client.models.generate_content(
                model=self._get_model("summarizer"),
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
            logger = get_logger("summarizer")
            if task_id:
                log_task_error(task_id, "generate_blog_post", e)
            else:
                log_error_with_traceback(logger, "Blog generation failed", e)
            print(f"[Error] Blog generation failed: {e}")
            raise e # retry가 잡을 수 있도록 예외 전파

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
        """설정된 Planner 모델을 사용하여 영상 전체의 블로그 구조를 설계합니다. (Retry 적용)
        기본적으로 `self._get_model("planner")`에 지정된 모델을 동적으로 사용합니다.

        Args:
            segments: 분석된 자막 세그먼트 리스트.
            video_filename: 원본 영상 파일명.
            status_callback: 진행 상태 콜백.

        Returns:
            블로그 챕터 구조(ID 범위 포함)가 담긴 딕셔너리.
        """
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        total_lines = len(segments)
        if total_lines == 0: return {"error": "Empty segments"}

        planner_model = self._get_model("planner")
        print(f"--- [Summarizer] Planning Blog Structure with {planner_model} ---")
        if status_callback: status_callback(f"{planner_model}가 블로그 구조를 설계 중입니다...")

        # 프롬프트 구성: 전체 스크립트를 전달 (Long Context 활용)
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
                            "type": {"type": "STRING", "description": "구간 성격 분류"},
                            "start_id": {"type": "INTEGER", "description": "시작 세그먼트 ID"},
                            "end_id": {"type": "INTEGER", "description": "종료 세그먼트 ID"},
                            "key_segment_ids": {
                                "type": "ARRAY",
                                "items": {"type": "INTEGER"},
                                "description": "이 챕터에서 가장 임팩트가 강한 핵심 자막 ID 목록 (최대 3개)"
                            },
                            "focus_point": {"type": "STRING", "description": "이 섹션에서 강조해야 할 핵심 논거 및 몰입 포인트 힌트"}
                        },
                        "required": ["title", "start_id", "end_id", "key_segment_ids", "focus_point"]
                    }
                }
            },
            "required": ["blog_title", "chapters"]
        }

        system_instruction = (
            "당신은 영상 콘텐츠를 고품질 블로그 포스트로 변환하는 전문 에디터입니다.\n"
            "제공된 전체 스크립트를 분석하여 독자가 몰입할 수 있는 논리적인 블로그 구조를 설계하세요.\n"
            "영상의 처음(ID:1)부터 끝까지 빈틈없이 챕터를 나누어야 합니다.\n"
            "각 챕터는 단순 요약이 아닌, 하나의 완결된 이야기를 구성할 수 있도록 ID 범위를 지정하세요."
        )

        try:
            client = genai.Client(api_key=self.api_key)
            # 동적으로 가져온 모델명 사용
            response = client.models.generate_content(
                model=self._get_model("planner"),
                contents=f"{system_instruction}\n\n[Full Script]:\n{script_text}",
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=response_schema
                )
            )
            
            plan = json.loads(response.text)
            return plan

        except Exception as e:
            logger = get_logger("summarizer")
            if task_id:
                log_task_error(task_id, "plan_blog_structure", e)
            else:
                log_error_with_traceback(logger, "Blog planning failed", e)
            print(f"[Error] Blog planning failed: {e}")
            raise e # retry 전파

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=20),
        reraise=True
    )
    def _call_gemini_with_retry(self, client, model, contents, config):
        """개별 API 호출 레벨의 재시도 유틸리티 (429 Rate Limit 대비)"""
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

    def summarize_map_reduce(
        self,
        segments: list[dict],
        video_filename: str,
        custom_title: str = None,
        status_callback: callable = None,
        content_type: str = "sermon",
    ) -> dict:
        """
        Gemini 3.1 Flash-Lite (Map) -> Gemini 3.5 Flash-Lite (Reduce) 기반 3단계 Map-Reduce 파이프라인.
        RPM 15 (4초/요청), TPM 250k 한도에 걸리지 않도록 Chunk 통합(6000자) 및 Rate-Limit Throttling 적용.
        """
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        total_lines = len(segments)
        if total_lines == 0:
            return {"error": "Empty segments"}

        print(f"--- [Summarizer] Running Map-Reduce Pipeline for {total_lines} lines ({video_filename}) ---")
        profile = get_content_profile(content_type)
        tracker = UsageTracker()

        # 1. Smart Chunking Engine 실행 (RPM 15 준수를 위해 target_chars를 6,000자로 상향 통합)
        if status_callback:
            status_callback("지능형 칭킹 엔진(Smart Chunking Engine) 실행 중...")
        chunks = build_smart_chunks(segments, target_chars=6000, overlap_chars=300)
        print(f"[Summarizer] Total segments: {total_lines} -> Smart Chunks created: {len(chunks)}")
        
        # 2. Stage 1: Map Phase (gemini-3.1-flash-lite) - Chunk별 정밀 노트 추출
        map_notes = []
        map_model = self._get_model("summarizer_map")
        client = genai.Client(api_key=self.api_key)
        
        for idx, chunk in enumerate(chunks, 1):
            if idx > 1:
                # RPM 15 제한 (60s / 15 = 4.0s) 준수를 위한 4.1초 슬롯 간격 보장
                time.sleep(4.1)

            if status_callback:
                status_callback(f"Stage 1 (Map): Chunk {idx}/{len(chunks)} 정밀 노트 추출 중... ({map_model})")
            
            chunk_lines = [f"{seg['id']} | [{self._format_time(seg['start'])} - {self._format_time(seg['end'])}] | {seg['text']}" for seg in chunk]
            chunk_script = "\n".join(chunk_lines)
            
            map_prompt = (
                f"당신은 영상 콘텐츠 정밀 분석가입니다. 아래 영상 자막 구간({idx}/{len(chunks)})을 분석하여 핵심 노트를 정리하세요.\n"
                f"[콘텐츠 분류]: {profile.content_type}\n\n"
                "**[작성 규칙]**\n"
                "1. 해당 구간에서 언급된 핵심 사실, 구체적 정보, 데이터/숫자, 핵심 발언/예화/인용구를 추출하세요.\n"
                "2. 서론/결론의 인사말이나 불필요한 감탄사는 완전히 배제하고, 마크다운 불릿 포인트(- ) 형태로 작성하세요.\n"
                "3. 반드시 주요 내용 옆에 해당 세그먼트 ID 또는 타임스탬프를 함께 언급하세요.\n\n"
                f"[Script Segment]:\n{chunk_script}"
            )
            
            response = self._call_gemini_with_retry(
                client=client,
                model=map_model,
                contents=map_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1
                )
            )
            tracker.update(response)
            map_notes.append(f"### [Chunk {idx} (ID: {chunk[0]['id']}~{chunk[-1]['id']}) Note]\n{response.text.strip()}")

        fused_notes_text = "\n\n".join(map_notes)

        # 3. Stage 2: Reduce Phase (gemini-3.5-flash-lite) - 전체 챕터 분할 및 완성형 블로그 포스팅 집필
        reduce_model = self._get_model("summarizer_reduce")
        time.sleep(4.1) # Reduce 호출 전에도 RPM 슬롯 보장

        if status_callback:
            status_callback(f"Stage 2 (Reduce): 전체 챕터 및 블로그 집필 중... ({reduce_model})")

        response_schema = {
            "type": "OBJECT",
            "properties": {
                "blog_title": {"type": "STRING", "description": "영상의 전체 흐름을 관통하는 대표 제목"},
                "chapters": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "title": {"type": "STRING", "description": "챕터 제목"},
                            "type": {"type": "STRING", "enum": profile.summary_type_enum, "description": "구간 성격 분류"},
                            "summary": {"type": "STRING", "description": "해당 챕터의 상세 핵심 요약"},
                            "start_id": {"type": "INTEGER", "description": "시작 세그먼트 ID (1부터 total_lines)"},
                            "end_id": {"type": "INTEGER", "description": "종료 세그먼트 ID (1부터 total_lines)"},
                            "key_segment_ids": {
                                "type": "ARRAY",
                                "items": {"type": "INTEGER"},
                                "description": f"이 챕터에서 임팩트 판단 기준({profile.impact_criteria})에 부합하는 가장 강력한 핵심 자막 ID (최대 3개)"
                            },
                            "focus_point": {"type": "STRING", "description": "이 챕터의 하이라이트 및 몰입 포인트 힌트"}
                        },
                        "required": ["title", "type", "summary", "start_id", "end_id", "key_segment_ids", "focus_point"]
                    }
                }
            },
            "required": ["blog_title", "chapters"]
        }

        reduce_prompt = (
            f"당신은 최고 권위의 미디어 에디터이자 콘텐츠 기획자입니다.\n"
            f"Stage 1에서 자막 구간별로 정밀 추출된 아래 노트들을 바탕으로, 중복 문장을 제거(Deduplication)하고 영상 전체 타임라인 챕터 및 핵심 요약을 JSON으로 작성하세요.\n\n"
            f"[콘텐츠 타입]: {profile.content_type}\n"
            f"[챕터 분류 타입 목록]: {profile.summary_type_enum}\n"
            f"[임팩트 판단 기준]: {profile.impact_criteria}\n"
            f"[전체 세그먼트 수]: 1 ~ {total_lines}\n\n"
            f"**[Reduce 지시사항]**\n"
            f"1. **chapters**: 영상을 1부터 {total_lines}까지 빈틈없이 타임라인 챕터로 구분하세요. {profile.summary_system_instruction}\n"
            f"2. **type**: 반드시 사전 정의된 분류 타입 목록({profile.summary_type_enum}) 중에서만 선택하세요.\n"
            f"3. **key_segment_ids**: 해당 챕터에서 가장 몰입도 높고 결정적인 핵심 자막 ID(1~{total_lines})를 최대 3개 선별하세요.\n"
            f"4. **summary & focus_point**: 핵심 내용, 구체적 예화, 데이터 포인트를 알차게 요약하고 숏츠 기획용 힌트를 명시하세요.\n\n"
            f"[Fused Map Notes]:\n{fused_notes_text}"
        )

        try:
            response = self._call_gemini_with_retry(
                client=client,
                model=reduce_model,
                contents=reduce_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=response_schema
                )
            )
            tracker.update(response)

            reduce_result = json.loads(response.text)
            parsed_chapters = reduce_result.get("chapters", [])
            final_chapters = self._normalize_chapter_ranges(parsed_chapters, total_lines)

            # 챕터 경계 보정 (Refinement)
            refined_count = 0
            final_chapters, refined_count = self._run_boundary_refinement(
                final_chapters,
                segments,
                profile,
                tracker,
                status_callback=status_callback
            )

            mapped_result = []
            for chap in final_chapters:
                s_idx = max(0, min(chap['start_id'] - 1, total_lines - 1))
                e_idx = max(0, min(chap['end_id'] - 1, total_lines - 1))
                start_time = segments[s_idx]['start']
                end_time = segments[e_idx]['end']
                clean_chapter_title = re.sub(r'\*\*|__', '', chap['title']).strip()

                mapped_result.append({
                    "title": clean_chapter_title,
                    "type": chap['type'],
                    "summary": chap['summary'],
                    "key_segment_ids": chap.get("key_segment_ids", [chap['start_id']]),
                    "focus_point": chap.get("focus_point", ""),
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
                "blog_title": reduce_result.get("blog_title", display_title),
                "blog_post": reduce_result.get("blog_post", ""),
                "content_type": profile.content_type,
                "profile_version": profile.profile_version,
                "analysis_meta": {
                    "mode": "map_reduce",
                    "chunks_count": len(chunks),
                    "boundary_refined_count": refined_count,
                },
                "total_chapters": len(mapped_result),
                "map_notes": map_notes,
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
            logger = get_logger("summarizer")
            log_error_with_traceback(logger, "Map-Reduce Summarization failed", e)
            print(f"[Error] Map-Reduce Summarization failed: {e}")
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
        status_callback: callable = None,
        content_type: str = "sermon",
    ) -> dict:
        """Gemini 3.1 Map -> Gemini 3.5 Reduce 3단계 파이프라인으로 자막을 분석하고 챕터 및 블로그를 생성합니다."""
        return self.summarize_map_reduce(
            segments=segments,
            video_filename=video_filename,
            custom_title=custom_title,
            status_callback=status_callback,
            content_type=content_type
        )
        
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
