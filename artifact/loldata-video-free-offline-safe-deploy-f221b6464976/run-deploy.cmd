@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-video-free-api.ps1" -ExpectedCommit f221b64649763eb8d325d87348fd2f42f48a6485
echo.
if errorlevel 1 (
  echo DEPLOYMENT FAILED OR ROLLED BACK. Keep the window output.
) else (
  echo DEPLOYMENT SUCCEEDED.
)
pause
