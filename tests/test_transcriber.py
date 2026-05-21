import multiprocessing
import sys
import pytest
from services.transcriber import run_whisper_worker

def test_whisper_worker_import_preservation():
    """
    tests that run_whisper_worker can resolve faster_whisper 
    when invoked with parent_sys_path.
    """
    queue = multiprocessing.Queue()
    # We pass empty/invalid paths to invoke the worker.
    # If the import fails, it will queue an error message "No module named 'faster_whisper'".
    # If the import succeeds, it might raise another exception (like file not found)
    # but not the ModuleNotFoundError for faster_whisper.
    p = multiprocessing.Process(
        target=run_whisper_worker,
        args=("invalid_wav.wav", "invalid_model", queue, 10, "prompt", sys.path)
    )
    p.start()
    p.join(timeout=10)
    
    if p.is_alive():
        p.terminate()
        p.join()
        
    assert not queue.empty(), "Worker did not return any status message"
    msg = queue.get()
    
    # We inspect the error message.
    # It should not contain "No module named 'faster_whisper'"
    assert msg["status"] == "error"
    error_msg = msg["message"]
    print(f"Worker output message: {error_msg}")
    assert "No module named 'faster_whisper'" not in error_msg
    assert "No module named" not in error_msg

def test_transcriber_vad_correction(tmp_path):
    """
    VAD 텐서 차원 보정 및 환각 필터링 로직이 정상 작동하는지 테스트합니다.
    """
    import numpy as np
    import soundfile as sf
    from services.transcriber import VideoTranscriber
    
    transcriber = VideoTranscriber(output_dir=str(tmp_path))
    
    # 1. 2채널(스테레오) 가짜 오디오 데이터 생성하여 저장
    # 16000Hz, 1초 분량의 스테레오 랜덤 데이터
    sr = 16000
    fake_audio = np.random.randn(sr, 2)
    fake_wav_path = tmp_path / "fake_stereo.wav"
    sf.write(fake_wav_path, fake_audio, sr)
    
    # 2. VAD 타임스탬프 추출 테스트 (텐서 차원 에러 crash 없이 무사히 완료되어야 함)
    segments = transcriber._get_vad_timestamps(str(fake_wav_path))
    assert isinstance(segments, list) or segments is None
    
    # 3. _filter_hallucinations 분기 테스트
    whisper_segs = [{"id": 1, "start": 0.0, "end": 2.0, "text": "환각 자막"}]
    
    # 3-1. VAD가 에러로 실패하여 None을 반환했을 때 (Whisper 자막 유지)
    filtered_fallback = transcriber._filter_hallucinations(whisper_segs, None)
    assert len(filtered_fallback) == 1
    assert filtered_fallback[0]["text"] == "환각 자막"
    
    # 3-2. VAD가 정상 작동했으나 음성이 없다고 판단하여 []을 반환했을 때 (Whisper 자막 모두 제거)
    filtered_empty = transcriber._filter_hallucinations(whisper_segs, [])
    assert len(filtered_empty) == 0


def test_transcriber_sanitize_segments_robustness(tmp_path):
    """
    _sanitize_segments 메서드가 단어 수준 타임스탬프가 포함된 복잡한 겹침 및 중복 문장,
    그리고 띄어쓰기가 다른 문장에 대해서도 크래시 없이 단조성(Monotonicity)을 유지하고
    stable_whisper.WhisperResult 빌드가 가능하도록 보장하는지 테스트합니다.
    """
    from services.transcriber import VideoTranscriber
    import stable_whisper
    
    transcriber = VideoTranscriber(output_dir=str(tmp_path))
    
    # 1. 띄어쓰기가 다른 중복 문장 및 단어 타임스탬프 겹침 상황 모사
    # 'prev' 세그먼트: "이십 오년 팔월 이십 이일날에 한 번 왔었네  그때가 언제냐" (공백 2개)
    # 'current' 세그먼트: "그때가 언제냐" (공백 1개)
    # 타임스탬프 겹침: prev.end = 1548.48, current.start = 1547.44
    test_segments = [
        {
            "start": 1538.56,
            "end": 1548.48,
            "text": " 이십 오년 팔월 이십 이일날에 한 번 왔었네  그때가 언제냐 ",
            "words": [
                {"word": "이십", "start": 1538.56, "end": 1539.00},
                {"word": "오년", "start": 1539.00, "end": 1540.00},
                {"word": "팔월", "start": 1540.00, "end": 1541.00},
                {"word": "이십", "start": 1541.00, "end": 1542.00},
                {"word": "이일날에", "start": 1542.00, "end": 1543.00},
                {"word": "한", "start": 1543.00, "end": 1544.00},
                {"word": "번", "start": 1544.00, "end": 1545.00},
                {"word": "왔었네", "start": 1545.00, "end": 1546.00},
                {"word": "그때가", "start": 1546.00, "end": 1547.50},
                {"word": "언제냐", "start": 1547.50, "end": 1548.48}
            ]
        },
        {
            "start": 1547.44,
            "end": 1550.00,
            "text": "그때가 언제냐",
            "words": [
                {"word": "그때가", "start": 1547.44, "end": 1548.50},
                {"word": "언제냐", "start": 1548.50, "end": 1550.00}
            ]
        }
    ]
    
    # 정제 실행
    sanitized = transcriber._sanitize_segments(test_segments)
    
    # 검증 1: 텍스트가 겹치고 내용상 중복이므로 current 세그먼트는 제거되고 prev만 살아남아야 함 (공백 무관히 중복 제거 성공 검증)
    assert len(sanitized) == 1
    assert "이십 오년" in sanitized[0]["text"]
    
    # 검증 2: 단어 타임스탬프들이 세그먼트 영역 내에 알맞게 잘 안착했는지 확인
    seg = sanitized[0]
    for w in seg.get("words", []):
        assert seg["start"] <= w["start"] <= w["end"] <= seg["end"]

    # 2. 텍스트가 서로 달라서 중복으로 지워지지 않지만, 시간만 겹치는 케이스 (Trimming 발생)
    # prev: 10.0 -> 20.0
    # current: 18.0 -> 25.0
    trim_segments = [
        {
            "start": 10.0,
            "end": 20.0,
            "text": "첫 번째 다른 문장",
            "words": [
                {"word": "첫", "start": 10.0, "end": 12.0},
                {"word": "번째", "start": 12.0, "end": 15.0},
                {"word": "다른", "start": 15.0, "end": 18.0},
                {"word": "문장", "start": 18.0, "end": 20.0}
            ]
        },
        {
            "start": 18.0,
            "end": 25.0,
            "text": "두 번째 완전히 다른 내용",
            "words": [
                {"word": "두", "start": 18.0, "end": 20.0},
                {"word": "번째", "start": 20.0, "end": 22.0},
                {"word": "완전히", "start": 22.0, "end": 24.0},
                {"word": "다른", "start": 24.0, "end": 24.5},
                {"word": "내용", "start": 24.5, "end": 25.0}
            ]
        }
    ]
    
    sanitized_trim = transcriber._sanitize_segments(trim_segments)
    
    # 둘 다 살아있어야 함
    assert len(sanitized_trim) == 2
    
    # 첫 번째 세그먼트의 종료 시간이 두 번째 시작 시간인 18.0으로 트리밍되어야 함
    assert sanitized_trim[0]["end"] == 18.0
    assert sanitized_trim[1]["start"] == 18.0
    
    # 첫 번째 세그먼트의 단어들 중 18.0 이후의 단어가 제거되거나 클램핑되어 순서가 만족해야 함
    for w in sanitized_trim[0]["words"]:
        assert w["end"] <= 18.0

    # 최종 검증: WhisperResult 객체를 생성할 때 예외(Timestamps not in ascending order)가 발생하지 않아야 함
    composition = {
        "text": " ".join([s['text'] for s in sanitized_trim]),
        "segments": sanitized_trim,
        "language": "ko"
    }
    
    # 에러 없이 정상 생성되어야 함
    res_obj = stable_whisper.WhisperResult(composition)
    assert res_obj is not None

