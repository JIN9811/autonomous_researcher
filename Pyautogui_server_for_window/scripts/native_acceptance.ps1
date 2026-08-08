param(
    [string]$Url = "http://127.0.0.1:8765",
    [string]$Token = "",
    [string]$TokenFile = "",
    [string]$OutputPath = "",
    [switch]$RunProgram1
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
if (-not $TokenFile) {
    $dataRoot = if ($env:WINDOWS_PYAUTOGUI_DATA_ROOT) { $env:WINDOWS_PYAUTOGUI_DATA_ROOT } else { "$env:LOCALAPPDATA\ATR\PyAutoGUIBridge" }
    $TokenFile = Join-Path $dataRoot ".bridge_token"
}
if (-not $Token -and (Test-Path -LiteralPath $TokenFile)) { $Token = (Get-Content $TokenFile -Raw).Trim() }
if (-not $Token) { throw "Bridge token is required for native acceptance." }
if (-not $OutputPath) { $OutputPath = Join-Path $projectRoot "artifacts\native_acceptance.json" }
$headers = @{ "X-Bridge-Token" = $Token }

$health = Invoke-RestMethod -Uri "$Url/health" -Headers $headers -Method Get
$examples = Invoke-RestMethod -Uri "$Url/examples" -Headers $headers -Method Get
$programResult = $null
if ($RunProgram1) {
    $programResult = Invoke-RestMethod -Uri "$Url/execute" -Headers $headers -Method Post -ContentType "application/json" -Body '{"program_id":"program1","confirm_execute":true}'
}
$accepted = [bool]($health.status -eq "ready" -and $health.platform.desktop_control_ready -and $health.dependencies.core_ready -and $health.demo_assets.available)
if ($RunProgram1) { $accepted = $accepted -and [bool]$programResult.ok }
$evidence = [ordered]@{
    schema = "atr.windows_pyautogui_native_acceptance.v1"
    accepted = $accepted
    captured_at = (Get-Date).ToUniversalTime().ToString("o")
    computer_name = $env:COMPUTERNAME
    user_name = $env:USERNAME
    powershell_version = $PSVersionTable.PSVersion.ToString()
    health = $health
    example_count = @($examples.examples).Count
    program1 = $programResult
}
New-Item -ItemType Directory -Path (Split-Path -Parent $OutputPath) -Force | Out-Null
$evidence | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Native acceptance: $accepted"
Write-Host "Evidence: $OutputPath"
if (-not $accepted) { exit 1 }
