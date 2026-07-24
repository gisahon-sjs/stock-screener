@echo off
cd /d "%~dp0"
echo ---- %date% %time% ---- >> "%~dp0pull_latest.log"
git pull origin main >> "%~dp0pull_latest.log" 2>&1
