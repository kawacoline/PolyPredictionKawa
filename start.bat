@echo off
cd /d "%~dp0"
echo Starting Polymarket Prediction Bot with Auto-Updater...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python updater.py
) else (
    echo Virtual environment not found! Using global python...
    python updater.py
)
pause
