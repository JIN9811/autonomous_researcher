#!/usr/bin/env bash
set -euo pipefail

PAYLOAD_JSON="${1:-}"
if [[ -z "${PAYLOAD_JSON}" ]]; then
  PAYLOAD_JSON="{}"
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

source_setup() {
  local setup="$1"
  if [[ -n "${setup}" && -f "${setup}" ]]; then
    # ROS setup scripts are not nounset-safe.
    set +u
    # shellcheck disable=SC1090
    source "${setup}"
    set -u
  fi
}

IFS=':' read -ra ROS_SETUPS <<< "${ATR_SPECIMEN_POSE_ROS_SETUP_PATHS:-/opt/ros/jazzy/setup.bash}"
for setup in "${ROS_SETUPS[@]}"; do
  source_setup "${setup}"
done
IFS=':' read -ra EXTRA_SETUPS <<< "${ATR_SPECIMEN_POSE_EXTRA_SETUP_PATHS:-${REPO_ROOT}/ros/install/setup.bash}"
for setup in "${EXTRA_SETUPS[@]}"; do
  source_setup "${setup}"
done

python3 - "$PAYLOAD_JSON" "$REPO_ROOT" <<'PY'
import json
import os
import subprocess
import sys

payload = json.loads(sys.argv[1] or "{}")
repo_root = sys.argv[2]
specimen_id = str(payload.get("specimen_id") or "specimen-live")
output_dir = str(payload.get("output_dir") or f"{repo_root}/runs/specimen_pose_tracker")
camera_id = str(payload.get("camera_id") or os.environ.get("ATR_SPECIMEN_POSE_CAMERA_ID") or "d455f_global")
workspace = str(payload.get("workspace") or "a4_robot_workspace")
color_topic = str(payload.get("color_topic") or os.environ.get("ATR_SPECIMEN_POSE_COLOR_TOPIC") or "/camera/d455f/color/image_raw")
depth_topic = str(payload.get("depth_topic") or os.environ.get("ATR_SPECIMEN_POSE_DEPTH_TOPIC") or "/camera/d455f/aligned_depth_to_color/image_raw")
info_topic = str(payload.get("info_topic") or os.environ.get("ATR_SPECIMEN_POSE_INFO_TOPIC") or "/camera/d455f/color/camera_info")
timeout_sec = str(payload.get("timeout_sec") or os.environ.get("ATR_SPECIMEN_POSE_TIMEOUT_SEC") or "8")
threshold = str(payload.get("confidence_threshold") or os.environ.get("ATR_SPECIMEN_POSE_THRESHOLD") or "0.75")
min_area = str(payload.get("min_contour_area_px") or os.environ.get("ATR_SPECIMEN_POSE_MIN_CONTOUR_AREA_PX") or "20")
offset_x = str(payload.get("camera_to_robot_x_mm") or os.environ.get("ATR_SPECIMEN_POSE_CAMERA_TO_ROBOT_X_MM") or "0")
offset_y = str(payload.get("camera_to_robot_y_mm") or os.environ.get("ATR_SPECIMEN_POSE_CAMERA_TO_ROBOT_Y_MM") or "0")
offset_z = str(payload.get("camera_to_robot_z_mm") or os.environ.get("ATR_SPECIMEN_POSE_CAMERA_TO_ROBOT_Z_MM") or "0")

direct_node = f"{repo_root}/ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker/specimen_pose_node.py"
base_cmd = [sys.executable, direct_node]
try:
    probe = subprocess.run(["ros2", "pkg", "prefix", "atr_specimen_pose_tracker"], text=True, capture_output=True, check=False)
    if probe.returncode == 0:
        base_cmd = ["ros2", "run", "atr_specimen_pose_tracker", "specimen_pose_node"]
except FileNotFoundError:
    pass

cmd = base_cmd + [
    "--specimen-id", specimen_id,
    "--camera-id", camera_id,
    "--workspace", workspace,
    "--color-topic", color_topic,
    "--depth-topic", depth_topic,
    "--info-topic", info_topic,
    "--output-dir", output_dir,
    "--timeout-sec", timeout_sec,
    "--confidence-threshold", threshold,
    "--min-contour-area-px", min_area,
    "--camera-to-robot-x-mm", offset_x,
    "--camera-to-robot-y-mm", offset_y,
    "--camera-to-robot-z-mm", offset_z,
]
completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
if completed.stdout:
    print(completed.stdout, end="")
if completed.stderr:
    print(completed.stderr, file=sys.stderr, end="")
sys.exit(completed.returncode)
PY
