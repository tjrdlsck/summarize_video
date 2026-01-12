from huggingface_hub import snapshot_download
import os

def download_whisper_model():
    """
    MLX Whisper 모델을 Hugging Face에서 명시적으로 다운로드하여
    로컬 캐시에 저장합니다. (추론 실행 X)
    """
    
    # 다운로드할 모델 ID (MLX Community 버전)
    # REPO_ID = "mlx-community/whisper-large-v3-mlx-4bit"
    REPO_ID = "mlx-community/whisper-large-v3-turbo-q4"
    
    print(f"--- [Start] Downloading Model: {REPO_ID} ---")
    print("This may take a while depending on your internet connection...")
    
    try:
        # snapshot_download: 리포지토리의 모든 파일(가중치, 설정파일 등)을 다운로드
        local_dir = snapshot_download(
            repo_id=REPO_ID,
            repo_type="model",
            # local_dir를 지정하지 않으면 기본 캐시 폴더(~/.cache/huggingface)에 저장됨 (권장)
        )
        
        print(f"\n--- [Success] Model downloaded successfully! ---")
        print(f"Location: {local_dir}")
        print("이제 transcribe 함수를 호출하면 다운로드 없이 즉시 실행됩니다.")
        
    except Exception as e:
        print(f"\n--- [Error] Failed to download model ---")
        print(e)

if __name__ == "__main__":
    download_whisper_model()