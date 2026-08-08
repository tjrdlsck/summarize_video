import os
from dotenv import load_dotenv
load_dotenv()

from services.shorts_maker import ShortsMaker

def test_shorts_candidate_generation():
    maker = ShortsMaker()
    print(f"ShortsMaker API Key Present: {bool(maker.api_key)}")
    print(f"ShortsMaker Model: {maker._get_model()}")
    
    mock_transcripts = [
        {"id": 1, "start": 0.0, "end": 10.0, "text": "안녕하세요. 오늘 정말 재미있는 이야기를 하나 해드리겠습니다."},
        {"id": 2, "start": 10.0, "end": 25.0, "text": "옛날 어느 마을에 사시사철 웃음이 끊이지 않는 신기한 집이 하나 있었습니다."},
        {"id": 3, "start": 25.0, "end": 45.0, "text": "그 집 비밀은 바로 매일 아침마다 온 가족이 모여서 서로 재미있는 농담을 나누는 것이었죠."},
        {"id": 4, "start": 45.0, "end": 60.0, "text": "여러분도 오늘 하루 웃으면서 행복하게 보내시길 바랍니다! 감사합니다."}
    ]
    
    candidates = maker.make_shorts_candidates(
        transcripts=mock_transcripts,
        video_title="재미있는 사연",
        content_type="general",
        min_duration=20.0,
        max_duration=60.0
    )
    
    print(f"Generated Candidates Count: {len(candidates)}")
    for idx, c in enumerate(candidates, 1):
        print(f"  Candidate {idx}: Title='{c['title']}', Segments={c['segments']}")
    
    assert len(candidates) > 0, "Candidates should not be empty!"

if __name__ == "__main__":
    test_shorts_candidate_generation()
