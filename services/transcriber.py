import os
import subprocess
import re
import json
import torch
import mlx_whisper
import soundfile as sf
import numpy as np
import stable_whisper

class VideoTranscriber:
    """
    영상 파일에서 오디오를 추출하고, Whisper 모델을 통해 텍스트로 변환(STT)하는 클래스.
    VAD(Voice Activity Detection)를 통해 환각(Hallucination)을 제거하고,
    Web UI에서 사용하기 쉬운 JSON 구조와 다운로드용 SRT 파일을 생성합니다.
    """

    def __init__(self, output_dir="static/results"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Whisper 모델 설정 (Apple Silicon 최적화 모델 사용)
        # self.model_path = "mlx-community/whisper-large-v3-mlx-4bit"
        self.model_path = "mlx-community/whisper-large-v3-turbo-q4"

    def _convert_to_16k_wav(self, input_path):
        """FFmpeg를 사용하여 영상을 16kHz Mono WAV로 변환"""
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_wav = os.path.join(self.output_dir, f"{base_name}_temp.wav")

        cmd = [
            "ffmpeg", "-i", input_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-vn",
            output_wav, "-y", "-hide_banner", "-loglevel", "error"
        ]
        
        try:
            subprocess.run(cmd, check=True)
            return output_wav
        except subprocess.CalledProcessError as e:
            print(f"[Error] FFmpeg conversion failed: {e}")
            return None

    def _get_vad_timestamps(self, audio_path):
        """Silero VAD를 사용하여 실제 음성이 있는 구간(초 단위)을 추출"""
        try:
            model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                          model='silero_vad',
                                          force_reload=False,
                                          trust_repo=True)
            (get_speech_timestamps, _, _, _, _) = utils
            
            audio_data, sr = sf.read(audio_path)
            wav = torch.from_numpy(audio_data).float()
            
            # 차원 및 샘플링 레이트 보정
            if wav.ndim > 1: wav = wav.mean(dim=0, keepdim=True) # Stereo -> Mono
            if wav.ndim == 1: wav = wav.unsqueeze(0)
            
            speech_timestamps = get_speech_timestamps(wav, model, threshold=0.5)
            
            # Sample -> Seconds 변환
            segments = []
            for item in speech_timestamps:
                segments.append((item['start'] / 16000, item['end'] / 16000))
            
            return segments
        except Exception as e:
            print(f"[Warning] VAD execution failed: {e}")
            return []

    def _filter_hallucinations(self, whisper_segments, vad_segments):
        """Whisper 세그먼트가 VAD 구간과 겹치지 않으면(환각이면) 제거"""
        if not vad_segments: return whisper_segments
        
        valid_segments = []
        for seg in whisper_segments:
            w_start, w_end = seg['start'], seg['end']
            duration = w_end - w_start
            if duration <= 0: continue

            # 교집합(Overlap) 시간 계산
            overlap_sum = 0.0
            for v_start, v_end in vad_segments:
                o_start = max(w_start, v_start)
                o_end = min(w_end, v_end)
                if o_end > o_start:
                    overlap_sum += (o_end - o_start)
            
            # 기준: 음성 비율이 20% 이상이거나, 절대 음성 길이가 2.0초 이상이면 통과
            if (overlap_sum / duration >= 0.2) or (overlap_sum >= 2.0):
                valid_segments.append(seg)
                
        return valid_segments

    def _clean_text(self, text):
        """반복되는 텍스트 및 무의미한 자모 제거"""
        if not text: return ""
        # 1. 유명한 환각 문구 제거
        for bad in ["아 아 아", "ㅋㅋㅋ", "으으으"]:
            text = text.replace(bad, "")
        # 2. 반복 문자 축소 (예: ㅋㅋㅋㅋㅋㅋ -> ㅋㅋ)
        text = re.sub(r'(.)\1{3,}', r'\1\1', text)
        # 3. 반복 단어 축소
        text = re.sub(r'(\S+)(?:\s+\1){3,}', r'\1 \1', text)
        return text.strip()

    def transcribe(self, video_path, status_callback=None):
        """
        [Main Pipeline] 영상 -> 오디오 -> VAD -> Whisper(Word-Level) -> Filter -> Regroup(Stable-Whisper) -> Save
        """
        print(f"--- [Transcriber] Start processing: {video_path} ---")
        
        # 1. 오디오 변환
        if status_callback:
            status_callback("오디오 추출 및 변환 중...")
            
        wav_path = self._convert_to_16k_wav(video_path)
        if not wav_path: raise Exception("Audio conversion failed")

        # 2. VAD 실행
        if status_callback:
            status_callback("음성 구간 탐지(VAD) 실행 중...")
            
        vad_segments = self._get_vad_timestamps(wav_path)
        
        # 3. Whisper 실행 (Word Timestamps 활성화)
        print(" -> Running Whisper Inference (with word timestamps)...")
        if status_callback:
            status_callback("AI가 스크립트를 작성하는 중... (시간이 걸립니다)")
            
        # [Modified] word_timestamps=True 추가
        output = mlx_whisper.transcribe(
            wav_path,
            path_or_hf_repo=self.model_path,
            language="ko",
            verbose=True,
            word_timestamps=True 
        )
        
        # 4. 필터링 (VAD 기반 환각 제거)
        if status_callback:
            status_callback("환각 필터링 및 데이터 정제 중...")
            
        raw_segments = output.get('segments', [])
        clean_segments = self._filter_hallucinations(raw_segments, vad_segments)

        # [New] Stable-Whisper 후처리 파이프라인 시작
        if status_callback:
            status_callback("자막 가독성 최적화(Regrouping) 중...")

        # 4-1. 텍스트 1차 정제 (특수문자/반복 제거)
        # Stable-Whisper에 넣기 전에 텍스트를 깨끗하게 만듭니다.
        for seg in clean_segments:
            if 'text' in seg:
                seg['text'] = self._clean_text(seg['text'])

        # 4-2. MLX 결과를 Stable-Whisper 객체로 변환
        # Stable-Whisper는 text, segments, language 키가 있는 dict를 받습니다.
        composition = {
            "text": " ".join([s['text'] for s in clean_segments]),
            "segments": clean_segments,
            "language": output.get("language", "ko")
        }
        result = stable_whisper.WhisperResult(composition)

        # 4-3. 스마트 분할 (Split) 적용
        # max_chars: 한 줄당 최대 글자 수 (25자 내외 추천)
        # max_words: 한 줄당 최대 단어 수 (무제한=None)
        # split_by_gap: 0.5초 이상 침묵이 있으면 줄바꿈
        result.split_by_length(max_chars=25, max_words=None)
        result.split_by_gap(0.5)

        # 5. 파일 저장
        if status_callback:
            status_callback("결과 파일 저장 중...")

        base_name = os.path.splitext(os.path.basename(video_path))[0]
        
        # (1) SRT 저장 (Stable-Whisper 내장 함수 사용)
        srt_filename = f"{base_name}.srt"
        srt_path = os.path.join(self.output_dir, srt_filename)
        result.to_srt_vtt(srt_path, word_level=False) # word_level=False여야 문장 단위 자막이 됨
        
        # (2) VTT 저장
        vtt_filename = f"{base_name}.vtt"
        vtt_path = os.path.join(self.output_dir, vtt_filename)
        result.to_srt_vtt(vtt_path, word_level=False)

        # (3) JSON 저장 및 반환 데이터 구성
        # Stable-Whisper 객체를 다시 리스트 형태로 변환
        final_data = []
        for idx, seg in enumerate(result.segments, 1):
            final_data.append({
                "id": idx,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip()
            })

        json_filename = f"{base_name}_transcript.json"
        json_path = os.path.join(self.output_dir, json_filename)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)

        # 임시 WAV 삭제
        if os.path.exists(wav_path):
            os.remove(wav_path)

        print(f"--- [Transcriber] Done. Processed with Stable-Whisper. Saved to {self.output_dir} ---")
        
        return {
            "status": "success",
            "srt_path": srt_path,
            "vtt_path": vtt_path,
            "json_path": json_path,
            "segments": final_data 
        }

# --- [Module Test] ---
if __name__ == "__main__":
    # Test execution
    tr = VideoTranscriber(output_dir="../static/results")
    # Make sure a test file exists at this path
    test_video = "../static/videos/test_video.mp4" 
    if os.path.exists(test_video):
        res = tr.transcribe(test_video)
        print(f"Result segments count: {len(res['segments'])}")