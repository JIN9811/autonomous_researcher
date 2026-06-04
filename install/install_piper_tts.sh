#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${REPO_ROOT}/.venv/bin/python"
VENV_PIP="${REPO_ROOT}/.venv/bin/pip"
VOICE_DIR="${REPO_ROOT}/models/tts/piper/en_US-lessac-medium"
MODEL="${VOICE_DIR}/en_US-lessac-medium.onnx"
CONFIG="${VOICE_DIR}/en_US-lessac-medium.onnx.json"

if [[ ! -x "${VENV_PYTHON}" || ! -x "${VENV_PIP}" ]]; then
  echo "ERROR: ${REPO_ROOT}/.venv is required before installing Piper TTS." >&2
  exit 1
fi

mkdir -p "${VOICE_DIR}"
"${VENV_PIP}" install piper-tts

if [[ ! -s "${MODEL}" ]]; then
  curl -L --fail --retry 3 \
    -o "${MODEL}" \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
fi

if [[ ! -s "${CONFIG}" ]]; then
  curl -L --fail --retry 3 \
    -o "${CONFIG}" \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
fi

"${VENV_PYTHON}" "${REPO_ROOT}/tools/tts/atr_piper_say.py" \
  "Piper voice package is ready." \
  --model "${MODEL}" \
  --config "${CONFIG}" \
  --piper-bin "${REPO_ROOT}/.venv/bin/piper" \
  --player true

echo "Piper TTS installed and verified."
