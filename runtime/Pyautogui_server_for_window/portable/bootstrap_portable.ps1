param([switch]$StartBridge)

$ErrorActionPreference = "Stop"
$packageRoot = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$runtimeRoot = Join-Path $packageRoot "runtime\python"
$pythonExe = Join-Path $runtimeRoot "python.exe"
$vendorRoot = Join-Path $packageRoot "vendor"
$pythonInstaller = Join-Path $vendorRoot "python\python-installer-amd64.exe"
$wheelhouse = Join-Path $vendorRoot "wheelhouse"
$requirements = Join-Path $packageRoot "requirements-portable.txt"
$dataRoot = Join-Path $packageRoot "data"
$markerPath = Join-Path $runtimeRoot ".atr-portable-ready"
$bootstrapLog = Join-Path $dataRoot "logs\portable-bootstrap.log"

function Write-PortableLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -LiteralPath $bootstrapLog -Value $line -Encoding UTF8
}

function Get-RuntimeSignature {
    $requirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash
    $wheelNames = Get-ChildItem -LiteralPath $wheelhouse -File -Filter "*.whl" |
        Sort-Object Name |
        ForEach-Object { $_.Name }
    $material = @($requirementsHash) + $wheelNames
    $bytes = [Text.Encoding]::UTF8.GetBytes(($material -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "") }
    finally { $sha.Dispose() }
}

New-Item -ItemType Directory -Path (Join-Path $dataRoot "logs") -Force | Out-Null
foreach ($name in @("artifacts", "locators", "utm_exports", "programs", "recordings")) {
    New-Item -ItemType Directory -Path (Join-Path $dataRoot $name) -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $pythonInstaller)) {
    throw "Offline Python installer is missing: $pythonInstaller. Rebuild the portable release."
}
if (-not (Test-Path -LiteralPath $requirements)) {
    throw "Portable requirements file is missing: $requirements"
}
if (-not (Test-Path -LiteralPath $wheelhouse)) {
    throw "Offline wheelhouse is missing: $wheelhouse. Rebuild the portable release."
}

$signature = Get-RuntimeSignature
$runtimeReady = (Test-Path -LiteralPath $pythonExe) -and
    (Test-Path -LiteralPath $markerPath) -and
    ((Get-Content -LiteralPath $markerPath -Raw).Trim() -eq $signature)

if (-not $runtimeReady) {
    Write-PortableLog "Preparing the folder-local Python runtime. No administrator rights are required."
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $installerArgs = @(
        "/quiet",
        "InstallAllUsers=0",
        ('TargetDir="{0}"' -f $runtimeRoot),
        "Include_pip=1",
        "Include_launcher=0",
        "PrependPath=0",
        "AssociateFiles=0",
        "Shortcuts=0",
        "Include_test=0",
        "Include_doc=0",
        "Include_debug=0"
    )
    $installer = Start-Process -FilePath $pythonInstaller -ArgumentList $installerArgs -Wait -PassThru
    if ($installer.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $pythonExe)) {
        throw "Folder-local Python setup failed with exit code $($installer.ExitCode)."
    }

    Write-PortableLog "Installing bridge dependencies from the bundled offline wheelhouse."
    & $pythonExe -m pip install --disable-pip-version-check --no-index --find-links $wheelhouse -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "Offline bridge dependency installation failed." }
    & $pythonExe -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Portable Python dependency verification failed." }
    Set-Content -LiteralPath $markerPath -Value $signature -Encoding ASCII
    Write-PortableLog "Portable runtime is ready."
} else {
    Write-PortableLog "Using the existing verified portable runtime."
}

if (-not $StartBridge) { return }

$runScript = Join-Path $packageRoot "scripts\start_supervisor.ps1"
if (-not (Test-Path -LiteralPath $runScript)) { throw "Bridge supervisor script is missing: $runScript" }

$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"{0}"' -f $runScript),
    "-Python", ('"{0}"' -f $pythonExe),
    "-DataRoot", ('"{0}"' -f $dataRoot),
    "-OpenBrowser"
)
Write-PortableLog "Starting the Equipment Agent Bridge and opening the operator GUI."
Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WorkingDirectory $packageRoot
