@echo off
echo ========================================
echo Resilience - URL to open from other laptop
echo ========================================
echo.
echo 1. Make sure server is running first: RUN_EXTERNAL.bat
echo 2. From the other laptop, open this URL in the browser:
echo.

powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notmatch '^169\.' } | ForEach-Object { Write-Host '   http://' $_.IPAddress ':8080' -ForegroundColor Green }"

echo.
echo If nothing showed: run "ipconfig", find your IPv4 Address, then use http://THAT_IP:8080
echo.
echo Same WiFi/network = use the URL above.
echo Other network = run "ngrok http 8080" and use the HTTPS URL ngrok gives you.
echo.
pause
