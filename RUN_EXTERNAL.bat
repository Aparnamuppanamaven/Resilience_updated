@echo off
echo ========================================
echo Resilience System - External Access Mode
echo ========================================
echo.
echo This will start the server on port 8080 accessible from external networks.
echo.
echo IMPORTANT SECURITY NOTES:
echo   - This allows access from ANY device on the internet
echo   - Only use this for testing/demo purposes
echo   - For production, use proper deployment (see DEPLOYMENT_GUIDE.md)
echo.
pause

REM Set environment variable to allow external hosts
set ALLOW_EXTERNAL=True
set ALLOWED_HOSTS=*

REM Navigate to project directory
cd /d "%~dp0"

REM Check if virtual environment exists and activate it
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo WARNING: Virtual environment not found. Using system Python.
    echo It's recommended to create a virtual environment first.
    echo.
)

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH!
    echo Please install Python first using INSTALL_PYTHON.bat
    pause
    exit /b 1
)

echo.
echo Starting Django server on 0.0.0.0:8080...
echo This makes it accessible from:
echo   - Local: http://localhost:8080
echo   - Network: http://YOUR_IP_ADDRESS:8080
echo   - External: Use ngrok or port forwarding (see DEPLOYMENT_GUIDE.md)
echo.
echo Press Ctrl+C to stop the server.
echo.

REM Start Django server on all interfaces (0.0.0.0) on port 8080
python manage.py runserver 0.0.0.0:8080

pause
