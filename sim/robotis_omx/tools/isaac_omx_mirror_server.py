#!/usr/bin/env python3
"""HTTP bridge for mirroring ROBOTIS OMX follower joint state into Isaac Sim.

Run this inside Isaac Sim Python when the GUI stage is open, or with Isaac Sim's
python.sh against a USD file for offline target updates. The ATR LeRobot bridge
POSTs follower joint samples to /joints.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
DEFAULT_SCENE = Path(__file__).resolve().parents[1] / "scene" / "omx_table_layout.usda"
LATEST_STATE_PATH = Path("/tmp/atr_isaac_omx_mirror_latest.json")
RUNTIME_GRIP_JOINT_PATH = "/World/RuntimeGrip/OmxTeleopGripJoint"
RED_SPECIMEN_BLOCK_PATH = "/World/Workspace/RedSpecimenBlock"
MM_TO_M = 0.001
LEISAAC_GRIPPER_EFFORT_MASS_DIVISOR_KG = 0.15
GRIPPER_CONTACT_FORCE_HOLD_THRESHOLD_N = 12.0
GRIPPER_CONTACT_PROBE_MAX_CLOSE_STEP_DEG = 6.0
GRIPPER_CONTACT_HOLD_OVERTRAVEL_DEG = 0.1
GRIPPER_CONTACT_RELEASE_MARGIN_DEG = 1.0
GRIPPER_CONTACT_PENETRATION_BACKOFF_THRESHOLD_M = 0.0005
GRIPPER_CLOSED_TARGET_THRESHOLD_DEG = 6.0
GRIPPER_OBJECT_NEAR_DISTANCE_M = 0.04
GRIPPER_OBJECT_LIFTED_Z_M = 0.04
GRIPPER_CONTACT_COLLIDER_TOKENS = (
    "InnerGripPadCollision",
    "follower_07_gripper_motorized",
    "follower_08_gripper_gear",
    "follower_05_tip",
)
GRIPPER_CONTACT_OBJECT_TOKENS = ("RedSpecimenBlock",)
GRIPPER_CONTACT_PRIMARY_SIDE = "primary"
GRIPPER_CONTACT_MIMIC_SIDE = "mimic"
GRIPPER_CONTACT_SIDE_ORDER = (GRIPPER_CONTACT_PRIMARY_SIDE, GRIPPER_CONTACT_MIMIC_SIDE)
DEFAULT_PHYSICS_DT_S = 1.0 / 240.0
REPO_ROOT = next(
    (
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "utils" / "isaac_omx_mirror_mapping.py").exists()
    ),
    Path(__file__).resolve().parents[3],
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from utils.isaac_omx_mirror_mapping import joint_state_item_to_isaac_target  # type: ignore  # noqa: E402
except ModuleNotFoundError:
    _mapping_path = REPO_ROOT / "utils" / "isaac_omx_mirror_mapping.py"
    _mapping_spec = importlib.util.spec_from_file_location("atr_isaac_omx_mirror_mapping", _mapping_path)
    if _mapping_spec is None or _mapping_spec.loader is None:
        raise
    _mapping_module = importlib.util.module_from_spec(_mapping_spec)
    _mapping_spec.loader.exec_module(_mapping_module)
    joint_state_item_to_isaac_target = _mapping_module.joint_state_item_to_isaac_target


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _normalize_yaw_deg(value: float) -> float:
    yaw = ((float(value) + 180.0) % 360.0) - 180.0
    if math.isclose(yaw, -180.0):
        return 180.0
    return yaw


def _specimen_yaw_deg_from_pose(pose: dict[str, Any]) -> float | None:
    orientation = pose.get("orientation_deg") if isinstance(pose.get("orientation_deg"), dict) else {}
    for value in (orientation.get("yaw"), orientation.get("yaw_deg"), pose.get("yaw_deg")):
        yaw = _safe_float(value, float("nan"))
        if yaw == yaw:
            return _normalize_yaw_deg(yaw)
    return None


def _xform_op_name(op: Any) -> str:
    getter = getattr(op, "GetOpName", None)
    if callable(getter):
        return str(getter())
    return ""


def _is_rotation_xform_op(name: str) -> bool:
    return name in {
        "xformOp:orient",
        "xformOp:rotateX",
        "xformOp:rotateY",
        "xformOp:rotateZ",
        "xformOp:rotateXYZ",
        "xformOp:rotateXZY",
        "xformOp:rotateYXZ",
        "xformOp:rotateYZX",
        "xformOp:rotateZXY",
        "xformOp:rotateZYX",
    }


def _single_yaw_xform_order(ops: list[Any], yaw_op: Any) -> list[Any]:
    yaw_name = _xform_op_name(yaw_op)
    translate_ops: list[Any] = []
    scale_ops: list[Any] = []
    other_ops: list[Any] = []
    seen: set[str] = set()
    for op in ops:
        name = _xform_op_name(op)
        if not name or name in seen:
            continue
        seen.add(name)
        if name == yaw_name or _is_rotation_xform_op(name):
            continue
        if name == "xformOp:translate":
            translate_ops.append(op)
        elif name == "xformOp:scale":
            scale_ops.append(op)
        else:
            other_ops.append(op)
    return other_ops + [yaw_op] + scale_ops + translate_ops


def _yaw_quaternion_value(yaw_deg: float) -> Any:
    half_rad = math.radians(float(yaw_deg)) * 0.5
    real = math.cos(half_rad)
    imag_z = math.sin(half_rad)
    try:
        from pxr import Gf  # type: ignore

        return Gf.Quatd(real, Gf.Vec3d(0.0, 0.0, imag_z))
    except Exception:
        return (real, 0.0, 0.0, imag_z)


def _apply_specimen_yaw_to_prim(prim: Any, yaw_deg: float | None) -> dict[str, Any]:
    if yaw_deg is None:
        return {"applied": False}
    yaw = _normalize_yaw_deg(float(yaw_deg))
    try:
        from pxr import UsdGeom  # type: ignore

        xformable = UsdGeom.Xformable(prim)
        ops = list(xformable.GetOrderedXformOps())
        orient_op = next((op for op in ops if _xform_op_name(op) == "xformOp:orient"), None)
        if orient_op is not None:
            yaw_op = orient_op
            yaw_op.Set(_yaw_quaternion_value(yaw))
        else:
            yaw_op = next((op for op in ops if _xform_op_name(op) == "xformOp:rotateZ"), None)
            if yaw_op is None:
                yaw_op = xformable.AddRotateZOp(precision=UsdGeom.XformOp.PrecisionDouble)
                ops = list(xformable.GetOrderedXformOps())
            yaw_op.Set(yaw)
        ordered_ops = _single_yaw_xform_order(ops, yaw_op)
        if yaw_op not in ordered_ops:
            ops = list(xformable.GetOrderedXformOps())
            ordered_ops = _single_yaw_xform_order(ops, yaw_op)
        xformable.SetXformOpOrder(ordered_ops)
    except Exception as exc:
        return {
            "applied": False,
            "failure_code": "SPECIMEN_ROTATE_Z_OP_ERROR",
            "message": f"큐브 yaw 적용 실패: {exc.__class__.__name__}: {exc}",
        }
    return {"applied": True, "yaw": yaw, "xformOpOrder": [_xform_op_name(op) for op in ordered_ops]}


def _load_usd_modules() -> tuple[Any, Any, Any]:
    try:
        from pxr import Usd, UsdPhysics, UsdGeom  # type: ignore
    except Exception:
        return None, None, None
    return Usd, UsdPhysics, UsdGeom


def _current_isaac_stage() -> Any:
    try:
        import omni.usd  # type: ignore

        return omni.usd.get_context().get_stage()
    except Exception:
        return None


def _joint_targets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    calibration = payload.get("calibration") if isinstance(payload.get("calibration"), dict) else None
    for item in payload.get("joint_state") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("isaac_joint_path") or "").strip()
        if not path:
            continue
        converted = joint_state_item_to_isaac_target(item, calibration=calibration)
        target_value = float(converted["target_value"])
        target = {
            "path": path,
            "mimic_path": str(item.get("mimic_joint_path") or "").strip(),
            "name": str(item.get("isaac_joint_name") or ""),
            "motor_name": str(item.get("motor_name") or ""),
            "motor_id": item.get("motor_id"),
            "target_value": target_value,
            "source_value": converted.get("source_value"),
            "base_target_value": converted.get("base_target_value"),
            "calibration_applied": converted.get("calibration_applied"),
            "clamped": converted.get("clamped"),
            "recomputed_from_source": converted.get("recomputed_from_source"),
            "mimic_multiplier": converted.get("mimic_multiplier", 1.0),
            "unit": str(item.get("unit") or "deg"),
        }
        for key in ("drive_stiffness", "drive_damping", "drive_max_force"):
            if key in converted:
                target[key] = converted[key]
        for key in (
            "conversion_mode",
            "source_raw_position",
            "source_zero_raw_position",
            "dynamixel_deg_per_tick",
            "source_raw_clamped",
            "motor_model",
            "backlash_deg",
            "backlash_source",
            "backlash_note",
            "backlash_direction_sign",
        ):
            if key in converted:
                target[key] = converted[key]
        targets.append(target)
    return targets


class MirrorActionProcessor:
    """Centralizes mirror-side action shaping before joint drive writes."""

    name = "MirrorActionProcessor"

    def __init__(self, state: "IsaacMirrorState") -> None:
        self._state = state

    def process(self, stage: Any, targets: list[dict[str, Any]]) -> dict[str, Any]:
        previous_gripper_target = self._state._last_gripper_target_value
        self._state._annotate_gripper_raw_targets(targets)
        gripper_contact = self._state._apply_gripper_contact_control(stage, targets, previous_gripper_target)
        gripper_effort_limit = self._state._apply_dynamic_gripper_effort_limit(stage, targets, gripper_contact)
        grasp_diagnostics = self._state._grasp_diagnostics(stage, targets, gripper_contact)
        return {
            "processor": self.name,
            "gripper_contact": gripper_contact,
            "gripper_effort_limit": gripper_effort_limit,
            "grasp_diagnostics": grasp_diagnostics,
        }


class IsaacReplicatorRgbdRenderBackend:
    """Best-effort Isaac Replicator RGB/depth renderer for mirror samples."""

    name = "isaac_replicator_rgbd"

    def __init__(self) -> None:
        self._resources: dict[str, dict[str, Any]] = {}
        self._pending_steps: dict[str, Any] = {}

    def __call__(self, *, request: dict[str, Any], output_dir: Path, stage: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if stage is None:
            return self._unavailable("stage is unavailable")
        try:
            import numpy as np  # type: ignore
            import omni.replicator.core as rep  # type: ignore
            from omni.replicator.core.functional import write_image  # type: ignore
        except Exception as exc:
            return self._unavailable(f"Replicator imports unavailable: {exc.__class__.__name__}: {exc}")

        cameras = [str(item).strip() for item in request.get("cameras", []) if str(item).strip()]
        if not cameras:
            return self._unavailable("render_request.cameras is empty")
        frame_index = _safe_int(request.get("frame_index"), _safe_int(request.get("sample_index"), 0, minimum=0), minimum=0)
        resolution = self._resolution(request)
        pending_key = self._pending_key(request, output_dir)
        finalize_after_async = bool(request.get("_atr_finalize_after_async_step"))
        camera_results: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []
        render_products = []
        rgb_annots = []
        depth_annots = []
        for camera_key in cameras:
            resource = self._resource_for_camera(rep, stage, camera_key, request, resolution)
            if not resource.get("ok"):
                camera_results.append(resource)
                continue
            render_products.append(resource["render_product"])
            rgb_annots.append((camera_key, resource["rgb_annotator"]))
            depth_annots.append((camera_key, resource["depth_annotator"]))
            camera_results.append(
                {
                    "ok": True,
                    "camera": camera_key,
                    "camera_path": resource.get("camera_path", ""),
                    "render_product": str(resource.get("render_product_name") or ""),
                }
            )
        if not render_products:
            return {
                "ok": False,
                "status": "render_failed",
                "backend": self.name,
                "failure_code": "ISAAC_RGBD_RENDER_NO_RENDER_PRODUCTS",
                "message": "No valid Isaac render products could be created for requested cameras.",
                "camera_results": camera_results,
                "files": [],
            }
        try:
            if finalize_after_async:
                step_result = self._finalize_pending_step(pending_key)
            else:
                step_result = self._step_orchestrator(rep, request, pending_key=pending_key)
        except Exception as exc:
            return {
                "ok": False,
                "status": "render_failed",
                "backend": self.name,
                "failure_code": "ISAAC_RGBD_RENDER_STEP_FAILED",
                "message": f"{exc.__class__.__name__}: {exc}",
                "camera_results": camera_results,
                "files": [],
            }
        if step_result.get("mode") == "async_scheduled":
            return {
                "ok": True,
                "status": "render_pending",
                "backend": self.name,
                "camera_results": camera_results,
                "files": [],
                "step_mode": step_result.get("mode"),
                "pending_key": pending_key,
            }
        if step_result.get("mode") == "async_pending":
            return {
                "ok": True,
                "status": "render_pending",
                "backend": self.name,
                "camera_results": camera_results,
                "files": [],
                "step_mode": step_result.get("mode"),
                "pending_key": pending_key,
            }
        for camera_key, annotator in rgb_annots:
            camera_dir = output_dir / camera_key
            camera_dir.mkdir(parents=True, exist_ok=True)
            rgb_path = camera_dir / f"frame_{frame_index:06d}_rgb.png"
            try:
                write_image(path=str(rgb_path), data=annotator.get_data())
                files.append({"camera": camera_key, "kind": "rgb", "path": str(rgb_path), "encoding": "png"})
            except Exception as exc:
                camera_results.append(
                    {
                        "ok": False,
                        "camera": camera_key,
                        "kind": "rgb",
                        "failure_code": "ISAAC_RGBD_RGB_WRITE_FAILED",
                        "message": f"{exc.__class__.__name__}: {exc}",
                    }
                )
        for camera_key, annotator in depth_annots:
            camera_dir = output_dir / camera_key
            camera_dir.mkdir(parents=True, exist_ok=True)
            depth_path = camera_dir / f"frame_{frame_index:06d}_depth.png"
            depth_npy_path = camera_dir / f"frame_{frame_index:06d}_depth_m.npy"
            try:
                depth_m = np.asarray(annotator.get_data(), dtype=np.float32)
                np.save(depth_npy_path, depth_m)
                depth_u16 = np.clip(np.nan_to_num(depth_m, nan=0.0, posinf=0.0, neginf=0.0) * 1000.0, 0, 65535).astype(np.uint16)
                self._write_depth_png(depth_path, depth_u16)
                files.append({"camera": camera_key, "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"})
                files.append({"camera": camera_key, "kind": "depth_m", "path": str(depth_npy_path), "encoding": "npy", "unit": "m"})
            except Exception as exc:
                camera_results.append(
                    {
                        "ok": False,
                        "camera": camera_key,
                        "kind": "depth",
                        "failure_code": "ISAAC_RGBD_DEPTH_WRITE_FAILED",
                        "message": f"{exc.__class__.__name__}: {exc}",
                    }
                )
        ok = bool(files) and not any(not item.get("ok", True) for item in camera_results)
        return {
            "ok": ok,
            "status": "rendered" if ok else "render_partial" if files else "render_failed",
            "backend": self.name,
            "files": files,
            "camera_results": camera_results,
            "step_mode": step_result.get("mode"),
        }

    @staticmethod
    def _pending_key(request: dict[str, Any], output_dir: Path) -> str:
        return "|".join(
            [
                str(output_dir),
                str(request.get("attempt_id") or ""),
                str(request.get("episode_index") or 0),
                str(request.get("frame_index") or request.get("sample_index") or 0),
                ",".join(str(item) for item in request.get("cameras", []) if str(item).strip())
                if isinstance(request.get("cameras"), list)
                else "",
            ]
        )

    def _step_orchestrator(self, rep: Any, request: dict[str, Any], *, pending_key: str) -> dict[str, Any]:
        kwargs = {
            "rt_subframes": _safe_int(request.get("rt_subframes"), 1, minimum=1),
            "delta_time": 0.0,
            "pause_timeline": False,
        }
        try:
            rep.orchestrator.step(**kwargs)
            return {"ok": True, "mode": "sync"}
        except Exception as exc:
            message = str(exc)
            step_async = getattr(rep.orchestrator, "step_async", None)
            if "Synchronous call to `step`" not in message or not callable(step_async):
                raise
            scheduled = self._run_or_schedule_awaitable(step_async(**kwargs), pending_key=pending_key)
            if scheduled == "scheduled":
                return {"ok": True, "mode": "async_scheduled", "pending_key": pending_key}
            return {"ok": True, "mode": "async_fallback"}

    def _run_or_schedule_awaitable(self, awaitable: Any, *, pending_key: str) -> str:
        if not hasattr(awaitable, "__await__"):
            return "completed"
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            asyncio.run(awaitable)
            return "completed"
        if loop.is_running():
            self._pending_steps[pending_key] = asyncio.ensure_future(awaitable)
            return "scheduled"
        loop.run_until_complete(awaitable)
        return "completed"

    def _finalize_pending_step(self, pending_key: str) -> dict[str, Any]:
        future = self._pending_steps.get(pending_key)
        if future is None:
            return {"ok": True, "mode": "async_missing"}
        done = bool(getattr(future, "done", lambda: True)())
        if not done:
            return {"ok": True, "mode": "async_pending", "pending_key": pending_key}
        try:
            result = future.result()
        finally:
            self._pending_steps.pop(pending_key, None)
        return {"ok": True, "mode": "async_complete", "result": result}

    @staticmethod
    def _unavailable(message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "backend_unavailable",
            "backend": IsaacReplicatorRgbdRenderBackend.name,
            "failure_code": "ISAAC_RGBD_RENDER_BACKEND_UNAVAILABLE",
            "message": message,
            "files": [],
        }

    @staticmethod
    def _resolution(request: dict[str, Any]) -> tuple[int, int]:
        value = request.get("resolution")
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return (_safe_int(value[0], 640, minimum=1), _safe_int(value[1], 480, minimum=1))
        return (
            _safe_int(request.get("width"), 640, minimum=1),
            _safe_int(request.get("height"), 480, minimum=1),
        )

    def _resource_for_camera(
        self,
        rep: Any,
        stage: Any,
        camera_key: str,
        request: dict[str, Any],
        resolution: tuple[int, int],
    ) -> dict[str, Any]:
        resource_key = f"{camera_key}:{resolution[0]}x{resolution[1]}:{self._camera_spec_signature(camera_key, request)}"
        cached = self._resources.get(resource_key)
        if cached:
            return cached
        try:
            camera_target = self._resolve_or_create_camera(rep, stage, camera_key, request)
            render_product = rep.create.render_product(camera_target["camera"], resolution, name=f"ATR_{camera_key}_RGBD_RP")
            rgb_annotator = rep.annotators.get("rgb")
            depth_annotator = rep.AnnotatorRegistry.get_annotator("distance_to_camera")
            rgb_annotator.attach(render_product)
            depth_annotator.attach(render_product)
        except Exception as exc:
            return {
                "ok": False,
                "camera": camera_key,
                "failure_code": "ISAAC_RGBD_RENDER_PRODUCT_CREATE_FAILED",
                "message": f"{exc.__class__.__name__}: {exc}",
            }
        cached = {
            "ok": True,
            "camera": camera_key,
            "camera_path": camera_target.get("camera_path", ""),
            "render_product": render_product,
            "render_product_name": f"ATR_{camera_key}_RGBD_RP",
            "rgb_annotator": rgb_annotator,
            "depth_annotator": depth_annotator,
        }
        self._resources[resource_key] = cached
        return cached

    def _resolve_or_create_camera(self, rep: Any, stage: Any, camera_key: str, request: dict[str, Any]) -> dict[str, Any]:
        request_spec = self._camera_spec_from_request(camera_key, request)
        if request_spec is not None:
            digest = self._camera_spec_signature(camera_key, request)[:10]
            name = f"{camera_key}_{digest}"
            try:
                from pxr import UsdGeom  # type: ignore

                UsdGeom.Xform.Define(stage, "/World/ATRRenderCameras")
            except Exception:
                pass
            camera = rep.functional.create.camera(
                **self._camera_create_kwargs(request_spec),
                parent="/World/ATRRenderCameras",
                name=name,
            )
            return {"camera": camera, "camera_path": f"/World/ATRRenderCameras/{name}"}
        camera_paths = request.get("camera_paths")
        candidates: list[str] = []
        if isinstance(camera_paths, dict) and str(camera_paths.get(camera_key) or "").strip():
            candidates.append(str(camera_paths[camera_key]).strip())
        candidates.extend(
            [
                f"/World/Cameras/{camera_key}",
                f"/World/Cameras/{camera_key}_camera",
                f"/World/{camera_key}_camera",
                f"/World/ATRRenderCameras/{camera_key}",
            ]
        )
        for path in candidates:
            prim = stage.GetPrimAtPath(path)
            if IsaacMirrorState._prim_is_valid(prim) and str(prim.GetTypeName()) == "Camera":
                return {"camera": path, "camera_path": path}
        spec = self._default_camera_spec(camera_key)
        try:
            from pxr import UsdGeom  # type: ignore

            UsdGeom.Xform.Define(stage, "/World/ATRRenderCameras")
        except Exception:
            pass
        camera = rep.functional.create.camera(
            **self._camera_create_kwargs(spec),
            parent="/World/ATRRenderCameras",
            name=camera_key,
        )
        return {"camera": camera, "camera_path": f"/World/ATRRenderCameras/{camera_key}"}

    @staticmethod
    def _camera_create_kwargs(spec: dict[str, Any]) -> dict[str, Any]:
        position = IsaacReplicatorRgbdRenderBackend._vec3_tuple(spec.get("position")) or (0.315, 0.265, 0.62)
        look_at = IsaacReplicatorRgbdRenderBackend._vec3_tuple(spec.get("look_at")) or (0.315, 0.265, 0.0)
        dx = position[0] - look_at[0]
        dy = position[1] - look_at[1]
        dz = position[2] - look_at[2]
        focus_distance = max(0.001, math.sqrt(dx * dx + dy * dy + dz * dz))
        return {
            "position": position,
            "look_at": look_at,
            "look_at_up_axis": tuple(spec.get("look_at_up_axis") or (0.0, 0.0, 1.0)),
            "focal_length": float(spec.get("focal_length") or 18.0),
            "focus_distance": float(spec.get("focus_distance") or focus_distance),
            "clipping_range": tuple(spec.get("clipping_range") or (0.001, 10.0)),
        }

    @staticmethod
    def _camera_spec_signature(camera_key: str, request: dict[str, Any]) -> str:
        spec = IsaacReplicatorRgbdRenderBackend._camera_spec_from_request(camera_key, request)
        if spec is None:
            return "default"
        raw = json.dumps(spec, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _camera_spec_from_request(camera_key: str, request: dict[str, Any]) -> dict[str, tuple[float, float, float]] | None:
        camera_specs = request.get("camera_specs")
        if not isinstance(camera_specs, dict):
            return None
        raw_spec = camera_specs.get(camera_key)
        if not isinstance(raw_spec, dict):
            return None
        position = IsaacReplicatorRgbdRenderBackend._vec3_tuple(raw_spec.get("position"))
        look_at = IsaacReplicatorRgbdRenderBackend._vec3_tuple(raw_spec.get("look_at"))
        if position is None or look_at is None:
            return None
        return {"position": position, "look_at": look_at}

    @staticmethod
    def _vec3_tuple(value: Any) -> tuple[float, float, float] | None:
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return None
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _default_camera_spec(camera_key: str) -> dict[str, tuple[float, float, float]]:
        key = str(camera_key or "").lower()
        if key == "top":
            return {"position": (0.315, 0.205, 0.72), "look_at": (0.315, 0.265, 0.0)}
        if key == "front":
            return {"position": (0.36, 0.96, 0.52), "look_at": (0.36, 0.28, 0.025), "focal_length": 14.0}
        if key == "right":
            return {"position": (0.86, 0.58, 0.52), "look_at": (0.38, 0.24, 0.02), "focal_length": 10.0}
        if key == "wrist":
            return {"position": (0.19, 0.08, 0.28), "look_at": (0.36, 0.28, 0.02)}
        if key == "sim_overhead":
            return {"position": (0.315, 0.265, 0.82), "look_at": (0.315, 0.265, 0.0)}
        if key == "sim_top_oblique":
            return {"position": (0.05, -0.12, 0.58), "look_at": (0.315, 0.265, 0.02)}
        if key == "sim_wrist_offset":
            return {"position": (0.14, 0.02, 0.32), "look_at": (0.36, 0.28, 0.02)}
        return {"position": (0.42, -0.08, 0.42), "look_at": (0.315, 0.265, 0.0)}

    @staticmethod
    def _write_depth_png(path: Path, depth_u16: Any) -> None:
        try:
            from PIL import Image  # type: ignore

            Image.fromarray(depth_u16).save(path)
        except Exception:
            import imageio.v2 as imageio  # type: ignore

            imageio.imwrite(path, depth_u16)


class IsaacMirrorState:
    def __init__(
        self,
        scene_path: Path,
        *,
        use_current_stage: bool = True,
        defer_apply: bool = False,
        save_stage_on_apply: bool | None = None,
        stage_provider: Callable[[], Any] | None = None,
        contact_force_provider: Callable[[Any], dict[str, Any]] | None = None,
        rgbd_render_backend: Callable[..., dict[str, Any]] | None = None,
        viewport_frame_callback: Callable[..., dict[str, Any]] | None = None,
        timeline_play_callback: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.scene_path = scene_path
        self.use_current_stage = use_current_stage
        self.defer_apply = defer_apply
        self.save_stage_on_apply = (not use_current_stage) if save_stage_on_apply is None else bool(save_stage_on_apply)
        self.stage_provider = stage_provider
        self.contact_force_provider = contact_force_provider
        self.rgbd_render_backend = rgbd_render_backend if rgbd_render_backend is not None else IsaacReplicatorRgbdRenderBackend()
        self.viewport_frame_callback = viewport_frame_callback
        self.timeline_play_callback = timeline_play_callback
        self.lock = threading.Lock()
        self.last_payload: dict[str, Any] = {}
        self.pending_payload: dict[str, Any] | None = None
        self.pending_specimen_pose: dict[str, Any] | None = None
        self.pending_render_payload: dict[str, Any] | None = None
        self.pending_render_jobs: list[dict[str, Any]] = []
        self.pending_viewport_frame: dict[str, Any] | None = None
        self.pending_timeline_play: dict[str, Any] | None = None
        self.last_apply_result: dict[str, Any] = {}
        self.last_specimen_pose_result: dict[str, Any] = {}
        self.last_render_request_result: dict[str, Any] = {}
        self.last_viewport_frame_result: dict[str, Any] = {}
        self.last_timeline_play_result: dict[str, Any] = {}
        self.last_error = ""
        self.last_scene_open_status = ""
        self.scene_open_request_count = 0
        self._last_scene_open_attempt_s = 0.0
        self._runtime_cleanup_stage_id: int | None = None
        self.sample_count = 0
        self.stage = None
        self._runtime_grip_active = False
        self._last_gripper_target_value: float | None = None
        self._gripper_contact_hold_target_value: float | None = None
        self._last_gripper_contact: dict[str, Any] = {
            "available": False,
            "contact": False,
            "force_n": 0.0,
            "status": "not_polled",
        }
        self.action_processor = MirrorActionProcessor(self)

    def stage_or_open(self) -> Any:
        if self.stage_provider is not None:
            stage = self.stage_provider()
            if stage is not None:
                return self._prepare_stage(stage)
        if self.use_current_stage:
            stage = _current_isaac_stage()
            if stage is not None:
                return self._prepare_stage(stage)
        if self.stage is not None:
            return self._prepare_stage(self.stage)
        Usd, _UsdPhysics, _UsdGeom = _load_usd_modules()
        if Usd is None:
            return None
        return self._prepare_stage(Usd.Stage.Open(str(self.scene_path)))

    def _prepare_stage(self, stage: Any) -> Any:
        self.stage = stage
        stage_id = id(stage)
        if self._runtime_cleanup_stage_id != stage_id:
            self._clear_stale_runtime_state(stage)
            self._runtime_cleanup_stage_id = stage_id
            self._runtime_grip_active = False
            self._last_gripper_target_value = None
        return stage

    @staticmethod
    def _clear_attr(prim: Any, name: str) -> bool:
        try:
            attr = prim.GetAttribute(name)
        except Exception:
            return False
        if attr is None:
            return False
        try:
            attr.Clear()
            return True
        except Exception:
            try:
                attr.Set(None)
                return True
            except Exception:
                return False

    @staticmethod
    def _set_or_create_vec3_attr(prim: Any, name: str, value: tuple[float, float, float]) -> bool:
        try:
            attr = prim.GetAttribute(name)
        except Exception:
            attr = None
        if attr is None:
            type_name = None
            try:
                from pxr import Sdf  # type: ignore

                type_name = Sdf.ValueTypeNames.Vector3f
            except Exception:
                type_name = None
            try:
                attr = prim.CreateAttribute(name, type_name)
            except Exception:
                return False
        try:
            attr.Set(value)
            return True
        except Exception:
            return False

    def _reset_rigid_body_velocity(self, prim: Any) -> bool:
        linear = self._set_or_create_vec3_attr(prim, "physics:velocity", (0.0, 0.0, 0.0))
        angular = self._set_or_create_vec3_attr(prim, "physics:angularVelocity", (0.0, 0.0, 0.0))
        return linear and angular

    def _clear_stale_runtime_state(self, stage: Any) -> int:
        try:
            prims = list(stage.Traverse())
        except Exception:
            return 0
        cleared = 0
        joint_runtime_attrs = (
            "drive:angular:physics:targetPosition",
            "state:angular:physics:position",
            "state:angular:physics:velocity",
        )
        link_runtime_attrs = (
            "physics:angularVelocity",
            "physics:velocity",
        )
        for prim in prims:
            try:
                path = str(prim.GetPath())
            except Exception:
                path = ""
            is_robot_geometry = "/Robot/Geometry/" in path or "/omx/Geometry/" in path or "/tn__omxscene_h8/Geometry/" in path
            if not is_robot_geometry:
                continue
            for attr_name in joint_runtime_attrs:
                if self._clear_attr(prim, attr_name):
                    cleared += 1
            for attr_name in link_runtime_attrs:
                if self._clear_attr(prim, attr_name):
                    cleared += 1
        return cleared

    def receive(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Accept a mirror sample from HTTP; apply now or queue for Isaac's update tick."""
        if not self.defer_apply:
            return self.apply(payload)
        with self.lock:
            self.sample_count += 1
            self.last_payload = self._received_payload(payload)
            self.pending_payload = dict(self.last_payload)
            self._write_latest_state(self.last_payload)
            render_result = self._handle_render_request(self.last_payload)
            result = {
                "ok": True,
                "status": "queued",
                "sample_count": self.sample_count,
                "target_count": len(_joint_targets(payload)),
                "latest_state_path": str(LATEST_STATE_PATH),
            }
            if render_result:
                result["render_request"] = render_result
            return result

    def receive_specimen_pose(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply a one-shot REDCUBE pose estimate without touching robot joint targets."""
        if self.defer_apply:
            with self.lock:
                self.pending_specimen_pose = dict(payload)
            return {
                "ok": True,
                "status": "specimen_pose_queued",
                "red_cube_path": RED_SPECIMEN_BLOCK_PATH,
                "latest_state_path": str(LATEST_STATE_PATH),
            }
        return self.apply_specimen_pose(payload)

    def receive_render(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Queue an RGB-D render snapshot without replacing the live mirror sample."""
        request = payload.get("render_request")
        if not isinstance(request, dict) or not request.get("enabled"):
            return {
                "ok": False,
                "status": "invalid",
                "failure_code": "ISAAC_RGBD_RENDER_REQUEST_MISSING",
                "message": "POST /render requires an enabled render_request object.",
            }
        if self.defer_apply:
            with self.lock:
                replaced = bool(self.pending_render_jobs)
                self.pending_render_jobs[:] = [dict(payload)]
                pending_count = len(self.pending_render_jobs)
            return {
                "ok": True,
                "status": "render_queued_replaced_stale" if replaced else "render_queued",
                "pending_render_jobs": pending_count,
                "attempt_id": str(request.get("attempt_id") or ""),
                "sample_index": request.get("sample_index", payload.get("sample_index")),
                "frame_index": request.get("frame_index", 0),
            }
        return self.apply_render(payload)

    def apply_next_render_job(self) -> dict[str, Any]:
        with self.lock:
            if isinstance(self.pending_render_payload, dict):
                return {
                    "ok": True,
                    "status": "render_waiting_for_async_step",
                    "pending_render_jobs": len(self.pending_render_jobs),
                }
            payload = dict(self.pending_render_jobs.pop(0)) if self.pending_render_jobs else {}
        if not payload:
            return {
                "ok": True,
                "status": "render_idle",
                "pending_render_jobs": 0,
            }
        result = self.apply_render(payload)
        with self.lock:
            result["pending_render_jobs"] = len(self.pending_render_jobs)
        return result

    def apply_render(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.apply(payload, record_received=False)
        render_result = result.get("render_request")
        if isinstance(render_result, dict):
            result["status"] = str(render_result.get("status") or result.get("status") or "render_processed")
        return result

    def receive_viewport_frame(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Frame the active Isaac viewport around the robot/workspace target prims."""
        if self.defer_apply:
            with self.lock:
                self.pending_viewport_frame = dict(payload or {})
            return {
                "ok": True,
                "status": "viewport_frame_queued",
                "reason": str((payload or {}).get("reason") or ""),
            }
        return self.apply_viewport_frame(payload or {})

    def receive_timeline_play(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Start Isaac's timeline from the Kit update thread when available."""
        if self.defer_apply:
            with self.lock:
                self.pending_timeline_play = dict(payload or {})
            return {
                "ok": True,
                "status": "timeline_play_queued",
                "reason": str((payload or {}).get("reason") or ""),
            }
        return self.apply_timeline_play(payload or {})

    def apply_pending_timeline_play(self) -> dict[str, Any]:
        with self.lock:
            payload = dict(self.pending_timeline_play or {})
            self.pending_timeline_play = None
        if not payload:
            return {}
        return self.apply_timeline_play(payload)

    def apply_timeline_play(self, payload: dict[str, Any]) -> dict[str, Any]:
        reason = str((payload or {}).get("reason") or "")
        if self.timeline_play_callback is None:
            result = {
                "ok": False,
                "status": "timeline_play_unavailable",
                "failure_code": "TIMELINE_PLAY_CALLBACK_UNAVAILABLE",
                "message": "Timeline play callback is not available in this receiver.",
                "reason": reason,
            }
        else:
            try:
                raw_result = self.timeline_play_callback(reason=reason)
            except Exception as exc:
                raw_result = {
                    "ok": False,
                    "status": "timeline_play_failed",
                    "failure_code": "TIMELINE_PLAY_CALLBACK_FAILED",
                    "message": f"{exc.__class__.__name__}: {exc}",
                    "reason": reason,
                }
            if isinstance(raw_result, dict):
                result = {
                    "ok": bool(raw_result.get("ok", True)),
                    "status": str(raw_result.get("status") or "timeline_play_requested"),
                    "reason": reason,
                    **raw_result,
                }
            else:
                result = {
                    "ok": False,
                    "status": "timeline_play_failed",
                    "failure_code": "TIMELINE_PLAY_INVALID_RESULT",
                    "message": "Timeline play callback did not return a dictionary.",
                    "reason": reason,
                }
        with self.lock:
            self.last_timeline_play_result = result
            self.last_apply_result = {**dict(self.last_apply_result or {}), "timeline_play": result}
        return result

    def apply_pending_viewport_frame(self) -> dict[str, Any]:
        with self.lock:
            payload = dict(self.pending_viewport_frame or {})
            self.pending_viewport_frame = None
        if not payload:
            return {}
        return self.apply_viewport_frame(payload)

    def apply_viewport_frame(self, payload: dict[str, Any]) -> dict[str, Any]:
        stage = self.stage_or_open()
        if stage is None:
            result = {
                "ok": False,
                "status": "stage_unavailable",
                "failure_code": "VIEWPORT_FRAME_STAGE_UNAVAILABLE",
                "message": "pxr/omni stage unavailable; viewport was not framed",
            }
            with self.lock:
                self.last_viewport_frame_result = result
            return result
        requested = payload.get("prim_paths") if isinstance(payload.get("prim_paths"), list) else []
        prim_paths = self._viewport_frame_prim_paths(stage, requested)
        reason = str(payload.get("reason") or "")
        callback = self.viewport_frame_callback or self._frame_active_viewport_prims
        try:
            result = callback(stage=stage, prim_paths=prim_paths, reason=reason)
        except Exception as exc:
            result = {
                "ok": False,
                "status": "viewport_frame_failed",
                "failure_code": "VIEWPORT_FRAME_CALLBACK_FAILED",
                "message": f"{exc.__class__.__name__}: {exc}",
                "prim_paths": prim_paths,
                "reason": reason,
            }
        if not isinstance(result, dict):
            result = {
                "ok": False,
                "status": "viewport_frame_failed",
                "failure_code": "VIEWPORT_FRAME_INVALID_RESULT",
                "message": "Viewport frame callback did not return a dictionary",
                "prim_paths": prim_paths,
                "reason": reason,
            }
        result = {
            "ok": bool(result.get("ok")),
            "status": str(result.get("status") or ("viewport_framed" if result.get("ok") else "viewport_frame_failed")),
            "prim_paths": list(result.get("prim_paths") or prim_paths),
            "reason": str(result.get("reason") or reason),
            **{key: value for key, value in result.items() if key not in {"ok", "status", "prim_paths", "reason"}},
        }
        with self.lock:
            self.last_viewport_frame_result = result
            if self.last_apply_result:
                self.last_apply_result = {**dict(self.last_apply_result), "viewport_frame": result}
        return result

    @staticmethod
    def _viewport_frame_prim_paths(stage: Any, requested: list[Any]) -> list[str]:
        candidates = [str(item).strip() for item in requested if str(item).strip()] or [
            "/World/Robot",
            "/World/Workspace",
        ]
        valid: list[str] = []
        for path in candidates:
            try:
                prim = stage.GetPrimAtPath(path)
            except Exception:
                prim = None
            if IsaacMirrorState._prim_is_valid(prim):
                valid.append(path)
        return valid

    @staticmethod
    def _frame_active_viewport_prims(*, stage: Any, prim_paths: list[str], reason: str = "") -> dict[str, Any]:
        try:
            from omni.kit.viewport.utility import frame_viewport_prims, frame_viewport_selection, get_active_viewport  # type: ignore
        except Exception as exc:
            return {
                "ok": False,
                "status": "viewport_frame_unavailable",
                "failure_code": "VIEWPORT_FRAME_API_UNAVAILABLE",
                "message": f"{exc.__class__.__name__}: {exc}",
                "prim_paths": prim_paths,
                "reason": reason,
            }
        viewport = get_active_viewport()
        if not viewport:
            return {
                "ok": False,
                "status": "viewport_frame_unavailable",
                "failure_code": "VIEWPORT_FRAME_NO_ACTIVE_VIEWPORT",
                "message": "No active Isaac viewport is available.",
                "prim_paths": prim_paths,
                "reason": reason,
            }
        framed = bool(frame_viewport_prims(viewport_api=viewport, prims=prim_paths)) if prim_paths else bool(frame_viewport_selection(viewport_api=viewport))
        return {
            "ok": framed,
            "status": "viewport_framed" if framed else "viewport_frame_failed",
            "prim_paths": prim_paths,
            "reason": reason,
        }

    def apply_specimen_pose(self, payload: dict[str, Any]) -> dict[str, Any]:
        stage = self.stage_or_open()
        if stage is None:
            return {
                "ok": False,
                "status": "stage_unavailable",
                "failure_code": "SPECIMEN_STAGE_UNAVAILABLE",
                "message": "pxr/omni stage unavailable; specimen pose was not applied",
            }
        pose = payload.get("pose") if isinstance(payload.get("pose"), dict) else payload
        position = pose.get("position_isaac_world_mm") if isinstance(pose, dict) else None
        if not isinstance(position, dict):
            return {
                "ok": False,
                "status": "specimen_pose_invalid",
                "failure_code": "SPECIMEN_POSE_POSITION_MISSING",
                "message": "position_isaac_world_mm is required",
            }
        try:
            translate_m = (
                float(position["x"]) * MM_TO_M,
                float(position["y"]) * MM_TO_M,
                float(position["z"]) * MM_TO_M,
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": "specimen_pose_invalid",
                "failure_code": "SPECIMEN_POSE_POSITION_INVALID",
                "message": f"{exc.__class__.__name__}: {exc}",
            }
        prim = stage.GetPrimAtPath(RED_SPECIMEN_BLOCK_PATH)
        if not self._prim_is_valid(prim):
            return {
                "ok": False,
                "status": "red_cube_missing",
                "failure_code": "SPECIMEN_RED_CUBE_PRIM_MISSING",
                "message": f"Red specimen prim not found: {RED_SPECIMEN_BLOCK_PATH}",
            }
        attr = prim.GetAttribute("xformOp:translate")
        if attr is None:
            type_name = None
            try:
                from pxr import Sdf  # type: ignore

                type_name = Sdf.ValueTypeNames.Double3
            except Exception:
                type_name = None
            attr = prim.CreateAttribute("xformOp:translate", type_name)
        attr.Set(translate_m)
        velocity_reset = self._reset_rigid_body_velocity(prim)
        yaw_deg = _specimen_yaw_deg_from_pose(pose)
        yaw_result = _apply_specimen_yaw_to_prim(prim, yaw_deg)
        if yaw_deg is not None and not bool(yaw_result.get("applied")):
            result = {
                "ok": False,
                "status": "attribute_error",
                "failure_code": str(yaw_result.get("failure_code") or "SPECIMEN_ROTATE_Z_OP_ERROR"),
                "message": str(yaw_result.get("message") or "Red specimen yaw apply failed."),
                "red_cube_path": RED_SPECIMEN_BLOCK_PATH,
            }
            with self.lock:
                self.last_specimen_pose_result = result
                self.last_apply_result = {**dict(self.last_apply_result or {}), "specimen_pose": result}
            return result
        result = {
            "ok": True,
            "status": "specimen_pose_applied",
            "red_cube_path": RED_SPECIMEN_BLOCK_PATH,
            "translate_m": [translate_m[0], translate_m[1], translate_m[2]],
            "source": str(pose.get("source") or payload.get("reason") or ""),
            "velocity_reset": velocity_reset,
        }
        if yaw_result.get("applied"):
            result["orientation_deg"] = {"yaw": yaw_result["yaw"]}
            result["xformOpOrder"] = yaw_result.get("xformOpOrder", [])
        with self.lock:
            self.last_specimen_pose_result = result
            self.last_apply_result = {**dict(self.last_apply_result or {}), "specimen_pose": result}
        return result

    def apply_latest_pending(self) -> dict[str, Any]:
        """Apply the most recent queued sample. Intended for Isaac Kit update callbacks."""
        with self.lock:
            payload = dict(self.pending_payload or {})
            self.pending_payload = None
            specimen_pose = dict(self.pending_specimen_pose or {})
            self.pending_specimen_pose = None
            viewport_frame = dict(self.pending_viewport_frame or {})
            self.pending_viewport_frame = None
            timeline_play = dict(self.pending_timeline_play or {})
            self.pending_timeline_play = None
        if not payload:
            result: dict[str, Any] = {
                "ok": True,
                "status": "idle",
                "sample_count": self.sample_count,
                "target_count": 0,
                "latest_state_path": str(LATEST_STATE_PATH),
            }
            if specimen_pose:
                specimen_result = self.apply_specimen_pose(specimen_pose)
                result = {**result, **specimen_result, "specimen_pose": specimen_result}
            if viewport_frame:
                result = {**result, "viewport_frame": self.apply_viewport_frame(viewport_frame)}
            if timeline_play:
                result = {**result, "timeline_play": self.apply_timeline_play(timeline_play)}
            if specimen_pose or viewport_frame or timeline_play:
                with self.lock:
                    self.last_apply_result = result
            return result
        result = self.apply(payload, record_received=False)
        if specimen_pose:
            specimen_result = self.apply_specimen_pose(specimen_pose)
            result = {**result, "specimen_pose": specimen_result}
            with self.lock:
                self.last_apply_result = result
        if viewport_frame:
            viewport_result = self.apply_viewport_frame(viewport_frame)
            result = {**result, "viewport_frame": viewport_result}
            with self.lock:
                self.last_apply_result = result
        if timeline_play:
            timeline_result = self.apply_timeline_play(timeline_play)
            result = {**result, "timeline_play": timeline_result}
            with self.lock:
                self.last_apply_result = result
        return result

    def finalize_pending_render(self) -> dict[str, Any]:
        pending = self.pending_render_payload
        if not isinstance(pending, dict):
            return {}
        stage = self.stage_or_open()
        if stage is None:
            return {}
        payload = dict(pending.get("payload") or {})
        request = dict(pending.get("request") or {})
        if not payload or not request:
            self.pending_render_payload = None
            return {}
        request["_atr_finalize_after_async_step"] = True
        payload["render_request"] = request
        result = self._handle_render_request(payload, render=True, stage=stage)
        if result.get("status") != "render_pending":
            self.pending_render_payload = None
        return result

    def apply(self, payload: dict[str, Any], *, record_received: bool = True) -> dict[str, Any]:
        targets = _joint_targets(payload)
        with self.lock:
            if record_received:
                self.sample_count += 1
                self.last_payload = self._received_payload(payload)
                self._write_latest_state(self.last_payload)
            else:
                self.last_payload = dict(payload)
            stage = self.stage_or_open()
            if stage is None:
                render_result = self._handle_render_request(self.last_payload, render=False)
                self.last_error = "pxr/omni stage unavailable; latest JSON state was written only"
                self.last_apply_result = {
                    "ok": False,
                    "status": "stage_unavailable",
                    "message": self.last_error,
                    "sample_count": self.sample_count,
                    "target_count": len(targets),
                    "latest_state_path": str(LATEST_STATE_PATH),
                }
                if render_result:
                    self.last_apply_result["render_request"] = render_result
                return dict(self.last_apply_result)
            stage_summary = self._stage_summary(stage)
            action_processing = self.action_processor.process(stage, targets)
            gripper_contact = action_processing["gripper_contact"]
            gripper_effort_limit = action_processing["gripper_effort_limit"]
            grasp_diagnostics = action_processing["grasp_diagnostics"]
            applied = []
            applied_targets = []
            missing = []
            for target in targets:
                if self._apply_joint_target(stage, target):
                    applied.append(target["path"])
                    applied_targets.append(self._applied_target_summary(target))
                else:
                    missing.append(target["path"])
                mimic_path = target.get("mimic_path") or ""
                if mimic_path:
                    mimic_multiplier = _safe_float(target.get("mimic_multiplier"), 1.0)
                    mimic = {**target, "path": mimic_path, "target_value": float(target["target_value"]) * mimic_multiplier}
                    if self._apply_joint_target(stage, mimic):
                        applied.append(mimic_path)
                        applied_targets.append(self._applied_target_summary(mimic))
                    else:
                        missing.append(mimic_path)
            runtime_grip = self._apply_runtime_grip_constraint(stage, targets)
            joint_readback = self._joint_readback_summary(stage, targets)
            robot_contacts = self._poll_robot_contact_summary(stage)
            if self.save_stage_on_apply:
                try:
                    stage.GetRootLayer().Save()
                except Exception:
                    pass
            action_processing_summary = {
                "processor": action_processing["processor"],
                "gripper_contact_status": gripper_contact.get("status"),
                "gripper_effort_status": gripper_effort_limit.get("status"),
                "grasp_status": grasp_diagnostics.get("status"),
            }
            action_metadata = {
                "action_processing": action_processing_summary,
                "gripper_contact": gripper_contact,
                "gripper_effort_limit": gripper_effort_limit,
                "grasp_diagnostics": grasp_diagnostics,
            }
            render_result = self._handle_render_request(
                self.last_payload,
                render=True,
                stage=stage,
                action_metadata=action_metadata,
            )
            self.last_apply_result = {
                "ok": True,
                "status": "applied",
                "sample_count": self.sample_count,
                "target_count": len(targets),
                "applied_count": len(applied),
                "applied_paths": applied[:12],
                "applied_targets": applied_targets[:12],
                "missing_paths": missing[:12],
                "runtime_grip": runtime_grip,
                "action_processing": action_processing_summary,
                "gripper_contact": gripper_contact,
                "gripper_effort_limit": gripper_effort_limit,
                "grasp_diagnostics": grasp_diagnostics,
                "robot_contacts": robot_contacts,
                "joint_readback": joint_readback,
                "stage_summary": stage_summary,
                "latest_state_path": str(LATEST_STATE_PATH),
            }
            if render_result:
                self.last_apply_result["render_request"] = render_result
            return dict(self.last_apply_result)

    def _received_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            **payload,
            "server_received_at": datetime.now(timezone.utc).isoformat(),
            "server_sample_count": self.sample_count,
        }

    @staticmethod
    def _write_latest_state(payload: dict[str, Any]) -> None:
        LATEST_STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _handle_render_request(
        self,
        payload: dict[str, Any],
        *,
        render: bool = False,
        stage: Any | None = None,
        action_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = payload.get("render_request")
        if not isinstance(request, dict) or not request.get("enabled"):
            return {}
        raw_output_dir = str(request.get("output_dir") or "").strip()
        if not raw_output_dir:
            result = {
                "ok": False,
                "status": "invalid",
                "failure_code": "ISAAC_RGBD_RENDER_OUTPUT_DIR_MISSING",
                "message": "render_request.output_dir is required",
            }
            self.last_render_request_result = result
            return result
        output_dir = Path(raw_output_dir).expanduser()
        manifest_path = output_dir / "manifest.jsonl"
        cameras = [str(item) for item in request.get("cameras", []) if str(item).strip()] if isinstance(request.get("cameras"), list) else []
        row = {
            "schema": "atr.isaac_rgbd.render_manifest.v1",
            "status": "metadata_only",
            "session_id": str(request.get("session_id") or payload.get("session_id") or ""),
            "attempt_id": str(request.get("attempt_id") or ""),
            "episode_index": request.get("episode_index", 0),
            "frame_index": request.get("frame_index", 0),
            "sample_index": request.get("sample_index", payload.get("sample_index")),
            "record_timestamp": str(request.get("timestamp") or payload.get("timestamp") or ""),
            "server_received_at": str(payload.get("server_received_at") or datetime.now(timezone.utc).isoformat()),
            "target_fps": request.get("target_fps", 0),
            "cameras": cameras,
            "output_dir": str(output_dir),
            "files": [],
        }
        metadata = dict(action_metadata or {})
        for key in ("action_processing", "gripper_contact", "gripper_effort_limit", "grasp_diagnostics"):
            if key not in metadata and key in payload:
                metadata[key] = payload[key]
            if key in metadata:
                row[key] = metadata[key]
        render_payload: dict[str, Any] = {}
        if render:
            render_payload = self._run_rgbd_render_backend(dict(request), output_dir=output_dir, stage=stage, payload=payload)
            row.update(
                {
                    "status": str(render_payload.get("status") or ("rendered" if render_payload.get("ok") else "render_failed")),
                    "backend": str(render_payload.get("backend") or ""),
                    "files": self._normalize_render_files(render_payload.get("files")),
                }
            )
            for key in ("camera_results", "message", "failure_code", "step_mode", "pending_key"):
                if key in render_payload:
                    row[key] = render_payload[key]
            if row["status"] == "render_pending":
                pending_payload = {**dict(payload), **metadata}
                self.pending_render_payload = {"payload": pending_payload, "request": dict(request)}
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            with manifest_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:
            result = {
                "ok": False,
                "status": "write_failed",
                "failure_code": "ISAAC_RGBD_RENDER_MANIFEST_WRITE_FAILED",
                "message": f"{exc.__class__.__name__}: {exc}",
                "manifest_path": str(manifest_path),
            }
            self.last_render_request_result = result
            return result
        result = {
            "ok": bool(render_payload.get("ok", True)),
            "status": row["status"],
            "manifest_path": str(manifest_path),
            "output_dir": str(output_dir),
            "attempt_id": row["attempt_id"],
            "sample_index": row["sample_index"],
            "frame_index": row["frame_index"],
            "backend": row.get("backend", ""),
            "files": row.get("files", []),
        }
        if "failure_code" in row:
            result["failure_code"] = row["failure_code"]
        if "message" in row:
            result["message"] = row["message"]
        if "camera_results" in row:
            result["camera_results"] = row["camera_results"]
        if "step_mode" in row:
            result["step_mode"] = row["step_mode"]
        if "pending_key" in row:
            result["pending_key"] = row["pending_key"]
        self.last_render_request_result = result
        return result

    def _run_rgbd_render_backend(
        self,
        request: dict[str, Any],
        *,
        output_dir: Path,
        stage: Any | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        backend = self.rgbd_render_backend
        if backend is None:
            return {"ok": True, "status": "metadata_only", "backend": "none", "files": []}
        try:
            result = backend(request=request, output_dir=output_dir, stage=stage, payload=payload)
        except Exception as exc:
            return {
                "ok": False,
                "status": "render_failed",
                "backend": getattr(backend, "name", backend.__class__.__name__),
                "failure_code": "ISAAC_RGBD_RENDER_BACKEND_EXCEPTION",
                "message": f"{exc.__class__.__name__}: {exc}",
                "files": [],
            }
        if not isinstance(result, dict):
            return {
                "ok": False,
                "status": "render_failed",
                "backend": getattr(backend, "name", backend.__class__.__name__),
                "failure_code": "ISAAC_RGBD_RENDER_BACKEND_INVALID_RESULT",
                "message": "RGBD render backend did not return a dictionary",
                "files": [],
            }
        if str(result.get("failure_code") or "") == "ISAAC_RGBD_RENDER_BACKEND_UNAVAILABLE":
            return {
                **result,
                "ok": True,
                "status": "metadata_only",
                "files": self._normalize_render_files(result.get("files")),
            }
        return {
            **result,
            "status": str(result.get("status") or ("rendered" if result.get("ok") else "render_failed")),
            "files": self._normalize_render_files(result.get("files")),
        }

    @staticmethod
    def _normalize_render_files(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        files: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            files.append({**item, "path": path})
        return files

    @staticmethod
    def _applied_target_summary(target: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "path": str(target.get("path") or ""),
            "name": str(target.get("name") or ""),
            "motor_id": target.get("motor_id"),
            "motor_model": str(target.get("motor_model") or ""),
            "target_value": target.get("target_value"),
            "raw_target_value": target.get("raw_target_value"),
            "slew_limited": bool(target.get("slew_limited")),
            "backlash_deg": target.get("backlash_deg"),
            "backlash_source": target.get("backlash_source"),
            "backlash_applied": bool(target.get("backlash_applied", False)),
            "backlash_direction": target.get("backlash_direction"),
            "source_value": target.get("source_value"),
            "recomputed_from_source": bool(target.get("recomputed_from_source")),
            "drive_stiffness": target.get("drive_stiffness"),
            "drive_damping": target.get("drive_damping"),
            "drive_max_force": target.get("drive_max_force"),
            "dynamic_gripper_effort_limit": target.get("dynamic_gripper_effort_limit"),
            "dynamic_gripper_effort_object_mass_kg": target.get("dynamic_gripper_effort_object_mass_kg"),
            "dynamic_gripper_mass_scaled_effort_limit": target.get("dynamic_gripper_mass_scaled_effort_limit"),
            "physics_lower_limit": target.get("physics_lower_limit"),
            "physics_upper_limit": target.get("physics_upper_limit"),
            "contact_probe_limited": bool(target.get("contact_probe_limited")),
            "contact_hold_active": bool(target.get("contact_hold_active")),
            "contact_hold_target_value": target.get("contact_hold_target_value"),
            "contact_penetration_limited": bool(target.get("contact_penetration_limited")),
            "unit": str(target.get("unit") or ""),
        }
        for key in (
            "conversion_mode",
            "source_raw_position",
            "source_zero_raw_position",
            "dynamixel_deg_per_tick",
            "source_raw_clamped",
        ):
            if key in target:
                summary[key] = target[key]
        return summary

    @staticmethod
    def _attr_float_from_prim(prim: Any, attr_name: str) -> float | None:
        try:
            attr = prim.GetAttribute(attr_name)
            if not attr:
                return None
            value = attr.Get()
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    def _joint_readback_summary(self, stage: Any, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for target in targets:
            path = str(target.get("path") or "")
            if not path:
                continue
            try:
                prim = stage.GetPrimAtPath(path)
            except Exception:
                prim = None
            if not prim or not prim.IsValid():
                continue
            target_value = _safe_float(target.get("target_value"), 0.0)
            drive_target = self._attr_float_from_prim(prim, "drive:angular:physics:targetPosition")
            state_position = self._attr_float_from_prim(prim, "state:angular:physics:position")
            state_velocity = self._attr_float_from_prim(prim, "state:angular:physics:velocity")
            rows.append(
                {
                    "path": path,
                    "name": str(target.get("name") or ""),
                    "motor_id": target.get("motor_id"),
                    "target_value": target_value,
                    "drive_target_position": drive_target,
                    "state_position": state_position,
                    "state_velocity": state_velocity,
                    "target_minus_state": None if state_position is None else target_value - state_position,
                    "physics_lower_limit": self._attr_float_from_prim(prim, "physics:lowerLimit"),
                    "physics_upper_limit": self._attr_float_from_prim(prim, "physics:upperLimit"),
                    "drive_max_force": self._attr_float_from_prim(prim, "drive:angular:physics:maxForce"),
                    "drive_stiffness": self._attr_float_from_prim(prim, "drive:angular:physics:stiffness"),
                    "drive_damping": self._attr_float_from_prim(prim, "drive:angular:physics:damping"),
                }
            )
        return rows[:12]

    @staticmethod
    def _prim_is_valid(prim: Any) -> bool:
        try:
            return bool(prim and prim.IsValid())
        except Exception:
            return bool(prim)

    @staticmethod
    def _vec3(value: Any) -> tuple[float, float, float] | None:
        if value is None:
            return None
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except Exception:
            return None

    @staticmethod
    def _avg_vec3(values: list[tuple[float, float, float]]) -> tuple[float, float, float] | None:
        if not values:
            return None
        scale = 1.0 / len(values)
        return (
            sum(value[0] for value in values) * scale,
            sum(value[1] for value in values) * scale,
            sum(value[2] for value in values) * scale,
        )

    @staticmethod
    def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5

    @staticmethod
    def _prim_world_translation(prim: Any) -> tuple[float, float, float] | None:
        if not IsaacMirrorState._prim_is_valid(prim):
            return None
        try:
            from pxr import Usd, UsdGeom  # type: ignore

            matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            return IsaacMirrorState._vec3(matrix.ExtractTranslation())
        except Exception:
            pass
        try:
            attr = prim.GetAttribute("xformOp:translate")
            if attr:
                return IsaacMirrorState._vec3(attr.Get())
        except Exception:
            return None
        return None

    @staticmethod
    def _local_position_for_world_point(prim: Any, world_point: tuple[float, float, float]) -> tuple[float, float, float]:
        try:
            from pxr import Usd, UsdGeom, Gf  # type: ignore

            matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            local = matrix.GetInverse().Transform(Gf.Vec3d(*world_point))
            return (float(local[0]), float(local[1]), float(local[2]))
        except Exception:
            return (0.0, 0.0, 0.0)

    @staticmethod
    def _target_is_gripper(target: dict[str, Any]) -> bool:
        name = str(target.get("name") or "")
        motor_name = str(target.get("motor_name") or "")
        motor_id = target.get("motor_id")
        return name == "Gripper" or motor_name == "gripper" or str(motor_id) == "16"

    @staticmethod
    def _prim_mass_kg(stage: Any, prim_path: str) -> float | None:
        try:
            prim = stage.GetPrimAtPath(prim_path)
        except Exception:
            return None
        if not IsaacMirrorState._prim_is_valid(prim):
            return None
        try:
            attr = prim.GetAttribute("physics:mass")
        except Exception:
            return None
        if not attr:
            return None
        mass = _safe_float(attr.Get(), float("nan"))
        if mass != mass or mass <= 0.0:
            return None
        return mass

    @staticmethod
    def _contact_report_is_reliable(contact: dict[str, Any]) -> bool:
        if not bool(contact.get("contact")):
            return False
        force_n = _safe_float(contact.get("force_n", contact.get("max_force_n")), 0.0)
        penetration_m = _safe_float(contact.get("penetration_m", contact.get("max_penetration_m")), 0.0)
        return force_n > 0.0 or penetration_m > 0.0

    def _apply_dynamic_gripper_effort_limit(
        self,
        stage: Any,
        targets: list[dict[str, Any]],
        gripper_contact: dict[str, Any],
    ) -> dict[str, Any]:
        gripper_targets = [target for target in targets if self._target_is_gripper(target)]
        if not gripper_targets:
            return {"enabled": False, "status": "no_gripper_target"}
        object_mass_kg = self._prim_mass_kg(stage, RED_SPECIMEN_BLOCK_PATH)
        if object_mass_kg is None:
            return {
                "enabled": False,
                "status": "object_mass_unavailable",
                "object_path": RED_SPECIMEN_BLOCK_PATH,
            }
        mass_scaled_effort_limit = object_mass_kg / LEISAAC_GRIPPER_EFFORT_MASS_DIVISOR_KG
        base_effort_limits = [
            _safe_float(target.get("drive_max_force"), float("nan"))
            for target in gripper_targets
        ]
        base_effort_limits = [value for value in base_effort_limits if value == value and value > 0.0]
        base_effort_limit = max(base_effort_limits) if base_effort_limits else 10.0
        contact_reliable = self._contact_report_is_reliable(gripper_contact)
        effort_limit = base_effort_limit
        for target in gripper_targets:
            target["drive_max_force"] = effort_limit
            target["dynamic_gripper_effort_limit"] = effort_limit
            target["dynamic_gripper_effort_object_mass_kg"] = object_mass_kg
            target["dynamic_gripper_mass_scaled_effort_limit"] = mass_scaled_effort_limit
        return {
            "enabled": True,
            "status": "stable_drive_effort",
            "object_path": RED_SPECIMEN_BLOCK_PATH,
            "object_mass_kg": object_mass_kg,
            "mass_divisor_kg": LEISAAC_GRIPPER_EFFORT_MASS_DIVISOR_KG,
            "mass_scaled_effort_limit": mass_scaled_effort_limit,
            "base_effort_limit": base_effort_limit,
            "effort_limit": effort_limit,
            "contact_reliable": contact_reliable,
        }

    def _annotate_gripper_raw_targets(self, targets: list[dict[str, Any]]) -> None:
        for target in targets:
            if not self._target_is_gripper(target):
                continue
            value = _safe_float(target.get("target_value"), float("nan"))
            if value != value:
                continue
            target["raw_target_value"] = value
            target["slew_limited"] = False

    def _remember_final_gripper_target(self, targets: list[dict[str, Any]]) -> None:
        value = self._gripper_target_value(targets)
        if value is not None:
            self._last_gripper_target_value = value

    @staticmethod
    def _gripper_target_value(targets: list[dict[str, Any]]) -> float | None:
        for target in targets:
            if IsaacMirrorState._target_is_gripper(target):
                value = _safe_float(target.get("target_value"), float("nan"))
                if value == value:
                    return value
        return None

    @staticmethod
    def _gripper_raw_target_value(targets: list[dict[str, Any]]) -> float | None:
        for target in targets:
            if IsaacMirrorState._target_is_gripper(target):
                raw_value = target.get("raw_target_value", target.get("target_value"))
                value = _safe_float(raw_value, float("nan"))
                if value == value:
                    return value
        return None

    @staticmethod
    def _vector_magnitude(value: Any) -> float:
        try:
            return sum(float(item) ** 2 for item in value) ** 0.5
        except Exception:
            return 0.0

    @staticmethod
    def _path_matches_any(path: str, tokens: tuple[str, ...]) -> bool:
        return any(token in path for token in tokens)

    @staticmethod
    def _gripper_contact_side_for_path(path: str) -> str | None:
        path = str(path)
        if (
            "/link7" in path
            or "follower_08_gripper_gear" in path
            or "Gripper_mimic" in path
            or "InnerGripPadCollision_mimic" in path
        ):
            return GRIPPER_CONTACT_MIMIC_SIDE
        if (
            "/link6" in path
            or "follower_07_gripper_motorized" in path
            or "InnerGripPadCollision" in path
        ):
            return GRIPPER_CONTACT_PRIMARY_SIDE
        return None

    def _gripper_finger_positions(self, stage: Any) -> list[dict[str, Any]]:
        positions: list[dict[str, Any]] = []
        try:
            prims = list(stage.Traverse())
        except Exception:
            prims = []
        for prim in prims:
            try:
                path = str(prim.GetPath())
            except Exception:
                continue
            if not self._path_matches_any(path, GRIPPER_CONTACT_COLLIDER_TOKENS):
                continue
            position = self._prim_world_translation(prim)
            if position is None:
                continue
            positions.append({"path": path, "position": position})
        return positions[:16]

    def _grasp_diagnostics(
        self,
        stage: Any,
        targets: list[dict[str, Any]],
        gripper_contact: dict[str, Any],
    ) -> dict[str, Any]:
        gripper_target = self._gripper_target_value(targets)
        gripper_raw_target = self._gripper_raw_target_value(targets)
        if stage is None:
            return {
                "available": False,
                "status": "stage_unavailable",
                "object_path": RED_SPECIMEN_BLOCK_PATH,
                "gripper_target_value": gripper_target,
                "gripper_raw_target_value": gripper_raw_target,
            }
        try:
            object_prim = stage.GetPrimAtPath(RED_SPECIMEN_BLOCK_PATH)
        except Exception:
            object_prim = None
        object_position = self._prim_world_translation(object_prim) if object_prim is not None else None
        if object_position is None:
            return {
                "available": False,
                "status": "missing_object_position",
                "object_path": RED_SPECIMEN_BLOCK_PATH,
                "gripper_target_value": gripper_target,
                "gripper_raw_target_value": gripper_raw_target,
                "contact": bool(gripper_contact.get("contact")),
            }
        finger_positions = self._gripper_finger_positions(stage)
        distances = [
            self._distance(tuple(item["position"]), object_position)
            for item in finger_positions
            if isinstance(item.get("position"), tuple)
        ]
        min_distance = min(distances) if distances else None
        gripper_closed = gripper_target is not None and gripper_target <= GRIPPER_CLOSED_TARGET_THRESHOLD_DEG
        near_object = min_distance is not None and min_distance <= GRIPPER_OBJECT_NEAR_DISTANCE_M
        contact = bool(gripper_contact.get("contact"))
        contact_reliable = self._contact_report_is_reliable(gripper_contact)
        lifted = object_position[2] >= GRIPPER_OBJECT_LIFTED_Z_M
        if gripper_target is None:
            status = "no_gripper_target"
        elif not finger_positions:
            status = "no_finger_positions"
        elif not gripper_closed:
            status = "gripper_open"
        elif near_object and contact:
            status = "grasp_candidate"
        elif near_object:
            status = "near_closed_without_contact"
        else:
            status = "closed_not_near_object"
        return {
            "available": True,
            "status": status,
            "object_path": RED_SPECIMEN_BLOCK_PATH,
            "object_position": [object_position[0], object_position[1], object_position[2]],
            "object_lifted": lifted,
            "lifted_threshold_z_m": GRIPPER_OBJECT_LIFTED_Z_M,
            "finger_count": len(finger_positions),
            "finger_paths": [str(item["path"]) for item in finger_positions[:8]],
            "min_finger_distance_m": min_distance,
            "near_object": near_object,
            "near_threshold_m": GRIPPER_OBJECT_NEAR_DISTANCE_M,
            "gripper_target_value": gripper_target,
            "gripper_raw_target_value": gripper_raw_target,
            "gripper_closed": gripper_closed,
            "closed_threshold_deg": GRIPPER_CLOSED_TARGET_THRESHOLD_DEG,
            "contact": contact,
            "contact_reliable": contact_reliable,
            "contact_status": str(gripper_contact.get("status") or ""),
            "contact_force_n": _safe_float(gripper_contact.get("force_n"), 0.0),
            "contact_penetration_m": _safe_float(gripper_contact.get("penetration_m"), 0.0),
            "contact_matched_pairs": int(_safe_float(gripper_contact.get("matched_pairs"), 0.0)),
        }

    def _poll_gripper_contact_force(self, stage: Any) -> dict[str, Any]:
        if self.contact_force_provider is not None:
            try:
                provided = self.contact_force_provider(stage)
                result = {
                    "available": bool(provided.get("available", True)),
                    "contact": bool(provided.get("contact", False)),
                    "raw_contact": bool(provided.get("raw_contact", provided.get("contact", False))),
                    "both_sides_contact": bool(provided.get("both_sides_contact", provided.get("contact", False))),
                    "gripper_contact_sides": list(provided.get("gripper_contact_sides") or []),
                    "force_n": _safe_float(provided.get("force_n"), 0.0),
                    "status": str(provided.get("status") or "provided"),
                }
                for key in ("penetration_m", "matched_pairs", "matched_pair_paths"):
                    if key in provided:
                        result[key] = provided[key]
                return result
            except Exception as exc:
                return {
                    "available": False,
                    "contact": False,
                    "force_n": 0.0,
                    "status": f"provider_error:{exc.__class__.__name__}",
                }
        try:
            from omni.physx import get_physx_simulation_interface  # type: ignore
            from pxr import PhysicsSchemaTools  # type: ignore
        except Exception as exc:
            return {
                "available": False,
                "contact": False,
                "force_n": 0.0,
                "status": f"contact_report_unavailable:{exc.__class__.__name__}",
            }
        try:
            interface = get_physx_simulation_interface()
            headers, contacts = interface.get_contact_report()
        except Exception as exc:
            return {
                "available": False,
                "contact": False,
                "force_n": 0.0,
                "status": f"contact_report_error:{exc.__class__.__name__}",
            }

        max_force_n = 0.0
        max_penetration_m = 0.0
        matched_pairs = 0
        matched_pair_paths: list[dict[str, str]] = []
        gripper_contact_sides: set[str] = set()
        try:
            dt = DEFAULT_PHYSICS_DT_S
            getter = getattr(interface, "get_simulation_time_steps_per_second", None)
            if callable(getter):
                try:
                    stage_id = 0
                    scene_path = ""
                    rate = float(getter(stage_id, scene_path))
                    if rate > 0:
                        dt = 1.0 / rate
                except Exception:
                    dt = DEFAULT_PHYSICS_DT_S
            for header in headers:
                has_collider_paths = hasattr(header, "collider0") and hasattr(header, "collider1")
                path0 = getattr(header, "collider0", getattr(header, "actor0", ""))
                path1 = getattr(header, "collider1", getattr(header, "actor1", ""))
                collider0 = str(PhysicsSchemaTools.intToSdfPath(path0))
                collider1 = str(PhysicsSchemaTools.intToSdfPath(path1))
                pair = (collider0, collider1)
                has_gripper = any(self._path_matches_any(path, GRIPPER_CONTACT_COLLIDER_TOKENS) for path in pair)
                has_object = any(self._path_matches_any(path, GRIPPER_CONTACT_OBJECT_TOKENS) for path in pair)
                if not (has_gripper and has_object):
                    continue
                for path in pair:
                    if not self._path_matches_any(path, GRIPPER_CONTACT_COLLIDER_TOKENS):
                        continue
                    side = self._gripper_contact_side_for_path(path)
                    if side is not None:
                        gripper_contact_sides.add(side)
                matched_pairs += 1
                if len(matched_pair_paths) < 8:
                    if has_collider_paths:
                        matched_pair_paths.append({"collider0": collider0, "collider1": collider1})
                    else:
                        matched_pair_paths.append({"actor0": str(path0), "actor1": str(path1)})
                start = int(getattr(header, "contact_data_offset", 0) or 0)
                count = int(getattr(header, "num_contact_data", 0) or 0)
                for index in range(start, start + count):
                    if index < 0 or index >= len(contacts):
                        continue
                    contact = contacts[index]
                    impulse_n_s = self._vector_magnitude(getattr(contact, "impulse", (0.0, 0.0, 0.0)))
                    max_force_n = max(max_force_n, impulse_n_s / dt if dt > 0 else 0.0)
                    separation = _safe_float(getattr(contact, "separation", 0.0), 0.0)
                    if separation < 0:
                        max_penetration_m = max(max_penetration_m, abs(separation))
        except Exception as exc:
            return {
                "available": False,
                "contact": False,
                "force_n": 0.0,
                "status": f"contact_parse_error:{exc.__class__.__name__}",
            }
        ordered_sides = [side for side in GRIPPER_CONTACT_SIDE_ORDER if side in gripper_contact_sides]
        raw_contact = matched_pairs > 0
        both_sides_contact = all(side in gripper_contact_sides for side in GRIPPER_CONTACT_SIDE_ORDER)
        return {
            "available": True,
            "contact": both_sides_contact,
            "raw_contact": raw_contact,
            "both_sides_contact": both_sides_contact,
            "gripper_contact_sides": ordered_sides,
            "force_n": max_force_n,
            "penetration_m": max_penetration_m,
            "matched_pairs": matched_pairs,
            "matched_pair_paths": matched_pair_paths,
            "contact_acceptance": "both_sides" if both_sides_contact else "single_side" if raw_contact else "none",
            "status": "contact_report",
        }

    def _poll_robot_contact_summary(self, stage: Any) -> dict[str, Any]:
        try:
            from omni.physx import get_physx_simulation_interface  # type: ignore
            from pxr import PhysicsSchemaTools  # type: ignore
        except Exception as exc:
            return {"available": False, "status": f"contact_report_unavailable:{exc.__class__.__name__}"}
        try:
            interface = get_physx_simulation_interface()
            headers, contacts = interface.get_contact_report()
        except Exception as exc:
            return {"available": False, "status": f"contact_report_error:{exc.__class__.__name__}"}
        matched_pairs = 0
        matched_pair_paths: list[dict[str, Any]] = []
        max_force_n = 0.0
        max_penetration_m = 0.0
        dt = DEFAULT_PHYSICS_DT_S
        try:
            for header in headers:
                try:
                    collider0 = str(PhysicsSchemaTools.intToSdfPath(getattr(header, "actor0", 0))).replace("Sdf.Path('", "").replace("')", "")
                    collider1 = str(PhysicsSchemaTools.intToSdfPath(getattr(header, "actor1", 0))).replace("Sdf.Path('", "").replace("')", "")
                except Exception:
                    continue
                if not self._path_matches_any(collider0, ("Robot/Geometry", "omx/Geometry", "tn__omxscene_h8/Geometry")):
                    continue
                if not self._path_matches_any(collider1, ("Robot/Geometry", "omx/Geometry", "tn__omxscene_h8/Geometry", "Workspace", "Table")):
                    continue
                matched_pairs += 1
                start = int(getattr(header, "contact_data_offset", 0) or 0)
                count = int(getattr(header, "num_contact_data", 0) or 0)
                pair_force_n = 0.0
                pair_penetration_m = 0.0
                for index in range(start, start + count):
                    if index < 0 or index >= len(contacts):
                        continue
                    contact = contacts[index]
                    impulse_n_s = self._vector_magnitude(getattr(contact, "impulse", (0.0, 0.0, 0.0)))
                    force_n = impulse_n_s / dt if dt > 0 else 0.0
                    pair_force_n = max(pair_force_n, force_n)
                    max_force_n = max(max_force_n, force_n)
                    separation = _safe_float(getattr(contact, "separation", 0.0), 0.0)
                    if separation < 0:
                        penetration = abs(separation)
                        pair_penetration_m = max(pair_penetration_m, penetration)
                        max_penetration_m = max(max_penetration_m, penetration)
                if len(matched_pair_paths) < 16:
                    matched_pair_paths.append(
                        {
                            "collider0": collider0,
                            "collider1": collider1,
                            "force_n": pair_force_n,
                            "penetration_m": pair_penetration_m,
                        }
                    )
        except Exception as exc:
            return {"available": False, "status": f"contact_parse_error:{exc.__class__.__name__}"}
        return {
            "available": True,
            "status": "contact_report",
            "matched_pairs": matched_pairs,
            "max_force_n": max_force_n,
            "max_penetration_m": max_penetration_m,
            "matched_pair_paths": matched_pair_paths,
        }

    def _apply_gripper_contact_control(
        self,
        stage: Any,
        targets: list[dict[str, Any]],
        previous_gripper_target: float | None,
    ) -> dict[str, Any]:
        contact = self._poll_gripper_contact_force(stage)
        for target in targets:
            target["contact_probe_limited"] = False
            target["contact_hold_active"] = False
            target["contact_hold_target_value"] = None
            target["contact_penetration_limited"] = False

        gripper_targets = [target for target in targets if self._target_is_gripper(target)]
        hold_target_value = self._gripper_contact_hold_target_value
        hold_reason = ""
        released_this_tick = False
        primary_target = gripper_targets[0] if gripper_targets else None
        primary_value = (
            _safe_float(primary_target.get("target_value"), float("nan"))
            if primary_target is not None
            else float("nan")
        )
        contact_reliable = self._contact_report_is_reliable(contact)

        if hold_target_value is not None and primary_value == primary_value:
            if primary_value > hold_target_value + GRIPPER_CONTACT_RELEASE_MARGIN_DEG:
                hold_target_value = None
                self._gripper_contact_hold_target_value = None
                hold_reason = "released_opening"
                released_this_tick = True

        if (
            hold_target_value is None
            and primary_target is not None
            and primary_value == primary_value
            and contact_reliable
            and not released_this_tick
        ):
            closing_or_unknown = previous_gripper_target is None or primary_value <= previous_gripper_target
            if closing_or_unknown:
                if previous_gripper_target is None:
                    hold_target_value = primary_value
                else:
                    hold_target_value = max(
                        primary_value,
                        previous_gripper_target - GRIPPER_CONTACT_HOLD_OVERTRAVEL_DEG,
                    )
                self._gripper_contact_hold_target_value = hold_target_value
                hold_reason = "contact_hold_armed"

        hold_active = hold_target_value is not None
        probe_limited = False
        if (
            not hold_active
            and primary_target is not None
            and primary_value == primary_value
            and previous_gripper_target is not None
        ):
            max_close_target_value = previous_gripper_target - GRIPPER_CONTACT_PROBE_MAX_CLOSE_STEP_DEG
            if primary_value < max_close_target_value:
                for target in gripper_targets:
                    value = _safe_float(target.get("target_value"), float("nan"))
                    if value == value and value < max_close_target_value:
                        target["target_value"] = max_close_target_value
                        target["contact_probe_limited"] = True
                        probe_limited = True
                if probe_limited and not hold_reason:
                    hold_reason = "contact_probe_limited"

        clamped = False
        if hold_active:
            for target in gripper_targets:
                value = _safe_float(target.get("target_value"), float("nan"))
                if value == value and value < hold_target_value:
                    target["target_value"] = hold_target_value
                    target["contact_hold_clamped"] = True
                    clamped = True
                else:
                    target["contact_hold_clamped"] = False
                target["contact_hold_active"] = True
                target["contact_hold_target_value"] = hold_target_value
            if clamped:
                hold_reason = "contact_hold_clamped"
            elif not hold_reason:
                hold_reason = "contact_hold_tracking"

        self._remember_final_gripper_target(targets)
        self._last_gripper_contact = {
            **contact,
            "hold_active": hold_active,
            "hold_reason": hold_reason,
            "hold_target_value": hold_target_value,
            "hold_overtravel_deg": GRIPPER_CONTACT_HOLD_OVERTRAVEL_DEG,
            "release_margin_deg": GRIPPER_CONTACT_RELEASE_MARGIN_DEG,
            "probe_limited": probe_limited,
        }
        return dict(self._last_gripper_contact)

    @staticmethod
    def _runtime_grip_joint_exists(stage: Any) -> bool:
        try:
            return IsaacMirrorState._prim_is_valid(stage.GetPrimAtPath(RUNTIME_GRIP_JOINT_PATH))
        except Exception:
            return False

    def _remove_runtime_grip_joint(self, stage: Any) -> bool:
        self._runtime_grip_active = False
        try:
            if self._runtime_grip_joint_exists(stage):
                return bool(stage.RemovePrim(RUNTIME_GRIP_JOINT_PATH))
        except Exception:
            return False
        return True

    def _apply_runtime_grip_constraint(self, stage: Any, targets: list[dict[str, Any]]) -> dict[str, Any]:
        gripper_target = self._gripper_target_value(targets)
        gripper_raw_target = self._gripper_raw_target_value(targets)
        removed_legacy_joint = self._remove_runtime_grip_joint(stage) if self._runtime_grip_joint_exists(stage) else False
        if gripper_target is None:
            return {
                "enabled": False,
                "status": "idle",
                "active": False,
                "removed_legacy_joint": removed_legacy_joint,
            }
        self._runtime_grip_active = False
        return {
            "enabled": False,
            "status": "runtime_grip_disabled",
            "active": False,
            "removed_legacy_joint": removed_legacy_joint,
            "gripper_target": gripper_target,
            "gripper_raw_target": gripper_raw_target,
        }

    def status_payload(self) -> dict[str, Any]:
        with self.lock:
            return {
                "ok": True,
                "status": "ready",
                "apply_mode": "deferred_update_tick" if self.defer_apply else "direct_http_thread",
                "pending_sample": self.pending_payload is not None,
                "pending_render_jobs": len(self.pending_render_jobs),
                "pending_viewport_frame": self.pending_viewport_frame is not None,
                "pending_timeline_play": self.pending_timeline_play is not None,
                "sample_count": self.sample_count,
                "scene_path": str(self.scene_path),
                "last_scene_open_status": self.last_scene_open_status,
                "scene_open_request_count": self.scene_open_request_count,
                "latest_state_path": str(LATEST_STATE_PATH),
                "last_error": self.last_error,
                "last_apply_result": dict(self.last_apply_result),
                "last_specimen_pose_result": dict(self.last_specimen_pose_result),
                "last_render_request_result": dict(self.last_render_request_result),
                "last_viewport_frame_result": dict(self.last_viewport_frame_result),
                "last_timeline_play_result": dict(self.last_timeline_play_result),
                "last_payload_summary": self._last_payload_summary_locked(),
            }

    def _last_payload_summary_locked(self) -> dict[str, Any]:
        payload = dict(self.last_payload or {})
        if not payload:
            return {}
        joint_state = payload.get("joint_state") if isinstance(payload.get("joint_state"), list) else []
        return {
            "session_id": str(payload.get("session_id") or ""),
            "sample_index": payload.get("sample_index"),
            "timestamp": str(payload.get("timestamp") or ""),
            "joint_count": len(joint_state),
            "target_count": len(_joint_targets(payload)),
        }

    @staticmethod
    def _stage_summary(stage: Any) -> dict[str, Any]:
        try:
            root_layer = stage.GetRootLayer() if stage is not None else None
        except Exception:
            root_layer = None
        try:
            default_prim = stage.GetDefaultPrim() if stage is not None else None
        except Exception:
            default_prim = None
        root_paths: list[str] = []
        joint_paths: list[str] = []
        physics_scene_paths: list[str] = []
        collision_paths: list[str] = []
        rigid_body_paths: list[str] = []
        try:
            root_paths = [str(prim.GetPath()) for prim in stage.GetPseudoRoot().GetChildren()]
        except Exception:
            root_paths = []
        try:
            for prim in stage.Traverse():
                name = prim.GetName()
                type_name = prim.GetTypeName()
                schemas = []
                try:
                    schemas = [str(item) for item in prim.GetAppliedSchemas()]
                except Exception:
                    schemas = []
                type_name_text = str(type_name)
                if type_name_text == "PhysicsScene":
                    physics_scene_paths.append(str(prim.GetPath()))
                if "PhysicsCollisionAPI" in schemas:
                    collision_paths.append(str(prim.GetPath()))
                if "PhysicsRigidBodyAPI" in schemas:
                    rigid_body_paths.append(str(prim.GetPath()))
                if "Joint" in str(type_name) or name in {"Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper", "Gripper_mimic"}:
                    joint_paths.append(str(prim.GetPath()))
                if len(joint_paths) >= 16 and len(collision_paths) >= 32 and len(rigid_body_paths) >= 16:
                    break
        except Exception:
            joint_paths = []
            physics_scene_paths = []
            collision_paths = []
            rigid_body_paths = []
        return {
            "root_layer_identifier": str(getattr(root_layer, "identifier", "") or ""),
            "default_prim_path": str(default_prim.GetPath()) if default_prim else "",
            "root_paths": root_paths,
            "joint_paths": joint_paths,
            "physics_scene_paths": physics_scene_paths[:8],
            "collision_paths": collision_paths[:32],
            "rigid_body_paths": rigid_body_paths[:16],
            "physics_ready": bool(physics_scene_paths and collision_paths and rigid_body_paths),
        }

    def ensure_gui_scene_open(self) -> None:
        """Keep the requested scene loaded in Isaac's GUI context."""
        if not self.use_current_stage or not self.scene_path.exists():
            return
        stage = _current_isaac_stage()
        try:
            prim = stage.GetPrimAtPath("/World/Robot/Geometry/link0/link1/Joint1") if stage is not None else None
            if prim and prim.IsValid():
                self.last_scene_open_status = "ready:/World/Robot"
                return
        except Exception:
            pass
        now = time.monotonic()
        if now - self._last_scene_open_attempt_s < 1.0:
            return
        self._last_scene_open_attempt_s = now
        self.scene_open_request_count += 1
        try:
            import omni.usd  # type: ignore

            context = omni.usd.get_context()
            result = context.open_stage(str(self.scene_path))
            self.last_scene_open_status = f"requested:{result}"
        except Exception as exc:
            self.last_scene_open_status = f"failed:{exc.__class__.__name__}: {exc}"

    @staticmethod
    def _apply_joint_target(stage: Any, target: dict[str, Any]) -> bool:
        prim = stage.GetPrimAtPath(target["path"])
        if not prim or not prim.IsValid():
            return False
        value = float(target["target_value"])
        drive_stiffness = _safe_float(target.get("drive_stiffness"), 1000.0)
        drive_damping = _safe_float(target.get("drive_damping"), 100.0)
        drive_max_force = _safe_float(target.get("drive_max_force"), 1000.0)

        def _set_or_create_attr(attr_name: str, attr_value: float) -> bool:
            try:
                attr = prim.GetAttribute(attr_name)
                if not attr:
                    value_type = None
                    try:
                        from pxr import Sdf  # type: ignore

                        value_type = Sdf.ValueTypeNames.Float
                    except Exception:
                        value_type = None
                    attr = prim.CreateAttribute(attr_name, value_type)
                attr.Set(attr_value)
                return True
            except Exception:
                return False

        def _attr_float(attr_name: str) -> float | None:
            try:
                attr = prim.GetAttribute(attr_name)
                if not attr:
                    return None
                return float(attr.Get())
            except Exception:
                return None

        def _expand_joint_limits() -> None:
            current_lower = _attr_float("physics:lowerLimit")
            current_upper = _attr_float("physics:upperLimit")
            next_lower = value if current_lower is None else min(current_lower, value)
            next_upper = value if current_upper is None else max(current_upper, value)
            if current_lower is None or next_lower < current_lower:
                _set_or_create_attr("physics:lowerLimit", next_lower)
            if current_upper is None or next_upper > current_upper:
                _set_or_create_attr("physics:upperLimit", next_upper)
            target["physics_lower_limit"] = _attr_float("physics:lowerLimit")
            target["physics_upper_limit"] = _attr_float("physics:upperLimit")

        _expand_joint_limits()

        try:
            from pxr import UsdPhysics  # type: ignore

            drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
            drive.CreateTargetPositionAttr(value).Set(value)
            drive.CreateStiffnessAttr(drive_stiffness).Set(drive_stiffness)
            drive.CreateDampingAttr(drive_damping).Set(drive_damping)
            drive.CreateMaxForceAttr(drive_max_force).Set(drive_max_force)
            return True
        except Exception:
            pass

        if _set_or_create_attr("drive:angular:physics:targetPosition", value):
            _set_or_create_attr("drive:angular:physics:stiffness", drive_stiffness)
            _set_or_create_attr("drive:angular:physics:damping", drive_damping)
            _set_or_create_attr("drive:angular:physics:maxForce", drive_max_force)
            return True

        # Authored joint state is an offline fallback. Updating it on a live
        # articulation teleports the joint state and can fight the drive target.
        try:
            attr = prim.GetAttribute("state:angular:physics:position")
            if attr:
                attr.Set(value)
                return True
        except Exception:
            pass
        return _set_or_create_attr("state:angular:physics:position", value)


def install_kit_update_subscription(state: IsaacMirrorState) -> Any:
    """Apply queued mirror samples on Isaac Kit's update stream when available."""
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        stream = app.get_update_event_stream()

        def _on_update(_event: Any) -> None:
            state.ensure_gui_scene_open()
            state.apply_latest_pending()
            state.finalize_pending_render()
            state.apply_next_render_job()

        subscription = stream.create_subscription_to_pop(_on_update, name="atr-isaac-omx-mirror-apply")
        state.defer_apply = True
        return subscription
    except Exception as exc:
        state.last_error = f"Kit update subscription unavailable: {exc.__class__.__name__}: {exc}"
        return None


def make_handler(state: IsaacMirrorState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json_response(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/", "/health", "/state"}:
                self._json_response(404, {"ok": False, "error": "not_found"})
                return
            self._json_response(200, state.status_payload())

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/joints", "/specimen_pose", "/viewport/frame", "/timeline/play", "/render"}:
                self._json_response(404, {"ok": False, "error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be an object")
                if self.path == "/specimen_pose":
                    result = state.receive_specimen_pose(payload)
                elif self.path == "/viewport/frame":
                    result = state.receive_viewport_frame(payload)
                elif self.path == "/timeline/play":
                    result = state.receive_timeline_play(payload)
                elif self.path == "/render":
                    result = state.receive_render(payload)
                else:
                    result = state.receive(payload)
                self._json_response(200 if result.get("ok") else 503, result)
            except Exception as exc:
                self._json_response(400, {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"})

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[isaac-omx-mirror] {self.address_string()} {fmt % args}")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve ROBOTIS OMX Isaac mirror joint target updates.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--scene", default=str(DEFAULT_SCENE))
    parser.add_argument("--no-current-stage", action="store_true", help="Do not use the active Isaac GUI stage; open --scene instead.")
    args = parser.parse_args()

    state = IsaacMirrorState(Path(args.scene).expanduser().resolve(), use_current_stage=not args.no_current_stage)
    subscription = install_kit_update_subscription(state)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    print(f"[isaac-omx-mirror] listening on http://{args.host}:{args.port}/joints")
    print(f"[isaac-omx-mirror] scene={state.scene_path}")
    if subscription is not None:
        print("[isaac-omx-mirror] Isaac Kit update subscription active; samples apply on update ticks")
    else:
        print(f"[isaac-omx-mirror] direct apply mode active; {state.last_error}")
    server.serve_forever()


if __name__ == "__main__":
    main()
