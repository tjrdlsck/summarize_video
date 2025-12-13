import os
import time
from services.clipper import VideoClipper

def test_vbr_optimization():
    print("=== Apple Silicon FFmpeg VBR (Quality-based) Test ===")
    
    # 1. 파일 준비
    video_dir = "static/videos"
    if not os.path.exists(video_dir):
        print(f"[Error] '{video_dir}' directory not found.")
        return

    files = [f for f in os.listdir(video_dir) if f.endswith(".mp4")]
    if not files:
        print(f"[Error] No MP4 files found.")
        return

    target_video = os.path.join(video_dir, files[0])
    print(f"-> Target Video: {target_video}")

    # 2. 자르기 실행 (10초 구간)
    # 10초 정도로 길게 잘라야 VBR 효과(용량 절감)를 체감하기 좋습니다.
    clipper = VideoClipper(temp_dir="static/temp")
    
    print("\n-> Processing 10s clip with '-q:v 65' (Quality Based VBR)...")
    start_time = time.time()
    
    try:
        output_path = clipper.cut_video(
            target_video, 
            start_sec=10, # 영상의 10초 지점부터
            end_sec=20,   # 20초 지점까지
            output_filename="test_vbr_clip.mp4"
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        # 3. 결과 리포트
        if os.path.exists(output_path):
            file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            video_duration = 10.0 # 우리가 10초를 잘랐으므로
            
            # 실제 적용된 평균 비트레이트 역산 (Video Only 추정치)
            # Size(MB) * 8(bits) / Time(sec)
            estimated_bitrate_mbps = (file_size_mb * 8) / video_duration
            
            print(f"\n[Success] Optimization Complete!")
            print(f" - Output Path: {output_path}")
            print(f" - Time Taken:  {duration:.4f} sec")
            print(f" - File Size:   {file_size_mb:.2f} MB")
            print(f" - Est. Bitrate: {estimated_bitrate_mbps:.2f} Mbps")
            
            print("\n[Analysis]")
            if estimated_bitrate_mbps < 6.0:
                print(" -> Good! The file is smaller than the previous fixed 6Mbps setting.")
                print("    Since we used '-q:v 65', quality remains high but space is saved.")
            else:
                print(" -> High Bitrate detected. The scene might be complex, so high bitrate is justified for quality.")
                
        else:
            print("[Fail] File was not created.")

    except Exception as e:
        print(f"[Fail] {e}")

if __name__ == "__main__":
    test_vbr_optimization()