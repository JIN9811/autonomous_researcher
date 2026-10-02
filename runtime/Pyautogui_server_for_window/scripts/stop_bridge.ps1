$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$bridgePath = Join-Path $projectRoot "bridge\windows_pyautogui_bridge_server.py"

$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($bridgePath)
}

if (-not $procs) {
    Write-Host "No Windows PyAutoGUI bridge process found."
    return
}

foreach ($proc in $procs) {
    Write-Host "Stopping bridge PID $($proc.ProcessId)"
    Stop-Process -Id $proc.ProcessId -Force
}

Write-Host "Bridge stopped."
