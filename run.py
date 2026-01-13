import subprocess
import sys
import os
import time

def run_server():
    """
    Main loop to manage the FastAPI server process.
    """
    # Use the same python interpreter that is running this script
    python_exe = sys.executable
    server_script = "main.py"
    
    # Exit code 5 will be our signal for "Update and Restart"
    UPDATE_SIGNAL = 5
    
    while True:
        print(f"\n--- [Guardian] Starting Server Process ({server_script}) ---")
        
        # Start the FastAPI server
        # We don't use 'uvicorn' directly here so that main.py's __main__ block handles it
        # This gives us more control over the process
        process = subprocess.Popen([python_exe, server_script])
        
        # Wait for the process to exit
        exit_code = process.wait()
        
        if exit_code == UPDATE_SIGNAL:
            print("\n--- [Guardian] Update signal received. Starting maintenance... ---")
            
            try:
                # 1. Update source code
                print("[Maintenance] Fetching latest changes from git...")
                subprocess.run(["git", "fetch", "origin", "main"], check=True)
                
                # 2. Explicitly checkout and sync main branch
                print("[Maintenance] Switching to main branch and syncing...")
                # -B: Create or reset the branch if it already exists
                subprocess.run(["git", "checkout", "-B", "main", "origin/main"], check=True)
                
                # 3. Update dependencies
                print("[Maintenance] Updating python dependencies...")
                subprocess.run([python_exe, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
                
                # 4. Rebuild macOS App Bundle (if on macOS)
                if sys.platform == "darwin" and os.path.exists("make_portable_app.sh"):
                    print("[Maintenance] Rebuilding macOS App Bundle...")
                    try:
                        subprocess.run(["bash", "make_portable_app.sh"], check=True)
                    except Exception as e:
                        print(f"--- [Warning] App rebuild failed: {e} ---")

                print("[Maintenance] Update successful. Switched to 'main' branch.")
                print("[Maintenance] Cooling down for 2 seconds...")
                time.sleep(2) # Grace period for port release
                
            except subprocess.CalledProcessError as e:
                print(f"!!! [Guardian] Maintenance failed: {e} !!!")
                print("[Guardian] Attempting to restart anyway in 5 seconds...")
                time.sleep(5)
            
            # Restart the loop
            continue
            
        elif exit_code == 0:
            print("--- [Guardian] Server stopped normally. Exiting. ---")
            break
        else:
            print(f"--- [Guardian] Server crashed with exit code {exit_code}. Restarting in 3 seconds... ---")
            time.sleep(3)
            continue

if __name__ == "__main__":
    # Ensure we are in the correct directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        run_server()
    except KeyboardInterrupt:
        print("\n--- [Guardian] Terminated by user. ---")
        sys.exit(0)
