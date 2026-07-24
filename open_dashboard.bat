@echo off
cd /d "%~dp0"

rem Pull the latest results committed by the cloud routine first.
git pull origin main

rem Start the local server only if port 8642 isn't already listening.
netstat -ano | findstr ":8642" | findstr "LISTENING" >nul
if errorlevel 1 (
    start "stock-screener-server" /min python -m http.server 8642 --bind 127.0.0.1
    timeout /t 2 /nobreak >nul
)

start "" "http://localhost:8642/dashboard/index.html"
