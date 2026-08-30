param(
    [string]$Python = "",
    [string]$DataRoot = "",
    [switch]$LocalOnly,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
try { $Host.UI.RawUI.WindowTitle = "ATR PyAutoGUI Bridge Supervisor" } catch {}
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

if (-not $DataRoot) {
    $DataRoot = if ($env:WINDOWS_PYAUTOGUI_DATA_ROOT) { $env:WINDOWS_PYAUTOGUI_DATA_ROOT } else { Join-Path $env:LOCALAPPDATA "ATR\PyAutoGUIBridge" }
}
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$env:ATR_WINDOWS_BRIDGE_PACKAGE_ROOT = $projectRoot
$env:WINDOWS_PYAUTOGUI_DATA_ROOT = $DataRoot
$env:ATR_WINDOWS_BRIDGE_SUPERVISED = "1"
if ($LocalOnly) { $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "127.0.0.1" } elseif (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST) { $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "0.0.0.0" }
if (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT) { $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765" }

if (-not $Python) {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) { $Python = $venvPython }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py" }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = "python" }
    else { throw "Python was not found. Run INSTALL_WINDOWS_BRIDGE.cmd first." }
}

$paths = @{
    artifacts = Join-Path $DataRoot "artifacts"
    locators = Join-Path $DataRoot "locators"
    utm = Join-Path $DataRoot "utm_exports"
    programs = Join-Path $DataRoot "programs"
    recordings = Join-Path $DataRoot "recordings"
}
foreach ($path in $paths.Values) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
$command = @(
    $Python,
    (Join-Path $projectRoot "bridge\windows_pyautogui_bridge_server.py"),
    "--artifact-dir", $paths.artifacts,
    "--reference-dir", $paths.locators,
    "--utm-export-dir", $paths.utm,
    "--program-dir", $paths.programs,
    "--recording-dir", $paths.recordings,
    "--demo-dir", (Join-Path $projectRoot "demo")
)
if ($OpenBrowser) { $command += "--open-browser" }
$commandJson = ConvertTo-Json -Compress -InputObject $command
$tempRoot = if ($env:TEMP) { $env:TEMP } else { [System.IO.Path]::GetTempPath() }
$supervisorDir = Join-Path $tempRoot "ATR\PyAutoGUIBridge\supervisor"
New-Item -ItemType Directory -Path $supervisorDir -Force | Out-Null
$commandFile = Join-Path $supervisorDir ("worker-command-{0}.json" -f $PID)
[System.IO.File]::WriteAllText($commandFile, $commandJson, (New-Object System.Text.UTF8Encoding($false)))
try {
    & $Python (Join-Path $projectRoot "scripts\bridge_supervisor.py") `
        --command-file $commandFile `
        --package-root $projectRoot `
        --health-url "http://127.0.0.1:$($env:WINDOWS_PYAUTOGUI_BRIDGE_PORT)/ping" `
        --update-lock (Join-Path $DataRoot "updates\update_in_progress.json") `
        --status-path (Join-Path $supervisorDir "status.json") `
        --singleton-lock (Join-Path $supervisorDir "supervisor.lock") `
        --interval-s 5.0
}
finally {
    Remove-Item -LiteralPath $commandFile -Force -ErrorAction SilentlyContinue
}
