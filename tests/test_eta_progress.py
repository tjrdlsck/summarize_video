import time

def test_eta_calculation():
    clip_start_time = time.time() - 10 # 10s elapsed
    local_percent = 50 # 50% done
    
    elapsed = time.time() - clip_start_time
    eta_seconds = int((elapsed / local_percent) * (100 - local_percent))
    print(f"Elapsed: {elapsed:.2f}s, Percent: {local_percent}%, Calculated ETA: {eta_seconds}s")
    assert eta_seconds >= 9 and eta_seconds <= 11

if __name__ == "__main__":
    test_eta_calculation()
