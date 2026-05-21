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
