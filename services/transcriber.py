import os
import subprocess
import re
import json
import torch
import mlx_whisper
import soundfile as sf
import numpy as np

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

    def _format_srt_time(self, seconds):
        """초 -> HH:MM:SS,mmm 포맷 변환"""
        ms = int((seconds - int(seconds)) * 1000)
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    def _format_srt_time(self, seconds):
        """초 -> HH:MM:SS,mmm 포맷 변환 (SRT용)"""
        ms = int((seconds - int(seconds)) * 1000)
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    # [New] WebVTT용 시간 포맷팅 메서드 추가 (위치는 _format_srt_time 바로 아래 권장)
    def _format_vtt_time(self, seconds):
        """초 -> HH:MM:SS.mmm 포맷 변환 (WebVTT 표준, 마침표 사용)"""
        ms = int((seconds - int(seconds)) * 1000)
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02}:{m:02}:{s:02}.{ms:03}"

    def transcribe(self, video_path, status_callback=None):
        """
        [Main Pipeline] 영상 -> 오디오 -> VAD -> Whisper -> Filter -> Clean -> Save & Return
        
        Args:
            video_path (str): 분석할 영상 파일 경로
            status_callback (func, optional): (message: str) -> None 형태의 상태 보고 콜백
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
        
        # 3. Whisper 실행
        print(" -> Running Whisper Inference...")
        if status_callback:
            status_callback("AI가 스크립트를 작성하는 중... (시간이 걸립니다)")
            
        output = mlx_whisper.transcribe(
            wav_path,
            path_or_hf_repo=self.model_path,
            language="ko",
            verbose=True
        )
        
        # 4. 필터링 및 정제
        if status_callback:
            status_callback("환각 필터링 및 데이터 정제 중...")
            
        raw_segments = output.get('segments', [])
        clean_segments = self._filter_hallucinations(raw_segments, vad_segments)
        
        final_data = []
        srt_content = []
        vtt_content = ["WEBVTT\n"]  # [New] VTT 헤더 추가
        
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        
        for idx, seg in enumerate(clean_segments, 1):
            text = self._clean_text(seg['text'])
            if not text: continue
            
            start = seg['start']
            end = seg['end']
            
            # JSON용 데이터 구조
            final_data.append({
                "id": idx,
                "start": start,
                "end": end,
                "text": text
            })
            
            # SRT용 포맷팅
            s_time_srt = self._format_srt_time(start)
            e_time_srt = self._format_srt_time(end)
            srt_content.append(f"{idx}\n{s_time_srt} --> {e_time_srt}\n{text}\n")

            # [New] VTT용 포맷팅
            s_time_vtt = self._format_vtt_time(start)
            e_time_vtt = self._format_vtt_time(end)
            vtt_content.append(f"{idx}\n{s_time_vtt} --> {e_time_vtt}\n{text}\n")

        # 5. 파일 저장
        if status_callback:
            status_callback("결과 파일 저장 중...")

        # (1) SRT 저장
        srt_filename = f"{base_name}.srt"
        srt_path = os.path.join(self.output_dir, srt_filename)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_content))
        
        # (2) [New] VTT 저장 (웹 플레이어 자막용)
        vtt_filename = f"{base_name}.vtt"
        vtt_path = os.path.join(self.output_dir, vtt_filename)
        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(vtt_content))

        # (3) JSON 저장 (프론트엔드 로딩 최적화용)
        json_filename = f"{base_name}_transcript.json"
        json_path = os.path.join(self.output_dir, json_filename)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)

        # 임시 WAV 삭제
        if os.path.exists(wav_path):
            os.remove(wav_path)

        print(f"--- [Transcriber] Done. Saved SRT & VTT to {self.output_dir} ---")
        
        return {
            "status": "success",
            "srt_path": srt_path,
            "vtt_path": vtt_path,       # [New] 결과에 VTT 경로 포함
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