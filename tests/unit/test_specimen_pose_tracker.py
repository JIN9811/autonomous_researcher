from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from device_bridges.specimen_pose_tracker import (
    SpecimenPoseTrackerBridge,
    SpecimenPoseTrackerConfig,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _bridge(tmp_path: Path) -> SpecimenPoseTrackerBridge:
    return SpecimenPoseTrackerBridge(
        SpecimenPoseTrackerConfig(
            enabled=True,
            d455f_serial="341522300873",
            script_path=tmp_path / "run_specimen_pose_snapshot.sh",
            log_dir=tmp_path / "logs",
            artifact_dir=tmp_path / "artifacts",
            ros_setup_paths=[],
            extra_setup_paths=[],
            max_runtime_sec=8.0,
            release_timeout_sec=5.0,
            allow_virtual_pose_in_test=True,
        )
    )


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON object in stdout: {stdout}")


def _a4_local_to_image_points(
    points_mm: np.ndarray,
    *,
    a4_px: tuple[int, int, int, int],
    a4_mm: tuple[float, float],
) -> np.ndarray:
    x0, y0, x1, y1 = a4_px
    width_mm, height_mm = a4_mm
    points = np.asarray(points_mm, dtype=np.float64)
    image_x = x0 + (points[:, 0] / width_mm) * (x1 - x0)
    image_y = y1 - (points[:, 1] / height_mm) * (y1 - y0)
    return np.column_stack([image_x, image_y]).round().astype(np.int32)


def _rotated_a4_rect_points(
    *,
    center_mm: tuple[float, float],
    size_mm: tuple[float, float],
    yaw_deg: float,
) -> np.ndarray:
    cx, cy = center_mm
    width, height = size_mm
    half = np.array(
        [
            [-width / 2.0, -height / 2.0],
            [width / 2.0, -height / 2.0],
            [width / 2.0, height / 2.0],
            [-width / 2.0, height / 2.0],
        ],
        dtype=np.float64,
    )
    theta = math.radians(yaw_deg)
    rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    return half @ rotation.T + np.array([cx, cy], dtype=np.float64)


def test_virtual_snapshot_returns_pose_and_released_camera(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.snapshot({"mode": "test", "specimen_id": "specimen-1"})

    assert result["ok"] is True
    assert result["tool"] == "vision.specimen_pose_snapshot"
    assert result["pose"]["schema"] == "specimen_pose.v1"
    assert result["pose"]["specimen_id"] == "specimen-1"
    assert result["pose"]["camera_owner_before"] == "vla_runtime"
    assert result["pose"]["camera_owner_after"] == "vla_runtime"
    assert result["pose"]["port_released"] is True
    assert result["pose"]["vla_camera_precheck_ok"] is True
    assert result["lease"]["owner"] == "vla_runtime"


def test_live_snapshot_blocks_when_script_missing(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.snapshot({"mode": "live", "specimen_id": "specimen-1"})

    assert result["ok"] is False
    assert result["failure_code"] == "SPECIMEN_POSE_TRACKER_SCRIPT_NOT_FOUND"
    assert result["lease"]["owner"] in {"free", "vla_runtime"}


def test_release_status_reports_vla_owner(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    status = bridge.release({"mode": "test"})

    assert status["ok"] is True
    assert status["tool"] == "vision.specimen_pose.release"
    assert status["lease"]["owner"] == "vla_runtime"
    assert status["camera_returned_to_vla"] is True


def test_status_payload_is_gui_safe(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    status = bridge.status()

    assert status["ok"] is True
    assert status["tool"] == "vision.specimen_pose.status"
    assert status["enabled"] is True
    assert status["camera_id"] == "d455f_global"
    assert "api_key" not in str(status).lower()


def test_live_snapshot_command_parses_json_stdout(tmp_path: Path) -> None:
    script = tmp_path / "run_specimen_pose_snapshot.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "echo '{\"ok\": true, \"pose\": {\"schema\": \"specimen_pose.v1\", \"confidence\": 0.88}}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    bridge = SpecimenPoseTrackerBridge(
        SpecimenPoseTrackerConfig(script_path=script, log_dir=tmp_path / "logs", artifact_dir=tmp_path / "artifacts")
    )

    result = bridge.snapshot({"mode": "live", "specimen_id": "specimen-live"})

    assert result["ok"] is True
    assert result["pose"]["schema"] == "specimen_pose.v1"
    assert result["pose"]["camera_owner_after"] == "vla_runtime"
    assert result["pose"]["port_released"] is True


def test_ros_wrapper_matches_snapshot_node_contract() -> None:
    script = Path("scripts/vision/run_specimen_pose_snapshot.sh").read_text(encoding="utf-8")
    node = Path("ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker/specimen_pose_node.py").read_text(encoding="utf-8")

    assert '${1:-{}}' not in script
    assert "set +u" in script
    assert "ros2\", \"topic\", \"list\"" in script
    assert "SPECIMEN_ROS_CAMERA_TOPICS_MISSING" in script
    assert "ATR_SPECIMEN_POSE_AUTOSTART_REALSENSE" in script
    assert "ATR_SPECIMEN_POSE_REALSENSE_SERIAL" in script
    assert "terminate_camera_process" in script
    assert "realsense2_camera" in script
    assert "rs_launch.py" in script
    assert "camera_namespace:=camera" in script
    assert "camera_name:=d455f" in script
    assert "align_depth.enable:=true" in script
    assert "wait_for_device_timeout:=5.0" in script
    assert "serial_no:=" in script
    assert "--frame-id" not in script
    assert "--color-topic" in script
    assert "--depth-topic" in script
    assert "--info-topic" in script
    assert "/camera/d455f/color/image_raw" in script
    assert "/camera/d455f/aligned_depth_to_color/image_raw" in script
    assert "/camera/d455f/color/camera_info" in script
    assert "create_subscription(Image" in node
    assert "CameraInfo" in node
    assert "No red specimen contour was detected in {self.cfg.camera_id}" in node
    assert "red_contour_image_min_area_rect" in node
    assert "specimen_pose_debug.pgm" not in node


def test_ros_wrapper_reports_missing_camera_topics_before_snapshot_timeout(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ros2 = fake_bin / "ros2"
    fake_ros2.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == \"topic\" && \"${2:-}\" == \"list\" ]]; then\n"
        "  printf '/rosout\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"${1:-}\" == \"pkg\" && \"${2:-}\" == \"prefix\" ]]; then\n"
        "  exit 1\n"
        "fi\n"
        "exit 9\n",
        encoding="utf-8",
    )
    fake_ros2.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["ATR_SPECIMEN_POSE_ROS_SETUP_PATHS"] = str(tmp_path / "missing_ros_setup.bash")
    env["ATR_SPECIMEN_POSE_EXTRA_SETUP_PATHS"] = str(tmp_path / "missing_extra_setup.bash")
    env["ATR_SPECIMEN_POSE_AUTOSTART_REALSENSE"] = "0"

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps({"specimen_id": "redcube-test", "timeout_sec": 2.0}),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode != 0
    assert payload["ok"] is False
    assert payload["failure_code"] == "SPECIMEN_ROS_CAMERA_TOPICS_MISSING"
    assert payload["missing_topics"] == [
        "/camera/d455f/color/image_raw",
        "/camera/d455f/aligned_depth_to_color/image_raw",
        "/camera/d455f/color/camera_info",
    ]
    assert payload["available_topics"] == ["/rosout"]
    assert payload["autostart_realsense"] is False


def test_snapshot_wrapper_detects_redcube_from_lerobot_frame_manifest_without_ros(tmp_path: Path) -> None:
    color = np.zeros((120, 160, 3), dtype=np.uint8)
    color[:, :] = (40, 40, 40)
    color[20:100, 24:136] = (245, 245, 245)
    color[45:75, 65:95] = (255, 0, 0)
    depth = np.full((120, 160), 620, dtype=np.uint16)
    color_path = tmp_path / "top_color.png"
    depth_path = tmp_path / "top_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "top",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
                "depth_clip_min_mm": 0.0,
                "depth_clip_max_mm": 2000.0,
            }
        ),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ros2 = fake_bin / "ros2"
    fake_ros2.write_text("#!/usr/bin/env bash\necho 'ros2 must not be called for frame manifest' >&2\nexit 19\n", encoding="utf-8")
    fake_ros2.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["ATR_SPECIMEN_POSE_ROS_SETUP_PATHS"] = str(tmp_path / "missing_ros_setup.bash")
    env["ATR_SPECIMEN_POSE_EXTRA_SETUP_PATHS"] = str(tmp_path / "missing_extra_setup.bash")

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-file",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    assert payload["ok"] is True
    assert payload["pose"]["schema"] == "specimen_pose.v1"
    assert payload["pose"]["source"] == "lerobot_latest_frame"
    assert payload["pose"]["camera_id"] == "top"
    assert payload["pose"]["center_px"] == [80, 60]
    assert payload["pose"]["depth_mm"] == 620.0
    assert payload["pose"]["coordinate_mapping"] == "a4_right_plane_crop_rgb_homography_xy_depth_checked"
    assert Path(payload["pose"]["debug_image_path"]).is_file()
    assert Path(payload["pose"]["a4_crop_image_path"]).is_file()


def test_snapshot_wrapper_maps_redcube_xy_inside_a4_from_lerobot_frame(tmp_path: Path) -> None:
    color = np.zeros((220, 300, 3), dtype=np.uint8)
    color[:, :] = (35, 35, 35)
    a4_x0, a4_y0, a4_x1, a4_y1 = 40, 30, 238, 170
    color[a4_y0:a4_y1, a4_x0:a4_x1] = (245, 245, 245)
    color[58:72, 83:97] = (255, 0, 0)
    depth = np.full((220, 300), 777, dtype=np.uint16)
    color_path = tmp_path / "top_color.png"
    depth_path = tmp_path / "top_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "top",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-a4",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    assert payload["ok"] is True
    pose = payload["pose"]
    assert pose["coordinate_mapping"] == "a4_right_plane_crop_rgb_homography_xy_depth_checked"
    assert pose["a4_detected"] is True
    assert pose["depth_source"] == "raw_uint16_mm"
    assert pose["depth_mm"] == 777.0
    assert pose["a4_width_mm"] == pytest.approx(250.0)
    assert pose["a4_height_mm"] == pytest.approx(170.0)
    assert pose["a4_camera_to_isaac_transform"] == "robot_right_plane"
    assert pose["a4_isaac_width_mm"] == pytest.approx(170.0)
    assert pose["a4_isaac_height_mm"] == pytest.approx(250.0)
    assert pose["specimen_depth_stats_mm"]["median"] == pytest.approx(777.0)
    assert pose["a4_local_plane_depth_stats_mm"]["median"] == pytest.approx(777.0)
    assert pose["depth_alignment"]["source"] == "raw_uint16_mm"
    assert pose["depth_alignment"]["specimen_above_a4_plane_mm"] == pytest.approx(0.0)
    assert pose["confidence"] >= 0.05
    assert pose["position_camera_a4_mm"]["lateral_x"] == pytest.approx(63.13, abs=2.0)
    assert pose["position_camera_a4_mm"]["forward_y"] == pytest.approx(127.5, abs=2.0)
    assert pose["position_a4_mm"]["x"] == pytest.approx(42.5, abs=2.0)
    assert pose["position_a4_mm"]["y"] == pytest.approx(63.13, abs=2.0)
    assert pose["position_isaac_world_mm"]["x"] == pytest.approx(272.5, abs=2.0)
    assert pose["position_isaac_world_mm"]["y"] == pytest.approx(183.13, abs=2.0)
    assert pose["position_isaac_world_mm"]["z"] == pytest.approx(15.2, abs=0.01)
    assert pose["position_robot_base_mm"]["z"] == pytest.approx(15.2, abs=0.01)


def test_snapshot_wrapper_prefers_redcube_inside_a4_over_larger_red_distractor(tmp_path: Path) -> None:
    color = np.zeros((220, 300, 3), dtype=np.uint8)
    color[:, :] = (35, 35, 35)
    a4_x0, a4_y0, a4_x1, a4_y1 = 40, 30, 238, 170
    color[a4_y0:a4_y1, a4_x0:a4_x1] = (245, 245, 245)
    color[58:72, 83:97] = (255, 0, 0)
    color[178:214, 12:48] = (255, 0, 0)
    depth = np.full((220, 300), 777, dtype=np.uint16)
    color_path = tmp_path / "top_color_with_red_distractor.png"
    depth_path = tmp_path / "top_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "top",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-a4-distractor",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert payload["ok"] is True
    pose = payload["pose"]
    assert pose["center_source"] == "contour_moments"
    assert pose["center_px"] == [90, 64]
    assert pose["position_camera_a4_mm"]["lateral_x"] == pytest.approx(63.45, abs=2.0)
    assert pose["position_camera_a4_mm"]["forward_y"] == pytest.approx(128.71, abs=2.0)


def test_snapshot_wrapper_uses_contour_moment_center_for_asymmetric_redcube(tmp_path: Path) -> None:
    color = np.zeros((220, 300, 3), dtype=np.uint8)
    color[:, :] = (35, 35, 35)
    color[30:170, 40:238] = (245, 245, 245)
    red_poly = np.array(
        [
            (86, 56),
            (134, 56),
            (134, 76),
            (110, 76),
            (110, 116),
            (86, 116),
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(color, [red_poly], (255, 0, 0))
    depth = np.full((220, 300), 777, dtype=np.uint16)
    color_path = tmp_path / "wrist_color_asymmetric.png"
    depth_path = tmp_path / "wrist_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "wrist",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )

    bgr = cv2.cvtColor(color, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    red_mask = cv2.inRange(hsv, np.array([0, 120, 100], dtype=np.uint8), np.array([12, 255, 255], dtype=np.uint8))
    red_mask |= cv2.inRange(hsv, np.array([168, 120, 100], dtype=np.uint8), np.array([180, 255, 255], dtype=np.uint8))
    kernel = np.ones((5, 5), np.uint8)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(contour)
    bbox_center = [int(x + w / 2), int(y + h / 2)]
    moments = cv2.moments(contour)
    moment_center = [int(round(moments["m10"] / moments["m00"])), int(round(moments["m01"] / moments["m00"]))]
    assert moment_center != bbox_center

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-asymmetric-center",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                    "camera_id": "active_robot_cam_d405",
                    "a4_camera_to_isaac_transform": "direct",
                    "a4_width_mm": 297.0,
                    "a4_height_mm": 210.0,
                    "a4_isaac_width_mm": 297.0,
                    "a4_isaac_height_mm": 210.0,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    pose = payload["pose"]
    assert pose["center_source"] == "contour_moments"
    assert pose["center_px"] == moment_center


def test_snapshot_wrapper_uses_direct_a4_mapping_for_active_d405_frame(tmp_path: Path) -> None:
    color = np.zeros((220, 300, 3), dtype=np.uint8)
    color[:, :] = (35, 35, 35)
    a4_x0, a4_y0, a4_x1, a4_y1 = 40, 30, 238, 170
    color[a4_y0:a4_y1, a4_x0:a4_x1] = (245, 245, 245)
    color[58:72, 83:97] = (255, 0, 0)
    depth = np.full((220, 300), 777, dtype=np.uint16)
    color_path = tmp_path / "wrist_color.png"
    depth_path = tmp_path / "wrist_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "wrist",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-d405",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                    "camera_id": "active_robot_cam_d405",
                    "a4_camera_to_isaac_transform": "direct",
                    "a4_width_mm": 297.0,
                    "a4_height_mm": 210.0,
                    "a4_isaac_width_mm": 297.0,
                    "a4_isaac_height_mm": 210.0,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    pose = payload["pose"]
    assert pose["coordinate_mapping"] == "a4_direct_crop_rgb_homography_xy_depth_checked"
    assert pose["camera_id"] == "wrist"
    assert pose["a4_width_mm"] == pytest.approx(297.0)
    assert pose["a4_height_mm"] == pytest.approx(210.0)
    assert pose["a4_camera_to_isaac_transform"] == "direct"
    assert pose["position_camera_a4_mm"]["lateral_x"] == pytest.approx(75.0, abs=3.0)
    assert pose["position_camera_a4_mm"]["forward_y"] == pytest.approx(157.5, abs=3.0)
    assert pose["position_a4_mm"]["x"] == pytest.approx(pose["position_camera_a4_mm"]["lateral_x"], abs=0.01)
    assert pose["position_a4_mm"]["y"] == pytest.approx(pose["position_camera_a4_mm"]["forward_y"], abs=0.01)


def test_snapshot_wrapper_applies_a4_world_offset_after_direct_mapping(tmp_path: Path) -> None:
    color = np.zeros((220, 300, 3), dtype=np.uint8)
    color[:, :] = (35, 35, 35)
    color[30:170, 40:238] = (245, 245, 245)
    color[58:72, 83:97] = (255, 0, 0)
    depth = np.full((220, 300), 777, dtype=np.uint16)
    color_path = tmp_path / "wrist_color_offset.png"
    depth_path = tmp_path / "wrist_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "wrist",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-d405-offset",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                    "camera_id": "active_robot_cam_d405",
                    "a4_camera_to_isaac_transform": "direct",
                    "a4_width_mm": 297.0,
                    "a4_height_mm": 210.0,
                    "a4_isaac_width_mm": 297.0,
                    "a4_isaac_height_mm": 210.0,
                    "a4_world_offset_x_mm": 10.0,
                    "a4_world_offset_y_mm": -5.0,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    pose = payload["pose"]
    assert pose["a4_world_offset_mm"] == {"x": 10.0, "y": -5.0}
    assert pose["position_isaac_world_mm"]["x"] == pytest.approx(230.0 + pose["position_a4_mm"]["x"] + 10.0)
    assert pose["position_isaac_world_mm"]["y"] == pytest.approx(120.0 + pose["position_a4_mm"]["y"] - 5.0)


def test_snapshot_wrapper_estimates_specimen_yaw_in_isaac_a4_frame(tmp_path: Path) -> None:
    color = np.zeros((480, 640, 3), dtype=np.uint8)
    color[:, :] = (35, 35, 35)
    a4_px = (80, 60, 574, 410)
    a4_mm = (297.0, 210.0)
    color[a4_px[1] : a4_px[3], a4_px[0] : a4_px[2]] = (245, 245, 245)
    yaw_deg = 32.0
    local_rect = _rotated_a4_rect_points(center_mm=(135.0, 105.0), size_mm=(90.0, 36.0), yaw_deg=yaw_deg)
    image_rect = _a4_local_to_image_points(local_rect, a4_px=a4_px, a4_mm=a4_mm)
    cv2.fillPoly(color, [image_rect], (255, 0, 0))
    depth = np.full((480, 640), 777, dtype=np.uint16)
    color_path = tmp_path / "wrist_color_rotated.png"
    depth_path = tmp_path / "wrist_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "wrist",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-yaw",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                    "camera_id": "active_robot_cam_d405",
                    "a4_camera_to_isaac_transform": "direct",
                    "a4_width_mm": a4_mm[0],
                    "a4_height_mm": a4_mm[1],
                    "a4_isaac_width_mm": a4_mm[0],
                    "a4_isaac_height_mm": a4_mm[1],
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    pose = payload["pose"]
    assert pose["orientation_deg"]["yaw"] == pytest.approx(yaw_deg, abs=4.0)
    assert pose["orientation_source"] == "red_contour_a4_min_area_rect"
    assert pose["orientation_quality"]["aspect_ratio"] > 1.5
    assert "pca_yaw_deg" not in pose["orientation_quality"]
    assert "pca_aspect_ratio" not in pose["orientation_quality"]


def test_snapshot_wrapper_keeps_low_aspect_red_cube_axis_aligned(tmp_path: Path) -> None:
    color = np.zeros((480, 640, 3), dtype=np.uint8)
    color[:, :] = (35, 35, 35)
    a4_px = (80, 60, 574, 410)
    color[a4_px[1] : a4_px[3], a4_px[0] : a4_px[2]] = (245, 245, 245)
    red_cube_with_texture_bias = np.array(
        [
            (150, 300),
            (210, 300),
            (210, 360),
            (150, 360),
            (150, 350),
            (170, 350),
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(color, [red_cube_with_texture_bias], (255, 0, 0))
    depth = np.full((480, 640), 777, dtype=np.uint16)
    color_path = tmp_path / "wrist_color_axis_aligned_cube.png"
    depth_path = tmp_path / "wrist_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "wrist",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-axis-aligned",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                    "camera_id": "active_robot_cam_d405",
                    "a4_camera_to_isaac_transform": "direct",
                    "a4_width_mm": 297.0,
                    "a4_height_mm": 210.0,
                    "a4_isaac_width_mm": 297.0,
                    "a4_isaac_height_mm": 210.0,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    pose = payload["pose"]
    assert pose["orientation_deg"]["yaw"] == pytest.approx(0.0, abs=1.0)
    assert pose["orientation_source"] == "red_contour_a4_min_area_rect_low_aspect"
    assert pose["orientation_quality"]["aspect_ratio"] < 1.5
    assert "pca_yaw_deg" not in pose["orientation_quality"]
    assert "pca_aspect_ratio" not in pose["orientation_quality"]


def test_snapshot_wrapper_preserves_low_aspect_square_rotation(tmp_path: Path) -> None:
    color = np.zeros((480, 640, 3), dtype=np.uint8)
    color[:, :] = (35, 35, 35)
    a4_px = (80, 60, 574, 410)
    a4_mm = (297.0, 210.0)
    color[a4_px[1] : a4_px[3], a4_px[0] : a4_px[2]] = (245, 245, 245)
    yaw_deg = 33.0
    local_rect = _rotated_a4_rect_points(center_mm=(135.0, 105.0), size_mm=(48.0, 48.0), yaw_deg=yaw_deg)
    image_rect = _a4_local_to_image_points(local_rect, a4_px=a4_px, a4_mm=a4_mm)
    cv2.fillPoly(color, [image_rect], (255, 0, 0))
    depth = np.full((480, 640), 777, dtype=np.uint16)
    color_path = tmp_path / "wrist_color_rotated_square.png"
    depth_path = tmp_path / "wrist_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "wrist",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-low-aspect-yaw",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                    "camera_id": "active_robot_cam_d405",
                    "a4_camera_to_isaac_transform": "direct",
                    "a4_width_mm": a4_mm[0],
                    "a4_height_mm": a4_mm[1],
                    "a4_isaac_width_mm": a4_mm[0],
                    "a4_isaac_height_mm": a4_mm[1],
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    pose = payload["pose"]
    assert pose["orientation_deg"]["yaw"] == pytest.approx(yaw_deg, abs=4.0)
    assert pose["orientation_source"] == "red_contour_a4_min_area_rect_low_aspect"
    assert pose["orientation_quality"]["aspect_ratio"] < 1.5


def test_snapshot_wrapper_accepts_d405_blue_tinted_a4_sheet(tmp_path: Path) -> None:
    color = np.zeros((480, 640, 3), dtype=np.uint8)
    color[:, :] = (38, 30, 24)
    a4_x0, a4_y0, a4_x1, a4_y1 = 155, 5, 512, 260
    color[a4_y0:a4_y1, a4_x0:a4_x1] = (110, 170, 210)
    color[178:205, 224:253] = (255, 0, 0)
    depth = np.full((480, 640), 702, dtype=np.uint16)
    color_path = tmp_path / "wrist_color_blue_tint.png"
    depth_path = tmp_path / "wrist_depth_raw_mm.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "wrist",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-d405-blue-tint",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                    "camera_id": "active_robot_cam_d405",
                    "a4_camera_to_isaac_transform": "direct",
                    "a4_width_mm": 297.0,
                    "a4_height_mm": 210.0,
                    "a4_isaac_width_mm": 297.0,
                    "a4_isaac_height_mm": 210.0,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, payload
    pose = payload["pose"]
    assert pose["coordinate_mapping"] == "a4_direct_crop_rgb_homography_xy_depth_checked"
    assert pose["camera_id"] == "wrist"
    assert pose["a4_quad_px"][0] == pytest.approx([155.0, 5.0], abs=2.0)
    assert pose["position_camera_a4_mm"]["lateral_x"] == pytest.approx(68.0, abs=4.0)
    assert pose["position_camera_a4_mm"]["forward_y"] == pytest.approx(59.0, abs=4.0)
    assert pose["position_a4_mm"]["x"] == pytest.approx(pose["position_camera_a4_mm"]["lateral_x"], abs=0.01)
    assert pose["position_a4_mm"]["y"] == pytest.approx(pose["position_camera_a4_mm"]["forward_y"], abs=0.01)


def test_snapshot_wrapper_uses_camera_specific_depth_scale(tmp_path: Path) -> None:
    color = np.zeros((220, 300, 3), dtype=np.uint8)
    color[:, :] = (35, 35, 35)
    color[30:170, 40:238] = (245, 245, 245)
    color[58:72, 83:97] = (255, 0, 0)
    depth = np.full((220, 300), 3009, dtype=np.uint16)
    color_path = tmp_path / "wrist_color.png"
    depth_path = tmp_path / "wrist_depth_raw_units.png"
    manifest_path = tmp_path / "latest_frame.json"
    cv2.imwrite(str(color_path), cv2.cvtColor(color, cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(depth_path), depth)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr_lerobot_latest_frame.v1",
                "camera_key": "wrist",
                "color_image_path": str(color_path),
                "raw_depth_image_path": str(depth_path),
                "color_space": "rgb",
                "depth_scale_m_per_unit": 0.001,
                "camera_depth_scale_m_per_unit": {"wrist": 0.0001},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-d405-scale",
                    "frame_manifest_path": str(manifest_path),
                    "output_dir": str(tmp_path / "out"),
                    "confidence_threshold": 0.01,
                    "autostart_realsense": False,
                    "camera_id": "active_robot_cam_d405",
                    "a4_camera_to_isaac_transform": "direct",
                    "a4_width_mm": 297.0,
                    "a4_height_mm": 210.0,
                    "a4_isaac_width_mm": 297.0,
                    "a4_isaac_height_mm": 210.0,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    assert completed.returncode == 0, payload
    assert payload["pose"]["depth_mm"] == pytest.approx(300.9)
    assert payload["pose"]["specimen_depth_stats_mm"]["median"] == pytest.approx(300.9)


def test_ros_wrapper_autostarts_realsense_when_topics_are_missing(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "topics_ready"
    log_path = tmp_path / "ros2_calls.log"
    fake_ros2 = fake_bin / "ros2"
    fake_ros2.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"MARKER={shlex.quote(str(marker))}\n"
        f"LOG={shlex.quote(str(log_path))}\n"
        "printf '%s\\n' \"$*\" >> \"$LOG\"\n"
        "if [[ \"${1:-}\" == \"topic\" && \"${2:-}\" == \"list\" ]]; then\n"
        "  if [[ -f \"$MARKER\" ]]; then\n"
        "    printf '/camera/d455f/color/image_raw\\n'\n"
        "    printf '/camera/d455f/aligned_depth_to_color/image_raw\\n'\n"
        "    printf '/camera/d455f/color/camera_info\\n'\n"
        "  else\n"
        "    printf '/rosout\\n'\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"${1:-}\" == \"launch\" && \"${2:-}\" == \"realsense2_camera\" ]]; then\n"
        "  touch \"$MARKER\"\n"
        "  while true; do sleep 1; done\n"
        "fi\n"
        "if [[ \"${1:-}\" == \"pkg\" && \"${2:-}\" == \"prefix\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"${1:-}\" == \"run\" && \"${2:-}\" == \"atr_specimen_pose_tracker\" ]]; then\n"
        "  printf '{\"ok\": true, \"pose\": {\"schema\": \"specimen_pose.v1\", \"position_isaac_world_mm\": {\"x\": 1, \"y\": 2, \"z\": 3}}}\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 9\n",
        encoding="utf-8",
    )
    fake_ros2.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["ATR_SPECIMEN_POSE_ROS_SETUP_PATHS"] = str(tmp_path / "missing_ros_setup.bash")
    env["ATR_SPECIMEN_POSE_EXTRA_SETUP_PATHS"] = str(tmp_path / "missing_extra_setup.bash")
    env["ATR_SPECIMEN_POSE_REALSENSE_SERIAL"] = "341522300873"

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
            json.dumps(
                {
                    "specimen_id": "redcube-test",
                    "timeout_sec": 2.0,
                    "camera_startup_timeout_sec": 1.0,
                    "autostart_realsense": True,
                }
            ),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    payload = _last_json(completed.stdout)
    call_log = log_path.read_text(encoding="utf-8")
    assert completed.returncode == 0
    assert payload["ok"] is True
    assert payload["pose"]["schema"] == "specimen_pose.v1"
    assert "launch realsense2_camera rs_launch.py" in call_log
    assert "camera_namespace:=camera" in call_log
    assert "camera_name:=d455f" in call_log
    assert "serial_no:=_341522300873" in call_log
    assert "align_depth.enable:=true" in call_log
    assert "rgb_camera.color_profile:=640x480x15" in call_log
    assert "depth_module.depth_profile:=640x480x15" in call_log
    assert "wait_for_device_timeout:=5.0" in call_log


def test_live_snapshot_injects_topics_and_rsusb_env(tmp_path: Path) -> None:
    script = tmp_path / "run_specimen_pose_snapshot.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"color=$ATR_SPECIMEN_POSE_COLOR_TOPIC\"\n"
        "echo \"depth=$ATR_SPECIMEN_POSE_DEPTH_TOPIC\"\n"
        "echo \"info=$ATR_SPECIMEN_POSE_INFO_TOPIC\"\n"
        "echo \"serial=$ATR_SPECIMEN_POSE_REALSENSE_SERIAL\"\n"
        "echo \"autostart=$ATR_SPECIMEN_POSE_AUTOSTART_REALSENSE\"\n"
        "echo \"startup=$ATR_SPECIMEN_POSE_CAMERA_STARTUP_TIMEOUT_SEC\"\n"
        "echo \"pythonpath=$PYTHONPATH\"\n"
        "echo \"ldpath=$LD_LIBRARY_PATH\"\n"
        "echo '{\"ok\": true, \"pose\": {\"schema\": \"specimen_pose.v1\"}}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    bridge = SpecimenPoseTrackerBridge(
        SpecimenPoseTrackerConfig(
            script_path=script,
            log_dir=tmp_path / "logs",
            artifact_dir=tmp_path / "artifacts",
            d455f_serial="341522300873",
            color_topic="/camera/d455f/color/image_raw",
            depth_topic="/camera/d455f/aligned_depth_to_color/image_raw",
            info_topic="/camera/d455f/color/camera_info",
            rsusb_pythonpath="/opt/rsusb/python",
            rsusb_library_path="/opt/rsusb/lib",
            autostart_realsense=False,
            camera_startup_timeout_sec=1.25,
        )
    )

    result = bridge.snapshot({"mode": "live", "specimen_id": "specimen-live"})
    log_text = Path(result["log_path"]).read_text(encoding="utf-8")

    assert result["ok"] is True
    assert "color=/camera/d455f/color/image_raw" in log_text
    assert "depth=/camera/d455f/aligned_depth_to_color/image_raw" in log_text
    assert "info=/camera/d455f/color/camera_info" in log_text
    assert "serial=341522300873" in log_text
    assert "autostart=0" in log_text
    assert "startup=1.25" in log_text
    assert "pythonpath=/opt/rsusb/python" in log_text
    assert "ldpath=/opt/rsusb/lib" in log_text
