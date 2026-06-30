"""Shared ROBOTIS OMX to Isaac Sim mirror joint conversion utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ISAAC_OMX_SCENE_RELATIVE_PATH = Path("sim/robotis_omx/scene/omx_table_layout.usda")
ISAAC_OMX_ARTICULATION_ROOT = "/World/Robot/Geometry/link0"
DYNAMIXEL_POSITION_MAX_TICK = 4095.0
DYNAMIXEL_DEG_PER_TICK = 360.0 / DYNAMIXEL_POSITION_MAX_TICK
ISAAC_OMX_X_SERIES_PROXY_BACKLASH_DEG = 0.25
ISAAC_OMX_X_SERIES_PROXY_BACKLASH_SOURCE = "xm430_w350_15_arcmin_proxy"
XL330_M288_T_STALL_TORQUE_NM_AT_5V = 0.52
XL430_W250_T_STALL_TORQUE_NM_AT_12V = 1.5
ISAAC_OMX_XL330_ARM_SIM_DRIVE_FORCE_NM = 1.5
ISAAC_OMX_XL430_ARM_SIM_DRIVE_FORCE_NM = 1.5
ISAAC_OMX_GRIPPER_SIM_GRASP_FORCE_NM = 4.0
ISAAC_OMX_ARM_DRIVE_STIFFNESS = 450.0
ISAAC_OMX_ARM_DRIVE_DAMPING = 60.0
ISAAC_OMX_GRIPPER_DRIVE_STIFFNESS = 180.0
ISAAC_OMX_GRIPPER_DRIVE_DAMPING = 18.0
ISAAC_OMX_XL330_M288_T_DRIVE = {
    "drive_stiffness": ISAAC_OMX_ARM_DRIVE_STIFFNESS,
    "drive_damping": ISAAC_OMX_ARM_DRIVE_DAMPING,
    "drive_max_force": ISAAC_OMX_XL330_ARM_SIM_DRIVE_FORCE_NM,
}
ISAAC_OMX_XL430_W250_T_DRIVE = {
    "drive_stiffness": ISAAC_OMX_ARM_DRIVE_STIFFNESS,
    "drive_damping": ISAAC_OMX_ARM_DRIVE_DAMPING,
    "drive_max_force": ISAAC_OMX_XL430_ARM_SIM_DRIVE_FORCE_NM,
}
ISAAC_OMX_XL330_M288_T_METADATA = {
    "motor_model": "xl330-m288",
    "backlash_deg": ISAAC_OMX_X_SERIES_PROXY_BACKLASH_DEG,
    "backlash_source": ISAAC_OMX_X_SERIES_PROXY_BACKLASH_SOURCE,
    "backlash_note": "Isaac mirror applies a conservative 15 arcmin X-series proxy backlash hysteresis unless a measured per-joint calibration overrides it.",
}
ISAAC_OMX_XL430_W250_T_METADATA = {
    "motor_model": "xl430-w250",
    "backlash_deg": ISAAC_OMX_X_SERIES_PROXY_BACKLASH_DEG,
    "backlash_source": ISAAC_OMX_X_SERIES_PROXY_BACKLASH_SOURCE,
    "backlash_note": "Isaac mirror applies a conservative 15 arcmin X-series proxy backlash hysteresis unless a measured per-joint calibration overrides it.",
}
ISAAC_OMX_JOINT_MAP: tuple[dict[str, Any], ...] = (
    {
        **ISAAC_OMX_XL430_W250_T_DRIVE,
        **ISAAC_OMX_XL430_W250_T_METADATA,
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
        **ISAAC_OMX_XL430_W250_T_DRIVE,
        **ISAAC_OMX_XL430_W250_T_METADATA,
        "motor_id": 12,
        "motor_name": "shoulder_lift",
        "isaac_joint_name": "Joint2",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/Joint2",
        "axis": "Y",
        "lower_deg": -180.0,
        "upper_deg": 180.0,
        "mode": "range_m100_100",
        "source_zero": 0.0,
        "source_to_raw_mode": "range_m100_100",
        "source_raw_min": 0.0,
        "source_raw_max": DYNAMIXEL_POSITION_MAX_TICK,
        "clamp_to_limits": True,
        "unit": "deg",
    },
    {
        **ISAAC_OMX_XL430_W250_T_DRIVE,
        **ISAAC_OMX_XL430_W250_T_METADATA,
        "motor_id": 13,
        "motor_name": "elbow_flex",
        "isaac_joint_name": "Joint3",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/Joint3",
        "axis": "Y",
        "lower_deg": -180.0,
        "upper_deg": 180.0,
        "mode": "range_m100_100",
        "source_zero": 0.0,
        "source_to_raw_mode": "range_m100_100",
        "source_raw_min": 0.0,
        "source_raw_max": DYNAMIXEL_POSITION_MAX_TICK,
        "clamp_to_limits": True,
        "unit": "deg",
    },
    {
        **ISAAC_OMX_XL330_M288_T_DRIVE,
        **ISAAC_OMX_XL330_M288_T_METADATA,
        "motor_id": 14,
        "motor_name": "wrist_flex",
        "isaac_joint_name": "Joint4",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/Joint4",
        "axis": "Y",
        "lower_deg": -180.0,
        "upper_deg": 180.0,
        "mode": "range_m100_100",
        "source_zero": 0.0,
        "source_to_raw_mode": "range_m100_100",
        "source_raw_min": 0.0,
        "source_raw_max": DYNAMIXEL_POSITION_MAX_TICK,
        "clamp_to_limits": True,
        "unit": "deg",
    },
    {
        **ISAAC_OMX_XL330_M288_T_DRIVE,
        **ISAAC_OMX_XL330_M288_T_METADATA,
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
        **ISAAC_OMX_XL330_M288_T_DRIVE,
        **ISAAC_OMX_XL330_M288_T_METADATA,
        "motor_id": 16,
        "motor_name": "gripper",
        "isaac_joint_name": "Gripper",
        "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper",
        "mimic_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic",
        "mimic_multiplier": -1.0,
        "axis": "Z",
        "lower_deg": 0.0,
        "upper_deg": 36.0,
        "mode": "range_0_100",
        "source_zero": 50.0,
        "source_to_raw_mode": "range_0_100",
        "source_raw_min": 0.0,
        "source_raw_max": DYNAMIXEL_POSITION_MAX_TICK,
        "clamp_to_limits": True,
        "drive_stiffness": ISAAC_OMX_GRIPPER_DRIVE_STIFFNESS,
        "drive_damping": ISAAC_OMX_GRIPPER_DRIVE_DAMPING,
        "drive_max_force": ISAAC_OMX_GRIPPER_SIM_GRASP_FORCE_NM,
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


def _joint_backlash_metadata(item: dict[str, Any], rule: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    motor_model = str(item.get("motor_model") or "").strip()
    if motor_model:
        metadata["motor_model"] = motor_model
    if "backlash_deg" in item:
        metadata["backlash_deg"] = _safe_float(item.get("backlash_deg"), 0.0)
    if "backlash_source" in item:
        metadata["backlash_source"] = str(item.get("backlash_source") or "")
    if "backlash_note" in item:
        metadata["backlash_note"] = str(item.get("backlash_note") or "")
    if rule:
        if "motor_model" in rule:
            metadata["motor_model"] = str(rule.get("motor_model") or metadata.get("motor_model", ""))
        if "backlash_deg" in rule:
            metadata["backlash_deg"] = _safe_float(rule.get("backlash_deg"), _safe_float(metadata.get("backlash_deg"), 0.0))
            metadata["backlash_source"] = str(rule.get("backlash_source") or "calibration")
        if "backlash_enabled" in rule and not bool(rule.get("backlash_enabled")):
            metadata["backlash_deg"] = 0.0
            metadata["backlash_source"] = str(rule.get("backlash_source") or "calibration_disabled")
        if "backlash_direction_sign" in rule:
            metadata["backlash_direction_sign"] = _safe_float(rule.get("backlash_direction_sign"), 1.0)
    return metadata


def _source_value_to_dynamixel_raw(item: dict[str, Any], source_value: float) -> float | None:
    mode = str(item.get("source_to_raw_mode") or "")
    if not mode:
        return None
    raw_min = _safe_float(item.get("source_raw_min"), 0.0)
    raw_max = _safe_float(item.get("source_raw_max"), DYNAMIXEL_POSITION_MAX_TICK)
    raw_span = raw_max - raw_min
    if raw_span == 0.0:
        return raw_min
    if mode == "range_m100_100":
        bounded = min(100.0, max(-100.0, source_value))
        return ((bounded + 100.0) / 200.0) * raw_span + raw_min
    if mode == "range_0_100":
        bounded = min(100.0, max(0.0, source_value))
        return (bounded / 100.0) * raw_span + raw_min
    return None


def _base_target_from_source(
    item: dict[str, Any],
    source_value: Any,
    *,
    values_are_isaac_targets: bool = False,
) -> dict[str, Any]:
    raw = _safe_float(source_value, 0.0)
    if values_are_isaac_targets:
        return {"base_target_value": raw, "conversion_mode": "isaac_target"}
    mode = str(item.get("mode") or "degrees")
    source_raw_position = _source_value_to_dynamixel_raw(item, raw)
    if source_raw_position is not None:
        source_raw_clamped = (
            (str(item.get("source_to_raw_mode") or "") == "range_m100_100" and (raw < -100.0 or raw > 100.0))
            or (str(item.get("source_to_raw_mode") or "") == "range_0_100" and (raw < 0.0 or raw > 100.0))
        )
        zero_source = _safe_float(item.get("source_zero"), 0.0)
        source_zero_raw_position = item.get("source_zero_raw_position")
        if source_zero_raw_position is None:
            source_zero_raw_position = _source_value_to_dynamixel_raw(item, zero_source)
        zero_raw = _safe_float(source_zero_raw_position, 0.0)
        deg_per_tick = _safe_float(item.get("dynamixel_deg_per_tick"), DYNAMIXEL_DEG_PER_TICK)
        base = ((source_raw_position - zero_raw) * deg_per_tick) + _safe_float(item.get("source_to_deg_offset"), 0.0)
        return {
            "base_target_value": base,
            "conversion_mode": "dynamixel_raw_resolution",
            "source_raw_position": source_raw_position,
            "source_zero_raw_position": zero_raw,
            "dynamixel_deg_per_tick": deg_per_tick,
            "source_raw_clamped": source_raw_clamped,
        }
    source_to_deg_scale = item.get("source_to_deg_scale")
    if source_to_deg_scale is not None:
        source_zero = _safe_float(item.get("source_zero"), 0.0)
        return {
            "base_target_value": ((raw - source_zero) * _safe_float(source_to_deg_scale, 1.0))
            + _safe_float(item.get("source_to_deg_offset"), 0.0),
            "conversion_mode": "source_scale",
        }
    lower = _safe_float(item.get("lower_deg"), raw)
    upper = _safe_float(item.get("upper_deg"), raw)
    source_lower = item.get("source_lower")
    source_upper = item.get("source_upper")
    if source_lower is not None and source_upper is not None:
        target_lower = _safe_float(item.get("target_lower_deg"), lower)
        target_upper = _safe_float(item.get("target_upper_deg"), upper)
        input_lower = _safe_float(source_lower, raw)
        input_upper = _safe_float(source_upper, raw)
        input_span = input_upper - input_lower
        if input_span == 0.0:
            return {"base_target_value": target_lower, "conversion_mode": "source_range"}
        return {
            "base_target_value": target_lower + ((raw - input_lower) / input_span) * (target_upper - target_lower),
            "conversion_mode": "source_range",
        }
    if mode == "range_m100_100":
        return {
            "base_target_value": lower + ((raw + 100.0) / 200.0) * (upper - lower),
            "conversion_mode": "legacy_range_m100_100",
        }
    if mode == "range_0_100":
        return {"base_target_value": lower + (raw / 100.0) * (upper - lower), "conversion_mode": "legacy_range_0_100"}
    return {"base_target_value": raw, "conversion_mode": "degrees"}


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
    base_details = _base_target_from_source(item, source, values_are_isaac_targets=values_are_isaac_targets)
    base = _safe_float(base_details.get("base_target_value"), source)
    rule = _joint_calibration(item, calibration)
    sign = _safe_float(rule.get("sign"), 1.0) if rule else 1.0
    scale = _safe_float(rule.get("scale"), 1.0) if rule else 1.0
    offset = _safe_float(rule.get("offset_deg"), 0.0) if rule else 0.0
    target = (base * sign * scale) + offset
    clamp_requested = bool(item.get("clamp_to_limits")) or (
        bool(rule) and ("clamp_lower_deg" in rule or "clamp_upper_deg" in rule)
    )
    lower = target
    upper = target
    if clamp_requested:
        item_lower = _safe_float(item.get("target_lower_deg"), _safe_float(item.get("lower_deg"), target))
        item_upper = _safe_float(item.get("target_upper_deg"), _safe_float(item.get("upper_deg"), target))
        lower = _safe_float(rule.get("clamp_lower_deg"), item_lower) if rule else item_lower
        upper = _safe_float(rule.get("clamp_upper_deg"), item_upper) if rule else item_upper
    clamped = bool(base_details.get("source_raw_clamped", False))
    if clamp_requested and lower <= upper:
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
        **{key: value for key, value in base_details.items() if key != "base_target_value"},
    }


def _joint_state_entry(item: dict[str, Any], source_value: Any, *, calibration: dict[str, Any] | None, values_are_isaac_targets: bool) -> dict[str, Any]:
    converted = value_to_isaac_target(item, source_value, calibration=calibration, values_are_isaac_targets=values_are_isaac_targets)
    target = converted["target_value"]
    entry = {
        "motor_id": item["motor_id"],
        "motor_name": item["motor_name"],
        "isaac_joint_name": item["isaac_joint_name"],
        "isaac_joint_path": item["isaac_joint_path"],
        "mimic_joint_path": item.get("mimic_joint_path", ""),
        "mimic_multiplier": _safe_float(item.get("mimic_multiplier"), 1.0),
        "axis": item["axis"],
        "position_deg": target,
        "target_value": target,
        "source_value": converted["source_value"],
        "base_target_value": converted["base_target_value"],
        "calibration_applied": converted["calibration_applied"],
        "calibration_rule": converted["calibration_rule"],
        "clamped": converted["clamped"],
        "source_value_is_isaac_target": bool(values_are_isaac_targets),
        "unit": item.get("unit", "deg"),
    }
    for key in (
        "conversion_mode",
        "source_raw_position",
        "source_zero_raw_position",
        "dynamixel_deg_per_tick",
    ):
        if key in converted:
            entry[key] = converted[key]
    for key in ("drive_stiffness", "drive_damping", "drive_max_force"):
        if key in item:
            entry[key] = _safe_float(item.get(key), 0.0)
    entry.update(_joint_backlash_metadata(item, converted.get("calibration_rule")))
    return entry


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


def _joint_map_item_for_payload_item(
    payload_item: dict[str, Any],
    joint_map: tuple[dict[str, Any], ...] | list[dict[str, Any]] = ISAAC_OMX_JOINT_MAP,
) -> dict[str, Any] | None:
    raw_motor_id = payload_item.get("motor_id")
    try:
        motor_id = int(raw_motor_id)
    except (TypeError, ValueError):
        motor_id = None
    motor_name = str(payload_item.get("motor_name") or "")
    isaac_joint_name = str(payload_item.get("isaac_joint_name") or "")
    isaac_joint_path = str(payload_item.get("isaac_joint_path") or "")
    for item in joint_map:
        if motor_id is not None and int(item.get("motor_id", -1)) == motor_id:
            return item
        if motor_name and str(item.get("motor_name") or "") == motor_name:
            return item
        if isaac_joint_name and str(item.get("isaac_joint_name") or "") == isaac_joint_name:
            return item
        if isaac_joint_path and str(item.get("isaac_joint_path") or "") == isaac_joint_path:
            return item
    return None


def joint_state_item_to_isaac_target(
    payload_item: dict[str, Any],
    *,
    calibration: dict[str, Any] | None = None,
    joint_map: tuple[dict[str, Any], ...] | list[dict[str, Any]] = ISAAC_OMX_JOINT_MAP,
) -> dict[str, Any]:
    """Return the receiver-side Isaac target for a posted joint_state item.

    Live sessions can keep running across mapping updates. When source_value is
    present, the receiver recomputes the target from the current shared mapping
    instead of trusting an older target_value produced by an already-running
    wrapper process.
    """

    mapped_item = _joint_map_item_for_payload_item(payload_item, joint_map)
    if mapped_item is not None and "source_value" in payload_item:
        source_value_is_isaac_target = bool(
            payload_item.get("source_value_is_isaac_target")
            or payload_item.get("source_values_are_isaac_targets")
            or payload_item.get("values_are_isaac_targets")
        )
        converted = value_to_isaac_target(
            mapped_item,
            payload_item.get("source_value"),
            calibration=calibration,
            values_are_isaac_targets=source_value_is_isaac_target,
        )
        result = {
            **converted,
            "recomputed_from_source": True,
            "source_value_is_isaac_target": source_value_is_isaac_target,
            "mimic_multiplier": _safe_float(mapped_item.get("mimic_multiplier"), _safe_float(payload_item.get("mimic_multiplier"), 1.0)),
        }
        for key in ("drive_stiffness", "drive_damping", "drive_max_force"):
            if key in mapped_item:
                result[key] = _safe_float(mapped_item.get(key), 0.0)
            elif key in payload_item:
                result[key] = _safe_float(payload_item.get(key), 0.0)
        result.update(_joint_backlash_metadata(mapped_item, converted.get("calibration_rule")))
        return result
    fallback_value = payload_item.get("target_value", payload_item.get("position_deg", 0.0))
    target = _safe_float(fallback_value, 0.0)
    fallback_mimic_multiplier = payload_item.get("mimic_multiplier")
    if fallback_mimic_multiplier is None and mapped_item is not None:
        fallback_mimic_multiplier = mapped_item.get("mimic_multiplier")
    result = {
        "source_value": _safe_float(payload_item.get("source_value"), target),
        "base_target_value": _safe_float(payload_item.get("base_target_value"), target),
        "target_value": target,
        "calibration_applied": bool(payload_item.get("calibration_applied", False)),
        "calibration_rule": dict(payload_item.get("calibration_rule") or {}),
        "clamped": bool(payload_item.get("clamped", False)),
        "recomputed_from_source": False,
        "source_value_is_isaac_target": bool(payload_item.get("source_value_is_isaac_target", False)),
        "mimic_multiplier": _safe_float(fallback_mimic_multiplier, 1.0),
    }
    for key in ("drive_stiffness", "drive_damping", "drive_max_force"):
        if key in payload_item:
            result[key] = _safe_float(payload_item.get(key), 0.0)
        elif mapped_item is not None and key in mapped_item:
            result[key] = _safe_float(mapped_item.get(key), 0.0)
    result.update(_joint_backlash_metadata(mapped_item or payload_item, result.get("calibration_rule")))
    return result


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
