@echo off
cd /d "%~dp0"
echo ---- %date% %time% ---- >> "%~dp0pull_latest.log"
git pull origin main >> "%~dp0pull_latest.log" 2>&1
if errorlevel 1 (
    echo FAILED (exit %errorlevel%) >> "%~dp0pull_latest.log"
    start "" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0notify_failure.ps1" -Title "Stock Screener 일일 동기화 실패" -Body "GitHub git pull이 실패했습니다. pull_latest.log를 확인하세요."
)
