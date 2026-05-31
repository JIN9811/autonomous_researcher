$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

if (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_URL) {
    $env:WINDOWS_PYAUTOGUI_BRIDGE_URL = "http://127.0.0.1:8765"
}

if (-not $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN) {
    throw "Set WINDOWS_PYAUTOGUI_BRIDGE_TOKEN before running this test."
}

$headers = @{
    "X-Bridge-Token" = $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN
}

Write-Host "GET /health"
curl.exe -s -H "X-Bridge-Token: $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" "$env:WINDOWS_PYAUTOGUI_BRIDGE_URL/health"
Write-Host ""

Write-Host "GET /programs"
curl.exe -s -H "X-Bridge-Token: $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" "$env:WINDOWS_PYAUTOGUI_BRIDGE_URL/programs"
Write-Host ""

Write-Host "POST /execute program1"
$payload = ConvertTo-Json @{
    sequence_id = "program1-check-001"
    program_id = "program1"
    command = "program1"
} -Depth 8 -Compress
$artifactDir = Join-Path $projectRoot "artifacts\equipment"
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
$payloadPath = Join-Path $artifactDir "test_bridge_program1_payload.json"
Set-Content -LiteralPath $payloadPath -Value $payload -Encoding UTF8
$dataArg = "@$payloadPath"
curl.exe -s -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN" --data-binary $dataArg "$env:WINDOWS_PYAUTOGUI_BRIDGE_URL/execute"
Write-Host ""
