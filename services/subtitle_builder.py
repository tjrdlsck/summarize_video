import json
import os
import re

class SubtitleBuilder:
    """
    _transcript.json (Master Data)를 기반으로 다양한 포맷의 자막을 생성하는 클래스.
    단어(Word) 단위의 타임스탬프를 활용하여, 사용자가 원하는 길이(글자 수)와 줄 수에 맞춰
    자막을 동적으로 재구성(Reflow)할 수 있습니다.
    """

    def __init__(self, json_path=None, data=None):
        if json_path:
            with open(json_path, 'r', encoding='utf-8') as f:
                self.segments = json.load(f)
        elif data:
            self.segments = data
        else:
            raise ValueError("Either json_path or data must be provided")

    def _format_timestamp_srt(self, seconds):
        """초(float)를 SRT 타임스탬프 포맷(HH:MM:SS,mmm)으로 변환"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

    def _format_timestamp_vtt(self, seconds):
        """초(float)를 VTT 타임스탬프 포맷(HH:MM:SS.mmm)으로 변환"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"

    def _reflow_segments(self, max_chars=20, max_lines=2, remove_punctuation=True):
        """
        단어 단위 정보를 바탕으로, 지정된 글자 수(max_chars)와 줄 수(max_lines)를 고려하여
        자막 블록을 재구성합니다.
        
        Args:
            max_chars (int): 한 줄당 최대 글자 수
            max_lines (int): 한 화면에 보여질 최대 줄 수
            remove_punctuation (bool): 문장 부호(.,!?) 제거 여부
        """
        new_segments = []
        
        for seg in self.segments:
            words = seg.get('words', [])
            
            # Case A: 단어 정보가 없는 경우 (Fallback)
            if not words:
                text = seg['text']
                if remove_punctuation:
                    text = re.sub(r'[.,?!]', '', text)
                new_segments.append({
                    "start": seg['start'],
                    "end": seg['end'],
                    "text": text
                })
                continue

            # Case B: 단어 정보가 있는 경우 (Main Logic)
            current_block_words = [] 
            current_lines = []       
            current_line_text = ""   
            
            for i, word_info in enumerate(words):
                word_text = word_info['word']
                
                # 문장 부호 제거
                if remove_punctuation:
                    word_text = re.sub(r'[.,?!]', '', word_text)
                
                # 문장 부호를 제거해서 빈 문자열이 된 경우(예: "." 만 있는 단어) 무시
                if not word_text.strip():
                    continue

                word_len = len(word_text)
                
                # 현재 줄에 단어를 추가했을 때 길이 체크
                pad = 1 if len(current_line_text) > 0 else 0
                predicted_len = len(current_line_text) + pad + word_len
                
                if predicted_len > max_chars:
                    if current_line_text:
                        current_lines.append(current_line_text)
                    
                    current_line_text = word_text 
                    
                    if len(current_lines) >= max_lines:
                        # **블록 Flush**
                        if current_block_words:
                            start_time = current_block_words[0]['start']
                            end_time = current_block_words[-1]['end']
                            
                            new_segments.append({
                                "start": start_time,
                                "end": end_time,
                                "text": "\n".join(current_lines)
                            })
                        
                        current_lines = []
                        current_block_words = []
                else:
                    if current_line_text:
                        current_line_text += " " + word_text
                    else:
                        current_line_text = word_text
                
                current_block_words.append(word_info)
            
            # 루프 종료 후 남은 내용 처리
            if current_line_text:
                current_lines.append(current_line_text)
            
            if current_lines and current_block_words:
                start_time = current_block_words[0]['start']
                end_time = current_block_words[-1]['end']
                new_segments.append({
                    "start": start_time,
                    "end": end_time,
                    "text": "\n".join(current_lines)
                })
        
        return new_segments

    def to_srt(self, max_chars=20, max_lines=2, remove_punctuation=True):
        """SRT 포맷 문자열 반환"""
        segments_to_process = self._reflow_segments(max_chars, max_lines, remove_punctuation)
        
        output = []
        for idx, seg in enumerate(segments_to_process, 1):
            start = self._format_timestamp_srt(seg['start'])
            end = self._format_timestamp_srt(seg['end'])
            text = seg['text'].strip()
            
            output.append(f"{idx}\n{start} --> {end}\n{text}\n")
            
        return "\n".join(output)

    def to_vtt(self, max_chars=20, max_lines=2, remove_punctuation=True):
        """WEBVTT 포맷 문자열 반환"""
        segments_to_process = self._reflow_segments(max_chars, max_lines, remove_punctuation)
        
        output = ["WEBVTT\n"]
        for seg in segments_to_process:
            start = self._format_timestamp_vtt(seg['start'])
            end = self._format_timestamp_vtt(seg['end'])
            text = seg['text'].strip()
            
            output.append(f"{start} --> {end}\n{text}\n")
            
        return "\n".join(output)

    def to_txt(self):
        """순수 텍스트 반환"""
        # TXT는 줄바꿈 없이 그냥 공백으로 이어서 쭉 쓰는 게 나을 수도 있고,
        # 원본 세그먼트대로 줄바꿈 하는 게 나을 수도 있음. 여기서는 원본 세그먼트 기준.
        return "\n".join([seg['text'].replace('\n', ' ').strip() for seg in self.segments])

# --- Test Block ---
if __name__ == "__main__":
    # Dummy data for testing
    dummy_data = [
        {
            "id": 1,
            "start": 0.0,
            "end": 5.0,
            "text": "안녕하세요 반갑습니다 오늘 날씨가 참 좋네요 그래요 맞아요",
            "words": [
                {"word": "안녕하세요", "start": 0.0, "end": 0.8},
                {"word": "반갑습니다", "start": 0.9, "end": 1.5},
                {"word": "오늘", "start": 1.6, "end": 1.8},
                {"word": "날씨가", "start": 1.9, "end": 2.1},
                {"word": "참", "start": 2.2, "end": 2.3},
                {"word": "좋네요", "start": 2.3, "end": 2.5},
                {"word": "그래요", "start": 2.6, "end": 3.0},
                {"word": "맞아요", "start": 3.1, "end": 3.5}
            ]
        }
    ]
    
    builder = SubtitleBuilder(data=dummy_data)
    print("--- SRT (Max 10 chars, 2 lines) ---")
    print(builder.to_srt(max_chars=10, max_lines=2))
    
    print("\n--- SRT (Max 10 chars, 1 line) ---")
    print(builder.to_srt(max_chars=10, max_lines=1))