@echo off
setlocal enabledelayedexpansion
echo ========================================
echo   NI-Sensor Sync Tool
echo ========================================

:: Check for git
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed or not in PATH.
    pause
    exit /b 1
)

:: Check git configuration for contribution credit
for /f "tokens=*" %%i in ('git config user.email') do set GIT_EMAIL=%%i
if "%GIT_EMAIL%"=="" (
    echo [WARNING] Git user.email is not set. 
    echo Contributions may not be visible on your GitHub profile.
    set /p GIT_EMAIL="Enter your GitHub email (optional, press Enter to skip): "
    if not "!GIT_EMAIL!"=="" git config --local user.email !GIT_EMAIL!
)

:: Sync process
echo Staging changes...
git add .

echo Committing changes...
set /p commit_msg="Enter commit message (or press Enter for default): "
if "%commit_msg%"=="" set "commit_msg=Sync session: %date% %time%"

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
