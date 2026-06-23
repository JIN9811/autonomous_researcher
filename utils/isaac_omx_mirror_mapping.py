"""Shared ROBOTIS OMX to Isaac Sim mirror joint conversion utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ISAAC_OMX_SCENE_RELATIVE_PATH = Path("sim/robotis_omx/scene/omx_table_layout.usda")
ISAAC_OMX_ARTICULATION_ROOT = "/World/Robot/Geometry/link0"
ISAAC_OMX_JOINT_MAP: tuple[dict[str, Any], ...] = (
    {
        "motor_id": 11,
        "motor_name": "shoulder_pan",
        "isaac_joint_name": "Joint1",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/Joint1",
        "axis": "Z",
        "lower_deg": -270.0,
        "upper_deg": 360.0,
        "mode": "degrees",
        "unit": "deg",
    },
    {
        "motor_id": 12,
        "motor_name": "shoulder_lift",
        "isaac_joint_name": "Joint2",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/Joint2",
        "axis": "Y",
        "lower_deg": -120.0,
        "upper_deg": 90.0,
        "mode": "range_m100_100",
        "unit": "deg",
    },
    {
        "motor_id": 13,
        "motor_name": "elbow_flex",
        "isaac_joint_name": "Joint3",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/Joint3",
        "axis": "Y",
        "lower_deg": -120.0,
        "upper_deg": 90.0,
        "mode": "range_m100_100",
        "unit": "deg",
    },
    {
        "motor_id": 14,
        "motor_name": "wrist_flex",
        "isaac_joint_name": "Joint4",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/Joint4",
        "axis": "Y",
        "lower_deg": -100.0,
        "upper_deg": 100.0,
        "mode": "range_m100_100",
        "unit": "deg",
    },
    {
        "motor_id": 15,
        "motor_name": "wrist_roll",
        "isaac_joint_name": "Joint5",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/Joint5",
        "axis": "X",
        "lower_deg": -270.0,
        "upper_deg": 270.0,
        "mode": "degrees",
        "unit": "deg",
    },
    {
        "motor_id": 16,
        "motor_name": "gripper",
        "isaac_joint_name": "Gripper",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper",
        "mimic_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic",
        "axis": "Z",
        "lower_deg": 0.0,
        "upper_deg": 100.0,
        "mode": "range_0_100",
        "unit": "percent",
    },
)
ISAAC_OMX_TEST_JOINT_STATE_DEG = {
    11: 0.0,
    12: 0.0,
    13: 0.0,
    14: 0.0,
    15: 0.0,
    16: 35.0,
}


def default_isaac_omx_mirror_calibration_path(repo_root: Path | str) -> Path:
    return Path(repo_root).expanduser().resolve() / "memory" / "isaac_omx_mirror_calibration.json"


def load_isaac_omx_mirror_calibration(path: Path | str | None) -> dict[str, Any]:
    if path is None or str(path).strip() == "":
        return {"loaded": False, "path": "", "joints": {}}
    calibration_path = Path(path).expanduser()
    if not calibration_path.exists():
        return {"loaded": False, "path": str(calibration_path), "joints": {}}
    try:
        raw = json.loads(calibration_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"loaded": False, "path": str(calibration_path), "joints": {}, "error": f"{exc.__class__.__name__}: {exc}"}
    if not isinstance(raw, dict):
        return {"loaded": False, "path": str(calibration_path), "joints": {}, "error": "calibration root must be an object"}
    joints = raw.get("joints")
    if not isinstance(joints, dict):
        joints = {}
    return {**raw, "loaded": True, "path": str(calibration_path), "joints": joints}


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _base_target_from_source(item: dict[str, Any], source_value: Any, *, values_are_isaac_targets: bool = False) -> float:
    raw = _safe_float(source_value, 0.0)
    if values_are_isaac_targets:
        return raw
    mode = str(item.get("mode") or "degrees")
    lower = _safe_float(item.get("lower_deg"), raw)
    upper = _safe_float(item.get("upper_deg"), raw)
    if mode == "range_m100_100":
        return lower + ((raw + 100.0) / 200.0) * (upper - lower)
    if mode == "range_0_100":
        return lower + (raw / 100.0) * (upper - lower)
    return raw


def _joint_calibration(item: dict[str, Any], calibration: dict[str, Any] | None) -> dict[str, Any]:
    if not calibration:
        return {}
    joints = calibration.get("joints") if isinstance(calibration, dict) else {}
    if not isinstance(joints, dict):
        return {}
    for key in (item.get("motor_name"), item.get("isaac_joint_name"), str(item.get("motor_id"))):
        rule = joints.get(str(key))
        if isinstance(rule, dict):
            return rule
    return {}


def value_to_isaac_target(
    item: dict[str, Any],
    source_value: Any,
    *,
    calibration: dict[str, Any] | None = None,
    values_are_isaac_targets: bool = False,
) -> dict[str, Any]:
    source = _safe_float(source_value, 0.0)
    base = _base_target_from_source(item, source, values_are_isaac_targets=values_are_isaac_targets)
    rule = _joint_calibration(item, calibration)
    sign = _safe_float(rule.get("sign"), 1.0) if rule else 1.0
    scale = _safe_float(rule.get("scale"), 1.0) if rule else 1.0
    offset = _safe_float(rule.get("offset_deg"), 0.0) if rule else 0.0
    target = (base * sign * scale) + offset
    lower = _safe_float(rule.get("clamp_lower_deg"), _safe_float(item.get("lower_deg"), target)) if rule else _safe_float(item.get("lower_deg"), target)
    upper = _safe_float(rule.get("clamp_upper_deg"), _safe_float(item.get("upper_deg"), target)) if rule else _safe_float(item.get("upper_deg"), target)
    clamped = False
    if lower <= upper:
        if target < lower:
            target = lower
            clamped = True
        elif target > upper:
            target = upper
            clamped = True
    return {
        "source_value": source,
        "base_target_value": base,
        "target_value": target,
        "calibration_applied": bool(rule),
        "calibration_rule": dict(rule),
        "clamped": clamped,
    }


def _joint_state_entry(item: dict[str, Any], source_value: Any, *, calibration: dict[str, Any] | None, values_are_isaac_targets: bool) -> dict[str, Any]:
    converted = value_to_isaac_target(item, source_value, calibration=calibration, values_are_isaac_targets=values_are_isaac_targets)
    target = converted["target_value"]
    return {
        "motor_id": item["motor_id"],
        "motor_name": item["motor_name"],
        "isaac_joint_name": item["isaac_joint_name"],
        "isaac_joint_path": item["isaac_joint_path"],
        "mimic_joint_path": item.get("mimic_joint_path", ""),
        "axis": item["axis"],
        "position_deg": target,
        "target_value": target,
        "source_value": converted["source_value"],
        "base_target_value": converted["base_target_value"],
        "calibration_applied": converted["calibration_applied"],
        "calibration_rule": converted["calibration_rule"],
        "clamped": converted["clamped"],
        "unit": item.get("unit", "deg"),
    }


def action_to_joint_state(
    action: dict[str, Any],
    *,
    calibration: dict[str, Any] | None = None,
    joint_map: tuple[dict[str, Any], ...] | list[dict[str, Any]] = ISAAC_OMX_JOINT_MAP,
) -> list[dict[str, Any]]:
    joint_state: list[dict[str, Any]] = []
    for item in joint_map:
        key = f"{item['motor_name']}.pos"
        if key not in action:
            continue
        joint_state.append(_joint_state_entry(item, action[key], calibration=calibration, values_are_isaac_targets=False))
    return joint_state


def positions_to_joint_state(
    positions: dict[int, float] | dict[str, float],
    *,
    calibration: dict[str, Any] | None = None,
    values_are_isaac_targets: bool = True,
    joint_map: tuple[dict[str, Any], ...] | list[dict[str, Any]] = ISAAC_OMX_JOINT_MAP,
) -> list[dict[str, Any]]:
    joint_state: list[dict[str, Any]] = []
    for item in joint_map:
        motor_id = int(item["motor_id"])
        if motor_id not in positions and str(motor_id) not in positions:
            continue
        value = positions.get(motor_id) if motor_id in positions else positions.get(str(motor_id))  # type: ignore[arg-type]
        joint_state.append(_joint_state_entry(item, value, calibration=calibration, values_are_isaac_targets=values_are_isaac_targets))
    return joint_state
