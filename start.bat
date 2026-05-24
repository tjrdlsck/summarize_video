@echo off
:: --- [AI Video Analyst Launcher] ---
echo Starting AI Video Analyst...

:: Activate Virtual Environment
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [Error] Virtual environment not found. Please run 'setup.bat' first.
    pause
    exit /b 1
)

:: Run Server
python run.py

pause
