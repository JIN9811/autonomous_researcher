"""Tests for shared ROBOTIS OMX real-to-Isaac joint conversion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils.isaac_omx_mirror_mapping import (
    ISAAC_OMX_GRIPPER_DRIVE_DAMPING,
    ISAAC_OMX_GRIPPER_DRIVE_STIFFNESS,
    ISAAC_OMX_JOINT_MAP,
    XL430_W250_T_STALL_TORQUE_NM_AT_12V,
    action_to_joint_state,
    joint_state_item_to_isaac_target,
    load_isaac_omx_mirror_calibration,
    positions_to_joint_state,
    value_to_isaac_target,
)


PROXY_BACKLASH_DEG = 0.25
PROXY_BACKLASH_SOURCE = "xm430_w350_15_arcmin_proxy"


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
    assert result["base_target_value"] == 0.0
    assert result["target_value"] == 5.0
    assert result["calibration_applied"] is True


def test_range_m100_100_body_joints_use_dynamixel_resolution_angle() -> None:
    shoulder_lift = next(item for item in ISAAC_OMX_JOINT_MAP if item["motor_name"] == "shoulder_lift")

    centered_result = value_to_isaac_target(shoulder_lift, 0.0)
    positive_result = value_to_isaac_target(shoulder_lift, 50.0)
    negative_result = value_to_isaac_target(shoulder_lift, -50.0)
    over_limit_result = value_to_isaac_target(shoulder_lift, 110.0)

    assert centered_result["target_value"] == pytest.approx(0.0)
    assert positive_result["target_value"] == pytest.approx(90.0)
    assert negative_result["target_value"] == pytest.approx(-90.0)
    assert over_limit_result["target_value"] == pytest.approx(180.0)
    assert over_limit_result["clamped"] is True
    assert centered_result["source_raw_position"] == pytest.approx(2047.5)
    assert positive_result["source_raw_position"] == pytest.approx(3071.25)
    assert positive_result["source_zero_raw_position"] == pytest.approx(2047.5)
    assert positive_result["dynamixel_deg_per_tick"] == pytest.approx(360.0 / 4095.0)
    assert positive_result["conversion_mode"] == "dynamixel_raw_resolution"


def test_gripper_uses_dynamixel_resolution_angle_with_closed_zero() -> None:
    gripper = next(item for item in ISAAC_OMX_JOINT_MAP if item["motor_name"] == "gripper")

    closed_result = value_to_isaac_target(gripper, 50.0)
    open_result = value_to_isaac_target(gripper, 60.0)
    under_closed_result = value_to_isaac_target(gripper, 49.0)
    over_open_result = value_to_isaac_target(gripper, 89.0)

    assert closed_result["target_value"] == pytest.approx(0.0)
    assert closed_result["base_target_value"] == pytest.approx(0.0)
    assert open_result["target_value"] == pytest.approx(36.0)
    assert under_closed_result["target_value"] == pytest.approx(0.0)
    assert under_closed_result["clamped"] is True
    assert over_open_result["target_value"] == pytest.approx(36.0)
    assert over_open_result["clamped"] is True
    assert closed_result["source_raw_position"] == pytest.approx(2047.5)
    assert open_result["source_raw_position"] == pytest.approx(2457.0)
    assert open_result["source_zero_raw_position"] == pytest.approx(2047.5)


def test_gripper_mapping_sets_contact_friendly_drive_impedance() -> None:
    converted = joint_state_item_to_isaac_target({"motor_id": 16, "motor_name": "gripper", "source_value": 59.9})

    assert converted["drive_stiffness"] == 180.0
    assert converted["drive_damping"] == 18.0
    assert converted["drive_max_force"] == 4.0


def test_joint_map_raises_all_xl330_drive_force_for_grasping() -> None:
    expected_by_motor_id = {
        11: XL430_W250_T_STALL_TORQUE_NM_AT_12V,
        12: XL430_W250_T_STALL_TORQUE_NM_AT_12V,
        13: XL430_W250_T_STALL_TORQUE_NM_AT_12V,
        14: 1.5,
        15: 1.5,
        16: 4.0,
    }

    for item in ISAAC_OMX_JOINT_MAP:
        assert item["drive_max_force"] == expected_by_motor_id[item["motor_id"]]


def test_joint_map_tracks_follower_motor_models_and_backlash_metadata() -> None:
    expected = {
        11: ("xl430-w250", PROXY_BACKLASH_DEG),
        12: ("xl430-w250", PROXY_BACKLASH_DEG),
        13: ("xl430-w250", PROXY_BACKLASH_DEG),
        14: ("xl330-m288", PROXY_BACKLASH_DEG),
        15: ("xl330-m288", PROXY_BACKLASH_DEG),
        16: ("xl330-m288", PROXY_BACKLASH_DEG),
    }

    for item in ISAAC_OMX_JOINT_MAP:
        motor_model, backlash_deg = expected[item["motor_id"]]
        assert item["motor_model"] == motor_model
        assert item["backlash_deg"] == pytest.approx(backlash_deg)
        assert item["backlash_source"] == PROXY_BACKLASH_SOURCE


def test_joint_state_conversion_carries_backlash_metadata() -> None:
    converted = joint_state_item_to_isaac_target({"motor_id": 12, "motor_name": "shoulder_lift", "source_value": 0.0})

    assert converted["target_value"] == pytest.approx(0.0)
    assert converted["motor_model"] == "xl430-w250"
    assert converted["backlash_deg"] == pytest.approx(PROXY_BACKLASH_DEG)
    assert converted["backlash_source"] == PROXY_BACKLASH_SOURCE


def test_value_to_isaac_target_clamps_after_sign_scale_offset() -> None:
    wrist_flex = next(item for item in ISAAC_OMX_JOINT_MAP if item["motor_name"] == "wrist_flex")
    calibration = {"joints": {"wrist_flex": {"scale": 2.0, "offset_deg": 60.0, "clamp_upper_deg": 100.0}}}

    result = value_to_isaac_target(wrist_flex, 100.0, calibration=calibration)

    assert result["base_target_value"] == 180.0
    assert result["target_value"] == 100.0
    assert result["clamped"] is True


def test_joint_state_item_to_isaac_target_recomputes_old_payload_from_source_value() -> None:
    converted = joint_state_item_to_isaac_target(
        {
            "motor_id": 13,
            "motor_name": "elbow_flex",
            "isaac_joint_name": "Joint3",
            "target_value": 43.58974358974362,
            "source_value": 55.799755799755815,
        }
    )

    assert converted["target_value"] == pytest.approx(100.43956043956047)
    assert converted["recomputed_from_source"] is True


def test_action_to_joint_state_uses_shared_calibration_contract() -> None:
    calibration = {"joints": {"shoulder_pan": {"offset_deg": 10.0}}}

    joint_state = action_to_joint_state({"shoulder_pan.pos": -12.0, "gripper.pos": 60.0}, calibration=calibration)

    shoulder_pan = next(item for item in joint_state if item["motor_name"] == "shoulder_pan")
    gripper = next(item for item in joint_state if item["motor_name"] == "gripper")
    assert shoulder_pan["target_value"] == -2.0
    assert shoulder_pan["source_value"] == -12.0
    assert shoulder_pan["calibration_applied"] is True
    assert gripper["target_value"] == 36.0
    assert gripper["calibration_applied"] is False


def test_positions_to_joint_state_accepts_preconverted_target_positions() -> None:
    calibration = {"joints": {"elbow_flex": {"sign": -1, "offset_deg": 3.0}}}

    joint_state = positions_to_joint_state({13: 40.0}, calibration=calibration, values_are_isaac_targets=True)

    elbow = joint_state[0]
    assert elbow["motor_name"] == "elbow_flex"
    assert elbow["source_value"] == 40.0
    assert elbow["base_target_value"] == 40.0
    assert elbow["target_value"] == -37.0


def test_preconverted_joint_state_payload_is_not_range_scaled_again() -> None:
    joint_state = positions_to_joint_state({13: 40.0}, values_are_isaac_targets=True)

    converted = joint_state_item_to_isaac_target(joint_state[0])

    assert converted["base_target_value"] == pytest.approx(40.0)
    assert converted["target_value"] == pytest.approx(40.0)
    assert converted["recomputed_from_source"] is True


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
