@echo off
setlocal
title ATR Windows PyAutoGUI Bridge Uninstaller

set "PACKAGE_ROOT=%~dp0"
set "UNINSTALL_SCRIPT=%PACKAGE_ROOT%scripts\uninstall_bridge.ps1"

if not exist "%UNINSTALL_SCRIPT%" (
    echo [ERROR] Bridge uninstall script is missing: %UNINSTALL_SCRIPT%
    goto failed
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%UNINSTALL_SCRIPT%"
if errorlevel 1 goto failed
echo Bridge program removed. User data was preserved.
pause
exit /b 0

:failed
echo.
echo [FAILED] Bridge removal failed. Review the error above.
pause
exit /b 1
