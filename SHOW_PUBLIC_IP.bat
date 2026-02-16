@echo off
echo ========================================
echo Resilience - Your public URL (internet)
echo ========================================
echo.
echo Use this URL from anywhere on the internet
echo AFTER you set up port forwarding (port 8080) on your router.
echo.
echo Fetching your public IP...
echo.

REM Try PowerShell to get public IP (works on Windows without curl)
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Invoke-WebRequest -Uri 'https://api.ipify.org' -UseBasicParsing -TimeoutSec 5).Content" 2^>nul') do set PUB=%%i

if defined PUB (
    echo.
    echo   Your public URL:
    echo   http://%PUB%:8080
    echo.
    echo   Copy the URL above. Make sure:
    echo   1. RUN_EXTERNAL.bat is running
    echo   2. Router port 8080 is forwarded to this PC
    echo.
) else (
    echo   Could not fetch public IP (check internet).
    echo   You can search "what is my ip" in a browser instead.
    echo   Then use: http://YOUR_IP:8080
    echo.
)

pause
