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

