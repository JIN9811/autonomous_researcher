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
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

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
realsense_serial = str(
    payload.get("realsense_serial")
    or payload.get("d455f_serial")
    or os.environ.get("ATR_SPECIMEN_POSE_REALSENSE_SERIAL")
    or os.environ.get("ATR_D455F_SERIAL")
    or "341522300873"
)
camera_startup_timeout_sec = float(
    payload.get("camera_startup_timeout_sec")
    or os.environ.get("ATR_SPECIMEN_POSE_CAMERA_STARTUP_TIMEOUT_SEC")
    or "5.0"
)


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


autostart_realsense = _as_bool(
    payload.get("autostart_realsense", os.environ.get("ATR_SPECIMEN_POSE_AUTOSTART_REALSENSE")),
    False,
)


def _failure(code, message, **extra):
    result = {"ok": False, "failure_code": code, "message": message, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    result.update(extra)
    return result


def _print_failure(code, message, **extra):
    print(json.dumps(_failure(code, message, **extra), ensure_ascii=True), flush=True)
    raise SystemExit(2)


def _safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_frame_manifest(path):
    manifest_path = Path(str(path or "")).expanduser()
    if not manifest_path.is_file():
        return None, f"LeRobot frame manifest not found: {manifest_path}"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")), ""
    except Exception as exc:
        return None, f"LeRobot frame manifest is invalid: {exc.__class__.__name__}: {exc}"


def _load_depth_mm_from_manifest(manifest):
    try:
        import cv2
        import numpy as np
    except Exception:
        return None, "depth_import_failed"
    raw_depth_path = str(manifest.get("raw_depth_image_path") or "")
    depth = None
    source = ""
    if raw_depth_path and Path(raw_depth_path).is_file():
        depth = cv2.imread(raw_depth_path, cv2.IMREAD_UNCHANGED)
        source = "raw_uint16_mm"
    if depth is None:
        return None, "raw_depth_missing"
    if depth.ndim == 3:
        depth = depth[..., 0]
    depth = depth.astype(np.float64)
    invalid = ~np.isfinite(depth) | (depth <= 0)
    camera_scales = manifest.get("camera_depth_scale_m_per_unit") if isinstance(manifest, dict) else {}
    camera_key = str(manifest.get("camera_key") or "") if isinstance(manifest, dict) else ""
    camera_depth_scale = None
    if isinstance(camera_scales, dict) and camera_key:
        camera_depth_scale = camera_scales.get(camera_key)
    depth_scale = _safe_float(camera_depth_scale if camera_depth_scale is not None else manifest.get("depth_scale_m_per_unit"), 0.001)
    if depth_scale > 0.0:
        depth = depth * depth_scale * 1000.0
    depth[invalid] = np.nan
    return depth, source


def _stats_from_depth_values(values):
    try:
        import numpy as np
    except Exception:
        return {}
    arr = np.asarray(values, dtype=np.float64)
    valid = arr[np.isfinite(arr) & (arr > 0.0)]
    if valid.size == 0:
        return {}
    return {
        "sample_count": int(valid.size),
        "median": round(float(np.median(valid)), 3),
        "p10": round(float(np.percentile(valid, 10)), 3),
        "p90": round(float(np.percentile(valid, 90)), 3),
        "min": round(float(np.min(valid)), 3),
        "max": round(float(np.max(valid)), 3),
    }


def _depth_stats_in_window(depth_mm_image, center_x, center_y, radius_px=4):
    if depth_mm_image is None:
        return {}
    y0, y1 = max(int(center_y) - radius_px, 0), min(int(center_y) + radius_px + 1, depth_mm_image.shape[0])
    x0, x1 = max(int(center_x) - radius_px, 0), min(int(center_x) + radius_px + 1, depth_mm_image.shape[1])
    return _stats_from_depth_values(depth_mm_image[y0:y1, x0:x1])


def _a4_local_plane_depth_stats(depth_mm_image, a4_mapping, center_x, center_y, bbox_xyxy, radius_px=55, exclude_pad_px=8):
    if depth_mm_image is None or not isinstance(a4_mapping, dict):
        return {}
    try:
        import cv2
        import numpy as np
    except Exception:
        return {}
    quad = np.asarray(a4_mapping.get("quad_px") or [], dtype=np.int32).reshape(-1, 2)
    if quad.shape[0] != 4:
        return {}
    mask = np.zeros(depth_mm_image.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [quad], 255)
    window = np.zeros_like(mask)
    x0 = max(int(center_x) - radius_px, 0)
    x1 = min(int(center_x) + radius_px + 1, depth_mm_image.shape[1])
    y0 = max(int(center_y) - radius_px, 0)
    y1 = min(int(center_y) + radius_px + 1, depth_mm_image.shape[0])
    window[y0:y1, x0:x1] = 255
    mask = cv2.bitwise_and(mask, window)
    bx0, by0, bx1, by1 = [int(value) for value in bbox_xyxy]
    mask[
        max(by0 - exclude_pad_px, 0) : min(by1 + exclude_pad_px, mask.shape[0]),
        max(bx0 - exclude_pad_px, 0) : min(bx1 + exclude_pad_px, mask.shape[1]),
    ] = 0
    return _stats_from_depth_values(depth_mm_image[mask > 0])


def _order_quad_points(points):
    import numpy as np

    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    rect = np.zeros((4, 2), dtype=np.float32)
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).reshape(4)
    rect[0] = pts[np.argmin(sums)]
    rect[2] = pts[np.argmax(sums)]
    rect[1] = pts[np.argmin(diffs)]
    rect[3] = pts[np.argmax(diffs)]
    return rect


def _detect_a4_quad(color_bgr, center_x=None, center_y=None, *, workspace_width_mm=250.0, workspace_height_mm=170.0):
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2HSV)
    white_mask = cv2.inRange(hsv, np.array([0, 0, 115], dtype=np.uint8), np.array([180, 130, 255], dtype=np.uint8))
    kernel = np.ones((9, 9), np.uint8)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, white_mask, "no_white_contour"
    target_aspect = max(workspace_width_mm, workspace_height_mm) / max(
        1.0,
        min(workspace_width_mm, workspace_height_mm),
    )
    best = None
    best_score = -1.0
    containing_best = None
    containing_best_score = -1.0
    image_area = max(1.0, float(color_bgr.shape[0] * color_bgr.shape[1]))
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area / image_area < 0.01:
            continue
        rect = cv2.minAreaRect(contour)
        (rw, rh) = rect[1]
        if rw <= 1.0 or rh <= 1.0:
            continue
        aspect = max(rw, rh) / max(1.0, min(rw, rh))
        aspect_error = abs(np.log(aspect / target_aspect))
        quad = _order_quad_points(cv2.boxPoints(rect))
        contains_center = False
        if center_x is not None and center_y is not None:
            contains_center = cv2.pointPolygonTest(quad, (float(center_x), float(center_y)), False) >= 0.0
        score = area / (1.0 + aspect_error * 4.0)
        if contains_center and score > containing_best_score:
            containing_best_score = score
            containing_best = quad
        if score > best_score:
            best_score = score
            best = quad
    if containing_best is not None:
        return containing_best, white_mask, ""
    if best is None:
        return None, white_mask, "no_a4_like_contour"
    return best, white_mask, ""


def _contour_center_px(contour, bbox):
    import cv2

    x, y, w, h = bbox
    moments = cv2.moments(contour)
    area = float(moments.get("m00") or 0.0)
    if abs(area) > 1e-6:
        return int(round(float(moments["m10"]) / area)), int(round(float(moments["m01"]) / area)), "contour_moments"
    return int(x + w / 2), int(y + h / 2), "bbox_center"


def _map_point_to_a4_mm(color_bgr, center_x, center_y):
    import cv2
    import numpy as np

    a4_width_mm = _safe_float(
        payload.get("a4_width_mm")
        or payload.get("a4_lateral_mm")
        or os.environ.get("ATR_SPECIMEN_A4_WIDTH_MM")
        or os.environ.get("ATR_SPECIMEN_A4_LATERAL_MM"),
        250.0,
    )
    a4_height_mm = _safe_float(
        payload.get("a4_height_mm")
        or payload.get("a4_forward_mm")
        or os.environ.get("ATR_SPECIMEN_A4_HEIGHT_MM")
        or os.environ.get("ATR_SPECIMEN_A4_FORWARD_MM"),
        170.0,
    )
    quad, white_mask, error = _detect_a4_quad(
        color_bgr,
        center_x=center_x,
        center_y=center_y,
        workspace_width_mm=a4_width_mm,
        workspace_height_mm=a4_height_mm,
    )
    if quad is None:
        return None, white_mask, {"a4_detected": False, "a4_failure_code": error}
    dst = np.array(
        [
            [0.0, a4_height_mm],
            [a4_width_mm, a4_height_mm],
            [a4_width_mm, 0.0],
            [0.0, 0.0],
        ],
        dtype=np.float32,
    )
    homography = cv2.getPerspectiveTransform(quad, dst)
    point = np.array([[[float(center_x), float(center_y)]]], dtype=np.float32)
    local = cv2.perspectiveTransform(point, homography)[0, 0]
    local_x = float(local[0])
    local_y = float(local[1])
    inside = -1.0 <= local_x <= a4_width_mm + 1.0 and -1.0 <= local_y <= a4_height_mm + 1.0
    local_x = min(max(local_x, 0.0), a4_width_mm)
    local_y = min(max(local_y, 0.0), a4_height_mm)
    crop_width_px = max(1, int(round(a4_width_mm)))
    crop_height_px = max(1, int(round(a4_height_mm)))
    return (
        {
            "local_x_mm": local_x,
            "local_y_mm": local_y,
            "inside": inside,
            "quad_px": [[round(float(x), 3), round(float(y), 3)] for x, y in quad],
            "a4_width_mm": a4_width_mm,
            "a4_height_mm": a4_height_mm,
            "crop_width_px": crop_width_px,
            "crop_height_px": crop_height_px,
            "homography": [[float(value) for value in row] for row in homography.tolist()],
        },
        white_mask,
        {"a4_detected": True, "a4_failure_code": ""},
    )


def _select_red_contour_inside_a4(color_bgr, contours, min_area_px):
    import cv2

    best_any = None
    best_inside = None
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area_px:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        cx, cy, center_source = _contour_center_px(contour, (x, y, w, h))
        a4_mapping, a4_mask, a4_status = _map_point_to_a4_mm(color_bgr, cx, cy)
        candidate = {
            "contour": contour,
            "area": area,
            "bbox": (x, y, w, h),
            "center": (cx, cy),
            "center_source": center_source,
            "a4_mapping": a4_mapping,
            "a4_mask": a4_mask,
            "a4_status": a4_status,
        }
        if best_any is None or area > best_any["area"]:
            best_any = candidate
        if a4_mapping is not None and bool(a4_mapping.get("inside")):
            if best_inside is None or area > best_inside["area"]:
                best_inside = candidate
    return best_inside or best_any


def _camera_a4_to_isaac_a4_mm(camera_lateral_mm, camera_forward_mm):
    isaac_width_mm = _safe_float(
        payload.get("a4_isaac_width_mm")
        or os.environ.get("ATR_SPECIMEN_A4_ISAAC_WIDTH_MM"),
        170.0,
    )
    isaac_height_mm = _safe_float(
        payload.get("a4_isaac_height_mm")
        or os.environ.get("ATR_SPECIMEN_A4_ISAAC_HEIGHT_MM"),
        250.0,
    )
    transform = str(
        payload.get("a4_camera_to_isaac_transform")
        or os.environ.get("ATR_SPECIMEN_A4_CAMERA_TO_ISAAC_TRANSFORM")
        or "robot_right_plane"
    ).strip().lower()
    if transform in {"robot_right_plane", "right_plane", "right_side_camera"}:
        isaac_x_mm = isaac_width_mm - float(camera_forward_mm)
        isaac_y_mm = float(camera_lateral_mm)
    elif transform in {"robot_right_plane_flipped_y", "right_plane_flipped_y"}:
        isaac_x_mm = isaac_width_mm - float(camera_forward_mm)
        isaac_y_mm = isaac_height_mm - float(camera_lateral_mm)
    elif transform in {"direct", "identity"}:
        isaac_x_mm = float(camera_lateral_mm)
        isaac_y_mm = float(camera_forward_mm)
    else:
        _print_failure("SPECIMEN_A4_CAMERA_TRANSFORM_UNSUPPORTED", f"Unsupported A4 camera transform: {transform}")
    isaac_x_mm = min(max(isaac_x_mm, 0.0), isaac_width_mm)
    isaac_y_mm = min(max(isaac_y_mm, 0.0), isaac_height_mm)
    return {
        "transform": transform,
        "isaac_x_mm": isaac_x_mm,
        "isaac_y_mm": isaac_y_mm,
        "isaac_width_mm": isaac_width_mm,
        "isaac_height_mm": isaac_height_mm,
        "camera_lateral_mm": float(camera_lateral_mm),
        "camera_forward_mm": float(camera_forward_mm),
    }


def _normalize_axis_yaw_deg(yaw_deg):
    yaw = ((float(yaw_deg) + 90.0) % 180.0) - 90.0
    if yaw == -90.0:
        return 90.0
    return yaw


def _canonical_low_aspect_yaw_deg(yaw_deg):
    yaw = _normalize_axis_yaw_deg(yaw_deg)
    if yaw > 45.0:
        yaw -= 90.0
    elif yaw <= -45.0:
        yaw += 90.0
    return 0.0 if abs(yaw) < 1e-9 else yaw


def _yaw_min_aspect_ratio():
    return _safe_float(os.environ.get("ATR_SPECIMEN_YAW_MIN_ASPECT_RATIO"), 1.5)


def _estimate_specimen_yaw_deg(contour, a4_mapping, a4_isaac_mapping):
    try:
        import cv2
        import numpy as np
    except Exception:
        return 0.0, {"source": "unavailable", "aspect_ratio": 1.0, "sample_count": 0}
    if not isinstance(a4_mapping, dict):
        return 0.0, {"source": "a4_mapping_missing", "aspect_ratio": 1.0, "sample_count": 0}
    homography = np.asarray(a4_mapping.get("homography") or [], dtype=np.float32)
    if homography.shape != (3, 3):
        return 0.0, {"source": "homography_missing", "aspect_ratio": 1.0, "sample_count": 0}
    points_px = np.asarray(contour, dtype=np.float32).reshape(-1, 1, 2)
    if points_px.shape[0] < 4:
        return 0.0, {"source": "contour_too_small", "aspect_ratio": 1.0, "sample_count": int(points_px.shape[0])}
    points_a4 = cv2.perspectiveTransform(points_px, homography).reshape(-1, 2).astype(np.float64)
    finite = np.isfinite(points_a4).all(axis=1)
    points_a4 = points_a4[finite]
    if points_a4.shape[0] < 4:
        return 0.0, {"source": "a4_points_invalid", "aspect_ratio": 1.0, "sample_count": int(points_a4.shape[0])}
    try:
        rect = cv2.minAreaRect(points_a4.astype(np.float32).reshape(-1, 1, 2))
        box = cv2.boxPoints(rect).astype(np.float64)
    except Exception:
        return 0.0, {"source": "min_area_rect_failed", "aspect_ratio": 1.0, "sample_count": int(points_a4.shape[0])}
    edges = [box[(index + 1) % 4] - box[index] for index in range(4)]
    lengths = np.asarray([float(np.linalg.norm(edge)) for edge in edges], dtype=np.float64)
    if not np.isfinite(lengths).all() or float(np.max(lengths)) <= 1e-9:
        return 0.0, {"source": "min_area_rect_degenerate", "aspect_ratio": 1.0, "sample_count": int(points_a4.shape[0])}
    major_index = int(np.argmax(lengths))
    major = max(float(lengths[major_index]), 1e-9)
    minor = max(float(np.min(lengths)), 1e-9)
    aspect_ratio = major / minor
    vector_camera = edges[major_index].astype(np.float64) / major
    if vector_camera[0] < 0:
        vector_camera *= -1.0
    transform = str(a4_isaac_mapping.get("transform") or "").strip().lower() if isinstance(a4_isaac_mapping, dict) else ""
    if transform in {"robot_right_plane", "right_plane", "right_side_camera"}:
        vector_isaac = np.array([-vector_camera[1], vector_camera[0]], dtype=np.float64)
    elif transform in {"robot_right_plane_flipped_y", "right_plane_flipped_y"}:
        vector_isaac = np.array([-vector_camera[1], -vector_camera[0]], dtype=np.float64)
    else:
        vector_isaac = np.array([vector_camera[0], vector_camera[1]], dtype=np.float64)
    if vector_isaac[0] < 0:
        vector_isaac *= -1.0
    raw_yaw = _normalize_axis_yaw_deg(math.degrees(math.atan2(float(vector_isaac[1]), float(vector_isaac[0]))))
    min_aspect_ratio = _yaw_min_aspect_ratio()
    if aspect_ratio < min_aspect_ratio:
        yaw = _canonical_low_aspect_yaw_deg(raw_yaw)
        canonical_axis = [round(float(math.cos(math.radians(yaw))), 6), round(float(math.sin(math.radians(yaw))), 6)]
        return yaw, {
            "source": "red_contour_a4_min_area_rect_low_aspect",
            "aspect_ratio": round(float(aspect_ratio), 3),
            "raw_yaw_deg": round(float(raw_yaw), 3),
            "low_aspect_yaw_canonicalized": True,
            "min_stable_aspect_ratio": round(float(min_aspect_ratio), 3),
            "sample_count": int(points_a4.shape[0]),
            "rect_size_mm": [round(float(major), 3), round(float(minor), 3)],
            "camera_axis": [round(float(vector_camera[0]), 6), round(float(vector_camera[1]), 6)],
            "isaac_axis": canonical_axis,
        }
    return raw_yaw, {
        "source": "red_contour_a4_min_area_rect",
        "aspect_ratio": round(float(aspect_ratio), 3),
        "sample_count": int(points_a4.shape[0]),
        "rect_size_mm": [round(float(major), 3), round(float(minor), 3)],
        "camera_axis": [round(float(vector_camera[0]), 6), round(float(vector_camera[1]), 6)],
        "isaac_axis": [round(float(vector_isaac[0]), 6), round(float(vector_isaac[1]), 6)],
    }


def _estimate_pose_from_lerobot_frame(manifest_path):
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        _print_failure("SPECIMEN_FRAME_DETECTOR_IMPORT_FAILED", f"{exc.__class__.__name__}: {exc}")
    manifest, manifest_error = _load_frame_manifest(manifest_path)
    if not isinstance(manifest, dict):
        _print_failure("SPECIMEN_LEROBOT_FRAME_MISSING", manifest_error)
    color_path = Path(str(manifest.get("color_image_path") or "")).expanduser()
    if not color_path.is_file():
        _print_failure("SPECIMEN_LEROBOT_FRAME_MISSING", f"LeRobot color frame not found: {color_path}")
    color = cv2.imread(str(color_path), cv2.IMREAD_COLOR)
    if color is None:
        _print_failure("SPECIMEN_LEROBOT_FRAME_INVALID", f"Could not decode LeRobot color frame: {color_path}")

    hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)
    red_mask = cv2.inRange(hsv, np.array([0, 120, 100], dtype=np.uint8), np.array([12, 255, 255], dtype=np.uint8))
    red_mask |= cv2.inRange(hsv, np.array([168, 120, 100], dtype=np.uint8), np.array([180, 255, 255], dtype=np.uint8))
    kernel = np.ones((5, 5), np.uint8)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        _print_failure("SPECIMEN_NOT_DETECTED", "No red specimen contour was detected in LeRobot latest frame.")
    min_area_px = _safe_float(min_area, 20.0)
    selected = _select_red_contour_inside_a4(color, contours, min_area_px)
    if selected is None:
        area = max((float(cv2.contourArea(contour)) for contour in contours), default=0.0)
        _print_failure(
            "SPECIMEN_CONTOUR_TOO_SMALL",
            f"Detected contour area {area:.1f}px is below {min_area_px:.1f}px.",
            contour_area_px=area,
        )
    contour = selected["contour"]
    area = float(selected["area"])
    x, y, w, h = selected["bbox"]
    cx, cy = selected["center"]
    depth_mm_image, depth_source = _load_depth_mm_from_manifest(manifest)
    specimen_depth_stats = _depth_stats_in_window(depth_mm_image, cx, cy, radius_px=4)
    depth_mm = specimen_depth_stats.get("median")
    if depth_mm is None:
        depth_mm = _safe_float(payload.get("default_depth_mm") or manifest.get("default_depth_mm"), 620.0)
        depth_source = depth_source or "default_depth_mm"
    a4_mapping = selected["a4_mapping"]
    a4_mask = selected["a4_mask"]
    a4_status = selected["a4_status"]
    if a4_mapping is None:
        _print_failure(
            "SPECIMEN_A4_NOT_DETECTED",
            "A4 sheet could not be detected in the LeRobot latest frame; refusing to map cube XY outside the A4 workspace.",
            a4_failure_code=a4_status.get("a4_failure_code"),
        )
    if not a4_mapping["inside"]:
        _print_failure(
            "SPECIMEN_OUTSIDE_A4",
            "Detected red specimen center is outside the detected A4 sheet.",
            position_a4_mm={"x": round(a4_mapping["local_x_mm"], 3), "y": round(a4_mapping["local_y_mm"], 3)},
            a4_quad_px=a4_mapping["quad_px"],
        )
    a4_plane_depth_stats = _a4_local_plane_depth_stats(depth_mm_image, a4_mapping, cx, cy, [x, y, x + w, y + h])
    specimen_above_a4_plane_mm = None
    if specimen_depth_stats.get("median") is not None and a4_plane_depth_stats.get("median") is not None:
        specimen_above_a4_plane_mm = round(float(a4_plane_depth_stats["median"]) - float(specimen_depth_stats["median"]), 3)
    depth_alignment = {
        "source": depth_source,
        "specimen_sample_count": int(specimen_depth_stats.get("sample_count") or 0),
        "a4_local_plane_sample_count": int(a4_plane_depth_stats.get("sample_count") or 0),
        "specimen_above_a4_plane_mm": specimen_above_a4_plane_mm,
        "aligned_to_color": bool(depth_mm_image is not None),
    }

    height, width = color.shape[:2]
    fx = _safe_float(payload.get("camera_fx_px") or manifest.get("fx_px"), max(width, 1))
    fy = _safe_float(payload.get("camera_fy_px") or manifest.get("fy_px"), max(width, 1))
    ppx = _safe_float(payload.get("camera_ppx_px") or manifest.get("ppx_px"), width / 2.0)
    ppy = _safe_float(payload.get("camera_ppy_px") or manifest.get("ppy_px"), height / 2.0)
    camera_x_mm = (cx - ppx) * depth_mm / fx
    camera_y_mm = (cy - ppy) * depth_mm / fy
    robot_x_mm = camera_x_mm + _safe_float(offset_x, 0.0)
    robot_y_mm = camera_y_mm + _safe_float(offset_y, 0.0)
    robot_z_mm = depth_mm + _safe_float(offset_z, 0.0)
    a4_world_min_x_mm = _safe_float(payload.get("a4_world_min_x_mm") or os.environ.get("ATR_SPECIMEN_A4_WORLD_MIN_X_MM"), 230.0)
    a4_world_min_y_mm = _safe_float(payload.get("a4_world_min_y_mm") or os.environ.get("ATR_SPECIMEN_A4_WORLD_MIN_Y_MM"), 120.0)
    a4_world_offset_x_mm = _safe_float(payload.get("a4_world_offset_x_mm") or os.environ.get("ATR_SPECIMEN_A4_WORLD_OFFSET_X_MM"), 0.0)
    a4_world_offset_y_mm = _safe_float(payload.get("a4_world_offset_y_mm") or os.environ.get("ATR_SPECIMEN_A4_WORLD_OFFSET_Y_MM"), 0.0)
    isaac_world_z_mm = _safe_float(payload.get("isaac_world_z_mm") or os.environ.get("ATR_SPECIMEN_ISAAC_WORLD_Z_MM"), 15.2)
    a4_isaac_mapping = _camera_a4_to_isaac_a4_mm(a4_mapping["local_x_mm"], a4_mapping["local_y_mm"])
    isaac_world_x_mm = a4_world_min_x_mm + a4_isaac_mapping["isaac_x_mm"] + a4_world_offset_x_mm
    isaac_world_y_mm = a4_world_min_y_mm + a4_isaac_mapping["isaac_y_mm"] + a4_world_offset_y_mm
    specimen_yaw_deg, orientation_quality = _estimate_specimen_yaw_deg(contour, a4_mapping, a4_isaac_mapping)

    output = Path(output_dir).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    debug = color.copy()
    cv2.polylines(debug, [np.asarray(a4_mapping["quad_px"], dtype=np.int32)], True, (255, 200, 20), 2)
    cv2.rectangle(debug, (x, y), (x + w, y + h), (20, 220, 130), 2)
    cv2.circle(debug, (cx, cy), 5, (255, 255, 0), -1)
    debug_path = output / "specimen_pose_lerobot_frame_debug.png"
    crop_path = output / "specimen_pose_lerobot_frame_a4_crop.png"
    pose_path = output / "specimen_pose_lerobot_frame.json"
    cv2.imwrite(str(debug_path), debug)
    try:
        crop = cv2.warpPerspective(
            color,
            np.asarray(a4_mapping["homography"], dtype=np.float32),
            (int(a4_mapping["crop_width_px"]), int(a4_mapping["crop_height_px"])),
        )
        cv2.circle(crop, (int(round(a4_mapping["local_x_mm"])), int(round(a4_mapping["local_y_mm"]))), 4, (255, 255, 0), -1)
        cv2.imwrite(str(crop_path), crop)
    except Exception:
        crop_path = Path("")

    image_area = float(max(1, width * height))
    a4_area_px = max(1.0, float(cv2.contourArea(np.asarray(a4_mapping["quad_px"], dtype=np.float32))))
    confidence = min(0.99, max(0.0, (area / image_area) * 18.0, (area / a4_area_px) * 18.0))
    threshold_value = _safe_float(threshold, 0.75)
    mapping_label = str(a4_isaac_mapping["transform"])
    if mapping_label == "robot_right_plane":
        mapping_label = "right_plane"
    pose = {
        "schema": "specimen_pose.v1",
        "source": "lerobot_latest_frame",
        "stage": "post_ejection_workspace_localization",
        "camera_id": str(manifest.get("camera_key") or camera_id),
        "camera_owner_before": "vla_runtime",
        "camera_owner_after": "vla_runtime",
        "workspace": workspace,
        "specimen_id": specimen_id,
        "frame_id": str(manifest.get("frame_id") or f"lerobot-frame-{int(time.time() * 1000)}"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "center_px": [cx, cy],
        "center_source": str(selected.get("center_source") or ""),
        "bbox_xyxy": [int(x), int(y), int(x + w), int(y + h)],
        "contour_area_px": round(area, 3),
        "depth_mm": round(depth_mm, 3),
        "depth_source": depth_source,
        "coordinate_mapping": f"a4_{mapping_label}_crop_rgb_homography_xy_depth_checked",
        "a4_detected": bool(a4_status.get("a4_detected")),
        "a4_quad_px": a4_mapping["quad_px"],
        "a4_area_px": round(a4_area_px, 3),
        "a4_width_mm": round(float(a4_mapping["a4_width_mm"]), 3),
        "a4_height_mm": round(float(a4_mapping["a4_height_mm"]), 3),
        "a4_camera_to_isaac_transform": a4_isaac_mapping["transform"],
        "a4_isaac_width_mm": round(float(a4_isaac_mapping["isaac_width_mm"]), 3),
        "a4_isaac_height_mm": round(float(a4_isaac_mapping["isaac_height_mm"]), 3),
        "a4_world_min_mm": {"x": round(float(a4_world_min_x_mm), 3), "y": round(float(a4_world_min_y_mm), 3)},
        "a4_world_offset_mm": {"x": round(float(a4_world_offset_x_mm), 3), "y": round(float(a4_world_offset_y_mm), 3)},
        "specimen_depth_stats_mm": specimen_depth_stats,
        "a4_local_plane_depth_stats_mm": a4_plane_depth_stats,
        "depth_alignment": depth_alignment,
        "position_camera_mm": {"x": round(camera_x_mm, 3), "y": round(camera_y_mm, 3), "z": round(depth_mm, 3)},
        "position_robot_base_mm": {"x": round(isaac_world_x_mm, 3), "y": round(isaac_world_y_mm, 3), "z": round(isaac_world_z_mm, 3)},
        "position_camera_a4_mm": {
            "lateral_x": round(a4_mapping["local_x_mm"], 3),
            "forward_y": round(a4_mapping["local_y_mm"], 3),
            "z": round(isaac_world_z_mm, 3),
        },
        "position_a4_mm": {
            "x": round(a4_isaac_mapping["isaac_x_mm"], 3),
            "y": round(a4_isaac_mapping["isaac_y_mm"], 3),
            "z": round(isaac_world_z_mm, 3),
        },
        "position_isaac_world_mm": {"x": round(isaac_world_x_mm, 3), "y": round(isaac_world_y_mm, 3), "z": round(isaac_world_z_mm, 3)},
        "orientation_deg": {"yaw": round(float(specimen_yaw_deg), 3)},
        "orientation_source": str(orientation_quality.get("source") or ""),
        "orientation_quality": orientation_quality,
        "confidence": round(confidence, 3),
        "stable_frames": 1,
        "freshness_ms": int(max(0.0, (time.time() - _safe_float(manifest.get("time_unix_s"), time.time())) * 1000.0)),
        "port_released": True,
        "vla_camera_precheck_ok": True,
        "debug_image_path": str(debug_path),
        "a4_crop_image_path": str(crop_path),
        "raw_pose_json_path": str(pose_path),
        "frame_manifest_path": str(Path(str(manifest_path)).expanduser()),
    }
    pose_path.write_text(json.dumps(pose, ensure_ascii=True, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": confidence >= threshold_value,
                "pose": pose,
                "failure_code": "" if confidence >= threshold_value else "SPECIMEN_POSE_LOW_CONFIDENCE",
                "message": "" if confidence >= threshold_value else f"confidence={confidence:.3f} below threshold={threshold_value:.3f}",
            },
            ensure_ascii=True,
        ),
        flush=True,
    )
    raise SystemExit(0 if confidence >= threshold_value else 2)


frame_manifest_path = payload.get("frame_manifest_path") or os.environ.get("ATR_LEROBOT_LATEST_FRAME_MANIFEST")
if frame_manifest_path:
    _estimate_pose_from_lerobot_frame(frame_manifest_path)


def _run_topic_list():
    try:
        completed = subprocess.run(["ros2", "topic", "list"], text=True, capture_output=True, timeout=2.0, check=False)
    except FileNotFoundError:
        return [], "ros2 executable was not found"
    except subprocess.TimeoutExpired:
        return [], "ros2 topic list timed out"
    if completed.returncode != 0:
        return [], (completed.stderr or completed.stdout or f"ros2 topic list exited with returncode={completed.returncode}").strip()
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()], ""


def _missing_topics(available_topics):
    available = set(available_topics)
    return [topic for topic in (color_topic, depth_topic, info_topic) if topic not in available]


def _serial_arg(serial):
    value = str(serial or "").strip().strip("'\"")
    if not value:
        return ""
    return value if value.startswith("_") else f"_{value}"


def _launch_realsense_camera():
    cmd = [
        "ros2",
        "launch",
        "realsense2_camera",
        "rs_launch.py",
        "camera_namespace:=camera",
        "camera_name:=d455f",
        "enable_color:=true",
        "enable_depth:=true",
        "align_depth.enable:=true",
        "enable_sync:=true",
        "rgb_camera.color_profile:=640x480x15",
        "depth_module.depth_profile:=640x480x15",
        "pointcloud.enable:=false",
        "initial_reset:=false",
        "wait_for_device_timeout:=5.0",
        "reconnect_timeout:=1.0",
        "output:=screen",
    ]
    serial_arg = _serial_arg(realsense_serial)
    if serial_arg:
        cmd.append(f"serial_no:={serial_arg}")
    return subprocess.Popen(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def terminate_camera_process(process):
    if process is None:
        return ""
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                process.kill()
            process.wait(timeout=2.0)
    try:
        stdout, stderr = process.communicate(timeout=0.2)
    except Exception:
        return ""
    return ((stdout or "") + "\n" + (stderr or "")).strip()


def _wait_for_topics(startup_timeout_sec):
    deadline = time.monotonic() + max(float(startup_timeout_sec), 0.1)
    available = []
    topic_error = ""
    while time.monotonic() < deadline:
        available, topic_error = _run_topic_list()
        if not _missing_topics(available):
            return available, topic_error
        time.sleep(0.1)
    return available, topic_error


available_topics, topic_error = _run_topic_list()
missing_topics = _missing_topics(available_topics)
camera_process = None
camera_launch_error = ""
camera_launch_output = ""
try:
    if missing_topics and autostart_realsense:
        try:
            camera_process = _launch_realsense_camera()
        except FileNotFoundError as exc:
            camera_launch_error = f"{exc.__class__.__name__}: {exc}"
        except Exception as exc:
            camera_launch_error = f"{exc.__class__.__name__}: {exc}"
        if camera_process is not None:
            available_topics, topic_error = _wait_for_topics(camera_startup_timeout_sec)
            missing_topics = _missing_topics(available_topics)
            if missing_topics:
                camera_launch_output = terminate_camera_process(camera_process)
                camera_process = None
    if missing_topics:
        _print_failure(
            "SPECIMEN_ROS_CAMERA_TOPICS_MISSING",
            "ROS2 camera topics are missing; D455F is not publishing RGB-D frames for specimen pose tracking.",
            required_topics=[color_topic, depth_topic, info_topic],
            missing_topics=missing_topics,
            available_topics=available_topics,
            topic_list_error=topic_error,
            autostart_realsense=autostart_realsense,
            realsense_serial=realsense_serial,
            realsense_launch_attempted=autostart_realsense,
            realsense_launch_error=camera_launch_error,
            realsense_launch_output_tail=camera_launch_output[-2000:],
        )

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
finally:
    terminate_camera_process(camera_process)
PY
