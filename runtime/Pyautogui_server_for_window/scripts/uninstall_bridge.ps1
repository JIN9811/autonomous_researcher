param(
    [string]$DataRoot = "$env:LOCALAPPDATA\ATR\PyAutoGUIBridge",
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
$packageRoot = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..")).Path
$taskName = "ATR Windows PyAutoGUI Bridge"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
$stopScript = Join-Path $packageRoot "scripts\stop_bridge.ps1"
if (Test-Path -LiteralPath $stopScript) { & $stopScript }
$desktopFolder = [Environment]::GetFolderPath("Desktop")
$startMenuFolder = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\ATR"
foreach ($shortcut in @(
    (Join-Path $desktopFolder "ATR Windows Bridge.lnk"),
    (Join-Path $desktopFolder "Uninstall ATR Windows Bridge.lnk"),
    (Join-Path $startMenuFolder "ATR Windows Bridge.lnk"),
    (Join-Path $startMenuFolder "Uninstall ATR Windows Bridge.lnk")
)) {
    if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut -Force }
}
if ((Test-Path -LiteralPath $startMenuFolder) -and -not (Get-ChildItem -LiteralPath $startMenuFolder -Force)) {
    Remove-Item -LiteralPath $startMenuFolder -Force
}
[Environment]::SetEnvironmentVariable("WINDOWS_PYAUTOGUI_DATA_ROOT", $null, "User")
[Environment]::SetEnvironmentVariable("ATR_WINDOWS_BRIDGE_INSTALL_ROOT", $null, "User")
$venvRoot = Join-Path $packageRoot ".venv"
if (Test-Path -LiteralPath $venvRoot) { Remove-Item -LiteralPath $venvRoot -Recurse -Force }
if ($RemoveData -and (Test-Path -LiteralPath $DataRoot)) { Remove-Item -LiteralPath $DataRoot -Recurse -Force }
Write-Host "Windows PyAutoGUI Bridge runtime and launcher integration removed. Package folder preserved. Data preserved: $(-not $RemoveData)"
