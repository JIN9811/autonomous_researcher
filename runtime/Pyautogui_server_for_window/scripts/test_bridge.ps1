$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$url = if ($env:WINDOWS_PYAUTOGUI_BRIDGE_URL) { $env:WINDOWS_PYAUTOGUI_BRIDGE_URL } else { "http://127.0.0.1:8765" }

Write-Host "GET /health"
Invoke-RestMethod -Uri "$url/health" -Method Get | ConvertTo-Json -Depth 8

Write-Host "GET /programs"
Invoke-RestMethod -Uri "$url/programs" -Method Get | ConvertTo-Json -Depth 8

$pairing = Invoke-RestMethod -Uri "$url/pairing/status" -Method Get
if (-not $pairing.paired) {
    throw "Pair this bridge from Linux ATR using the four-digit code before testing execution."
}

Write-Host "POST /execute program1"
$payload = @{
    sequence_id = "program1-check-001"
    program_id = "program1"
    command = "program1"
} | ConvertTo-Json -Depth 8
$artifactDir = Join-Path $projectRoot "artifacts\equipment"
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
Set-Content -LiteralPath (Join-Path $artifactDir "test_bridge_program1_payload.json") -Value $payload -Encoding UTF8
Invoke-RestMethod -Uri "$url/execute" -Method Post -ContentType "application/json" -Body $payload | ConvertTo-Json -Depth 8
