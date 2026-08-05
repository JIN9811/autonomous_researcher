#!/usr/bin/env bash
# File purpose:
# - Bootstrap a fresh Linux/WSL autonomous_researcher checkout for default use.
# - Installs the main Python venv, Python dependencies, .env template, and atr CLI.
#
# Scope:
# - Does not install heavy optional systems such as LeRobot, Bambu Studio,
#   NemoClaw/vLLM models, Docker images, or RealSense RSUSB builds.
# - Runs scripts/doctor.py at the end so the operator sees which optional
#   hardware dependencies still need setup.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WITH_PIPER=0
WITH_LOCAL_PYAUTOGUI=0
SKIP_CLI=0
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage:
  bash install/bootstrap_linux.sh [--with-piper] [--with-local-pyautogui] [--skip-cli] [--dry-run]

Options:
  --with-piper  Also install the packaged Piper TTS voice after requirements.
  --with-local-pyautogui  Install X11 desktop-control tools for the localhost bridge.
  --skip-cli    Do not install ~/.local/bin/atr.
  --dry-run     Print commands without executing them.

Environment:
  PYTHON_BIN    Python executable to use. Default: python3.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-piper) WITH_PIPER=1; shift ;;
    --with-local-pyautogui) WITH_LOCAL_PYAUTOGUI=1; shift ;;
    --skip-cli) SKIP_CLI=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

run() {
  echo "+ $*"
  if [[ "${DRY_RUN}" != "1" ]]; then
    "$@"
  fi
}

cd "${REPO_ROOT}"

echo "Repository: ${REPO_ROOT}"
echo "Python: ${PYTHON_BIN}"

if [[ ! -d .venv ]]; then
  run "${PYTHON_BIN}" -m venv .venv
else
  echo "Using existing .venv"
fi

run .venv/bin/python -m pip install --upgrade pip setuptools wheel
run .venv/bin/pip install -r requirements.txt

if [[ "${WITH_LOCAL_PYAUTOGUI}" == "1" ]]; then
  run sudo apt-get update
  run sudo apt-get install -y python3-tk scrot wmctrl xdotool
fi

if [[ ! -f .env ]]; then
  run cp .env.example .env
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "Would create .env from .env.example."
  else
    echo "Created .env from .env.example. Add API keys or backend overrides if needed."
  fi
else
  echo "Keeping existing .env"
fi

if [[ "${WITH_PIPER}" == "1" ]]; then
  run bash install/install_piper_tts.sh
fi

if [[ "${SKIP_CLI}" != "1" ]]; then
  run bash install/install_cli.sh
fi

if [[ "${DRY_RUN}" != "1" ]]; then
  .venv/bin/python scripts/doctor.py || true
fi

cat <<'NEXT'

Next steps:
  1. Start the server: atr up
  2. Open the GUI: http://localhost:7860/
  3. For physical devices, follow REQUIREMENTS.md sections for Bambu/Prusa,
     LeRobot, RealSense RSUSB, NemoClaw/vLLM, and Windows equipment bridge.
NEXT
