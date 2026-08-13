@echo off
setlocal
title Stop ATR Equipment Agent Bridge

set "PACKAGE_ROOT=%~dp0"
set "STOP_SCRIPT=%PACKAGE_ROOT%scripts\stop_bridge.ps1"

if not exist "%STOP_SCRIPT%" (
    echo [ERROR] Bridge stop script is missing: %STOP_SCRIPT%
    goto failed
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%STOP_SCRIPT%"
if errorlevel 1 goto failed
timeout /t 2 /nobreak >nul
exit /b 0

:failed
echo.
echo [FAILED] Equipment bridge stop failed. Review the error above.
pause
exit /b 1
