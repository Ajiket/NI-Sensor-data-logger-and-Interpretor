@echo off
setlocal
echo ===================================================
echo   NI Sensor System - One-Time Setup
echo ===================================================

:: 1. Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed. 
    echo Please install Python 3.7+ from python.org before continuing.
    pause
    exit /b 1
)

:: 2. Create Virtual Environment
echo [1/3] Creating virtual environment...
python -m venv venv
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

:: 3. Install Dependencies
echo [2/3] Installing required libraries...
call venv\Scripts\activate
python -m pip install --upgrade pip
if exist "requirements.txt" (
    pip install -r requirements.txt
) else (
    pip install nidaqmx flask gspread google-auth
)

:: 4. Finalizing
echo [3/3] Finalizing setup...
if not exist "config\config.json" (
    echo. > "config\config.json"
    echo [INFO] Empty config.json created in config folder.
)

echo ===================================================
echo   SETUP COMPLETE! 
echo   You can now use START_SYSTEM.bat to run the app.
echo ===================================================
pause
