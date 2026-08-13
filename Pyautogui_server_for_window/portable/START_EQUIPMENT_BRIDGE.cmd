@echo off
setlocal
title ATR Equipment Agent Bridge

set "PACKAGE_ROOT=%~dp0"
set "BOOTSTRAP=%PACKAGE_ROOT%bootstrap_portable.ps1"

if not exist "%BOOTSTRAP%" (
    echo [ERROR] Portable bootstrap is missing: %BOOTSTRAP%
    goto failed
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%" -StartBridge
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo [FAILED] Equipment bridge startup failed. Review the error above.
pause
exit /b 1
