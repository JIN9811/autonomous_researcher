param([string]$Version = "dev")

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..")).Path
$releaseRoot = Join-Path $projectRoot "dist\release\WindowsPyAutoGUIBridge-$Version"
$zipPath = "$releaseRoot.zip"
if (Test-Path $releaseRoot) { Remove-Item $releaseRoot -Recurse -Force }
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null

foreach ($directory in @("bridge", "demo", "docs", "examples", "portable", "scripts", "tests")) {
    Copy-Item (Join-Path $projectRoot $directory) (Join-Path $releaseRoot $directory) -Recurse -Force
}
foreach ($file in @(
    "README.md",
    "requirements.txt",
    "requirements-portable.txt",
    "requirements-windows.txt",
    "INSTALL_WINDOWS_BRIDGE.cmd",
    "START_WINDOWS_BRIDGE.cmd",
    "UNINSTALL_WINDOWS_BRIDGE.cmd"
)) {
    Copy-Item (Join-Path $projectRoot $file) (Join-Path $releaseRoot $file) -Force
}
Get-ChildItem -Path $releaseRoot -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Path $releaseRoot -File -Recurse -Include "*.pyc", "*.pyo" | Remove-Item -Force
Compress-Archive -Path "$releaseRoot\*" -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "Release ZIP: $zipPath"
