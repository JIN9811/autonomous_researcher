param(
    [string]$Python = "",
    [string]$Name = "WindowsPyAutoGUIBridge",
    [switch]$InstallBuildDeps
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

$pythonCmd = Resolve-Python -ExplicitPython $Python

if ($InstallBuildDeps) {
    & $pythonCmd -m pip install -r (Join-Path $projectRoot "requirements-windows.txt")
}

try {
    & $pythonCmd -m PyInstaller --version | Out-Host
} catch {
    throw "PyInstaller is not installed. Run: $pythonCmd -m pip install pyinstaller"
}

$hiddenImports = @(
    "--hidden-import=pyautogui",
    "--hidden-import=pyscreeze",
    "--hidden-import=mouseinfo",
    "--hidden-import=pygetwindow",
    "--hidden-import=pymsgbox",
    "--hidden-import=pytweening",
    "--hidden-import=PIL",
    "--hidden-import=cv2",
    "--hidden-import=pynput",
    "--hidden-import=pywinauto",
    "--hidden-import=pytesseract"
)
$demoData = "$projectRoot\demo;demo"

& $pythonCmd -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name $Name `
    --distpath (Join-Path $projectRoot "dist") `
    --workpath (Join-Path $projectRoot "build\pyinstaller") `
    --specpath (Join-Path $projectRoot "build") `
    --add-data $demoData `
    $hiddenImports `
    (Join-Path $projectRoot "bridge\windows_pyautogui_bridge_server.py")

Write-Host ""
Write-Host "Built executable:"
Write-Host (Join-Path $projectRoot "dist\$Name.exe")
Write-Host ""
Write-Host "Example run:"
Write-Host '$env:WINDOWS_PYAUTOGUI_BRIDGE_TOKEN = "<token>"'
Write-Host '$env:WINDOWS_PYAUTOGUI_BRIDGE_HOST = "0.0.0.0"'
Write-Host '$env:WINDOWS_PYAUTOGUI_BRIDGE_PORT = "8765"'
Write-Host ".\dist\$Name.exe"
