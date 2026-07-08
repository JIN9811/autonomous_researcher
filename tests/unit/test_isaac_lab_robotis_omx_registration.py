"""Import-only tests for the Robotis OMX Isaac Lab registration package."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest
import torch


def test_external_callback_registers_expected_task_names_without_launching_sim() -> None:
    callback = importlib.import_module("integrations.isaac_lab_robotis_omx.external_callback")
    accepted_args = callback.register()
    assert isinstance(accepted_args, list)

    registry = importlib.import_module("integrations.isaac_lab_robotis_omx.task_registry")
    assert registry.MIMIC_TASK_NAME == "ATR-Robotis-OMX-PickPlace-Mimic-v0"
    assert registry.POLICY_TASK_NAME == "ATR-Robotis-OMX-PickPlace-v0"


def test_external_callback_consumes_robotis_domain_profile_arg(monkeypatch) -> None:
    callback = importlib.import_module("integrations.isaac_lab_robotis_omx.external_callback")
    monkeypatch.delenv("ROBOTIS_OMX_DOMAIN_RANDOMIZATION_PROFILE", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_dataset.py",
            "--task",
            "ATR-Robotis-OMX-PickPlace-Mimic-v0",
            "--robotis-domain-randomization-profile",
            "standard",
            "--headless",
        ],
    )

    remaining = callback.register()

    assert remaining == []
    assert os.environ["ROBOTIS_OMX_DOMAIN_RANDOMIZATION_PROFILE"] == "standard"
    assert "--robotis-domain-randomization-profile" not in sys.argv
    assert "standard" not in sys.argv


def test_external_callback_consumes_robotis_camera_resolution_args(monkeypatch) -> None:
    callback = importlib.import_module("integrations.isaac_lab_robotis_omx.external_callback")
    monkeypatch.delenv("ROBOTIS_OMX_CAMERA_WIDTH", raising=False)
    monkeypatch.delenv("ROBOTIS_OMX_CAMERA_HEIGHT", raising=False)
    monkeypatch.delenv("ROBOTIS_OMX_CAMERA_MODE", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_dataset.py",
            "--robotis-camera-width",
            "320",
            "--robotis-camera-height",
            "240",
            "--robotis-camera-mode",
            "off",
            "--headless",
        ],
    )

    remaining = callback.register()

    assert remaining == []
    assert os.environ["ROBOTIS_OMX_CAMERA_WIDTH"] == "320"
    assert os.environ["ROBOTIS_OMX_CAMERA_HEIGHT"] == "240"
    assert os.environ["ROBOTIS_OMX_CAMERA_MODE"] == "off"
    assert "--robotis-camera-width" not in sys.argv
    assert "--robotis-camera-height" not in sys.argv
    assert "--robotis-camera-mode" not in sys.argv


def test_external_callback_consumes_robotis_mimic_generation_debug_args(monkeypatch) -> None:
    callback = importlib.import_module("integrations.isaac_lab_robotis_omx.external_callback")
    monkeypatch.delenv("ROBOTIS_OMX_MIMIC_GENERATION_GUARANTEE", raising=False)
    monkeypatch.delenv("ROBOTIS_OMX_MIMIC_KEEP_FAILED", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_dataset.py",
            "--robotis-mimic-generation-guarantee",
            "false",
            "--robotis-mimic-keep-failed",
            "true",
            "--headless",
        ],
    )

    remaining = callback.register()

    assert remaining == []
    assert os.environ["ROBOTIS_OMX_MIMIC_GENERATION_GUARANTEE"] == "false"
    assert os.environ["ROBOTIS_OMX_MIMIC_KEEP_FAILED"] == "true"
    assert "--robotis-mimic-generation-guarantee" not in sys.argv
    assert "--robotis-mimic-keep-failed" not in sys.argv


def test_mimic_env_class_exposes_required_helper_methods() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env")
    cls = module.RobotisOMXPickPlaceMimicEnv
    for name in (
        "get_robot_eef_pose",
        "target_eef_pose_to_action",
        "action_to_target_eef_pose",
        "actions_to_gripper_actions",
        "get_object_poses",
        "get_subtask_term_signals",
    ):
        assert callable(getattr(cls, name))


def test_domain_randomization_profiles_are_bounded() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.domain_randomization")
    profiles = module.DOMAIN_RANDOMIZATION_PROFILES
    assert set(profiles) == {"off", "conservative", "standard", "stress", "mimic_pose"}
    for profile in profiles.values():
        lo, hi = profile["cube_xy_m"]
        assert lo <= hi
        assert -0.105 <= lo <= 0.105
        assert -0.105 <= hi <= 0.105


def test_domain_randomization_event_ranges_follow_selected_profile() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.domain_randomization")
    standard = module.event_ranges("standard")
    conservative = module.event_ranges("conservative")
    assert standard["cube_static_friction_range"] == module.DOMAIN_RANDOMIZATION_PROFILES["standard"]["cube_static_friction"]
    assert standard["cube_dynamic_friction_range"] == module.DOMAIN_RANDOMIZATION_PROFILES["standard"]["cube_dynamic_friction"]
    assert standard["cube_mass_scale_range"] == module.DOMAIN_RANDOMIZATION_PROFILES["standard"]["cube_mass_scale"]
    assert standard["cube_static_friction_range"] == conservative["cube_static_friction_range"]
    assert (
        module.DOMAIN_RANDOMIZATION_PROFILES["standard"]["lighting_intensity_scale"]
        != module.DOMAIN_RANDOMIZATION_PROFILES["conservative"]["lighting_intensity_scale"]
    )


def test_physical_task_names_and_visual_bc_config_are_registered() -> None:
    registry = importlib.import_module("integrations.isaac_lab_robotis_omx.task_registry")

    assert registry.PHYSICAL_POLICY_TASK_NAME == "ATR-Robotis-OMX-PickPlace-Physical-v0"
    assert registry.PHYSICAL_POLICY_STATE_TASK_NAME == "ATR-Robotis-OMX-PickPlace-Physical-State-v0"
    assert registry.PHYSICAL_MIMIC_TASK_NAME == "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0"

    kwargs_by_task = registry.task_registration_kwargs()
    physical = kwargs_by_task[registry.PHYSICAL_POLICY_TASK_NAME]
    physical_state = kwargs_by_task[registry.PHYSICAL_POLICY_STATE_TASK_NAME]
    physical_mimic = kwargs_by_task[registry.PHYSICAL_MIMIC_TASK_NAME]
    assert physical["env_cfg_entry_point"].endswith(
        "robotis_omx_physical_env_cfg:RobotisOMXPhysicalPickPlaceEnvCfg"
    )
    assert physical["robomimic_bc_cfg_entry_point"].endswith("robomimic:bc_visual.json")
    assert physical_state["robomimic_bc_cfg_entry_point"].endswith("robomimic:bc.json")
    assert physical_mimic["env_cfg_entry_point"].endswith(
        "robotis_omx_physical_mimic_env_cfg:RobotisOMXPhysicalPickPlaceMimicEnvCfg"
    )


def test_physical_mimic_env_uses_joint_position_action_contract() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_physical_mimic_env_cfg")
    cfg = module.RobotisOMXPhysicalPickPlaceMimicEnvCfg()

    assert cfg.action_contract["control_mode"] == "joint_position_physical_articulation"
    assert cfg.action_contract["joint_names"] == [
        "Joint1",
        "Joint2",
        "Joint3",
        "Joint4",
        "Joint5",
        "Gripper",
        "Gripper_mimic",
    ]
    assert cfg.action_contract["action_dim"] == 7
    assert cfg.action_contract["retarget_mode"] == "differential_ik"
    assert cfg.action_contract["arm_joint_names"] == ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5"]
    assert cfg.action_contract["eef_body_name"] == "link5"
    assert cfg.action_contract["gripper_contact_hold"]["enabled"] is True


def test_physical_mimic_subtasks_match_successful_replay_boundaries() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_physical_mimic_env_cfg")
    cfg = module.RobotisOMXPhysicalPickPlaceMimicEnvCfg()

    subtasks = cfg.subtask_configs["omx"]

    assert [task.object_ref for task in subtasks] == ["red_cube", "place_target", "place_target"]
    assert [task.subtask_term_signal for task in subtasks] == ["cube_lifted", "released_at_target", None]
    assert [task.selection_strategy_kwargs for task in subtasks] == [{"nn_k": 1}, {"nn_k": 1}, {"nn_k": 1}]
    assert [task.subtask_term_offset_range for task in subtasks] == [(0, 0), (0, 0), (0, 0)]
    assert [task.action_noise for task in subtasks] == [0.0, 0.0, 0.0]
    assert "cylinder" in subtasks[1].description.lower()


def test_physical_mimic_generation_debug_env_can_disable_guarantee(monkeypatch) -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_physical_mimic_env_cfg")
    monkeypatch.setenv("ROBOTIS_OMX_MIMIC_GENERATION_GUARANTEE", "false")
    monkeypatch.setenv("ROBOTIS_OMX_MIMIC_KEEP_FAILED", "true")

    cfg = module.RobotisOMXPhysicalPickPlaceMimicEnvCfg()

    assert cfg.datagen_config.generation_guarantee is False
    assert cfg.datagen_config.generation_keep_failed is True


def test_physical_mimic_adapter_preserves_successful_joint_replay_contract() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env")
    env = module.RobotisOMXPickPlaceMimicEnv.__new__(module.RobotisOMXPickPlaceMimicEnv)

    class _Cfg:
        subtask_configs = {"omx": []}
        action_contract = {
            "control_mode": "joint_position_physical_articulation",
            "joint_names": ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper", "Gripper_mimic"],
            "action_dim": 7,
        }

    env.cfg = _Cfg()
    env._is_closed = True
    class _Scene:
        num_envs = 2

    class _Sim:
        device = "cpu"

    env.scene = _Scene()
    env.sim = _Sim()
    eef_pose = torch.eye(4, dtype=torch.float32).repeat(2, 1, 1)
    eef_pose[:, :3, 3] = torch.tensor([[0.30, 0.20, 0.10], [0.31, 0.21, 0.11]], dtype=torch.float32)
    object_pose = torch.eye(4, dtype=torch.float32).repeat(2, 1, 1)
    object_pose[:, :3, 3] = torch.tensor([[0.40, 0.30, 0.015], [0.590, 0.078, 0.119]], dtype=torch.float32)
    env.obs_buf = {
        "policy": {"eef_pose": eef_pose, "object_pose": object_pose},
        "subtask_terms": {
            "approach": torch.tensor([[True], [True]]),
            "grasp": torch.tensor([[False], [True]]),
            "lift": torch.tensor([[False], [True]]),
            "place": torch.tensor([[False], [True]]),
            "release": torch.tensor([[False], [True]]),
            "retract": torch.tensor([[False], [False]]),
        },
    }

    object_poses = env.get_object_poses()
    assert set(object_poses) == {"red_cube", "place_target"}
    assert torch.allclose(object_poses["red_cube"], object_pose)
    target_xyz = object_poses["place_target"][:, :3, 3]
    target_center_xy = torch.tensor([0.590, 0.078], dtype=torch.float32)
    assert torch.all(torch.linalg.norm(target_xyz[:, :2] - target_center_xy, dim=1) <= 0.050 + 1.0e-6)
    assert torch.allclose(target_xyz[:, 2], torch.tensor([0.119, 0.119], dtype=torch.float32))

    terms = env.get_subtask_term_signals(env_ids=[1])
    assert set(terms) == {"approach", "grasp", "lift", "place", "release", "retract", "cube_lifted", "released_at_target"}
    assert terms["cube_lifted"].shape == (1, 1)
    assert terms["cube_lifted"].item() is True
    assert terms["released_at_target"].shape == (1, 1)
    assert terms["released_at_target"].item() is True

    joint_actions = torch.tensor(
        [[0.10, 0.20, 0.30, 0.40, 0.50, 0.12, -0.12], [0.11, 0.21, 0.31, 0.41, 0.51, 0.20, -0.20]],
        dtype=torch.float32,
    )
    gripper_actions = env.actions_to_gripper_actions(joint_actions)
    assert torch.allclose(gripper_actions["omx"], joint_actions)
    target_pose = env.action_to_target_eef_pose(joint_actions)
    assert torch.allclose(target_pose["omx"], eef_pose)
    replay_action = env.target_eef_pose_to_action({"omx": eef_pose[1]}, {"omx": joint_actions[1]}, env_id=1)
    assert torch.allclose(replay_action, joint_actions[1])


def test_physical_mimic_adapter_retargets_arm_with_jacobian_when_available() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env")
    env = module.RobotisOMXPickPlaceMimicEnv.__new__(module.RobotisOMXPickPlaceMimicEnv)

    class _Cfg:
        subtask_configs = {"omx": []}
        action_contract = {
            "control_mode": "joint_position_physical_articulation",
            "joint_names": ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper", "Gripper_mimic"],
            "arm_joint_names": ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5"],
            "action_dim": 7,
            "retarget_mode": "differential_ik",
            "eef_body_name": "link5",
            "ik_damping": 0.01,
            "ik_position_gain": 1.0,
            "ik_max_delta_rad": 0.5,
        }

    class _Proxy:
        def __init__(self, value: torch.Tensor) -> None:
            self.torch = value

    class _RobotData:
        body_link_jacobian_w = _Proxy(torch.zeros(2, 1, 6, 7, dtype=torch.float32))
        joint_pos = _Proxy(torch.zeros(2, 7, dtype=torch.float32))
        soft_joint_pos_limits = _Proxy(torch.tensor([[[-3.14, 3.14]] * 7, [[-3.14, 3.14]] * 7], dtype=torch.float32))

    _RobotData.body_link_jacobian_w.torch[:, 0, 0, 0] = 1.0
    _RobotData.body_link_jacobian_w.torch[:, 0, 1, 1] = 1.0
    _RobotData.body_link_jacobian_w.torch[:, 0, 2, 2] = 1.0

    class _Robot:
        body_names = ["base", "link5"]
        joint_names = ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper", "Gripper_mimic"]
        data = _RobotData()

        def find_bodies(self, names, preserve_order=False):
            return [1], ["link5"]

        def find_joints(self, names, preserve_order=False):
            return [self.joint_names.index(name) for name in names], list(names)

    class _Scene(dict):
        num_envs = 2

    class _Sim:
        device = "cpu"

    env.cfg = _Cfg()
    env._is_closed = True
    env.scene = _Scene(robot=_Robot())
    env.sim = _Sim()
    eef_pose = torch.eye(4, dtype=torch.float32).repeat(2, 1, 1)
    env.obs_buf = {
        "policy": {
            "eef_pose": eef_pose,
            "joint_pos": torch.zeros(2, 7, dtype=torch.float32),
        }
    }
    source_action = torch.tensor([0.9, 0.8, 0.7, 0.6, 0.5, 0.12, -0.12], dtype=torch.float32)
    target_pose = torch.eye(4, dtype=torch.float32)
    target_pose[:3, 3] = torch.tensor([0.10, -0.05, 0.02], dtype=torch.float32)

    retargeted = env.target_eef_pose_to_action({"omx": target_pose}, {"omx": source_action}, env_id=0)

    assert torch.allclose(retargeted[:3], torch.tensor([0.99999, 0.75, 0.72]), atol=1.0e-3)
    assert torch.allclose(retargeted[3:5], source_action[3:5], atol=1.0e-6)
    assert not torch.allclose(retargeted[:5], source_action[:5])
    assert torch.allclose(retargeted[5:], source_action[5:])


def test_physical_mimic_place_target_covers_full_cylinder_top_region() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env")
    env = module.RobotisOMXPickPlaceMimicEnv.__new__(module.RobotisOMXPickPlaceMimicEnv)

    class _Cfg:
        subtask_configs = {"omx": []}
        action_contract = {"control_mode": "joint_position_physical_articulation", "action_dim": 7}

    class _Scene:
        num_envs = 2

    class _Sim:
        device = "cpu"

    env.cfg = _Cfg()
    env._is_closed = True
    env.scene = _Scene()
    env.sim = _Sim()
    object_pose = torch.eye(4, dtype=torch.float32).repeat(2, 1, 1)
    object_pose[:, :3, 3] = torch.tensor(
        [
            [0.625, 0.078, 0.119],
            [0.590, 0.118, 0.119],
        ],
        dtype=torch.float32,
    )
    env.obs_buf = {"policy": {"object_pose": object_pose}, "subtask_terms": {}}

    place_target = env.get_object_poses()["place_target"]

    assert not torch.allclose(place_target[:, :3, 3], torch.tensor([[0.590, 0.078, 0.119]]).repeat(2, 1))
    assert torch.allclose(place_target[:, :2, 3], object_pose[:, :2, 3])
    assert torch.allclose(place_target[:, 2, 3], torch.tensor([0.119, 0.119], dtype=torch.float32))


def test_physical_env_contract_uses_real_omx_articulation_contacts_and_cameras() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_physical_env_cfg")

    assert Path(module.ROBOTIS_OMX_USD_PATH).name == "omx.usda"
    assert Path(module.ROBOTIS_OMX_STAGE_PATH).name == "omx_table_layout.usda"
    assert module.ROBOTIS_OMX_JOINT_NAMES == (
        "Joint1",
        "Joint2",
        "Joint3",
        "Joint4",
        "Joint5",
        "Gripper",
        "Gripper_mimic",
    )
    assert module.ROBOTIS_OMX_EEF_BODY_NAME == "link5"
    assert module.ROBOTIS_OMX_CAMERA_NAMES == ("top", "front", "right")
    cfg = module.RobotisOMXPhysicalPickPlaceEnvCfg()
    assert cfg.action_contract["control_mode"] == "joint_position_physical_articulation"
    assert cfg.action_contract["joint_names"] == list(module.ROBOTIS_OMX_JOINT_NAMES)
    assert cfg.action_contract["gripper_contact_hold"]["threshold_n"] == 0.2
    assert cfg.action_contract["gripper_contact_hold"]["required_sides"] == ["left", "right"]
    assert cfg.contact_contract["required_pairs"] == ["left_finger:red_cube", "right_finger:red_cube"]
    assert cfg.rgbd_contract["cameras"] == ["top", "front", "right"]
    assert cfg.rgbd_contract["depth_encoding"] == "png16"
    assert cfg.rgbd_contract["depth_scale_m_per_unit"] == 0.001
    assert cfg.scene_contract["source_stage_path"] == module.ROBOTIS_OMX_STAGE_PATH
    assert cfg.scene_contract["robot_stage_prim"] == "/World/Robot"
    assert cfg.scene_contract["red_cube_stage_prim"] == "/World/Workspace/RedSpecimenBlock"
    assert cfg.scene_contract["static_prim_names"] == [
        "TableTop",
        "TableTopFrontLeft",
        "TableTopFrontRight",
        "RobotBasePocketFloor",
        "A4Sheet",
        "A4CornerMarker_1",
        "A4CornerMarker_2",
        "A4CornerMarker_3",
        "A4CornerMarker_4",
        "A4CenterMarker",
        "RightDiskAluminumTop",
        "RightDiskBlackBase",
        "RightDiskCenterYellowMarker",
    ]
    assert cfg.scene_contract["layout_basis"] == "omx_table_layout_usda_static_props"


def test_physical_reset_randomizes_cube_after_scene_default_reset() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_physical_env_cfg")

    cfg = module.RobotisOMXPhysicalPickPlaceEnvCfg()
    reset_terms = [name for name in dir(cfg.events) if name.startswith("reset")]

    assert "reset_base_scene" in reset_terms
    assert "reset_cube_pose" in reset_terms
    assert "reset_scene" not in reset_terms
    assert sorted(reset_terms).index("reset_base_scene") < sorted(reset_terms).index("reset_cube_pose")


def test_physical_env_camera_resolution_can_be_overridden(monkeypatch) -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_physical_env_cfg")
    monkeypatch.setenv("ROBOTIS_OMX_CAMERA_WIDTH", "320")
    monkeypatch.setenv("ROBOTIS_OMX_CAMERA_HEIGHT", "240")

    cfg = module.RobotisOMXPhysicalPickPlaceEnvCfg()

    assert cfg.rgbd_contract["width"] == 320
    assert cfg.rgbd_contract["height"] == 240
    for camera_attr in ("top_cam", "front_cam", "right_cam"):
        camera_cfg = getattr(cfg.scene, camera_attr, None)
        if camera_cfg is not None:
            assert camera_cfg.width == 320
            assert camera_cfg.height == 240


def test_physical_rgbd_cameras_match_standard_training_views(monkeypatch) -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_physical_env_cfg")
    monkeypatch.delenv("ROBOTIS_OMX_CAMERA_MODE", raising=False)

    cfg = module.RobotisOMXPhysicalPickPlaceEnvCfg()

    top = cfg.scene.top_cam.offset
    front = cfg.scene.front_cam.offset
    right = cfg.scene.right_cam.offset
    assert top.convention == "opengl"
    assert front.convention == "opengl"
    assert right.convention == "opengl"
    assert top.pos == (0.315, 0.205, 0.72)
    assert front.pos == (0.36, 0.96, 0.52)
    assert right.pos == (0.86, 0.58, 0.52)
    assert getattr(cfg.scene.top_cam.spawn, "focal_length") == pytest.approx(18.0)
    assert getattr(cfg.scene.front_cam.spawn, "focal_length") == pytest.approx(14.0)
    assert getattr(cfg.scene.right_cam.spawn, "focal_length") == pytest.approx(10.0)


def test_physical_env_camera_mode_off_disables_camera_observations(monkeypatch) -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_physical_env_cfg")
    monkeypatch.setenv("ROBOTIS_OMX_CAMERA_MODE", "off")

    cfg = module.RobotisOMXPhysicalPickPlaceEnvCfg()

    assert cfg.rgbd_contract["enabled"] is False
    for camera_attr in ("top_cam", "front_cam", "right_cam"):
        if hasattr(cfg.scene, camera_attr):
            assert getattr(cfg.scene, camera_attr) is None
    policy_obs = getattr(cfg.observations, "policy", None)
    if policy_obs is not None:
        for obs_attr in ("top_rgb", "top_depth", "front_rgb", "front_depth", "right_rgb", "right_depth"):
            if hasattr(policy_obs, obs_attr):
                assert getattr(policy_obs, obs_attr) is None


def test_physical_env_explicitly_applies_contact_reporters_to_finger_links() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_physical_env_cfg")

    assert module.ROBOTIS_OMX_CONTACT_REPORTER_PRIM_PATHS == (
        "Geometry/link0/link1/link2/link3/link4/link5/link6",
        "Geometry/link0/link1/link2/link3/link4/link5/link7",
    )
    assert module.ROBOTIS_OMX_SPAWN_FUNC.endswith(":spawn_robotis_omx_usd_with_contact_reporters")
    cfg = module.RobotisOMXPhysicalPickPlaceEnvCfg()
    assert cfg.contact_contract["contact_reporter_prims"] == list(module.ROBOTIS_OMX_CONTACT_REPORTER_PRIM_PATHS)


def test_physical_finger_contact_sensors_allocate_enough_contact_points() -> None:
    source = Path("integrations/isaac_lab_robotis_omx/robotis_omx_physical_env_cfg.py").read_text(encoding="utf-8")

    assert source.count("max_contact_data_count_per_prim=128") >= 2


def test_physical_policy_observation_declares_rgbd_camera_terms() -> None:
    source = Path("integrations/isaac_lab_robotis_omx/robotis_omx_physical_env_cfg.py").read_text(encoding="utf-8")

    for camera in ("top", "front", "right"):
        assert f"{camera}_rgb = ObsTerm(func=mdp.image" in source
        assert f"{camera}_depth = ObsTerm(func=mdp.image" in source
        assert f'SceneEntityCfg("{camera}_cam")' in source


def test_physical_subtask_signals_are_geometry_and_contact_based() -> None:
    observations = importlib.import_module("integrations.isaac_lab_robotis_omx.mdp.physical_observations")

    class _Data:
        root_pos_w = torch.tensor([[0.40, 0.30, 0.015]], dtype=torch.float32)

    class _Cube:
        data = _Data()

    class _Env:
        device = "cpu"
        num_envs = 1
        scene = {"red_cube": _Cube()}
        physical_contact_state = {
            "left_finger:red_cube": torch.tensor([[0.25]], dtype=torch.float32),
            "right_finger:red_cube": torch.tensor([[0.24]], dtype=torch.float32),
        }
        physical_eef_pos_w = torch.tensor([[0.402, 0.302, 0.05]], dtype=torch.float32)

    env = _Env()
    assert observations.approach(env).item() is True
    assert observations.grasp(env).item() is True
    assert observations.lift(env).item() is False
    env.scene["red_cube"].data.root_pos_w = torch.tensor([[0.40, 0.30, 0.095]], dtype=torch.float32)
    assert observations.lift(env).item() is True
    assert observations.place(env).item() is False
    env.scene["red_cube"].data.root_pos_w = torch.tensor([[0.52, 0.30, 0.026]], dtype=torch.float32)
    assert observations.place(env).item() is False
    env.scene["red_cube"].data.root_pos_w = torch.tensor([[0.590, 0.078, 0.070]], dtype=torch.float32)
    assert observations.place(env).item() is False
    env.scene["red_cube"].data.root_pos_w = torch.tensor([[0.590, 0.078, 0.119]], dtype=torch.float32)
    assert observations.place(env).item() is True


def test_physical_contact_force_reads_isaac_lab_proxy_array_torch_payload() -> None:
    observations = importlib.import_module("integrations.isaac_lab_robotis_omx.mdp.physical_observations")

    class _ProxyArray:
        def __init__(self, payload: torch.Tensor) -> None:
            self.torch = payload

    class _Data:
        force_matrix_w = _ProxyArray(torch.tensor([[[[0.0, 0.0, 0.30]]]], dtype=torch.float32))
        net_forces_w = _ProxyArray(torch.zeros((1, 1, 3), dtype=torch.float32))

    class _Sensor:
        data = _Data()

    class _Env:
        device = "cpu"
        num_envs = 1
        scene = {"left_finger_contact": _Sensor()}

    force = observations.contact_force(_Env(), "left_finger:red_cube")

    assert force.shape == (1,)
    assert torch.allclose(force, torch.tensor([0.30], dtype=torch.float32))


def test_physical_gripper_contact_hold_clamps_both_gripper_joints() -> None:
    actions = importlib.import_module("integrations.isaac_lab_robotis_omx.mdp.actions")

    processed = torch.tensor([[0.0, 0.0, 0.0, 0.0, 0.0, 0.20, -0.20]], dtype=torch.float32)
    last = torch.tensor([0.25], dtype=torch.float32)
    hold = torch.full((1,), float("nan"), dtype=torch.float32)
    left = torch.tensor([0.24], dtype=torch.float32)
    right = torch.tensor([0.25], dtype=torch.float32)

    adjusted, next_hold, diagnostics = actions.apply_contact_gripper_hold(
        processed,
        joint_names=["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper", "Gripper_mimic"],
        previous_primary_target=last,
        hold_target=hold,
        left_force_n=left,
        right_force_n=right,
        threshold_n=0.2,
        overtravel_rad=0.01,
        release_margin_rad=0.01,
    )

    assert torch.allclose(next_hold, torch.tensor([0.19], dtype=torch.float32))
    assert torch.allclose(adjusted[:, 5], torch.tensor([0.20], dtype=torch.float32))
    assert torch.allclose(adjusted[:, 6], torch.tensor([-0.20], dtype=torch.float32))
    assert diagnostics["hold_reason"] == ["contact_hold_armed"]

    closing_deeper = torch.tensor([[0.0, 0.0, 0.0, 0.0, 0.0, 0.05, -0.05]], dtype=torch.float32)
    adjusted, next_hold, diagnostics = actions.apply_contact_gripper_hold(
        closing_deeper,
        joint_names=["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper", "Gripper_mimic"],
        previous_primary_target=torch.tensor([0.20], dtype=torch.float32),
        hold_target=next_hold,
        left_force_n=left,
        right_force_n=right,
        threshold_n=0.2,
        overtravel_rad=0.01,
        release_margin_rad=0.01,
    )

    assert torch.allclose(adjusted[:, 5], torch.tensor([0.19], dtype=torch.float32))
    assert torch.allclose(adjusted[:, 6], torch.tensor([-0.19], dtype=torch.float32))
    assert diagnostics["clamped"] == [True]
    assert diagnostics["hold_reason"] == ["contact_hold_clamped"]


def test_physical_success_term_uses_cube_pose_not_step_counter() -> None:
    terminations = importlib.import_module("integrations.isaac_lab_robotis_omx.mdp.physical_terminations")

    class _Data:
        root_pos_w = torch.tensor([[0.590, 0.078, 0.119], [0.52, 0.30, 0.026]], dtype=torch.float32)

    class _Cube:
        data = _Data()

    class _Env:
        device = "cpu"
        num_envs = 2
        scene = {"red_cube": _Cube()}

    assert terminations.task_success(_Env()).tolist() == [True, False]


def test_visual_bc_config_names_rgb_and_depth_observations() -> None:
    config_path = Path("integrations/isaac_lab_robotis_omx/robomimic/bc_visual.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    obs = config["observation"]["modalities"]["obs"]

    assert obs["rgb"] == ["top_rgb", "front_rgb", "right_rgb"]
    assert obs["depth"] == ["top_depth", "front_depth", "right_depth"]
    assert "object_pose" in obs["low_dim"]
