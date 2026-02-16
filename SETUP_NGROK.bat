@echo off
echo ========================================
echo Resilience System - ngrok Setup
echo ========================================
echo.
echo This script will help you expose your local server to the internet
echo using ngrok (creates a public URL that tunnels to your localhost:8080)
echo.
echo Step 1: Download ngrok
echo   - Visit: https://ngrok.com/download
echo   - Download for Windows
echo   - Extract ngrok.exe to a folder (e.g., C:\ngrok)
echo.
echo Step 2: Sign up for free account
echo   - Visit: https://dashboard.ngrok.com/signup
echo   - Create a free account
echo   - Get your authtoken from: https://dashboard.ngrok.com/get-started/your-authtoken
echo.
echo Step 3: Configure ngrok
echo   - Open command prompt as Administrator
echo   - Run: ngrok config add-authtoken YOUR_AUTHTOKEN
echo.
echo Step 4: Start your Django server
echo   - Run: RUN_EXTERNAL.bat (in another terminal)
echo   - Wait for server to start on port 8080
echo.
echo Step 5: Start ngrok tunnel
echo   - Run: ngrok http 8080
echo   - Copy the "Forwarding" URL (e.g., https://abc123.ngrok.io)
echo   - This URL works from anywhere on the internet!
echo.
echo ========================================
echo Quick Start (if ngrok is already installed):
echo ========================================
echo.
echo 1. Make sure Django server is running on port 8080
echo 2. Run this command in a new terminal:
echo    ngrok http 8080
echo 3. Copy the HTTPS URL from ngrok output
echo 4. Share that URL - it works from anywhere!
echo.
pause

REM Check if ngrok is installed
where ngrok >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo ngrok is installed! Starting tunnel...
    echo Make sure Django server is running on port 8080 first!
    echo.
    pause
    ngrok http 8080
) else (
    echo.
    echo ngrok is not installed or not in PATH.
    echo Please follow the steps above to install ngrok first.
    echo.
)

pause
