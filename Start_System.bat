@echo off
setlocal
title NI Sensor Data Logger - ACTIVE

echo ===================================================
echo   NI Sensor System - Launcher
echo ===================================================

:: 1. Check for Virtual Environment (Root)
if exist ".venv\Scripts\activate" (
    echo [1/2] Activating .venv environment...
    call .venv\Scripts\activate
) else if exist "venv\Scripts\activate" (
    echo [1/2] Activating venv environment...
    call venv\Scripts\activate
) else (
    echo [1/2] No virtual environment detected. Running with system python.
)

:: 2. Check for NI Drivers (Optional but helpful)
where nicaiu.dll >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] NI-DAQmx drivers not detected in PATH. 
    echo System will likely start in DEMO MODE.
    echo ---------------------------------------------------
)

:: 3. Start Application
echo [2/2] Starting Production Logger...
echo Dashboard will be available at http://localhost:5000
echo.
python app.py
pause
