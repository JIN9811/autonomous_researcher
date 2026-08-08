@echo off
setlocal
title ATR Windows PyAutoGUI Bridge

set "PACKAGE_ROOT=%~dp0"
set "RUN_SCRIPT=%PACKAGE_ROOT%scripts\run_bridge.ps1"

if not exist "%RUN_SCRIPT%" (
    echo [ERROR] Bridge start script is missing: %RUN_SCRIPT%
    goto failed
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%RUN_SCRIPT%" -OpenBrowser
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo [FAILED] Bridge startup failed. Review the error above.
pause
exit /b 1
