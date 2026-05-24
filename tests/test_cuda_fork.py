import multiprocessing
import sys
import torch

def worker(queue):
    try:
        import ctranslate2
        # CUDA 장치를 초기화하여 에러가 나는지 확인
        print("[Worker] Trying to access CUDA via ctranslate2...")
        types = ctranslate2.get_supported_compute_types("cuda")
        queue.put(("success", types))
    except Exception as e:
        import traceback
        queue.put(("error", traceback.format_exc()))

def test_fork():
    # 1. 부모 프로세스에서 CUDA를 초기화
    print("Parent CUDA available:", torch.cuda.is_available())
    
    # 2. fork 방식으로 프로세스 시작
    queue = multiprocessing.Queue()
    p = multiprocessing.Process(target=worker, args=(queue,))
    p.start()
    p.join()
    
    if not queue.empty():
        result = queue.get()
        print("Fork method result:", result)
    else:
        print("Fork method timed out or crashed without putting to queue.")

def test_spawn():
    # 3. spawn 방식으로 프로세스 시작
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    p = ctx.Process(target=worker, args=(queue,))
    p.start()
    p.join()
    
    if not queue.empty():
        result = queue.get()
        print("Spawn method result:", result)
    else:
        print("Spawn method timed out or crashed without putting to queue.")

if __name__ == "__main__":
    print("--- Testing Fork ---")
    test_fork()
    print("--- Testing Spawn ---")
    test_spawn()
