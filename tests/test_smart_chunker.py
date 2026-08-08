import unittest
from services.summarizer import build_smart_chunks

class TestSmartChunker(unittest.TestCase):
    def setUp(self):
        # 가상의 세그먼트 데이터 20개 생성 (각 약 150자)
        self.segments = []
        for i in range(1, 21):
            text = f"이것은 테스트용 세그먼트 {i}번 문장입니다. 영상의 내용이 계속해서 전개되고 있으며 중요 설명이 포함되어 있습니다."
            if i % 4 == 0:
                text += " 마침표로 끝납니다."
            start_time = (i - 1) * 10.0
            end_time = i * 10.0
            # 5번 세그먼트 후 2초 이상의 무음 갭 부여
            if i == 5:
                end_time = start_time + 8.0 # 다음 시작과 2초 gap
            self.segments.append({
                "id": i,
                "start": start_time,
                "end": end_time,
                "text": text
            })

    def test_build_smart_chunks_creation(self):
        chunks = build_smart_chunks(self.segments, target_chars=500, overlap_chars=100)
        self.assertGreater(len(chunks), 1, "Chunk가 2개 이상으로 분할되어야 합니다.")
        
        # 첫 번째 Chunk와 두 번째 Chunk 사이의 Overlap 확인
        chunk1_ids = [s["id"] for s in chunks[0]]
        chunk2_ids = [s["id"] for s in chunks[1]]
        
        overlap_ids = set(chunk1_ids).intersection(set(chunk2_ids))
        self.assertGreater(len(overlap_ids), 0, "Chunk 간 Sliding Window Overlap이 존재해야 합니다.")

    def test_empty_segments(self):
        chunks = build_smart_chunks([], target_chars=500, overlap_chars=100)
        self.assertEqual(chunks, [], "빈 입력에 대해서는 빈 리스트를 반환해야 합니다.")

if __name__ == "__main__":
    unittest.main()
