@echo off
title ComplyNex CMS - Automated Startup
echo ==============================================
echo    ComplyNex CMS - Automated Startup Script
echo ==============================================

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your system PATH!
    echo Please install Python 3.9+ from python.org and ensure "Add Python to PATH" is checked.
    pause
    exit /b
)

:: Create Virtual Environment if missing
if not exist "venv_deploy\" (
    echo [INFO] Creating new virtual environment...
    python -m venv venv_deploy
    
    echo [INFO] Activating virtual environment...
    call venv_deploy\Scripts\activate.bat
    
    echo [INFO] Installing required packages ^(this will take several minutes^)...
    pip install --upgrade pip
    pip install -r requirements.txt
) else (
    echo [INFO] Activating existing virtual environment...
    call venv_deploy\Scripts\activate.bat
)

:: Start Flask App
echo [INFO] Starting the ComplyNex CMS application...
echo ----------------------------------------------
echo Note: If Elasticsearch is not running locally, screening will gracefully fall back to SQLite queries.
echo To stop the server at any time, press CTRL + C
echo ----------------------------------------------
python run.py

pause
