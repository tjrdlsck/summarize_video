@echo off
setlocal

:: --- [AI Video Analyst Setup Script for Windows] ---
:: Author: AI Agent
:: Description: Installs dependencies for Windows (NVIDIA CUDA support).

echo ========================================================
echo        AI Video Analyst Setup (Windows/NVIDIA)
echo ========================================================
echo.

:: 1. Check Prerequisites
echo [1/5] Checking system requirements...

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [Error] Python not found. Please install Python 3.10+ from python.org or Microsoft Store.
    pause
    exit /b 1
)

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [Warning] Git not found. Some features might not work.
    echo Installing Git via Winget...
    winget install --id Git.Git -e --source winget
)

where ffmpeg >nul 2>nul
if %errorlevel% neq 0 (
    echo [Error] FFmpeg not found.
    echo Please install FFmpeg and add it to your PATH.
    echo Recommendation: 'winget install --id Gyan.FFmpeg -e --source winget'
    pause
    exit /b 1
)

:: 2. Setup Virtual Environment
echo.
echo [2/5] Setting up Python virtual environment...

if not exist "venv" (
    echo Creating 'venv'...
    python -m venv venv
)

:: Activate venv
call venv\Scripts\activate.bat

:: 3. Install Dependencies
echo.
echo [3/5] Installing Python libraries...

python -m pip install --upgrade pip

:: Install PyTorch with CUDA 12.4 support explicitly
echo Installing PyTorch with CUDA support (for NVIDIA GPU)...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

:: Install other requirements
echo Installing other dependencies...
pip install -r requirements_win.txt

:: 3.5 Model Download
if exist "model_down.py" (
    echo.
    echo [3.5/5] Pre-downloading AI models...
    python model_down.py
)

:: 4. Environment Configuration
echo.
echo [4/5] Checking configuration...

if not exist ".env" (
    echo Creating .env file...
    if exist ".env.example" (
        copy .env.example .env >nul
    ) else (
        echo GOOGLE_API_KEY=> .env
    )
    echo.
    echo [IMPORTANT] Please open '.env' file and enter your GOOGLE_API_KEY.
) else (
    echo .env file exists.
)

:: 5. Create Start Script shortcut (Optional)
if not exist "start.bat" (
    echo.
    echo [Error] start.bat is missing.
)

echo.
echo ========================================================
echo      Setup Complete! Run 'start.bat' to launch.
echo ========================================================
pause
