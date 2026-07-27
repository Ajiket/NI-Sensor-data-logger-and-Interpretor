@echo off
setlocal
echo ========================================
echo   NI-Sensor Sync Tool
echo ========================================

:: Check for git
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Git is not installed or not in PATH.
    pause
    exit /b 1
)

:: Sync process
echo Staging changes...
git add .

echo Committing changes...
set "commit_msg=Sync session: %date% %time%"
git commit -m "%commit_msg%"

echo Pushing to branch: Thermocouples...
git push origin Thermocouples

if %errorlevel% equ 0 (
    echo.
    echo SUCCESS: Sync complete!
) else (
    echo.
    echo ERROR: Push failed. Check your internet connection or credentials.
)

echo ========================================
pause
