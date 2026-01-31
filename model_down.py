import os
import sys
from huggingface_hub import snapshot_download
from services.system_manager import ConfigManager

def download_whisper_model():
    """
    Whisper 모델을 다운로드하여 로컬 캐시에 저장합니다.
    OS에 따라 다운로드 방식이 다릅니다.
    - Mac: MLX 모델 (via huggingface_hub)
    - Windows: Faster-Whisper 모델 (via faster_whisper)
    """
    
    # 설정에서 현재 Whisper 모델명 가져오기
    model_name = ConfigManager.get_model("whisper")
    
    print(f"--- [Start] Downloading Model: {model_name} ---")
    print("This may take a while depending on your internet connection...")
    
    try:
        if sys.platform != "darwin":
            # [Windows/Linux] Faster-Whisper
            print("[Info] Detected Windows/Linux environment. Using faster-whisper downloader.")
            from faster_whisper import download_model
            
            # model_name이 'large-v3' 같은 단순 이름이면 알아서 systran/.. 에서 받음
            # 이미 경로가 포함된 경우(systran/...)도 처리 가능
            local_path = download_model(model_name)
            
            print(f"\n--- [Success] Model downloaded successfully! ---")
            print(f"Location: {local_path}")
            
        else:
            # [Mac] MLX Whisper (via HuggingFace Hub)
            print("[Info] Detected macOS environment. Using huggingface_hub downloader.")
            local_dir = snapshot_download(
                repo_id=model_name,
                repo_type="model",
            )
            print(f"\n--- [Success] Model downloaded successfully! ---")
            print(f"Location: {local_dir}")

        print("이제 transcribe 함수를 호출하면 다운로드 없이 즉시 실행됩니다.")
        
    except Exception as e:
        print(f"\n--- [Error] Failed to download model ---")
        print(e)

if __name__ == "__main__":
    download_whisper_model()