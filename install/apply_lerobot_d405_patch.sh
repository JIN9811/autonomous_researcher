#!/usr/bin/env bash
# File purpose:
# - Apply the ATR Spark workstation RealSense D405/RSUSB LeRobot patch to a
#   separate LeRobot checkout.
#
# Usage:
#   bash install/apply_lerobot_d405_patch.sh [/path/to/lerobot]

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
LEROBOT_ROOT="${1:-${LEROBOT_ROOT:-${HOME}/lerobot}}"
PATCH_FILE="${REPO_ROOT}/patches/lerobot/spark_realsense_d405_rsusb.patch"

if [[ ! -d "${LEROBOT_ROOT}/.git" ]]; then
  echo "error: LeRobot checkout not found: ${LEROBOT_ROOT}" >&2
  echo "clone LeRobot first, or pass the checkout path explicitly." >&2
  exit 2
fi

if [[ ! -f "${PATCH_FILE}" ]]; then
  echo "error: patch file not found: ${PATCH_FILE}" >&2
  exit 2
fi

cd "${LEROBOT_ROOT}"

echo "LeRobot checkout: ${LEROBOT_ROOT}"
echo "Patch: ${PATCH_FILE}"

git apply --check "${PATCH_FILE}"
git apply "${PATCH_FILE}"

echo "Patch applied. Review with: git -C ${LEROBOT_ROOT} diff --stat"
