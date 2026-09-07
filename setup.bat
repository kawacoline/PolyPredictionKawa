@echo off
cd /d "%~dp0"
echo Setting up Polymarket Prediction Bot...
echo Creating virtual environment...
python -m venv .venv
if exist ".venv\Scripts\pip.exe" (
    echo Installing requirements in virtual environment...
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\pip install -r requirements.txt
) else (
    echo Virtual environment pip failed [common on some VPS]. Falling back to global Python...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    REM Remove the broken venv so start.bat doesn't try to use it
    rmdir /s /q .venv
)
echo.
echo Setup complete! You can now run start.bat
pause
