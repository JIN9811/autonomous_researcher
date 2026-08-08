param(
    [string]$Url = "",
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$tokenPath = Join-Path $projectRoot ".bridge_token"

if (-not $Url) {
    if ($env:WINDOWS_PYAUTOGUI_BRIDGE_URL) {
        $Url = $env:WINDOWS_PYAUTOGUI_BRIDGE_URL
    } else {
        $port = if ($env:WINDOWS_PYAUTOGUI_BRIDGE_PORT) { $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT } else { "8765" }
        $Url = "http://127.0.0.1:$port"
    }
}

if (-not $Token) {
    if ($env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN) {
        $Token = $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN
    } elseif (Test-Path -LiteralPath $tokenPath) {
        $Token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
    }
}

Write-Host "Checking bridge: $Url"
if ($Token) {
    Write-Host "Using configured bridge token."
    curl.exe -s -H "X-Bridge-Token: $Token" "$Url/health"
} else {
    Write-Host "No token found. Request may return auth_required."
    curl.exe -s "$Url/health"
}
Write-Host ""
