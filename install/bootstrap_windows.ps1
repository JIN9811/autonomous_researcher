<#
File purpose:
- Bootstrap a fresh Windows checkout for API/GUI-first use.
- Creates .venv, installs Python requirements, and creates .env.

Limitations:
- The Bash atr launcher is Linux/WSL/Git-Bash oriented. Native Windows should
  start with: python -m app.serve
- LeRobot, RealSense RSUSB, Bambu Studio, Docker, and Windows PyAutoGUI bridge
  setup remain separate steps documented in install/README.md and REQUIREMENTS.md.
#>

param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $RepoRoot

function Run-Step {
  param([string]$Command)
  Write-Host "+ $Command"
  if (-not $DryRun) {
    powershell -NoProfile -ExecutionPolicy Bypass -Command $Command
  }
}

Write-Host "Repository: $RepoRoot"

if (-not (Test-Path ".venv")) {
  Run-Step "py -3.11 -m venv .venv"
} else {
  Write-Host "Using existing .venv"
}

Run-Step ".\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel"
Run-Step ".\.venv\Scripts\pip.exe install -r requirements.txt"

if (-not (Test-Path ".env")) {
  Run-Step "Copy-Item .env.example .env"
  Write-Host "Created .env from .env.example. Add OPENAI_API_KEY or backend overrides if needed."
} else {
  Write-Host "Keeping existing .env"
}

if (-not $DryRun) {
  .\.venv\Scripts\python.exe scripts\doctor.py
}

Write-Host ""
Write-Host "Start server:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python -m app.serve"
