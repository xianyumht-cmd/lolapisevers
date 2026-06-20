@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set APP_PORT=5001
if not exist logs mkdir logs
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py >> logs\server.log 2>&1
) else (
  python app.py >> logs\server.log 2>&1
)
