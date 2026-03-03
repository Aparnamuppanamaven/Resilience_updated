@echo off
echo ========================================
echo Resilience System - Quick Start
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed!
    echo.
    echo Please install Python first:
    echo 1. Run INSTALL_PYTHON.bat
    echo 2. Or download from: https://www.python.org/downloads/windows/
    echo 3. Make sure to check "Add Python to PATH"
    echo 4. Close and reopen VS Code after installation
    pause
    exit /b 1
)

echo Python found! Starting setup...
echo.

REM Navigate to project directory
cd /d "%~dp0"

REM Create virtual environment
echo [1/6] Creating virtual environment...
python -m venv venv
if %errorlevel% neq 0 (
    echo ERROR: Failed to create virtual environment
    pause
    exit /b 1
)

REM Activate virtual environment
echo [2/6] Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo [3/6] Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

REM Create migrations
echo [4/6] Creating database migrations...
python manage.py makemigrations
if %errorlevel% neq 0 (
    echo ERROR: Failed to create migrations
    pause
    exit /b 1
)

REM Run migrations
echo [5/6] Applying database migrations...
python manage.py migrate
if %errorlevel% neq 0 (
    echo ERROR: Failed to run migrations
    pause
    exit /b 1
)

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo Next steps:
echo 1. (Optional) Create admin user: python manage.py createsuperuser
echo 2. Start server: python manage.py runserver 8001
echo 3. Open browser: http://127.0.0.1:8001/
echo.
echo To start the server now, press any key...
pause >nul

echo Starting development server...
python manage.py runserver 8001


