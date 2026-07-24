@echo off
cd /d "%~dp0"
echo ---- %date% %time% ---- >> "%~dp0live_scan.log"
python screener.py --prefix live_results >> "%~dp0live_scan.log" 2>&1
if errorlevel 1 (
    echo FAILED (exit %errorlevel%) >> "%~dp0live_scan.log"
    start "" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0notify_failure.ps1" -Title "Stock Screener 실시간 스캔 실패" -Body "live_scan.log를 확인하세요."
) else (
    python "%~dp0notify_telegram.py" --prefix live_results --min-score 55 >> "%~dp0live_scan.log" 2>&1
    python "%~dp0notify_webhook.py" --prefix live_results --min-score 55 >> "%~dp0live_scan.log" 2>&1
)
