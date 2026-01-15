import os
import json
import traceback
from services.summarizer import VideoSummarizer

def test_summarizer_modes():
    """리팩토링된 Summarizer가 다양한 모드를 지원하는지 테스트"""
    summ = VideoSummarizer(output_dir="static/results")
    
    dummy_segments = [
        {"id": 1, "start": 0.0, "end": 5.0, "text": "반갑습니다. 오늘은 웃긴 영상을 분석해볼게요."},
        {"id": 2, "start": 5.0, "end": 10.0, "text": "갑자기 사람이 넘어집니다. ㅋㅋㅋ"},
        {"id": 3, "start": 10.0, "end": 15.0, "text": "정말 웃기네요. 구독 부탁드립니다."}
    ]

    # 1. Sermon 모드 테스트
    print("\n--- Testing SERMON Mode ---")
    try:
        res_sermon = summ.summarize(dummy_segments, "test_sermon.mp4", mode="sermon")
        print(f"Sermon Result Mode: {{res_sermon.get('mode')}}")
        assert res_sermon.get('mode') == "sermon"
    except Exception:
        print("Sermon Test Error:")
        traceback.print_exc()

    # 2. Humor 모드 테스트
    print("\n--- Testing HUMOR Mode ---")
    try:
        res_humor = summ.summarize(dummy_segments, "test_humor.mp4", mode="humor")
        print(f"Humor Result Mode: {{res_humor.get('mode')}}")
        assert res_humor.get('mode') == "humor"
        if res_humor.get('chapters'):
            print(f"First chapter sample: {{res_humor['chapters'][0].keys()}}")
    except Exception:
        print("Humor Test Error:")
        traceback.print_exc()

if __name__ == "__main__":
    if not os.getenv("GOOGLE_API_KEY"):
        print("Skip test: GOOGLE_API_KEY not found in environment.")
    else:
        test_summarizer_modes()
