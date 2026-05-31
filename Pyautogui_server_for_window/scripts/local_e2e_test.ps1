param(
    [string]$Python = "",
    [int]$Port = 8777
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

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
    throw "Python was not found. Pass -Python C:\Path\To\python.exe or install Python 3.10+."
}

function Join-ProcessArguments {
    param([string[]]$Arguments)
    $quoted = foreach ($arg in $Arguments) {
        if ($arg -match '[\s"]') {
            $escaped = $arg -replace '"', '\"'
            '"' + $escaped + '"'
        } else {
            $arg
        }
    }
    return ($quoted -join " ")
}

$pythonCmd = Resolve-Python -ExplicitPython $Python
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$token = [Convert]::ToBase64String($bytes)
$baseUrl = "http://127.0.0.1:$Port"

$artifactDir = Join-Path $projectRoot "artifacts\equipment"
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
$badPayloadPath = Join-Path $artifactDir "local_e2e_bad_action_payload.json"
$programPayloadPath = Join-Path $artifactDir "local_e2e_program1_payload.json"
$stdoutPath = Join-Path $artifactDir "local_e2e_server_stdout.log"
$stderrPath = Join-Path $artifactDir "local_e2e_server_stderr.log"

$serverArgs = @(
    (Join-Path $projectRoot "bridge\windows_pyautogui_bridge_server.py"),
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--token", "$token",
    "--artifact-dir", $artifactDir,
    "--reference-dir", (Join-Path $projectRoot "reference_images")
)

$process = $null
try {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $pythonCmd
    $startInfo.Arguments = Join-ProcessArguments -Arguments $serverArgs
    $startInfo.WorkingDirectory = $projectRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        if ($process.HasExited) {
            break
        }
        try {
            $probe = curl.exe -s "$baseUrl/"
            if ($probe -match "Windows PyAutoGUI Bridge") {
                $ready = $true
                break
            }
        } catch {
        }
        Start-Sleep -Milliseconds 250
    }

    if (-not $ready) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id
            $process.WaitForExit()
        }
        Set-Content -LiteralPath $stdoutPath -Value $stdoutTask.Result -Encoding UTF8
        Set-Content -LiteralPath $stderrPath -Value $stderrTask.Result -Encoding UTF8
        Write-Host "Server did not become ready."
        Write-Host "Server stdout:"
        Write-Host $stdoutTask.Result
        Write-Host "Server stderr:"
        Write-Host $stderrTask.Result
        Write-Host "Logs:"
        Write-Host $stdoutPath
        Write-Host $stderrPath
        throw "Web GUI HTML was not served from /"
    }

    Write-Host "GET / Web GUI"
    $html = curl.exe -s "$baseUrl/"
    if (($html -match "Windows PyAutoGUI Bridge") -and ($html -match "Run Timeline") -and ($html -match "Live Proof Checklist")) {
        Write-Host "Web GUI HTML served with Run Timeline / Live Proof Checklist"
    } else {
        Write-Host "Received from /:"
        Write-Host $html
        throw "Web GUI HTML did not include required operator panels"
    }
    Write-Host ""

    Write-Host "GET /health"
    curl.exe -s -H "X-Bridge-Token: $token" "$baseUrl/health"
    Write-Host ""

    Write-Host "GET /programs"
    curl.exe -s -H "X-Bridge-Token: $token" "$baseUrl/programs"
    Write-Host ""

    Write-Host "GET /readiness"
    curl.exe -s -H "X-Bridge-Token: $token" "$baseUrl/readiness"
    Write-Host ""

    Write-Host "GET /request-log"
    curl.exe -s -H "X-Bridge-Token: $token" "$baseUrl/request-log"
    Write-Host ""

    Write-Host "POST /execute guarded sequence or install-required block"
    $badPayload = ConvertTo-Json @{
        sequence_id = "bad-action"
        sequence = @(@{ action = "shell" })
    } -Depth 8 -Compress
    Set-Content -LiteralPath $badPayloadPath -Value $badPayload -Encoding UTF8
    $badDataArg = "@$badPayloadPath"
    curl.exe -s -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $token" --data-binary $badDataArg "$baseUrl/execute"
    Write-Host ""

    Write-Host "GET /artifacts"
    curl.exe -s -H "X-Bridge-Token: $token" "$baseUrl/artifacts"
    Write-Host ""

    Write-Host "POST /execute program1"
    $programPayload = ConvertTo-Json @{
        sequence_id = "program1-local-e2e"
        program_id = "program1"
        command = "program1"
    } -Depth 8 -Compress
    Set-Content -LiteralPath $programPayloadPath -Value $programPayload -Encoding UTF8
    $programDataArg = "@$programPayloadPath"
    curl.exe -s -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $token" --data-binary $programDataArg "$baseUrl/execute"
    Write-Host ""

    Write-Host "Local E2E completed."
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id
        $process.WaitForExit()
    }
    if ($process) {
        if ($stdoutTask) {
            Set-Content -LiteralPath $stdoutPath -Value $stdoutTask.Result -Encoding UTF8
        }
        if ($stderrTask) {
            Set-Content -LiteralPath $stderrPath -Value $stderrTask.Result -Encoding UTF8
        }
    }
}
