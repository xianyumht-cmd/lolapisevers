@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title Lanzou Watcher Sync

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found in PATH.
    echo.
    pause
    exit /b 1
)

python "%~dp0sync_lanzou_watchers_from_website.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%
