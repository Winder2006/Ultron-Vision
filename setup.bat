@echo off
echo ============================================
echo    MOTHER VISION - Setup Script
echo ============================================
echo.

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Create virtual environment
if not exist "venv" (
    echo [1/4] Creating virtual environment...
    python -m venv venv
) else (
    echo [1/4] Virtual environment already exists
)

:: Activate venv
echo [2/4] Activating virtual environment...
call venv\Scripts\activate.bat

:: Install dependencies
echo [3/4] Installing Python dependencies...
echo       This may take a few minutes (dlib compilation)...
pip install --upgrade pip
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [WARNING] Some packages may have failed to install.
    echo If face_recognition fails, try:
    echo   pip install cmake
    echo   pip install dlib
    echo   pip install face_recognition
)

:: Done
echo.
echo [4/4] Setup complete!
echo.
echo ============================================
echo To start MOTHER VISION:
echo   1. Run: venv\Scripts\activate
echo   2. Run: python main.py
echo   3. Open: http://localhost:8200/status
echo   4. (Optional) cd web ^& npm install ^& npm run dev
echo ============================================
pause

