import os
import sys
import subprocess
import time

class SystemManager:
    @staticmethod
    def check_for_updates():
        """
        Check if the local git repo is behind origin/main.
        Returns dict with status and version hashes.
        """
        try:
            # 1. Fetch latest changes from remote
            subprocess.run(["git", "fetch", "origin", "main"], check=True, capture_output=True, timeout=30)
            
            # 2. Get current HEAD hash
            current_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
            
            # 3. Get remote HEAD hash
            remote_hash = subprocess.check_output(["git", "rev-parse", "origin/main"]).decode().strip()
            
            return {
                "update_available": current_hash != remote_hash,
                "current_version": current_hash[:7],
                "latest_version": remote_hash[:7]
            }
        except Exception as e:
            return {"update_available": False, "error": str(e)}

    @staticmethod
    def perform_update():
        """
        Signals the guardian process (run.py) to perform update and restart.
        Exits current process with code 5.
        """
        print("--- [System] Signaling Update to Guardian in 1s... ---")
        # Exit code 5 is our custom signal defined in run.py
        # We use a short delay and os._exit to bypass FastAPI's exception handling
        time.sleep(1)
        os._exit(5)

    @staticmethod
    def restart_server():
        """
        Signals the guardian process to just restart.
        """
        print("--- [System] Signaling Restart to Guardian in 1s... ---")
        time.sleep(1)
        os._exit(5)
