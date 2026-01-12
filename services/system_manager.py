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
            # 1. Fetch latest changes from remote (this updates origin/main pointer)
            # Timeout set to 30s to prevent hanging
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
        except subprocess.CalledProcessError as e:
            # Git command failed
            return {"update_available": False, "error": "Git error: " + str(e)}
        except Exception as e:
            # Other errors (network, etc)
            return {"update_available": False, "error": str(e)}

    @staticmethod
    def perform_update():
        """
        Executes git reset --hard and pip install.
        Raises exception on failure.
        """
        try:
            # 1. Reset hard to origin/main (Discards local changes to tracked files)
            subprocess.run(["git", "reset", "--hard", "origin/main"], check=True, capture_output=True)
            
            # 2. Update dependencies
            # We use sys.executable to ensure we use the same python environment
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True, capture_output=True)
            
            return True
        except subprocess.CalledProcessError as e:
            # Capture stderr for debugging
            error_msg = e.stderr.decode() if e.stderr else str(e)
            raise Exception(f"Update failed: {error_msg}")
        except Exception as e:
            raise Exception(f"Update failed: {str(e)}")

    @staticmethod
    def restart_server():
        """
        Restarts the current python process with a slight delay to allow port release.
        Uses a shell command to wait and then re-execute.
        """
        print("--- [System] Restarting Server in 2 seconds... ---")
        sys.stdout.flush()
        
        # Combined command: sleep then restart
        # This gives the OS time to release the bound port (8000)
        python_cmd = f"{sys.executable} {' '.join(sys.argv)}"
        restart_cmd = f"sleep 2 && {python_cmd}"
        
        os.execv("/bin/sh", ["/bin/sh", "-c", restart_cmd])
