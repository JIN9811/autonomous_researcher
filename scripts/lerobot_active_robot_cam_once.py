#!/usr/bin/env python3
"""Run one LeRobot ActiveRobotCam pose/capture/return cycle.

This is intentionally a thin runner around the existing
lerobot_isaac_mirror_runtime_wrapper ActiveRobotCamTracker. It must not grow a
second camera-only path: the contract is follower pose -> capture -> resume.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _print_json(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)
    raise SystemExit(exit_code)


def _opencv_camera_config(data: dict[str, Any]) -> Any:
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig

    raw = data.get("index_or_path")
    if raw is None:
        raw = data.get("path") or data.get("port") or 0
    index_or_path: int | Path
    if isinstance(raw, int):
        index_or_path = raw
    else:
        text = str(raw)
        index_or_path = int(text) if text.isdigit() else Path(text)
    return OpenCVCameraConfig(
        index_or_path=index_or_path,
        fps=int(data.get("fps") or 30),
        width=int(data.get("width") or 640),
        height=int(data.get("height") or 480),
        warmup_s=int(float(data.get("warmup_s") or 1)),
    )


def _realsense_camera_config(data: dict[str, Any]) -> Any:
    from lerobot.cameras.realsense.configuration_realsense import RealSenseCameraConfig

    identifier = str(data.get("serial_number_or_name") or data.get("index_or_path") or data.get("port") or "").strip()
    if not identifier:
        raise ValueError("RealSense serial_number_or_name is required for ActiveCam")
    return RealSenseCameraConfig(
        serial_number_or_name=identifier,
        fps=int(data.get("fps") or 15),
        width=int(data.get("width") or 640),
        height=int(data.get("height") or 480),
        color_format=str(data.get("color_format") or "rgb8"),
        use_depth=bool(data.get("use_depth", True)),
        align_depth_to_color=bool(data.get("align_depth_to_color", True)),
        depth_scale_m_per_unit=float(data.get("depth_scale_m_per_unit") or 0.001),
        depth_clip_min_mm=float(data.get("depth_clip_min_mm") or 0.0),
        depth_clip_max_mm=float(data.get("depth_clip_max_mm") or 2000.0),
        warmup_s=int(float(data.get("warmup_s") or 1)),
    )


def _camera_config(data: dict[str, Any]) -> Any:
    camera_type = str(data.get("type") or "opencv").strip().lower()
    if camera_type in {"intelrealsense", "realsense", "intel_realsense", "realsense_sdk"}:
        return _realsense_camera_config(data)
    return _opencv_camera_config(data)


def _load_latest_frame_capture(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        return {"ok": False, "failure_code": "LEROBOT_LATEST_FRAME_MISSING", "message": str(manifest_path)}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "failure_code": "LEROBOT_LATEST_FRAME_INVALID", "message": f"{exc.__class__.__name__}: {exc}"}
    color_path = str(manifest.get("color_image_path") or "")
    path = color_path or str(manifest_path)
    width = 0
    height = 0
    shape = manifest.get("image_shape")
    if isinstance(shape, list) and len(shape) >= 2:
        height = int(shape[0] or 0)
        width = int(shape[1] or 0)
    return {
        "ok": bool(color_path),
        "path": path,
        "serve_url": f"/api/lerobot/visualization/file?path={quote(path)}",
        "width": width,
        "height": height,
        "synthetic": False,
        "manifest_path": str(manifest_path),
        "raw_depth_image_path": str(manifest.get("raw_depth_image_path") or ""),
        "depth_visual_image_path": str(manifest.get("depth_visual_image_path") or ""),
    }


def _connect_robot(payload: dict[str, Any]) -> Any:
    from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig
    from lerobot.robots.omx_follower.omx_follower import OmxFollower

    cameras = {str(key): _camera_config(dict(value or {})) for key, value in dict(payload.get("cameras") or {}).items()}
    calibration_dir = str(payload.get("calibration_dir") or "").strip()
    config = OmxFollowerConfig(
        port=str(payload["robot_port"]),
        id=str(payload.get("robot_id") or "omx_follower_arm"),
        calibration_dir=Path(calibration_dir) if calibration_dir else None,
        cameras=cameras,
        disable_torque_on_disconnect=False,
    )
    robot = OmxFollower(config)
    try:
        robot.connect(calibrate=False)
    except TypeError:
        robot.connect()
    return robot


def main() -> None:
    try:
        payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except Exception as exc:
        _print_json({"ok": False, "failure_code": "ACTIVE_ROBOT_CAM_PAYLOAD_INVALID", "message": str(exc)}, 2)
    try:
        from scripts.lerobot_isaac_mirror_runtime_wrapper import (
            ActiveRobotCamTracker,
            LatestFrameSidecar,
            SpecimenPoseFrameUpdater,
        )

        robot = _connect_robot(payload)
    except Exception as exc:
        _print_json({"ok": False, "failure_code": "ACTIVE_ROBOT_CAM_CONNECT_FAILED", "message": f"{exc.__class__.__name__}: {exc}"}, 3)

    try:
        sidecar = LatestFrameSidecar()
        updater = SpecimenPoseFrameUpdater()
        tracker = ActiveRobotCamTracker(sidecar, updater)
        current_action = tracker.present_action(robot)
        result = tracker.capture_once(
            robot,
            send_action=lambda active_robot, action: active_robot.send_action(action),
            current_action=current_action,
            reason=str(payload.get("reason") or "spc_autoejection_verification"),
            force=True,
        )
        sidecar.flush(timeout_s=2.0)
        capture = _load_latest_frame_capture(sidecar.manifest_path)
        if not result.get("ok"):
            _print_json({**result, "capture": capture, "robot_pose_included": True}, 4)
        resume_pose = {}
        resume_action = result.get("resume_action")
        if isinstance(resume_action, dict) and resume_action:
            resume_pose = tracker.wait_until_action_reached(
                robot,
                resume_action,
                reason="active_robot_cam_resume",
            )
            if resume_pose and not resume_pose.get("ok"):
                _print_json(
                    {
                        **result,
                        "ok": False,
                        "failure_code": "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED",
                        "robot_pose_included": True,
                        "capture": capture,
                        "capture_pose": result.get("capture_wait") or {},
                        "resume_pose": resume_pose,
                        "port_released": False,
                        "camera_returned_to_vla": False,
                        "camera_owner_after": "active_cam_process",
                        "release_status": "disconnect_pending",
                    },
                    6,
                )
        _print_json(
            {
                **result,
                "ok": True,
                "robot_pose_included": True,
                "capture": capture,
                "capture_pose": result.get("capture_wait") or {},
                "resume_pose": resume_pose or {"status": "not_checked"},
                "port_released": False,
                "camera_returned_to_vla": False,
                "camera_owner_after": "active_cam_process",
                "release_status": "disconnect_pending",
            }
        )
    except Exception as exc:
        _print_json({"ok": False, "failure_code": "ACTIVE_ROBOT_CAM_ERROR", "message": f"{exc.__class__.__name__}: {exc}"}, 5)
    finally:
        try:
            robot.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
