"""Tests for shared ROBOTIS OMX real-to-Isaac joint conversion."""

from __future__ import annotations

import json
from pathlib import Path

from utils.isaac_omx_mirror_mapping import (
    ISAAC_OMX_JOINT_MAP,
    action_to_joint_state,
    load_isaac_omx_mirror_calibration,
    positions_to_joint_state,
    value_to_isaac_target,
)


def test_value_to_isaac_target_converts_lerobot_range_then_applies_calibration() -> None:
    shoulder_lift = next(item for item in ISAAC_OMX_JOINT_MAP if item["motor_name"] == "shoulder_lift")
    calibration = {
        "joints": {
            "shoulder_lift": {
                "sign": -1,
                "scale": 1.0,
                "offset_deg": 5.0,
                "clamp_lower_deg": -120.0,
                "clamp_upper_deg": 90.0,
            }
        }
    }

    result = value_to_isaac_target(shoulder_lift, 0.0, calibration=calibration)

    assert result["source_value"] == 0.0
    assert result["base_target_value"] == -15.0
    assert result["target_value"] == 20.0
    assert result["calibration_applied"] is True


def test_value_to_isaac_target_clamps_after_sign_scale_offset() -> None:
    wrist_flex = next(item for item in ISAAC_OMX_JOINT_MAP if item["motor_name"] == "wrist_flex")
    calibration = {"joints": {"wrist_flex": {"scale": 2.0, "offset_deg": 60.0}}}

    result = value_to_isaac_target(wrist_flex, 100.0, calibration=calibration)

    assert result["base_target_value"] == 100.0
    assert result["target_value"] == 100.0
    assert result["clamped"] is True


def test_action_to_joint_state_uses_shared_calibration_contract() -> None:
    calibration = {"joints": {"shoulder_pan": {"offset_deg": 10.0}}}

    joint_state = action_to_joint_state({"shoulder_pan.pos": -12.0, "gripper.pos": 60.0}, calibration=calibration)

    shoulder_pan = next(item for item in joint_state if item["motor_name"] == "shoulder_pan")
    gripper = next(item for item in joint_state if item["motor_name"] == "gripper")
    assert shoulder_pan["target_value"] == -2.0
    assert shoulder_pan["source_value"] == -12.0
    assert shoulder_pan["calibration_applied"] is True
    assert gripper["target_value"] == 60.0
    assert gripper["calibration_applied"] is False


def test_positions_to_joint_state_accepts_preconverted_target_positions() -> None:
    calibration = {"joints": {"elbow_flex": {"sign": -1, "offset_deg": 3.0}}}

    joint_state = positions_to_joint_state({13: 40.0}, calibration=calibration, values_are_isaac_targets=True)

    elbow = joint_state[0]
    assert elbow["motor_name"] == "elbow_flex"
    assert elbow["source_value"] == 40.0
    assert elbow["base_target_value"] == 40.0
    assert elbow["target_value"] == -37.0


def test_load_isaac_omx_mirror_calibration_tolerates_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"

    calibration = load_isaac_omx_mirror_calibration(missing)

    assert calibration["loaded"] is False
    assert calibration["joints"] == {}
    assert calibration["path"] == str(missing)


def test_load_isaac_omx_mirror_calibration_reads_joint_rules(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({"joints": {"Joint2": {"sign": -1}}}), encoding="utf-8")

    calibration = load_isaac_omx_mirror_calibration(path)

    assert calibration["loaded"] is True
    assert calibration["joints"]["Joint2"]["sign"] == -1
