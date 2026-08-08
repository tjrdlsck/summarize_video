import asyncio
import os
import sys
import time
import pytest
from services.clipper import VideoClipper

pytestmark = pytest.mark.anyio

async def test_real_video_merge():
    clipper = VideoClipper()
    
    input_video = os.path.abspath("static/videos/역대_최고!_극찬_쏟아진_올림픽_광고.mp4")
    if not os.path.exists(input_video):
        print(f"Test video not found at: {input_video}")
        return
    
    print(f"Found input video: {input_video} ({os.path.getsize(input_video)} bytes)")
    
    segments = [
        {"start": 5.0, "end": 15.0},
        {"start": 20.0, "end": 30.0}
    ]
    
    def progress_callback(percent):
        print(f"[Merge Progress] {percent}%")
        
    output_filename = "test_merged_output.mp4"
    
    print("--- Starting merge_segments Execution ---")
    start_time = time.time()
    try:
        res = await clipper.merge_segments(
            input_path=input_video,
            segments=segments,
            output_filename=output_filename,
            sub_input_path=None,
            progress_callback=progress_callback
        )
        elapsed = time.time() - start_time
        print(f"--- Merge Completed Successfully in {elapsed:.2f}s ---")
        print(f"Output result: {res}")
        if os.path.exists(res["video"]):
            print(f"Output video size: {os.path.getsize(res['video'])} bytes")
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"--- Merge Failed after {elapsed:.2f}s with Error: {e} ---")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_real_video_merge())
