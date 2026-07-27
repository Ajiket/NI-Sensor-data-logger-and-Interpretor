@echo off
setlocal
title NI Sensor Data Logger - ACTIVE

echo ===================================================
echo   NI Sensor System - Launcher
echo ===================================================

:: 1. Check for Virtual Environment
if not exist "venv\Scripts\activate" (
    echo [ERROR] Virtual environment not found. 
    echo Please run SETUP_PREREQUISITES.bat first.
    pause
    exit /b 1
)

:: 2. Activate Environment
echo [1/2] Activating environment...
call venv\Scripts\activate

:: 3. Check for NI Drivers (Optional but helpful)
:: We check if the nidaqmx system library is likely present
where nicaiu.dll >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] NI-DAQmx drivers not detected in PATH. 
    echo System will likely start in DEMO MODE.
    echo ---------------------------------------------------
)

:: 4. Start Application
echo [2/2] Starting Production Logger...
echo Dashboard will be available at http://localhost:5000
echo.
python production_logger.py
pause
