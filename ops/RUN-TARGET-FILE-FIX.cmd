@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo LOLDataSystem Target File Push Production Fix
echo ============================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-TargetFilePushProductionFix.ps1"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo TARGET FILE PUSH FIX SUCCEEDED.
    echo DO NOT REBASELINE. Keep the current pending/baseline state.
) else if "%RC%"=="1" (
    echo PRE-SWITCH VALIDATION FAILED. PRODUCTION WAS NOT CHANGED.
) else if "%RC%"=="2" (
    echo DEPLOYMENT FAILED. INNER AUTOMATIC ROLLBACK SUCCEEDED.
    echo EXTRA TARGET-FILE SAFETY BACKUP WAS ALSO VERIFIED.
) else (
    echo DEPLOYMENT OR ROLLBACK FAILED. KEEP ALL BACKUP DIRECTORIES.
)

echo Exit code: %RC%
pause
exit /b %RC%
