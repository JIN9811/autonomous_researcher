param(
    [string]$Python = "",
    [switch]$LocalOnly,
    [switch]$AllowNoToken,
    [switch]$InstallPyAutoGUI,
    [switch]$OpenBrowser,
    [switch]$ResetToken,
    [ValidateRange(4, 64)]
    [int]$TokenLength = 8
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$tokenPath = Join-Path $projectRoot ".bridge_token"

function Resolve-Python {
    param([string]$ExplicitPython)
    if ($ExplicitPython) {
        & $ExplicitPython -c "import sys; print(sys.executable)" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Explicit Python failed: $ExplicitPython"
        }
        return $ExplicitPython
    }
    foreach ($candidate in @("py", "python", "python3")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            & $candidate -c "import sys; print(sys.executable)" | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
    }
    throw "Python was not found. Install Python 3.10+ or pass -Python C:\Path\To\python.exe."
}

function Test-PortAvailable {
    param(
        [string]$HostName,
        [int]$Port
    )

    $ipAddress = [System.Net.IPAddress]::Loopback
    if ($HostName -eq "0.0.0.0") {
        $ipAddress = [System.Net.IPAddress]::Any
    } elseif ($HostName -eq "127.0.0.1" -or $HostName -eq "localhost") {
        $ipAddress = [System.Net.IPAddress]::Loopback
    } else {
        $ipAddress = [System.Net.IPAddress]::Parse($HostName)
    }

    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new($ipAddress, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) {
            $listener.Stop()
        }
    }
}

function New-ShortBridgeToken {
    param([int]$Length)
    $alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    $bytes = New-Object byte[] $Length
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $chars = New-Object char[] $Length
    for ($i = 0; $i -lt $Length; $i++) {
        $chars[$i] = $alphabet[$bytes[$i] % $alphabet.Length]
    }
    return -join $chars
}

$python = Resolve-Python -ExplicitPython $Python

if (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN) {
    if ($ResetToken -and (Test-Path -LiteralPath $tokenPath)) {
        Remove-Item -LiteralPath $tokenPath -Force
    }

    if (Test-Path -LiteralPath $tokenPath) {
        $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        Write-Host "Loaded saved bridge token. Use this value on the Linux side:"
    } else {
        $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = New-ShortBridgeToken -Length $TokenLength
        Set-Content -LiteralPath $tokenPath -Value $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN -Encoding ASCII
        Write-Host "Generated saved bridge token. Use this value on the Linux side:"
    }
    Write-Host $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN
} else {
    Write-Host "Using bridge token from WINDOWS_PYAUTOGUI_BRIDGE_TOKEN:"
    Write-Host $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN
}

if ($LocalOnly) {
    $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "127.0.0.1"
} elseif (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST) {
    $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "0.0.0.0"
}

if (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT) {
    $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765"
}

if ($InstallPyAutoGUI) {
    & $python -m pip install pyautogui
}

if (-not (Test-PortAvailable -HostName $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST -Port ([int]$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT))) {
    throw "Port $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT is already in use or cannot be bound on $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST. Try another port: `$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = '8766'"
}

Write-Host "Starting Windows PyAutoGUI bridge on $env:WINDOWS_PYAUTOGUI_BRIDGE_HOST`:$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT"
Write-Host "Health URL: http://<windows-private-ip>:$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT/health"
Write-Host "Local Web GUI: http://127.0.0.1:$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT/"
Write-Host "Saved token file: $tokenPath"

$serverArgs = @(
    (Join-Path $projectRoot "bridge\windows_pyautogui_bridge_server.py"),
    "--artifact-dir", (Join-Path $projectRoot "artifacts\equipment"),
    "--reference-dir", (Join-Path $projectRoot "reference_images")
)
if ($AllowNoToken) {
    $serverArgs += "--allow-no-token"
}
if ($OpenBrowser) {
    $serverArgs += "--open-browser"
}

& $python $serverArgs
