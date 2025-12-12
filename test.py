import os
import subprocess
import sys
import torch
import mlx_whisper
import numpy as np
import torchaudio
import re

# --- [Module 1] 미디어 변환 (FFmpeg Wrapper) ---
def check_ffmpeg():
    """시스템에 FFmpeg가 설치되어 있는지 확인합니다."""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

def convert_to_16k_wav(input_path):
    """
    입력된 미디어 파일(mp4 등)을 Whisper와 VAD에 최적화된 포맷으로 변환합니다.
    Target: WAV, 16000Hz, Mono, PCM 16-bit
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # 확장자를 제외한 파일명 추출
    base_name = os.path.splitext(input_path)[0]
    output_path = f"{base_name}_converted.wav"
    
    print(f"--- [Step 0] Converting '{input_path}' to 16kHz WAV... ---")

    # FFmpeg 명령어 구성
    # -i: 입력 파일
    # -ar 16000: Audio Rate (샘플링 레이트)를 16kHz로 리샘플링
    # -ac 1: Audio Channel을 1 (Mono)로 병합 (Whisper는 모노 처리함)
    # -c:a pcm_s16le: 코덱을 PCM 16-bit Little Endian으로 설정 (비압축 표준)
    # -y: 출력 파일이 이미 존재하면 덮어쓰기
    # -vn: 비디오 스트림 제거 (오디오만 추출)
    command = [
        "ffmpeg",
        "-i", input_path,
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        "-vn", 
        output_path,
        "-y",
        "-hide_banner",   # 불필요한 정보 출력 숨김
        "-loglevel", "error" # 에러만 출력
    ]

    try:
        subprocess.run(command, check=True)
        print(f"-> Conversion Successful: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"Error during FFmpeg conversion: {e}")
        return None

# --- [Module 2] VAD (Voice Activity Detection) ---

# --- [Module 2] VAD (Voice Activity Detection) - Returns Timestamps ---
def get_speech_timestamps_silero(audio_path, threshold=0.5):
    """
    Silero VAD를 사용하여 음성 구간의 타임스탬프(초 단위)를 추출합니다.
    Return: [(start_sec, end_sec), (start_sec, end_sec), ...]
    """
    print("--- [Step 1] Running VAD & Extracting Timestamps ---")
    
    import soundfile as sf
    import torch
    
    try:
        # 1. 모델 로드
        model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                      model='silero_vad',
                                      force_reload=False,
                                      trust_repo=True)
        (get_speech_timestamps, _, _, _, _) = utils

        # 2. 오디오 로드
        audio_data, sr = sf.read(audio_path)
        wav = torch.from_numpy(audio_data).float()
        
        # 차원 정리
        if wav.ndim > 1:
            wav = wav.transpose(0, 1)
            if wav.shape[0] > 1:
                wav = wav.mean(dim=0, keepdim=True)
        else:
            wav = wav.unsqueeze(0)

        # 샘플링 레이트 보정
        if sr != 16000:
            import torchaudio.transforms as T
            resampler = T.Resample(orig_freq=sr, new_freq=16000)
            wav = resampler(wav)

        # 3. 타임스탬프 추출 (단위: Samples)
        speech_timestamps_samples = get_speech_timestamps(
            wav, 
            model, 
            threshold=threshold,
            min_speech_duration_ms=250,
            min_silence_duration_ms=500
        )
        
        # 4. Samples -> Seconds 변환
        vad_segments_sec = []
        for section in speech_timestamps_samples:
            start_sec = section['start'] / 16000
            end_sec = section['end'] / 16000
            vad_segments_sec.append((start_sec, end_sec))
            
        print(f"-> VAD detected {len(vad_segments_sec)} valid speech segments.")
        return vad_segments_sec

    except Exception as e:
        print(f"[Warning] VAD failed: {e}")
        return [] # 에러나면 빈 리스트 반환 (검증 포기)

# --- [Module 2.5] VAD Overlap Filter (The Logical Cutter) ---
def filter_hallucinations_by_vad(whisper_segments, vad_segments, threshold_sec=2.0):
    """
    Whisper가 생성한 세그먼트와 실제 VAD 음성 구간을 비교하여,
    '소리는 없는데 텍스트만 긴' 환각 구간을 제거합니다.
    
    Args:
        whisper_segments (list): Whisper 결과의 'segments' 리스트
        vad_segments (list): VAD가 감지한 [(start, end), ...] 리스트
        threshold_sec (float): 허용 오차 (초). (기본 2초)
                               Whisper 구간이 실제 음성보다 2초 이상 길면 환각으로 간주.
    """
    if not vad_segments:
        return whisper_segments # VAD 정보 없으면 필터링 스킵

    valid_segments = []
    dropped_count = 0
    
    print(f"\n--- [Filter] Checking {len(whisper_segments)} segments against VAD ---")

    for seg in whisper_segments:
        w_start = seg['start']
        w_end = seg['end']
        w_dur = w_end - w_start
        w_text = seg['text']

        # 해당 Whisper 구간 내에 존재하는 '실제 음성 시간'의 합을 계산
        actual_speech_dur = 0.0
        
        for v_start, v_end in vad_segments:
            # 두 구간의 교집합(Overlap) 구하기
            overlap_start = max(w_start, v_start)
            overlap_end = min(w_end, v_end)
            
            if overlap_end > overlap_start:
                actual_speech_dur += (overlap_end - overlap_start)
        
        # [핵심 판별 로직]
        # "생성된 텍스트 시간" > "실제 음성 시간" + "임계값(2초)"
        # 예: Whisper는 30초라고 주장하는데, 실제 음성은 1초밖에 없다? -> 탈락
        if w_dur > (actual_speech_dur + threshold_sec):
            print(f" -> Dropped Hallucination: [{w_start:.2f}~{w_end:.2f}] (Speech: {actual_speech_dur:.2f}s) '{w_text.strip()[:20]}...'")
            dropped_count += 1
            continue # 리스트에 추가하지 않음 (삭제)
            
        valid_segments.append(seg)

    print(f"-> Removed {dropped_count} segments based on VAD duration check.")
    return valid_segments

# --- [Module 2.5] 텍스트 후처리 (청소부) ---
def clean_repetitive_text(text):
    """
    Whisper의 고질적인 무한 루프(ㅋㅋㅋ, 아아아, 노노노)와 환각을
    정규표현식으로 강력하게 제거하는 전처리기 Ver 2.0
    """
    if not text:
        return ""

    # 1. [유명한 환각 문구 제거]
    # Whisper가 침묵이나 잡음 구간에서 자주 뱉는 헛소리들입니다.
    # 'I\'m so hot'은 숨소리가 섞일 때 자주 나오는 대표적인 환각입니다.
    hallucination_blacklist = [
        "아 아 아 ", "ㅋ ㅋ ㅋ ㅋ ", "ㅋㅋㅋㅋㅋㅋ", "으 으 으 으" 
    ]
    
    for bad_phrase in hallucination_blacklist:
        if bad_phrase in text:
            # 해당 문구가 포함된 줄을 아예 날리거나, 문구만 지움
            text = text.replace(bad_phrase, "")

    # 2. [초성/단일 문자 무한 반복 압축]
    # 예: "ㅋㅋㅋㅋㅋㅋㅋㅋ" -> "ㅋㅋ"
    # (설명: 어떤 글자(.)가 3번 이상({3,}) 연속되면, 그 글자를 2번(\1\1)만 남김)
    text = re.sub(r'(.)\1{3,}', r'\1\1', text)

    # 3. [단어+공백 무한 반복 압축]
    # 예: "아 아 아 아 아" -> "아 아"
    # 예: "노노노노노" (띄어쓰기 없는 경우도 일부 커버)
    # (설명: 단어(\S+)와 공백이 3번 이상 반복되면 2번만 남김)
    text = re.sub(r'(\S+)(?:\s+\1){3,}', r'\1 \1', text)

    # 4. [특수 패턴 제거] 
    # "노노노..." 처럼 한 글자짜리 단어가 붙어서 길게 나오는 경우
    # 한국어에서 5글자 이상 동일한 음절이 반복되는 단어는 거의 없음
    def collapse_repeats(match):
        g = match.group(0)
        if len(g) > 4: # 4글자 넘게 똑같은게 반복되면
            return g[:2] # 2글자로 줄임
        return g
    
    # 5. [자음/모음 단독 반복 삭제]
    # ㅋㅋㅋ, ㅎㅎㅎ, ㅠㅠㅠ 처럼 자음/모음만 3자 이상 연속되면 삭제하거나 줄임
    # 여기서는 문장 전체가 자음 범벅이면 아예 지워버리는 전략
    if re.fullmatch(r'[ㄱ-ㅎㅏ-ㅣ\s?!.,]+', text):
        return "" # 내용이 온통 ㅋㅋㅋ 뿐이면 빈 문자열 반환 (삭제)

    # 한글 자모 또는 완성형 글자가 연속되는 경우를 찾아서 줄임 함수 적용
    text = re.sub(r'([가-힣])\1{2,}', collapse_repeats, text)

    return text.strip()

# --- [Module 3] Whisper Inference (Final Integration) ---
# --- [Module 3] Whisper Inference (Final Integration) - 주석 해제 수정본 ---
def transcribe_video(video_path, initial_prompt):
    
    # 1. FFmpeg 변환
    if not check_ffmpeg(): return
    wav_path = convert_to_16k_wav(video_path)
    if not wav_path: return

    # 2. VAD 실행 (타임스탬프 획득)
    vad_segments = get_speech_timestamps_silero(wav_path)
    
    if not vad_segments:
        print("[Info] No speech detected by VAD. Skipping.")
        return ""

    MODEL_PATH = "mlx-community/whisper-large-v3-mlx-4bit"
    print(f"--- [Step 2] Transcribing with {MODEL_PATH} ---")

    try:
        # 3. Whisper 실행
        output = mlx_whisper.transcribe(
            wav_path,
            path_or_hf_repo=MODEL_PATH,
            language="ko",
            initial_prompt=initial_prompt,
            verbose=True, 
            temperature=0.0,
            condition_on_previous_text=False, 
            no_speech_threshold=0.6,          
        )
        
        raw_segments = output.get('segments', [])
        
        # 4. [1차 필터] VAD 기반 시간 대조 (소리 없는 환각 제거)
        clean_segments = filter_hallucinations_by_vad(raw_segments, vad_segments, threshold_sec=2.0)
        
        # 5. [2차 필터] 텍스트 기반 패턴 제거 (웃음소리 반복 제거) - 핵심!
        final_text_parts = []
        for seg in clean_segments:
            raw_text = seg['text'].strip()
            
            # [수정됨] 주석(#)을 제거하고 함수를 확실히 호출합니다.
            cleaned_text = clean_repetitive_text(raw_text)
            
            # 정제 후 내용이 빈 문자열이 아니면 추가
            if cleaned_text:
                final_text_parts.append(cleaned_text)
            else:
                print(f" -> Removed purely repetitive segment: '{raw_text[:20]}...'")
            
        final_text = "\n".join(final_text_parts)

        print("\n" + "="*50)
        print(" [Verified Result] ")
        print("="*50)
        print(final_text)
        
        return final_text

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

# --- [Main Execution] ---
if __name__ == "__main__":
    # 1. 입력 파일 설정 (여기에 MP4 파일 경로를 넣으세요)
    # 예: "lecture_video.mp4"
    INPUT_VIDEO = "video/test_video1.mp4" 
    
    # 2. 문맥 프롬프트 설정
    CONTEXT_PROMPT = (
        "게임하는 영상입니다."
    )

    if os.path.exists(INPUT_VIDEO):
        transcribe_video(INPUT_VIDEO, CONTEXT_PROMPT)
    else:
        print(f"File '{INPUT_VIDEO}' not found. Please provide a valid video file.")
        
        # 테스트용 파일 생성 (없을 경우를 대비한 더미 코드)
        # 실제 사용 시에는 무시하셔도 됩니다.
        print("\n[Tip] 테스트할 MP4 파일이 없다면, 아래 명령어로 샘플을 다운로드해 보세요:")
        print(f"curl -o {INPUT_VIDEO} https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4")