import os
import torch
from services.audio_analyst import AudioAnalyst

def test_audio_analyst():
    """AudioAnalyst의 macOS 최적화 및 기본 분석 기능 테스트"""
    analyst = AudioAnalyst(output_dir="static/temp")
    
    # 1. 기기 가속 확인
    print(f"\n--- [Test] Device Check ---")
    print(f"Device being used: {analyst.device}")
    if torch.backends.mps.is_available():
        print("✅ Apple Silicon MPS is available and active.")
    else:
        print("⚠️ MPS not found, falling back to CPU.")

    # 2. 실제 파일 분석 테스트 (영상이 있는 경우)
    test_video = "static/videos/test_video.mp4"
    if os.path.exists(test_video):
        print(f"\n--- [Test] Full Analysis on {test_video} ---")
        meta = analyst.get_audio_metadata(test_video)
        
        print(f"Average Energy: {meta['average_energy']:.4f}")
        print(f"Peaks Found: {len(meta['peaks'])}")
        
        if meta['peaks']:
            print(f"First peak sample: {meta['peaks'][0]}")
            
        assert "energy_map" in meta
        assert "peaks" in meta
        print("✅ Audio metadata generation successful.")
    else:
        print(f"\n⚠️ Skip file test: {test_video} not found.")

if __name__ == "__main__":
    test_audio_analyst()