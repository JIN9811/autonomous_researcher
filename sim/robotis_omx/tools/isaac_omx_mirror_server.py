#!/usr/bin/env python3
"""HTTP bridge for mirroring ROBOTIS OMX follower joint state into Isaac Sim.

Run this inside Isaac Sim Python when the GUI stage is open, or with Isaac Sim's
python.sh against a USD file for offline target updates. The ATR LeRobot bridge
POSTs follower joint samples to /joints.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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
RUNTIME_GRIP_TARGET_MAX_STEP_DEG = 36.0
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
        ):
            if key in converted:
                target[key] = converted[key]
        targets.append(target)
    return targets


class IsaacMirrorState:
    def __init__(
        self,
        scene_path: Path,
        *,
        use_current_stage: bool = True,
        defer_apply: bool = False,
        save_stage_on_apply: bool | None = None,
        stage_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.scene_path = scene_path
        self.use_current_stage = use_current_stage
        self.defer_apply = defer_apply
        self.save_stage_on_apply = (not use_current_stage) if save_stage_on_apply is None else bool(save_stage_on_apply)
        self.stage_provider = stage_provider
        self.lock = threading.Lock()
        self.last_payload: dict[str, Any] = {}
        self.pending_payload: dict[str, Any] | None = None
        self.last_apply_result: dict[str, Any] = {}
        self.last_error = ""
        self.last_scene_open_status = ""
        self.scene_open_request_count = 0
        self._last_scene_open_attempt_s = 0.0
        self._runtime_cleanup_stage_id: int | None = None
        self.sample_count = 0
        self.stage = None
        self._runtime_grip_active = False
        self._last_gripper_target_value: float | None = None

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
            return {
                "ok": True,
                "status": "queued",
                "sample_count": self.sample_count,
                "target_count": len(_joint_targets(payload)),
                "latest_state_path": str(LATEST_STATE_PATH),
            }

    def apply_latest_pending(self) -> dict[str, Any]:
        """Apply the most recent queued sample. Intended for Isaac Kit update callbacks."""
        with self.lock:
            payload = dict(self.pending_payload or {})
            self.pending_payload = None
        if not payload:
            return {
                "ok": True,
                "status": "idle",
                "sample_count": self.sample_count,
                "target_count": 0,
                "latest_state_path": str(LATEST_STATE_PATH),
            }
        return self.apply(payload, record_received=False)

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
                self.last_error = "pxr/omni stage unavailable; latest JSON state was written only"
                self.last_apply_result = {
                    "ok": False,
                    "status": "stage_unavailable",
                    "message": self.last_error,
                    "sample_count": self.sample_count,
                    "target_count": len(targets),
                    "latest_state_path": str(LATEST_STATE_PATH),
                }
                return dict(self.last_apply_result)
            stage_summary = self._stage_summary(stage)
            self._slew_limit_gripper_targets(targets)
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
            if self.save_stage_on_apply:
                try:
                    stage.GetRootLayer().Save()
                except Exception:
                    pass
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
                "stage_summary": stage_summary,
                "latest_state_path": str(LATEST_STATE_PATH),
            }
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

    @staticmethod
    def _applied_target_summary(target: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "path": str(target.get("path") or ""),
            "name": str(target.get("name") or ""),
            "motor_id": target.get("motor_id"),
            "target_value": target.get("target_value"),
            "raw_target_value": target.get("raw_target_value"),
            "slew_limited": bool(target.get("slew_limited")),
            "source_value": target.get("source_value"),
            "recomputed_from_source": bool(target.get("recomputed_from_source")),
            "drive_stiffness": target.get("drive_stiffness"),
            "drive_damping": target.get("drive_damping"),
            "drive_max_force": target.get("drive_max_force"),
            "physics_lower_limit": target.get("physics_lower_limit"),
            "physics_upper_limit": target.get("physics_upper_limit"),
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

    def _slew_limit_gripper_targets(self, targets: list[dict[str, Any]]) -> None:
        for target in targets:
            if not self._target_is_gripper(target):
                continue
            value = _safe_float(target.get("target_value"), float("nan"))
            if value != value:
                continue
            previous = self._last_gripper_target_value
            target["raw_target_value"] = value
            target["slew_limited"] = False
            if previous is not None:
                delta = value - previous
                max_step = RUNTIME_GRIP_TARGET_MAX_STEP_DEG
                if abs(delta) > max_step:
                    value = previous + (max_step if delta > 0 else -max_step)
                    target["target_value"] = value
                    target["slew_limited"] = True
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
                "sample_count": self.sample_count,
                "scene_path": str(self.scene_path),
                "last_scene_open_status": self.last_scene_open_status,
                "scene_open_request_count": self.scene_open_request_count,
                "latest_state_path": str(LATEST_STATE_PATH),
                "last_error": self.last_error,
                "last_apply_result": dict(self.last_apply_result),
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
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/", "/health", "/state"}:
                self._json_response(404, {"ok": False, "error": "not_found"})
                return
            self._json_response(200, state.status_payload())

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/joints":
                self._json_response(404, {"ok": False, "error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be an object")
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
