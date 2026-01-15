import os
import subprocess
import numpy as np
import librosa
import torch
import json
from scipy.signal import medfilt

class AudioAnalyst:
    """
    MacOS(Apple Silicon) GPU 가속을 활용한 오디오 이벤트 분석 엔진.
    영상에서 소리 에너지를 추출하고 주요 리액션(웃음, 정적 등)을 감지합니다.
    """
    def __init__(self, output_dir="static/temp"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Apple Silicon GPU(MPS) 사용 여부 확인
        self.device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")
        print(f"[AudioAnalyst] Using device: {self.device}")

    def extract_audio(self, video_path: str) -> str:
        """영상에서 분석용 16kHz Mono WAV 파일을 추출합니다."""
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        wav_path = os.path.join(self.output_dir, f"{base_name}_analyst.wav")
        
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vn", "-ac", "1", "-ar", "16000",
            "-y", wav_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return wav_path

    def analyze_energy(self, wav_path: str, frame_duration: float = 0.5) -> list[dict]:
        """
        오디오의 RMS 에너지를 분석하여 시간대별 텐션을 측정합니다.
        
        Args:
            wav_path: 분석할 오디오 파일 경로.
            frame_duration: 분석 단위 시간 (초).
            
        Returns:
            시간별 에너지 데이터 리스트.
        """
        y, sr = librosa.load(wav_path, sr=16000)
        
        # 0.5초 단위로 RMS 계산
        hop_length = int(sr * frame_duration)
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        
        # 정규화 (0~1)
        if rms.max() > 0:
            rms_norm = (rms - rms.min()) / (rms.max() - rms.min())
        else:
            rms_norm = rms

        energy_map = []
        for i, val in enumerate(rms_norm):
            energy_map.append({
                "time": i * frame_duration,
                "energy": float(val),
                "is_silence": bool(val < 0.05) # 임계값 미만은 정적 처리
            })
            
        return energy_map

    def detect_events(self, wav_path: str) -> list[dict]:
        """
        [TODO] 사전 학습된 SED 모델을 사용하여 웃음, 박수 등을 감지합니다.
        현재는 기초 에너지 분석 기반의 'High Energy' 구간만 추출합니다.
        """
        # Phase 2 고도화 작업에서 실제 Torch 모델 로드 예정
        energy_map = self.analyze_energy(wav_path)
        events = []
        
        for item in energy_map:
            if item['energy'] > 0.8:
                events.append({
                    "start": item['time'],
                    "end": item['time'] + 0.5,
                    "label": "Peak_Energy",
                    "score": item['energy']
                })
        
        return events

    def get_audio_metadata(self, video_path: str) -> dict:
        """영상에 대한 통합 오디오 분석 결과를 반환합니다."""
        wav_path = None
        try:
            wav_path = self.extract_audio(video_path)
            energy_map = self.analyze_energy(wav_path)
            peaks = self.detect_events(wav_path)
            
            return {
                "energy_map": energy_map,
                "peaks": peaks,
                "average_energy": float(np.mean([e['energy'] for e in energy_map]))
            }
        finally:
            if wav_path and os.path.exists(wav_path):
                os.remove(wav_path)

if __name__ == "__main__":
    # 간단한 모듈 테스트
    analyst = AudioAnalyst()
    # test_video.mp4가 있을 경우 실행
    test_path = "static/videos/test_video.mp4"
    if os.path.exists(test_path):
        meta = analyst.get_audio_metadata(test_path)
        print(f"Analysis complete. Average energy: {meta['average_energy']}")
