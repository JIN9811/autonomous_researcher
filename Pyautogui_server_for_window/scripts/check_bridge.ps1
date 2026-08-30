param([string]$Url = "")

$ErrorActionPreference = "Stop"
if (-not $Url) {
    if ($env:WINDOWS_PYAUTOGUI_BRIDGE_URL) {
        $Url = $env:WINDOWS_PYAUTOGUI_BRIDGE_URL
    } else {
        $port = if ($env:WINDOWS_PYAUTOGUI_BRIDGE_PORT) { $env:WINDOWS_PYAUTOGUI_BRIDGE_PORT } else { "8765" }
        $Url = "http://127.0.0.1:$port"
    }
}

Write-Host "Checking bridge: $Url"
$health = Invoke-RestMethod -Uri "$Url/health" -Method Get
$pairing = Invoke-RestMethod -Uri "$Url/pairing/status" -Method Get
$health | ConvertTo-Json -Depth 8
Write-Host "Pairing: $($pairing.status)"
