@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\run_service.ps1" >> logs\server.log 2>&1
