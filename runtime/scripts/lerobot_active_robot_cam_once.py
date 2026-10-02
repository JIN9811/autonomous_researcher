#!/usr/bin/env python3
"""Run one LeRobot ActiveRobotCam pose/capture/return cycle.

This is intentionally a thin runner around the existing
lerobot_isaac_mirror_runtime_wrapper ActiveRobotCamTracker. It must not grow a
second camera-only path: the contract is follower pose -> capture -> resume.
"""

from __future__ import annotations

import json
import sys
import time
from collections import deque
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
        # One-shot ActiveCam only: retain SDK bootstrap/retry, then check RGB-D
        # readiness explicitly before any capture-pose command. Shared recording
        # and rollout camera settings remain unchanged.
        warmup_s=1,
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


def _accept_soft_resume_tolerance(wait_result: dict[str, Any], *, soft_tolerance_deg: float) -> dict[str, Any]:
    """Accept small Dynamixel settling error without masking a real return failure."""
    if str(wait_result.get("failure_code") or "") != "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED":
        return wait_result
    try:
        max_error_deg = float(wait_result.get("max_error_deg"))
        tolerance_deg = float(soft_tolerance_deg)
    except (TypeError, ValueError):
        return wait_result
    if max_error_deg > tolerance_deg:
        return wait_result
    recovered = dict(wait_result)
    recovered.pop("failure_code", None)
    recovered.update(
        {
            "ok": True,
            "status": "reached_within_soft_tolerance",
            "warning_only": True,
            "soft_tolerance_deg": tolerance_deg,
        }
    )
    return recovered


def _wait_for_camera_ready(camera: Any, *, timeout_s: float = 20.0) -> dict[str, Any]:
    """Require a stable window of fresh, synchronous RGB-D reads; never pass on timeout."""
    import numpy as np

    started = time.monotonic()
    deadline = started + timeout_s
    # Leave room for the duration condition at 15+ FPS: eight frames alone
    # span less than 0.5 s. The 50 ms polling pause bounds the sampling rate.
    window: deque = deque(maxlen=16)
    last_error = "insufficient_stable_frames"
    while time.monotonic() < deadline:
        timeout_ms = max(1, min(500, int((deadline - time.monotonic()) * 1000)))
        try:
            if camera.use_depth:
                color, depth = camera.read_color_depth(timeout_ms=timeout_ms)
            else:
                color, depth = camera.read(timeout_ms=timeout_ms), None
            color = np.asarray(color)
            if color.ndim != 3 or color.shape[2] != 3 or not color.size or not np.isfinite(color).all():
                raise ValueError("invalid_color_frame")
            mean = color.mean(axis=(0, 1))
            if not 2.0 < float(mean.mean()) < 253.0:
                raise ValueError("color_frame_under_or_overexposed")
            depth_fraction, depth_median = 1.0, 0.0
            if camera.use_depth:
                depth = np.asarray(depth)
                if depth.shape != color.shape[:2]:
                    raise ValueError("rgb_depth_shape_mismatch")
                valid = np.isfinite(depth) & (depth > 0)
                depth_fraction = float(valid.mean())
                if depth_fraction < 0.05:
                    raise ValueError("insufficient_valid_depth")
                depth_median = float(np.median(depth[valid]))
            now = time.monotonic()
            if now >= deadline:
                break
            window.append((now, mean, depth_fraction, depth_median))
            if len(window) >= 8 and now - window[0][0] >= 0.5:
                colors = np.stack([entry[1] for entry in window])
                fractions = [entry[2] for entry in window]
                medians = [entry[3] for entry in window]
                exposure_stable = bool(np.all(np.ptp(colors, axis=0) <= np.maximum(3.0, colors.mean(axis=0) * 0.03)))
                depth_stable = max(fractions) - min(fractions) <= 0.05 and max(medians) - min(medians) <= max(1.0, float(np.mean(medians)) * 0.05)
                if exposure_stable and depth_stable:
                    return {"ok": True, "status": "stable_frames", "elapsed_s": round(now - started, 3),
                            "stable_frames": len(window), "valid_depth_fraction": depth_fraction,
                            "depth_required": bool(camera.use_depth)}
                last_error = "exposure_or_depth_unstable"
        except (RuntimeError, TimeoutError, ValueError, TypeError) as exc:
            window.clear()
            last_error = str(exc)
        time.sleep(max(0.0, min(0.05, deadline - time.monotonic())))
    raise RuntimeError(f"ACTIVE_ROBOT_CAM_CAMERA_NOT_READY: {last_error}; elapsed_s={time.monotonic() - started:.3f}")


def _connect_robot(payload: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
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
    started = time.monotonic()
    try:
        try:
            robot.connect(calibrate=False)
        except TypeError:
            robot.connect()
        readiness = {}
        for key, data in dict(payload.get("cameras") or {}).items():
            if str(data.get("type") or "opencv").strip().lower() in {"intelrealsense", "realsense", "intel_realsense", "realsense_sdk"}:
                readiness[key] = _wait_for_camera_ready(robot.cameras[key])
        return robot, {"elapsed_s": round(time.monotonic() - started, 3), "cameras": readiness}
    except Exception:
        try:
            robot.disconnect()
        except Exception:
            pass  # Child exit also releases handles if connection was partial.
        raise


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

        robot, camera_readiness = _connect_robot(payload)
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
        result["camera_readiness"] = camera_readiness
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
            resume_pose = _accept_soft_resume_tolerance(
                resume_pose,
                soft_tolerance_deg=tracker.resume_wait_soft_tolerance_deg,
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
