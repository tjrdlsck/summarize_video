import os
import re
import json
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import types

# --- [Class 0] Usage Tracker (New!) ---
class UsageTracker:
    """
    API 호출 횟수와 토큰 사용량을 추적하고 리포트를 출력하는 클래스
    """
    def __init__(self):
        self.call_count = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def update(self, response):
        """API 응답 객체에서 메타데이터를 추출하여 누적합니다."""
        if not response or not hasattr(response, 'usage_metadata'):
            return
        
        usage = response.usage_metadata
        self.call_count += 1
        # API 버전에 따라 속성명이 다를 수 있어 안전하게 처리
        self.input_tokens += getattr(usage, 'prompt_token_count', 0)
        self.output_tokens += getattr(usage, 'candidates_token_count', 0)

    def print_report(self):
        """최종 사용량 리포트를 출력합니다."""
        total_tokens = self.input_tokens + self.output_tokens
        print("\n" + "="*40)
        print(" 📊 [AI Resource Usage Report]")
        print("-" * 40)
        print(f" • API Calls      : {self.call_count} times")
        print(f" • Input Tokens   : {self.input_tokens:,} tokens (Context)")
        print(f" • Output Tokens  : {self.output_tokens:,} tokens (Generation)")
        print(f" • TOTAL TOKENS   : {total_tokens:,} tokens")
        print("="*40 + "\n")

# --- [Module 1] SRT Parser & Indexer (변경 없음) ---
class SRTProcessor:
    """
    SRT 파일을 읽어 '인덱스 맵'을 생성하고, LLM 입력용 '경량 텍스트'를 만듭니다.
    """
    def __init__(self, srt_path):
        self.srt_path = srt_path
        self.segments = []     # {id, start_time, end_time, text} 리스트
        self.total_lines = 0   # 전체 라인 수
        self._load_srt()

    def _load_srt(self):
        if not os.path.exists(self.srt_path):
            raise FileNotFoundError(f"SRT Not Found: {self.srt_path}")
        
        with open(self.srt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 정규식: (번호) -> (시간) -> (텍스트)
        pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\Z)', re.DOTALL)
        matches = pattern.findall(content)

        # 1-based index로 데이터를 정렬 및 저장
        for idx, match in enumerate(matches, start=1):
            self.segments.append({
                "id": idx,  
                "start": match[1],
                "end": match[2],
                "text": match[3].replace('\n', ' ').strip()
            })
        self.total_lines = len(self.segments)
        print(f"--- [SRT Loaded] Total Lines: {self.total_lines} ---")

    def get_prompt_text(self):
        """
        LLM에게 던져줄 'ID | Text' 형태의 경량화된 텍스트를 반환합니다.
        """
        lines = []
        for seg in self.segments:
            lines.append(f"{seg['id']} | {seg['text']}")
        return "\n".join(lines)

    def get_segment_by_id(self, target_id):
        if 1 <= target_id <= self.total_lines:
            return self.segments[target_id - 1]
        return None

# --- [Module 2] Intelligent Parser & Healer (Update) ---
class ChapterHealer:
    """
    LLM의 마크다운 출력을 파싱하고, 누락된 구간(Gap)을 자동으로 메워주는 클래스
    (상세 요약이 여러 줄로 나와도 처리할 수 있도록 정규식 강화됨)
    """
    @staticmethod
    def parse_markdown_output(llm_output):
        # [변경점] Regex 로직 강화
        # 기존: 요약이 줄바꿈(\n)을 만나면 끝남.
        # 변경: '요약:' 이후부터 '구간:' 키워드가 나오기 직전까지 모두 캡처 (Lookahead 사용)
        regex = re.compile(
            r'##\s*(.+?)\n'                          # Group 1: Title
            r'\s*-\s*요약:\s*(.+?)(?=\n\s*-\s*구간:)' # Group 2: Summary (구간 키워드 전까지)
            r'\s*-\s*구간:\s*\[(\d+)\s*-\s*(\d+)\]',  # Group 3, 4: Start, End
            re.DOTALL  # 줄바꿈이 포함된 텍스트도 매칭 허용
        )
        
        chapters = []
        matches = regex.findall(llm_output)
        
        for m in matches:
            chapters.append({
                "title": m[0].strip(),
                "summary": m[1].strip(), # 앞뒤 공백 제거
                "start_id": int(m[2]),
                "end_id": int(m[3])
            })
        return chapters

    @staticmethod
    def heal_chapters(raw_chapters, total_lines):
        # (기존 로직과 동일)
        if not raw_chapters: return []
        raw_chapters.sort(key=lambda x: x['start_id'])

        healed_chapters = []
        current_start = 1
        
        for i in range(len(raw_chapters)):
            chapter = raw_chapters[i]
            title = chapter['title']
            summary = chapter['summary']
            
            if i == len(raw_chapters) - 1:
                final_end = total_lines
            else:
                next_chap_start_raw = raw_chapters[i+1]['start_id']
                final_end = max(current_start, next_chap_start_raw - 1)

            if current_start > final_end: final_end = current_start
            final_end = min(final_end, total_lines)

            healed_chapters.append({
                "title": title,
                "summary": summary,
                "start_id": current_start,
                "end_id": final_end
            })

            current_start = final_end + 1
            if current_start > total_lines: break
                
        return healed_chapters
# --- [Module 3] Google Gen AI API Client (Tracker Integrated) ---
def generate_chapters_api(script_text, api_key, tracker, model_name="gemini-2.5-flash"):
    """
    tracker: UsageTracker 객체를 전달받아 사용량을 기록함
    긴 영상 처리를 위해 프롬프트가 강화된 버전
    """
    print(f"--- [Cloud API] Connecting to Google Gen AI ({model_name})... ---")
    
    try:
        client = genai.Client(api_key=api_key)

        # 시스템 프롬프트 (긴 영상 최적화)
        system_instruction = (
            "당신은 영상 콘텐츠 분석가입니다. 대본(Script)을 정밀 분석하여 논리적인 '챕터(Chapter)'로 구분하세요.\n"
            "각 문장 앞에는 `ID |` 형식으로 번호가 매겨져 있습니다.\n\n"
            "반드시 아래 **Markdown 형식**으로만 출력해야 합니다.\n"
            "## 챕터 제목\n"
            "- 요약: (육하원칙에 의거한 상세 서술)\n"
            "- 구간: [시작ID - 종료ID]\n\n"
            "**[필수 준수 가이드라인]**\n"
            "1. **상세한 요약:** 단순 한 줄 요약 금지. 누가, 왜, 무엇을 했는지 구체적으로 서술하세요.\n"
            "2. **정확한 매핑:** 문맥이 바뀌는 지점의 ID를 정확히 포착하여 구간을 설정하세요.\n"
            "3. **전체 커버리지 (매우 중요):**\n"
            "   - **반드시 영상의 처음부터 끝까지 빠짐없이 균등한 비중으로 챕터를 나누세요.**\n"
            "   - 스크립트가 길더라도 중간 내용을 건너뛰거나, 뒤쪽 내용만 자세히 다루면 안 됩니다.\n"
            "   - 시작 ID(1번)부터 마지막 ID까지 빈틈없이 분석하세요."
        )

        one_shot_example = (
            "Example Input:\n"
            "1 | 오늘 점심 뭐 먹지?\n ... (중략) ... \n500 | 잘 먹었습니다.\n\n"
            "Example Output:\n"
            "## 점심 메뉴 고민\n"
            "- 요약: 화자들이 점심 메뉴를 두고 한식과 중식 사이에서 갈등하다가 투표를 제안함.\n"
            "- 구간: [1 - 250]\n\n"
            "## 식사 및 마무리\n"
            "- 요약: 결정된 메뉴를 주문하여 식사를 마치고, 만족스러운 평을 남기며 대화를 종료함.\n"
            "- 구간: [251 - 500]"
        )

        full_prompt = (
            f"{system_instruction}\n\n"
            f"{one_shot_example}\n\n"
            f"[Target Script Data]:\n{script_text}\n\n"
            "**다시 한번 강조합니다:** 스크립트의 **처음(ID:1)부터 끝(Last ID)까지** 모든 내용이 포함되도록 균등하게 챕터를 나누세요."
        )

        # API 호출
        response = client.models.generate_content(
            model=model_name,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=8192
            )
        )
        
        # [핵심] 트래커 업데이트
        tracker.update(response)
        
        # 실시간 로그 (선택 사항)
        if response.usage_metadata:
            in_t = response.usage_metadata.prompt_token_count
            out_t = response.usage_metadata.candidates_token_count
            print(f"   -> [Usage Log] Input: {in_t:,}, Output: {out_t:,}")

        return response.text

    except Exception as e:
        print(f"[Error] API Call Failed: {e}")
        if "429" in str(e):
            print(" -> [Tip] 할당량 초과. 잠시 후 다시 시도하세요.")
        return None
    
# --- [Main Controller] ---
def process_video_chapters(srt_path, output_json_path):
    # 0. 환경 변수 및 트래커 초기화
    load_dotenv()
    API_KEY = os.getenv("GOOGLE_API_KEY")
    
    if not API_KEY:
        print("[Error] .env 파일에 'GOOGLE_API_KEY'가 없습니다.")
        return

    tracker = UsageTracker() # 트래커 인스턴스 생성

    # 1. SRT 로드
    processor = SRTProcessor(srt_path)
    if processor.total_lines == 0:
        print("Error: Empty SRT file.")
        return

    print(f"--- [Target] Processing {processor.total_lines} lines ---")

    # 2. API 실행 (긴 영상 대응 모델 사용 + 트래커 전달)
    target_model = "gemini-2.5-flash-lite" 
    print(f"--- [Strategy] Using '{target_model}' with Usage Tracking ---")

    prompt_text = processor.get_prompt_text()
    
    # tracker 인자 전달
    raw_markdown = generate_chapters_api(prompt_text, API_KEY, tracker, model_name=target_model)
    
    if not raw_markdown:
        print("Error: LLM generation failed.")
        return

    # 3. 파싱 및 오토 힐링
    print("\n--- [Post-Processing] Parsing & Auto-Healing ---")
    raw_chapters = ChapterHealer.parse_markdown_output(raw_markdown)
    
    if not raw_chapters:
        print("[Warning] Parsing failed. Creating fallback chapter.")
        healed_chapters = [{
            "title": "전체 영상",
            "summary": "자동 챕터 구분 실패 (전체)",
            "start_id": 1,
            "end_id": processor.total_lines
        }]
    else:
        healed_chapters = ChapterHealer.heal_chapters(raw_chapters, processor.total_lines)

    # 4. JSON 데이터 조립 및 무결성 검증
    final_data = {
        "video_source": os.path.basename(srt_path),
        "total_chapters": len(healed_chapters),
        "chapters": []
    }

    total_mapped_count = 0

    for idx, chap in enumerate(healed_chapters, 1):
        s_id = max(1, chap['start_id'])
        e_id = min(processor.total_lines, chap['end_id'])
        
        current_count = (e_id - s_id) + 1
        total_mapped_count += current_count

        chapter_segments = []
        for seg_id in range(s_id, e_id + 1):
            seg = processor.get_segment_by_id(seg_id)
            if seg:
                chapter_segments.append({
                    "time": seg['start'],
                    "text": seg['text']
                })

        start_time = processor.get_segment_by_id(s_id)['start']
        end_time = processor.get_segment_by_id(e_id)['end']

        final_data["chapters"].append({
            "chapter_no": idx,
            "title": chap['title'],
            "summary": chap['summary'],
            "timeline": {
                "start": start_time,
                "end": end_time
            },
            "contents": chapter_segments
        })
        
        print(f" -> Chapter {idx}: {chap['title']} ({current_count} lines) [{s_id}~{e_id}]")

    # 5. 검증 리포트 출력
    print("-" * 60)
    print(f"[Integrity Check] Total SRT Lines: {processor.total_lines}")
    print(f"[Integrity Check] Mapped Lines   : {total_mapped_count}")
    
    if processor.total_lines == total_mapped_count:
        print("[Result] ✅ PERFECT MATCH! 모든 문장이 빠짐없이 포함되었습니다.")
    else:
        diff = processor.total_lines - total_mapped_count
        print(f"[Result] ❌ WARNING! {diff} lines mismatch.")
    print("-" * 60)

    # 6. 저장 및 토큰 사용량 출력
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=4)
    
    print(f"SUCCESS: Structured JSON saved to '{output_json_path}'")
    
    # [마지막] 토큰 사용량 리포트 출력
    tracker.print_report()

if __name__ == "__main__":
    INPUT_SRT = "video/test3.srt"
    OUTPUT_JSON = "video/test3_chapters.json"
    
    if os.path.exists(INPUT_SRT):
        process_video_chapters(INPUT_SRT, OUTPUT_JSON)
    else:
        print(f"File not found: {INPUT_SRT}")