import os
import subprocess
import pytest
import re
from services.clipper import VideoClipper

@pytest.mark.anyio
async def test_multiple_exports_audio():
    """
    영상 처음 구간(start_time = 0.0)과 영상 중간 구간(start_time > 5.0)을 자르는 경우
    두 클립 모두 오디오 스트림이 유실되거나 음소거(-91dB)되지 않고
    정상적으로 소리가 포함되어 인코딩되는지 검증합니다.
    """
    video_dir = "static/videos"
    video_files = [f for f in os.listdir(video_dir) if f.endswith(".mp4")]
    assert len(video_files) > 0, "테스트용 MP4 비디오 파일이 static/videos 디렉토리에 필요합니다."
    
    # 테스트에 사용할 크기가 작은 영상 선택
    test_video = None
    for vf in video_files:
        path = os.path.join(video_dir, vf)
        if "Yonhapnews" in vf: # 소리가 풍부하고 확실한 뉴스 영상 우선 선택
            test_video = path
            break
            
    if not test_video:
        for vf in video_files:
            path = os.path.join(video_dir, vf)
            if os.path.getsize(path) < 50 * 1024 * 1024:
                test_video = path
                break
                
    if not test_video:
        test_video = os.path.join(video_dir, video_files[0])
        
    print(f"테스트 타깃 비디오: {test_video}")
    
    clipper = VideoClipper(temp_dir="static/temp_test")
    
    # 1. 처음 구간 자르기 (0.0초 ~ 5.0초)
    out_1 = await clipper.cut_video(test_video, 0.0, 5.0, output_filename="clip_test_start.mp4")
    assert os.path.exists(out_1), "처음 구간 잘라내기 클립이 생성되지 않았습니다."
    
    # 2. 중간 구간 자르기 (5.0초 ~ 10.0초)
    out_2 = await clipper.cut_video(test_video, 5.0, 10.0, output_filename="clip_test_middle.mp4")
    assert os.path.exists(out_2), "중간 구간 잘라내기 클립이 생성되지 않았습니다."
    
    # 오디오 스트림 확인 함수 (ffprobe 사용)
    def has_audio_stream(file_path):
        cmd = [
            "ffprobe", 
            "-v", "error", 
            "-select_streams", "a", 
            "-show_entries", "stream=codec_name", 
            "-of", "csv=p=0", 
            file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return len(result.stdout.strip()) > 0

    # 볼륨 정보 파싱 함수 (ffmpeg volumedetect 사용)
    def parse_max_volume(file_path):
        cmd = [
            "ffmpeg",
            "-i", file_path,
            "-filter:a", "volumedetect",
            "-f", "null",
            "-"
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # max_volume 파싱
        max_vol = -91.0
        for line in result.stderr.split("\n"):
            if "max_volume:" in line:
                match = re.search(r"max_volume:\s*([\-\d\.]+)\s*dB", line)
                if match:
                    max_vol = float(match.group(1))
                    break
        return max_vol

    has_audio_1 = has_audio_stream(out_1)
    has_audio_2 = has_audio_stream(out_2)
    
    vol_1 = parse_max_volume(out_1)
    vol_2 = parse_max_volume(out_2)
    
    print(f"[검증 결과] 처음 구간 클립 오디오 스트림 존재: {has_audio_1}, 최대 볼륨: {vol_1} dB")
    print(f"[검증 결과] 중간 구간 클립 오디오 스트림 존재: {has_audio_2}, 최대 볼륨: {vol_2} dB")
    
    # 정리
    if os.path.exists(out_1):
        os.remove(out_1)
    if os.path.exists(out_2):
        os.remove(out_2)
        
    assert has_audio_1, "처음 구간 클립에 오디오 스트림이 유실되었습니다."
    assert has_audio_2, "중간 구간 클립에 오디오 스트림이 유실되었습니다."
    
    # 오디오 볼륨이 완벽한 무음(-91.0 dB 부근)이 아닌 실제 오디오 값이 보존되었는지 검증
    # -60.0 dB 보다 크면 실제 음성 데이터가 유의미하게 포함된 것으로 간주합니다.
    assert vol_1 > -60.0, f"처음 구간 클립이 음소거 상태입니다. (Volume: {vol_1} dB)"
    assert vol_2 > -60.0, f"중간 구간 클립이 음소거 상태입니다. (Volume: {vol_2} dB)"
