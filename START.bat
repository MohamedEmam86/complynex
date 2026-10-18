@echo off
title ComplyNex CMS - Automated Startup
echo ==============================================
echo    ComplyNex CMS - Automated Startup Script
echo ==============================================
echo.

echo Checking Elasticsearch...
curl -s http://localhost:9200 >nul 2>&1
if errorlevel 1 (
    echo WARNING: Elasticsearch is not running.
    echo Screening will work but may be slower.
    echo Start Elasticsearch manually if needed.
    echo.
)

echo Checking Redis...
redis-cli ping >nul 2>&1
if errorlevel 1 (
    echo WARNING: Redis is not running. Cache disabled.
    echo.
)

echo Activating virtual environment...
call venv_deploy\Scripts\activate.bat

echo.
echo Starting ComplyNex CMS application...
echo The application will open in your default browser automatically.
echo Keep this window open to keep the server running.
echo Press CTRL+C in this window to stop the server.
echo ==============================================
echo.

start http://localhost:5000
python run.py

pause
