param(
    [string]$DataRoot = "$env:LOCALAPPDATA\ATR\PyAutoGUIBridge",
    [string]$PythonLauncher = "py",
    [string]$ControllerAddress = ""
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..")).Path
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)

$venvPython = Join-Path $sourceRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($PythonLauncher -eq "py") { & py -3.11 -m venv (Join-Path $sourceRoot ".venv") }
    else { & $PythonLauncher -m venv (Join-Path $sourceRoot ".venv") }
    if ($LASTEXITCODE -ne 0) { throw "Dedicated bridge virtual environment creation failed." }
}
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $sourceRoot "requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "Windows bridge dependency installation failed." }

New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
[Environment]::SetEnvironmentVariable("WINDOWS_PYAUTOGUI_DATA_ROOT", $DataRoot, "User")

if ($ControllerAddress) {
    & (Join-Path $sourceRoot "scripts\firewall_allow_private.ps1") -RemoteAddress $ControllerAddress
}

$taskName = "ATR Windows PyAutoGUI Bridge"
$supervisorScript = Join-Path $sourceRoot "scripts\start_supervisor.ps1"
$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$supervisorScript`" -DataRoot `"$DataRoot`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null

function New-BridgeShortcut {
    param([string]$ShortcutPath, [string]$LauncherPath, [string]$Description)
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = Join-Path $env:SystemRoot "System32\cmd.exe"
    $shortcut.Arguments = "/c `"$LauncherPath`""
    $shortcut.WorkingDirectory = $sourceRoot
    $shortcut.Description = $Description
    $shortcut.Save()
}

$desktopFolder = [Environment]::GetFolderPath("Desktop")
$startMenuFolder = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\ATR"
New-Item -ItemType Directory -Path $startMenuFolder -Force | Out-Null
$startLauncher = Join-Path $sourceRoot "START_WINDOWS_BRIDGE.cmd"
$uninstallLauncher = Join-Path $sourceRoot "UNINSTALL_WINDOWS_BRIDGE.cmd"
New-BridgeShortcut -ShortcutPath (Join-Path $desktopFolder "ATR Windows Bridge.lnk") -LauncherPath $startLauncher -Description "Start ATR Windows PyAutoGUI Bridge"
New-BridgeShortcut -ShortcutPath (Join-Path $desktopFolder "Uninstall ATR Windows Bridge.lnk") -LauncherPath $uninstallLauncher -Description "Remove ATR Windows PyAutoGUI Bridge"
New-BridgeShortcut -ShortcutPath (Join-Path $startMenuFolder "ATR Windows Bridge.lnk") -LauncherPath $startLauncher -Description "Start ATR Windows PyAutoGUI Bridge"
New-BridgeShortcut -ShortcutPath (Join-Path $startMenuFolder "Uninstall ATR Windows Bridge.lnk") -LauncherPath $uninstallLauncher -Description "Remove ATR Windows PyAutoGUI Bridge"
Write-Host "Desktop and Start Menu shortcuts created."

Write-Host "Prepared Windows PyAutoGUI Bridge in package folder: $sourceRoot"
Write-Host "Data root: $DataRoot"
Write-Host "Start: powershell -ExecutionPolicy Bypass -File `"$sourceRoot\scripts\start_supervisor.ps1`""
