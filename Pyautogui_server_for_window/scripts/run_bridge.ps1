param(
    [string]$Python = "",
    [string]$DataRoot = "",
    [switch]$LocalOnly,
    [switch]$AllowNoToken,
    [switch]$InstallPyAutoGUI,
    [switch]$OpenBrowser,
    [switch]$ResetToken,
    [switch]$ShowToken,
    [ValidateRange(16, 64)]
    [int]$TokenLength = 32
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

function Resolve-Python {
    param([string]$ExplicitPython)
    if ($ExplicitPython) {
        & $ExplicitPython -c "import sys; print(sys.executable)" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Explicit Python failed: $ExplicitPython" }
        return $ExplicitPython
    }
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) { return $venvPython }
    foreach ($candidate in @("py", "python", "python3")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            & $candidate -c "import sys; print(sys.executable)" | Out-Null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
    throw "Python was not found. Run scripts\install_bridge.ps1 or pass -Python C:\Path\To\python.exe."
}

function Test-PortAvailable {
    param([string]$HostName, [int]$Port)
    $ipAddress = if ($HostName -eq "0.0.0.0") {
        [System.Net.IPAddress]::Any
    } elseif ($HostName -eq "127.0.0.1" -or $HostName -eq "localhost") {
        [System.Net.IPAddress]::Loopback
    } else {
        [System.Net.IPAddress]::Parse($HostName)
    }
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new($ipAddress, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) { $listener.Stop() }
    }
}

function New-BridgeToken {
    param([int]$Length)
    $alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    $bytes = New-Object byte[] $Length
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $chars = New-Object char[] $Length
    for ($i = 0; $i -lt $Length; $i++) { $chars[$i] = $alphabet[$bytes[$i] % $alphabet.Length] }
    return -join $chars
}

function Protect-TokenFile {
    param([string]$Path)
    if ($IsWindows -or $env:OS -eq "Windows_NT") {
        & icacls.exe $Path /inheritance:r /grant:r "$env:USERNAME`:(R,W)" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to apply a user-only ACL to $Path" }
    }
}

if (-not $DataRoot) {
    $DataRoot = if ($env:WINDOWS_PYAUTOGUI_DATA_ROOT) {
        $env:WINDOWS_PYAUTOGUI_DATA_ROOT
    } else {
        Join-Path $env:LOCALAPPDATA "ATR\PyAutoGUIBridge"
    }
}
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$env:WINDOWS_PYAUTOGUI_DATA_ROOT = $DataRoot

$paths = @{
    artifacts = if ($env:WINDOWS_PYAUTOGUI_BRIDGE_ARTIFACT_ROOT) { $env:WINDOWS_PYAUTOGUI_BRIDGE_ARTIFACT_ROOT } else { Join-Path $DataRoot "artifacts" }
    locators = if ($env:WINDOWS_PYAUTOGUI_LOCATOR_ROOT) { $env:WINDOWS_PYAUTOGUI_LOCATOR_ROOT } else { Join-Path $DataRoot "locators" }
    utm = if ($env:WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR) { $env:WINDOWS_PYAUTOGUI_UTM_EXPORT_DIR } else { Join-Path $DataRoot "utm_exports" }
    programs = if ($env:WINDOWS_PYAUTOGUI_PROGRAM_DIR) { $env:WINDOWS_PYAUTOGUI_PROGRAM_DIR } else { Join-Path $DataRoot "programs" }
    recordings = if ($env:WINDOWS_PYAUTOGUI_RECORDING_DIR) { $env:WINDOWS_PYAUTOGUI_RECORDING_DIR } else { Join-Path $DataRoot "recordings" }
}
foreach ($path in $paths.Values) { New-Item -ItemType Directory -Path $path -Force | Out-Null }

$tokenPath = Join-Path $DataRoot ".bridge_token"
if (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN) {
    if ($ResetToken -and (Test-Path -LiteralPath $tokenPath)) { Remove-Item -LiteralPath $tokenPath -Force }
    if (Test-Path -LiteralPath $tokenPath) {
        $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        Write-Host "Loaded saved bridge token."
    } else {
        $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = New-BridgeToken -Length $TokenLength
        Set-Content -LiteralPath $tokenPath -Value $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN -Encoding ASCII
        Protect-TokenFile -Path $tokenPath
        Write-Host "Generated a saved bridge token."
    }
} else {
    Write-Host "Using bridge token from the environment."
}
if ($ShowToken) { Write-Host "Bridge token: $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" }

if ($LocalOnly) {
    $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "127.0.0.1"
} elseif (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST) {
    $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "0.0.0.0"
}
if (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT) { $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765" }

$python = Resolve-Python -ExplicitPython $Python
if ($InstallPyAutoGUI) {
    & $python -m pip install -r (Join-Path $projectRoot "requirements-windows.txt")
    if ($LASTEXITCODE -ne 0) { throw "Windows bridge dependency installation failed." }
}
if (-not (Test-PortAvailable -HostName $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST -Port ([int]$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT))) {
    throw "Port $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT is already in use on $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST."
}

$serverArgs = @(
    (Join-Path $projectRoot "bridge\windows_pyautogui_bridge_server.py"),
    "--artifact-dir", $paths.artifacts,
    "--reference-dir", $paths.locators,
    "--utm-export-dir", $paths.utm,
    "--program-dir", $paths.programs,
    "--recording-dir", $paths.recordings,
    "--demo-dir", (Join-Path $projectRoot "demo")
)
if ($AllowNoToken) { $serverArgs += "--allow-no-token" }
if ($OpenBrowser) { $serverArgs += "--open-browser" }

Write-Host "Starting Windows PyAutoGUI bridge on $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST`:$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT"
Write-Host "Data root: $DataRoot"
Write-Host "Token file: $tokenPath"
& $python $serverArgs
