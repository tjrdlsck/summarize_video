import os
import sys
import subprocess
import shutil

def check_command(cmd):
    path = shutil.which(cmd)
    if not path:
        return False, "Not Found in PATH"
    try:
        res = subprocess.run([cmd, "--version"], capture_output=True, text=True, check=False)
        first_line = (res.stdout or res.stderr).splitlines()[0] if (res.stdout or res.stderr) else "Found"
        return True, first_line
    except Exception as e:
        return True, f"Found at {path} (Error getting version: {e})"

def check_env_file():
    env_path = ".env"
    if not os.path.exists(env_path):
        return False, ".env file missing"
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    api_key_found = False
    key_length = 0
    for line in lines:
        if line.strip().startswith("GOOGLE_API_KEY"):
            parts = line.strip().split("=", 1)
            if len(parts) == 2:
                val = parts[1].strip("'\" ")
                if val and val != "your_actual_gemini_api_key_here":
                    api_key_found = True
                    key_length = len(val)
    
    if api_key_found:
        return True, f"Configured (Key length: {key_length})"
    else:
        return False, "GOOGLE_API_KEY is empty or missing"

def check_python_imports():
    try:
        import torch
        cuda_avail = torch.cuda.is_available()
        device_name = torch.cuda.get_device_name(0) if cuda_avail else "CPU"
        return True, f"PyTorch {torch.__version__} (CUDA: {cuda_avail}, Device: {device_name})"
    except ImportError as e:
        return False, f"Missing PyTorch: {e}"
    except Exception as e:
        return False, f"Error importing PyTorch: {e}"

def main():
    print("==================================================")
    print("       SermonCutter AI Prerequisites Check        ")
    print("==================================================")
    
    # 1. System Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"[1] Python Executable: {sys.executable}")
    print(f"    Python Version   : {py_ver}")
    
    # 2. Git Check
    git_ok, git_msg = check_command("git")
    print(f"[2] Git Status       : {'[OK]' if git_ok else '[FAIL]'} ({git_msg})")
    
    # 3. FFmpeg Check
    ffmpeg_ok, ffmpeg_msg = check_command("ffmpeg")
    print(f"[3] FFmpeg Status    : {'[OK]' if ffmpeg_ok else '[FAIL]'} ({ffmpeg_msg})")
    
    # 4. .env & API Key Check
    env_ok, env_msg = check_env_file()
    print(f"[4] .env / API Key   : {'[OK]' if env_ok else '[FAIL]'} ({env_msg})")
    
    # 5. PyTorch / Dependencies Check
    torch_ok, torch_msg = check_python_imports()
    print(f"[5] PyTorch / CUDA   : {'[OK]' if torch_ok else '[FAIL]'} ({torch_msg})")
    
    print("==================================================")
    all_ok = git_ok and ffmpeg_ok and env_ok and torch_ok
    if all_ok:
        print(" RESULT: All prerequisites satisfied! Ready to run start.bat.")
    else:
        print(" RESULT: Some requirements are missing or not configured.")
    print("==================================================")

if __name__ == "__main__":
    main()
