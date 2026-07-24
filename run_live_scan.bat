@echo off
cd /d "%~dp0"
echo ---- %date% %time% ---- >> "%~dp0live_scan.log"
python screener.py --prefix live_results >> "%~dp0live_scan.log" 2>&1
