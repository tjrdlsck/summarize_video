import os
import re
import json
from typing import Any
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential # [Add] 재시도 로직 추가
from services.content_profiles import get_content_profile

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

            normalized.append(
                {
                    "title": str(chapter.get("title", "")).strip() or f"챕터 {index + 1}",
                    "type": str(chapter.get("type", "")).strip() or "Preaching_Main",
                    "summary": str(chapter.get("summary", "")).strip() or "요약 정보 없음",
                    "start_id": current_start,
                    "end_id": final_end,
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
        except Exception:
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

    def _create_blog_prompt(self, segments: list[dict]) -> str:
        """블로그 포스트 생성을 위한 프롬프트를 생성합니다.

        Args:
            segments: 분석된 자막 세그먼트 리스트.

        Returns:
            블로그 작성 지시사항과 스크립트 데이터가 포함된 프롬프트 문자열.
        """
        lines = [f"{seg['id']} | {seg['text']}" for seg in segments]
        script_text = "\n".join(lines)
        
        system_instruction = (
            "당신은 전문 지식을 독자에게 친절하고 논리적으로 가르치는 **세계 최고의 블로그 에디터**입니다.\n"
            "제공된 스크립트를 바탕으로 독자가 몰입할 수 있는 **스토리텔링형 블로그 포스트**를 작성하세요.\n"
            "**절대 시간 순서대로 단순히 나열하지 마세요.** 주제별로 내용을 재구성하여 독자의 지적 호기심을 충족시켜야 합니다.\n\n"
            "**[필수 작성 및 강조 규칙]**\n"
            "1. **정형화된 서사 구조**: 모든 주제 섹션은 아래 구성을 따라야 합니다.\n"
            "   - **도입부 (Introduction)**: 독자의 호기심을 자극하고 본문에서 다룰 핵심 질문을 던지는 문장으로 시작.\n"
            "   - **본문 (Body)**: 매력적인 소제목과 함께 내용을 논리적으로 상세히 설명.\n"
            "   - **맺음말 (Conclusion)**: 내용을 갈무리하며 독자에게 깊은 통찰이나 제언을 던지는 문장으로 마무리.\n"
            "2. **시각적 강조 (Highlighting)**:\n"
            "   - **핵심 키워드**: 문맥상 중요한 단어나 고유 명사는 반드시 `**굵게**` 표시하세요. (섹션당 5개 이상)\n"
            "   - **핵심 메시지**: 각 챕터나 섹션의 결론이 담긴 가장 중요한 문장 1~2개는 반드시 `<mark>핵심 문장</mark>` 태그로 감싸세요.\n"
            "3. **인용(Citation)**: 본문의 내용이 스크립트의 특정 부분에 기반할 때, 문장 끝에 반드시 `[[ID:숫자]]` 형식으로 출처를 남기세요.\n"
            "   - **주의**: 여러 개의 출처를 인용할 경우 반드시 `[[ID:1]][[ID:2]]`와 같이 개별적으로 작성하세요. `[[ID:1, 2]]`와 같이 쉼표로 연결하지 마세요.\n"
            "4. **어조**: 친절하고 전문적인 블로거의 말투(해요체)를 사용하세요."
        )
        return f"{system_instruction}\n\n[Script Data]:\n{script_text}"

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def generate_blog_post(
        self, 
        segments: list[dict], 
        video_filename: str, 
        status_callback: callable = None
    ) -> dict:
        """Gemini를 사용하여 주제 중심의 블로그 포스트를 생성합니다. (Retry 적용)

        타임스탬프를 인용(`[[ID:숫자]]`) 형태로 받아 실제 시간으로 치환합니다.

        Args:
            segments: 분석된 자막 세그먼트 리스트.
            video_filename: 원본 영상 파일명.
            status_callback: 진행 상태 콜백.

        Returns:
            블로그 포스트 내용과 메타데이터가 포함된 딕셔너리.
        """
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        if not segments:
            return {"error": "Empty segments"}

        print(f"--- [Summarizer] Generating Blog Post for {video_filename} ---")
        if status_callback: status_callback("Gemini가 블로그 포스트를 작성 중입니다...")

        tracker = UsageTracker()
        prompt = self._create_blog_prompt(segments)

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
            print(f"[Error] Blog planning failed: {e}")
            raise e # retry 전파

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
        """Gemini API의 JSON Mode를 사용하여 자막을 분석하고 챕터 정보를 생성합니다. (Retry 적용)

        Args:
            segments: 분석된 자막 세그먼트 리스트.
            video_filename: 원본 영상 파일명.
            custom_title: 사용자가 지정한 영상 제목 (선택 사항).
            status_callback: 진행 상태를 보고할 콜백 함수 (선택 사항).

        Returns:
            요약 결과, 챕터 리스트, 토큰 사용량 등이 포함된 결과 딕셔너리.
        """
        if not self.api_key:
            return {"error": "GOOGLE_API_KEY is missing in .env"}
        
        total_lines = len(segments)
        if total_lines == 0: return {"error": "Empty segments"}

        print(f"--- [Summarizer] Analyzing {total_lines} lines with Gemini (JSON Mode) ---")
        if status_callback: status_callback("Gemini가 내용을 정밀 분석 중 (JSON Mode)...")

        profile = get_content_profile(content_type)
        tracker = UsageTracker()

        use_coarse = self.coarse_enabled and total_lines >= self.coarse_trigger_lines
        analysis_segments: list[dict[str, Any]] = segments
        coarse_segments: list[dict[str, Any]] = []
        compression_meta = {
            "mode": "direct",
            "original_segments": total_lines,
            "analysis_segments": total_lines,
            "compression_ratio": 1.0,
        }

        if use_coarse:
            coarse_segments = self._build_coarse_segments(segments)
            if len(coarse_segments) >= 2:
                analysis_segments = coarse_segments
                compression_meta = {
                    "mode": "coarse",
                    "original_segments": total_lines,
                    "analysis_segments": len(coarse_segments),
                    "compression_ratio": round(total_lines / max(1, len(coarse_segments)), 3),
                }

        # 프롬프트 구성 (direct 또는 coarse)
        lines = [f"{seg['id']} | {seg['text']}" for seg in analysis_segments]
        script_text = "\n".join(lines)
        
        # JSON 스키마 정의
        response_schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "내용을 직관적으로 알 수 있는 챕터 제목 (예: '예화: 탕자의 비유')"},
                    "type": {
                        "type": "STRING", 
                        "enum": profile.summary_type_enum,
                        "description": "편집 작업을 위한 구간 성격 분류"
                    },
                    "summary": {"type": "STRING", "description": "편집자가 내용을 파악할 수 있는 핵심 내용 요약"},
                    "start_id": {"type": "INTEGER", "description": "시작 세그먼트 ID"},
                    "end_id": {"type": "INTEGER", "description": "종료 세그먼트 ID"}
                },
                "required": ["title", "type", "summary", "start_id", "end_id"]
            }
        }

        system_instruction = profile.summary_system_instruction

        try:
            client = genai.Client(api_key=self.api_key)
            
            response = client.models.generate_content(
                model=self._get_model("summarizer"),
                contents=f"{system_instruction}\n\n[Script]:\n{script_text}",
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json", 
                    response_schema=response_schema       
                )
            )
            tracker.update(response)
            
            # JSON 파싱
            parsed_chapters = json.loads(response.text)
            final_chapters = self._normalize_chapter_ranges(parsed_chapters, len(analysis_segments))
            if use_coarse and analysis_segments is coarse_segments:
                final_chapters = self._map_coarse_chapters_to_original(final_chapters, coarse_segments, total_lines)

            refined_count = 0
            final_chapters, refined_count = self._run_boundary_refinement(
                final_chapters,
                segments,
                profile,
                tracker,
                status_callback=status_callback,
            )
            
            # ID -> Time 매핑 & 챕터 제목 정제
            mapped_result = []
            for chap in final_chapters:
                s_idx = max(0, min(chap['start_id'] - 1, total_lines - 1))
                e_idx = max(0, min(chap['end_id'] - 1, total_lines - 1))
                
                start_time = segments[s_idx]['start']
                end_time = segments[e_idx]['end']
                
                # 챕터 제목 내 불필요한 마크다운(**, __) 제거
                clean_chapter_title = re.sub(r'\*\*|__', '', chap['title']).strip()
                
                mapped_result.append({
                    "title": clean_chapter_title,
                    "type": chap['type'],
                    "summary": chap['summary'],
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
                "content_type": profile.content_type,
                "profile_version": profile.profile_version,
                "analysis_meta": {
                    **compression_meta,
                    "boundary_refined_count": refined_count,
                },
                "total_chapters": len(mapped_result),
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
            print(f"[Error] Summarization failed: {e}")
            raise e # retry 전파
        
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
