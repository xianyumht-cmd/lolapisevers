@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo LOLDataSystem Target File Direct URL Current-History Hotfix
echo ============================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-TargetFileDirectCurrentHotfix.ps1"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo HOTFIX SUCCEEDED OR WAS ALREADY INSTALLED.
    echo DO NOT REBASELINE. DO NOT DEPLOY 6108 OR 6178.
) else if "%RC%"=="11" (
    echo CURRENT PRODUCTION HEAD DOES NOT MATCH THE RECORDED CURRENT BRANCH.
    echo PRODUCTION WAS NOT STOPPED OR CHANGED.
) else if "%RC%"=="2" (
    echo HOTFIX FAILED BUT AUTOMATIC ROLLBACK SUCCEEDED.
) else (
    echo HOTFIX DID NOT COMPLETE. READ THE MESSAGE ABOVE.
)

echo Exit code: %RC%
pause
exit /b %RC%
