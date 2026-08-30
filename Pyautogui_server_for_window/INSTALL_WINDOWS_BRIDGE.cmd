@echo off
setlocal
title ATR Windows PyAutoGUI Bridge Installer

set "PACKAGE_ROOT=%~dp0"
set "INSTALL_SCRIPT=%PACKAGE_ROOT%scripts\install_bridge.ps1"
set "RUN_SCRIPT=%PACKAGE_ROOT%scripts\start_supervisor.ps1"

if not exist "%INSTALL_SCRIPT%" (
    echo [ERROR] Installer script is missing: %INSTALL_SCRIPT%
    goto failed
)

echo Installing ATR Windows PyAutoGUI Bridge...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_SCRIPT%"
if errorlevel 1 goto failed

if not exist "%RUN_SCRIPT%" (
    echo [ERROR] Package start script is missing: %RUN_SCRIPT%
    goto failed
)

echo Installation completed. Starting the bridge in a new window...
start "ATR Windows PyAutoGUI Bridge" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%RUN_SCRIPT%" -OpenBrowser
if errorlevel 1 goto failed

echo Desktop and Start Menu shortcuts are ready.
pause
exit /b 0

:failed
echo.
echo [FAILED] Installation did not complete. Review the error above.
pause
exit /b 1
