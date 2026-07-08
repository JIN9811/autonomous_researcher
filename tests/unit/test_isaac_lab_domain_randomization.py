"""Unit tests for Robotis OMX Isaac Lab domain-randomization profiles."""

from __future__ import annotations

import importlib


def test_standard_domain_randomization_keeps_cube_and_physics_fixed() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.domain_randomization")
    profile = module.get_profile("standard")
    ranges = module.event_ranges("standard")

    assert profile["cube_xy_m"] == (0.0, 0.0)
    assert profile["cube_yaw_rad"] == (0.0, 0.0)
    assert profile["cube_mass_scale"] == (1.0, 1.0)
    assert profile["cube_static_friction"] == (0.9, 0.9)
    assert profile["cube_dynamic_friction"] == (0.7, 0.7)
    assert profile["gripper_inner_static_friction"] == (1.2, 1.2)
    assert ranges["cube_rest_offset_range"] == (0.0, 0.0)
    assert ranges["cube_contact_offset_range"] == (0.004, 0.004)


def test_standard_domain_randomization_exposes_environment_only_ranges() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.domain_randomization")
    profile = module.get_profile("standard")

    assert profile["lighting_intensity_scale"] == (0.75, 1.25)
    assert profile["color_temperature_shift_k"] == (-400.0, 400.0)
    assert profile["shadow_softness_scale"] == (0.85, 1.2)
    assert profile["table_color_brightness"] == (0.85, 1.15)
    assert profile["background_brightness"] == (0.85, 1.2)
    assert profile["a4_brightness"] == (0.92, 1.08)
    assert profile["camera_exposure_scale"] == (0.9, 1.1)
    assert profile["camera_gamma"] == (0.95, 1.05)
    assert profile["white_balance_rgb_scale"] == (0.96, 1.04)
    assert profile["rgb_noise_sigma"] == (0.0, 0.012)
    assert profile["rgb_blur_px"] == (0.0, 0.5)
    assert profile["depth_noise_mm"] == (0.0, 1.5)
    assert profile["depth_dropout_ratio"] == (0.0, 0.008)


def test_mimic_pose_profile_randomizes_only_pose_not_physics() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.domain_randomization")
    profile = module.get_profile("mimic_pose")
    ranges = module.event_ranges("mimic_pose")

    assert profile["cube_xy_m"] == (-0.015, 0.015)
    assert profile["cube_yaw_rad"] == (-0.12, 0.12)
    assert profile["cube_mass_scale"] == (1.0, 1.0)
    assert profile["cube_static_friction"] == (0.9, 0.9)
    assert profile["cube_dynamic_friction"] == (0.7, 0.7)
    assert ranges["cube_static_friction_range"] == (0.9, 0.9)
    assert ranges["cube_dynamic_friction_range"] == (0.7, 0.7)
    assert ranges["cube_mass_scale_range"] == (1.0, 1.0)
