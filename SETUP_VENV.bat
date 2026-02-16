@echo off
echo ========================================
echo Resilience - Create venv and install deps
echo ========================================
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    echo Virtual environment already exists.
    echo Activating and upgrading pip / installing requirements...
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    echo.
    echo Done. Activate with: venv\Scripts\activate  then run: python manage.py runserver
    pause
    exit /b 0
)

echo Creating virtual environment...
python -m venv venv
if %errorlevel% neq 0 (
    echo ERROR: Could not create venv. Is Python installed? Try INSTALL_PYTHON.bat
    pause
    exit /b 1
)

echo Activating and installing dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ========================================
echo Setup complete.
echo ========================================
echo To run the project:
echo   1. venv\Scripts\activate
echo   2. python manage.py runserver
echo.
echo Or double-click RUN_EXTERNAL.bat to run on port 8080.
echo.
pause
