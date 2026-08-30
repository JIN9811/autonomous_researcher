param(
    [string]$Url = "http://127.0.0.1:8765",
    [string]$OutputPath = "",
    [switch]$RunProgram1
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
if (-not $OutputPath) { $OutputPath = Join-Path $projectRoot "artifacts\native_acceptance.json" }

$health = Invoke-RestMethod -Uri "$Url/health" -Method Get
$pairing = Invoke-RestMethod -Uri "$Url/pairing/status" -Method Get
$examples = $null
$programResult = $null
if ($pairing.paired) {
    $examples = Invoke-RestMethod -Uri "$Url/examples" -Method Get
    if ($RunProgram1) {
        $programResult = Invoke-RestMethod -Uri "$Url/execute" -Method Post -ContentType "application/json" -Body '{"program_id":"program1","confirm_execute":true}'
    }
}

$accepted = [bool]($health.status -eq "ready" -and $health.platform.desktop_control_ready -and $health.dependencies.core_ready -and $health.demo_assets.available)
if ($RunProgram1) { $accepted = $accepted -and [bool]$pairing.paired -and [bool]$programResult.ok }
$evidence = [ordered]@{
    schema = "atr.windows_pyautogui_native_acceptance.v1"
    accepted = $accepted
    captured_at = (Get-Date).ToUniversalTime().ToString("o")
    computer_name = $env:COMPUTERNAME
    user_name = $env:USERNAME
    powershell_version = $PSVersionTable.PSVersion.ToString()
    health = $health
    pairing = @{ paired = [bool]$pairing.paired; status = $pairing.status }
    example_count = if ($examples) { @($examples.examples).Count } else { 0 }
    program1 = $programResult
}
New-Item -ItemType Directory -Path (Split-Path -Parent $OutputPath) -Force | Out-Null
$evidence | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Native acceptance: $accepted"
Write-Host "Pairing: $($pairing.status)"
Write-Host "Evidence: $OutputPath"
if (-not $accepted) { exit 1 }
