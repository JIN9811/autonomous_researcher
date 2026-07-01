"""Tests for the LeRobot Isaac Lab synthetic pipeline contracts."""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import pyarrow as pa
import pyarrow.parquet as pq

import device_bridges.isaac_lab_synthetic as isaac_lab_synthetic
from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from mcp_tools.lerobot_schemas import (
    IsaacLabSyntheticRequest,
    IsaacSyntheticFallbackPolicy,
    IsaacSyntheticPipelineMode,
    IsaacSyntheticSourceIntent,
)


def _bridge(tmp_path: Path) -> LeRobotBridge:
    config = {
        "lerobot": {
            "default_profile_id": "fake_omx_ai",
            "session_memory_path": str(tmp_path / "memory" / "sessions.json"),
            "fake_dataset_root": str(tmp_path / "datasets"),
            "dataset_root": str(tmp_path / "hf_datasets"),
            "fake_checkpoint_root": str(tmp_path / "checkpoints"),
            "output_root": str(tmp_path / "outputs"),
            "policy_root": str(tmp_path / "policies"),
            "session_log_root": str(tmp_path / "logs"),
            "profiles": {
                "fake_omx_ai": {
                    "profile_id": "fake_omx_ai",
                    "display_name": "Fake ROBOTIS OMX-AI",
                    "robot_family": "robotis_omx",
                    "robot_type": "omx_follower",
                    "teleop_type": "omx_leader",
                    "robot_port": "/dev/ttyUSB_FAKE_FOLLOWER",
                    "teleop_port": "/dev/ttyUSB_FAKE_LEADER",
                    "robot_id": "omx_follower_arm",
                    "teleop_id": "omx_leader_arm",
                    "calibration_dir": "",
                    "fps": 30,
                    "safety_limits": {"live_enabled": False},
                    "command_templates": {},
                }
            },
        }
    }
    return LeRobotBridge(LeRobotBridgeConfig.from_config(config, repo_root=tmp_path))


def _make_dataset(path: Path, *, total_frames: int = 3) -> None:
    (path / "meta").mkdir(parents=True, exist_ok=True)
    (path / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (path / "meta" / "info.json").write_text(
        json.dumps({"codebase_version": "v2.1", "total_episodes": 1, "total_frames": total_frames}),
        encoding="utf-8",
    )
    (path / "meta" / "tasks.jsonl").write_text(
        json.dumps({"task_index": 0, "task": "Pick up the cube"}) + "\n",
        encoding="utf-8",
    )
    (path / "meta" / "episodes.jsonl").write_text(
        json.dumps({"episode_index": 0, "tasks": ["Pick up the cube"], "length": total_frames}) + "\n",
        encoding="utf-8",
    )
    (path / "data" / "chunk-000" / "episode_000000.parquet").write_bytes(b"PAR1")
    depth_dir = path / "sidecar" / "depth_raw"
    depth_dir.mkdir(parents=True, exist_ok=True)
    (depth_dir / "transform_manifest.json").write_text(
        json.dumps(
            {
                "camera_keys": ["top", "wrist"],
                "depth_encoding": "png16",
                "depth_scale_m_per_unit": 0.001,
            }
        ),
        encoding="utf-8",
    )


def _write_mirror_grasp_diagnostics(path: Path, diagnostics: list[dict[str, object]]) -> None:
    mirror_dir = path / "sidecar" / "isaac_mirror"
    mirror_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, grasp_diagnostics in enumerate(diagnostics, start=1):
        rows.append(
            {
                "schema": "atr.lerobot.isaac_mirror.sample.v1",
                "episode_index": 0,
                "sample_index": index,
                "elapsed_s": round((index - 1) / 15.0, 6),
                "grasp_diagnostics": grasp_diagnostics,
            }
        )
    (mirror_dir / "lr-record-fixture.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_episode_parquet(path: Path) -> None:
    table = pa.table(
        {
            "episode_index": pa.array([0, 0, 0], type=pa.int64()),
            "frame_index": pa.array([0, 1, 2], type=pa.int64()),
            "timestamp": pa.array([0.0, 1.0 / 15.0, 2.0 / 15.0], type=pa.float64()),
            "observation.state": pa.array(
                [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
                type=pa.list_(pa.float64()),
            ),
            "action": pa.array(
                [[1.0, 1.1, 1.2], [2.0, 2.1, 2.2], [3.0, 3.1, 3.2]],
                type=pa.list_(pa.float64()),
            ),
        }
    )
    pq.write_table(table, path / "data" / "chunk-000" / "episode_000000.parquet")


def test_isaac_lab_synthetic_request_defaults() -> None:
    request = IsaacLabSyntheticRequest.model_validate({"dataset_path": "/tmp/demo"})

    assert request.pipeline_mode == IsaacSyntheticPipelineMode.ISAAC_LAB_REPLICATOR
    assert request.fallback_policy == IsaacSyntheticFallbackPolicy.BLOCK_ON_PRIMARY_FAILURE
    assert request.source_intent == IsaacSyntheticSourceIntent.TRAIN_READY_SUCCESS_ONLY
    assert request.cameras == ["top", "front", "right"]
    assert request.real_weight == 1.0
    assert request.isaac_lab_synthetic_weight == 0.25


def test_isaac_lab_validate_blocks_missing_dataset(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    missing_dataset = tmp_path / "missing_dataset"

    result = bridge.isaac_lab_validate({"mode": "test", "dataset_path": str(missing_dataset)})

    assert result["ok"] is False
    assert result["tool"] == "lerobot.isaac_lab.validate"
    assert result["status"] == "BLOCKED"
    assert result["validation_report"]["blockers"][0]["code"] == "REQ_INVALID_DATASET"


def test_isaac_lab_prepare_writes_preflight_artifacts(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")

    result = bridge.isaac_lab_prepare(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    assert result["ok"] is True
    assert result["tool"] == "lerobot.isaac_lab.prepare"
    assert result["status"] == "READY_TO_BUILD"
    output_root = Path(result["output_root"])
    assert (output_root / "validation_report.json").is_file()
    assert (output_root / "compatibility.json").is_file()
    assert (output_root / "digital_twin_preflight.json").is_file()
    assert result["compatibility"]["isaac_lab_path"] == str(isaac_lab.resolve())


def test_isaac_lab_prepare_physics_preflight_accepts_contact_safe_stage(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "physics_valid"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text(
        """#usda 1.0
# atr:physics physics_time_steps_per_second=120 solver_position_iterations=12 solver_velocity_iterations=4 gpu_dynamics_enabled=false ccd_enabled=true
# atr:physics cube_rigid_body=dynamic cube_collider_type=box cube_mass_kg=0.08 cube_size_m=0.05 contact_offset_m=0.005 rest_offset_m=0.0
# atr:physics cube_static_friction=0.8 cube_dynamic_friction=0.6 a4_static_friction=0.9 gripper_inner_static_friction=1.2 gripper_inner_dynamic_friction=1.0
# atr:physics gripper_collider_type=convex_decomposition gripper_collider_skin_fraction=0.04 gripper_inner_pad_only=true
# atr:physics filtered_collision_pairs=nonessential_self_only finger_object_contact_filtered=false contact_report_enabled=true contact_threshold_n=0.2 contact_report_fingers=left,right sdf_custom_geometry_used=false
def Xform "World"
{
    def Xform "Robot" {}
    def Cube "RedCube" {}
}
""",
        encoding="utf-8",
    )

    result = bridge.isaac_lab_prepare(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "validation_checks": ["physics"],
            "require_physics_pass": True,
        }
    )

    assert result["ok"] is True
    output_root = Path(result["output_root"])
    physics = json.loads((output_root / "physics_preflight.json").read_text(encoding="utf-8"))
    check = physics["checks"][0]
    assert check["status"] == "passed"
    evidence = check["evidence"]
    assert evidence["cube_rigid_body"]["dynamic"] is True
    assert evidence["cube_collider"]["type"] == "box"
    assert evidence["gripper_collider"]["type"] == "convex_decomposition"
    assert evidence["collision_skin"]["contact_offset_m"] == 0.005
    assert evidence["collision_skin"]["rest_offset_m"] == 0.0
    assert evidence["materials"]["cube"]["static_friction"] == 0.8
    assert evidence["materials"]["gripper_inner_pad"]["static_friction"] == 1.2
    assert evidence["filtered_pairs"]["finger_object_contact_filtered"] is False
    assert evidence["contact_reporting"]["both_fingers_to_cube"] is True
    assert evidence["physx_limitations"]["sdf_custom_geometry_used"] is False


def test_isaac_lab_prepare_physics_preflight_blocks_unsafe_contact_stage(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "physics_invalid"
    _make_dataset(dataset)
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text(
        """#usda 1.0
# atr:physics cube_rigid_body=static cube_collider_type=none cube_mass_kg=0 cube_size_m=0.05 contact_offset_m=0.02 rest_offset_m=0.0
# atr:physics cube_static_friction=0.0 cube_dynamic_friction=0.0 gripper_collider_type=plane gripper_collider_skin_fraction=0.5
# atr:physics filtered_collision_pairs=finger_object finger_object_contact_filtered=true contact_report_enabled=false contact_threshold_n=0.2 contact_report_fingers=left sdf_custom_geometry_used=true
def Xform "World"
{
    def Xform "Robot" {}
    def Cube "RedCube" {}
}
""",
        encoding="utf-8",
    )

    result = bridge.isaac_lab_prepare(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "stage_path": str(stage),
            "enable_replicator": False,
            "validation_checks": ["physics"],
            "require_physics_pass": True,
        }
    )

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    blocker_codes = {blocker["code"] for blocker in result["validation_report"]["blockers"]}
    assert "CUBE_RIGID_BODY_MISSING" in blocker_codes
    physics = json.loads((Path(result["output_root"]) / "physics_preflight.json").read_text(encoding="utf-8"))
    check = physics["checks"][0]
    assert check["status"] == "blocked"
    assert set(check["evidence"]["blocking_failures"]) >= {
        "CUBE_RIGID_BODY_MISSING",
        "COLLIDER_PRECHECK_FAILED",
        "PHYSICS_MATERIAL_MISSING",
        "CONTACT_REPORT_MISSING",
        "FILTERED_PAIR_UNSAFE",
        "SDF_UNSUPPORTED_FOR_BACKEND",
    }


def test_isaac_lab_prepare_articulation_preflight_accepts_safe_joint_drive_contract(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "articulation_valid"
    _make_dataset(dataset)
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text(
        """#usda 1.0
# atr:articulation articulation_root=/World/Robot solver_position_iterations=12 solver_velocity_iterations=4
# atr:articulation joint_names=joint1,joint2,joint3,joint4,joint5,gripper_left,gripper_right lerobot_action_keys=joint1,joint2,joint3,joint4,joint5,gripper_left,gripper_right joint_mapping=one_to_one
# atr:articulation joint_zero_pose_policy=reference_only drive_targets_initialized_from_current_pose=true command_modes=position drive_mode_per_joint=position
# atr:articulation stiffness_max=180 damping_min=8 max_force_max=1.5 max_velocity_max=4.0
# atr:articulation mimic_joints=gripper_left,gripper_right mimic_gear_ratio=1.0 mimic_direction=opposed_close
# atr:articulation lerobot_joint_source=leader explicit_source_policy=leader_only leader_joint_source=present follower_joint_source=present
def Xform "World"
{
    def Xform "Robot" {}
}
""",
        encoding="utf-8",
    )

    result = bridge.isaac_lab_prepare(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "stage_path": str(stage),
            "enable_replicator": False,
            "validation_checks": ["articulation"],
            "require_articulation_pass": True,
        }
    )

    assert result["ok"] is True
    articulation = json.loads((Path(result["output_root"]) / "articulation_preflight.json").read_text(encoding="utf-8"))
    check = articulation["checks"][0]
    assert check["status"] == "passed"
    evidence = check["evidence"]
    assert evidence["joint_mapping"]["one_to_one"] is True
    assert evidence["joint_mapping"]["joint_count"] == 7
    assert evidence["joint_zero_policy"]["reference_only"] is True
    assert evidence["initial_drive_targets"]["initialized_from_current_pose"] is True
    assert evidence["command_modes"]["exclusive"] is True
    assert evidence["drive_gains"]["within_bounds"] is True
    assert evidence["mimic_mapping"]["valid"] is True
    assert evidence["joint_source"]["source"] == "leader"
    assert evidence["joint_source"]["safe"] is True
    assert evidence["solver"]["position_iterations"] == 12


def test_isaac_lab_prepare_articulation_preflight_blocks_unsafe_joint_drive_contract(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "articulation_invalid"
    _make_dataset(dataset)
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text(
        """#usda 1.0
# atr:articulation articulation_root= solver_position_iterations=1 solver_velocity_iterations=0
# atr:articulation joint_names=joint1,joint2 lerobot_action_keys=joint1,joint2,joint3 joint_mapping=partial
# atr:articulation joint_zero_pose_policy=command drive_targets_initialized_from_current_pose=false command_modes=position,velocity,teleport drive_mode_per_joint=position,velocity
# atr:articulation stiffness_max=25000 damping_min=0 max_force_max=500 max_velocity_max=80
# atr:articulation mimic_joints=gripper_left,gripper_right mimic_gear_ratio=-1.0 mimic_direction=same_close
# atr:articulation lerobot_joint_source=mixed explicit_source_policy= leader_joint_source=present follower_joint_source=present
def Xform "World"
{
    def Xform "Robot" {}
}
""",
        encoding="utf-8",
    )

    result = bridge.isaac_lab_prepare(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "stage_path": str(stage),
            "enable_replicator": False,
            "validation_checks": ["articulation"],
            "require_articulation_pass": True,
        }
    )

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    blocker_codes = {blocker["code"] for blocker in result["validation_report"]["blockers"]}
    assert "JOINT_MAP_MISSING" in blocker_codes
    articulation = json.loads((Path(result["output_root"]) / "articulation_preflight.json").read_text(encoding="utf-8"))
    check = articulation["checks"][0]
    assert check["status"] == "blocked"
    assert set(check["evidence"]["blocking_failures"]) >= {
        "JOINT_MAP_MISSING",
        "JOINT_ZERO_USED_AS_COMMAND",
        "DRIVE_TARGET_JUMP_RISK",
        "COMMAND_MODE_CONFLICT",
        "DRIVE_GAIN_UNSTABLE",
        "MIMIC_MAPPING_INVALID",
        "JOINT_SOURCE_UNKNOWN",
    }


def test_isaac_lab_prepare_extracts_digital_twin_stage_contract_and_snapshot(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage_text = """#usda 1.0
(
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "World"
{
    def Xform "Robot"
    {
    }

    def Xform "A4Workspace"
    {
    }

    def Cube "RedCube"
    {
    }

    def Camera "Camera_top"
    {
    }

    def Camera "Camera_front"
    {
    }
}
"""
    stage.write_text(stage_text, encoding="utf-8")

    result = bridge.isaac_lab_prepare(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
            "validation_checks": ["digital_twin"],
            "cameras": ["top", "front"],
        }
    )

    digital_twin = result["digital_twin"]
    snapshot_path = Path(digital_twin["stage_snapshot_path"])
    checks = {check["id"]: check for check in result["validation_report"]["checks"]}
    camera_prims = {camera["camera"]: camera for camera in digital_twin["camera_prims"]}

    assert result["ok"] is True
    assert digital_twin["stage_units_meters_per_unit"] == 1.0
    assert digital_twin["up_axis"] == "Z"
    assert digital_twin["robot_root_prim"] == {"path": "/World/Robot", "found": True}
    assert digital_twin["workspace_root_prim"] == {"path": "/World/A4Workspace", "found": True}
    assert digital_twin["cube_prim"] == {"path": "/World/RedCube", "found": True}
    assert camera_prims["top"] == {"camera": "top", "path": "/World/Camera_top", "found": True}
    assert camera_prims["front"] == {"camera": "front", "path": "/World/Camera_front", "found": True}
    assert digital_twin["joint_zero_pose"]["reference"] == "stop_button_default_pose"
    assert digital_twin["joint_zero_pose"]["usd_joint_zero_is_default_pose"] is True
    assert digital_twin["lerobot_joint_mapping"]["joint_count"] >= 6
    assert digital_twin["lerobot_joint_mapping"]["action_dimension"] == 7
    assert digital_twin["active_robot_cam"]["primary_camera_key"] == "wrist"
    assert digital_twin["d405_mount"]["mass_kg"] > 0.0
    assert digital_twin["physics_materials"]["cube"]["material"] == "3dp_pla"
    assert digital_twin["physics_materials"]["gripper_inner"]["material"] == "anti_slip_tape"
    assert digital_twin["rtsp_streams"]["required"] is False
    assert digital_twin["rtsp_streams"]["unique_port_allocation"] is True
    assert digital_twin["rtsp_streams"]["manifest_path"].endswith("digital_twin/rtsp_streams.json")
    assert [row["camera"] for row in digital_twin["rtsp_streams"]["registrations"]] == ["top", "front"]
    assert len({row["port"] for row in digital_twin["rtsp_streams"]["registrations"]}) == 2
    assert all(row["startup_diagnostics"]["first_frame_status"] == "not_requested" for row in digital_twin["rtsp_streams"]["registrations"])
    assert all(row["sei_metadata_capture"]["enabled"] is True for row in digital_twin["rtsp_streams"]["registrations"])
    assert Path(digital_twin["rtsp_streams"]["manifest_path"]).is_file()
    assert snapshot_path.is_file()
    assert snapshot_path.read_text(encoding="utf-8") == stage_text
    assert checks["validate_stage_units"]["status"] == "passed"
    assert checks["validate_digital_twin_prims"]["status"] == "passed"


def test_isaac_lab_prepare_does_not_treat_table_prims_as_requested_cameras(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text(
        """#usda 1.0
(
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "World"
{
    def Xform "Robot" {}
    def Xform "Workspace" {}
    def Cube "RedCube" {}
    def Cube "TableTop" {}
    def Cube "TableTopFrontLeft" {}
}
""",
        encoding="utf-8",
    )

    result = bridge.isaac_lab_prepare(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
            "validation_checks": ["digital_twin"],
            "cameras": ["top", "front"],
        }
    )

    camera_prims = {camera["camera"]: camera for camera in result["digital_twin"]["camera_prims"]}
    checks = {check["id"]: check for check in result["validation_report"]["checks"]}

    assert result["ok"] is True
    assert camera_prims["top"]["path"] == "/World/ATRRenderCameras/top"
    assert camera_prims["top"]["source"] == "replicator_worker_fallback"
    assert camera_prims["top"]["planned_pose"]["position"] == [0.315, 0.205, 0.72]
    assert camera_prims["top"]["planned_pose"]["look_at"] == [0.315, 0.265, 0.0]
    assert camera_prims["top"]["found"] is False
    assert camera_prims["front"]["path"] == "/World/ATRRenderCameras/front"
    assert camera_prims["front"]["source"] == "replicator_worker_fallback"
    assert camera_prims["front"]["planned_pose"]["position"] == [0.36, 0.96, 0.52]
    assert camera_prims["front"]["planned_pose"]["look_at"] == [0.36, 0.28, 0.025]
    assert camera_prims["front"]["found"] is False
    assert checks["validate_digital_twin_prims"]["status"] == "passed"
    assert checks["validate_digital_twin_prims"]["message"] == "Required robot, workspace, and cube prims were detected."
    assert checks["validate_render_camera_plan"]["status"] == "passed"
    assert checks["validate_render_camera_plan"]["evidence"]["camera_sources"] == {
        "top": "replicator_worker_fallback",
        "front": "replicator_worker_fallback",
    }


def test_isaac_lab_build_blocks_enabled_replicator_without_isaac_sim_python(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        isaac_lab_synthetic,
        "DEFAULT_ISAAC_SIM_PYTHON",
        tmp_path / "missing" / "python.sh",
        raising=False,
    )
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")

    result = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": True,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert result["replicator"]["status"] == "blocked"
    assert result["replicator"]["blocker"] == "REPLICATOR_RUNTIME_MISSING"
    blockers = result["validation_report"]["blockers"]
    assert any(blocker["code"] == "REPLICATOR_RUNTIME_MISSING" for blocker in blockers)


def test_isaac_lab_build_writes_replicator_readiness_artifacts_when_runtime_is_configured(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    result = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "isaac_sim_python": str(isaac_python),
            "stage_path": str(stage),
            "enable_replicator": True,
            "enable_hdf5_export": False,
            "enable_mimic": False,
            "enable_rl_teacher": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
            "cameras": ["top", "right"],
            "attempts_per_source_frame": 2,
            "rgb_strength": 0.21,
            "depth_strength": 0.31,
            "render_strength": 0.41,
            "camera_pose_strength": 0.07,
        }
    )

    output_root = Path(result["output_root"])
    assert result["ok"] is True
    assert result["replicator"]["status"] == "ready"
    assert result["replicator"]["expected_render_rows"] == 12
    assert result["replicator"]["rendered_count"] == 0
    assert result["replicator"]["render_manifest_available"] is False
    assert result["replicator"]["cameras"] == ["top", "right"]
    assert result["replicator"]["replicator_available"] is False
    assert result["replicator"]["writer_type"] == "BasicWriter"
    assert result["replicator"]["annotators"] == ["rgb", "distance_to_image_plane", "semantic_segmentation"]
    assert result["replicator"]["render_products"]["requested_count"] == 12
    assert result["replicator"]["render_products"]["camera_names"] == ["top", "right"]
    assert result["replicator"]["rgb_output_count"] == 0
    assert result["replicator"]["depth_output_count"] == 0
    assert result["replicator"]["segmentation_output_count"] == 0
    assert result["replicator"]["depth_units_replicator"]["unit"] == "meters"
    augmentation = result["replicator"]["post_render_augmentation"]
    assert augmentation["schema"] == "atr.lerobot.replicator.post_render_augmentation.v1"
    assert augmentation["owner"] == "isaac_sim_replicator_writer_annotators"
    assert augmentation["execution_stage"] == "replicator_writer_annotator"
    assert augmentation["rgb"]["annotator"] == "rgb"
    assert augmentation["rgb"]["strength"] == 0.21
    assert augmentation["depth"]["annotator"] == "distance_to_image_plane"
    assert augmentation["depth"]["strength"] == 0.31
    assert augmentation["depth"]["source_profile"] == "d405_raw_depth_profile"
    assert augmentation["render"]["strength"] == 0.41
    assert augmentation["camera_pose"]["strength"] == 0.07
    assert augmentation["camera_pose"]["cameras"] == ["top", "right"]
    assert augmentation["trajectory_boundary"] == "render_only_not_action_trajectory"
    assert result["replicator"]["teleop_sdg_replay_used"] is False
    assert result["replicator"]["teleop_sdg_replay_boundary"] == "render_only_not_physics_rollout"
    assert result["replicator"]["runtime_probe"] == {
        "status": "pending",
        "import_checked": False,
        "required_modules": ["omni.replicator.core"],
        "python_path": str(isaac_python.resolve()),
        "reason": "Runtime path is configured, but Replicator import is deferred to the Isaac Sim worker.",
    }
    assert result["replicator"]["isaac_sim_smoke"]["schema"] == "atr.lerobot.isaac_sim.smoke_checks.v1"
    assert result["replicator"]["isaac_sim_smoke"]["status"] == "ready_to_probe"
    smoke_checks = {check["id"]: check for check in result["replicator"]["isaac_sim_smoke"]["checks"]}
    assert smoke_checks["replicator_rgb_render_product"]["status"] == "ready_to_probe"
    assert smoke_checks["replicator_depth_render_product"]["annotator"] == "distance_to_image_plane"
    assert smoke_checks["replicator_writer_output"]["writer_type"] == "BasicWriter"
    assert smoke_checks["scene_randomization"]["status"] == "ready_to_probe"
    assert smoke_checks["physics_collider_debug"]["status"] == "ready_to_probe"
    assert {
        "id": "replicator_import_probe",
        "status": "pending",
        "required_modules": ["omni.replicator.core"],
    } in result["replicator"]["checks"]
    assert (output_root / "replicator" / "summary.json").is_file()
    assert (output_root / "replicator" / "build_plan.json").is_file()
    assert (output_root / "replicator" / "post_render_augmentation.json").is_file()
    build_plan = json.loads((output_root / "replicator" / "build_plan.json").read_text(encoding="utf-8"))
    assert build_plan["runtime_probe"]["status"] == "pending"
    assert build_plan["runtime_probe"]["import_checked"] is False
    assert build_plan["worker"]["script"].endswith("scripts/lerobot_isaac_replicator_synthetic.py")
    assert "--canonical-index" in build_plan["worker"]["command"]
    assert str(output_root / "canonical_episode_index" / "manifest.jsonl") in build_plan["worker"]["command"]
    assert "--stage-url" in build_plan["worker"]["command"]
    assert str(stage.resolve()) in build_plan["worker"]["command"]
    assert "--output-dir" in build_plan["worker"]["command"]
    assert str(output_root / "replicator") in build_plan["worker"]["command"]
    assert "--augmentation-config" in build_plan["worker"]["command"]
    assert str(output_root / "replicator" / "post_render_augmentation.json") in build_plan["worker"]["command"]
    assert "--cameras" in build_plan["worker"]["command"]
    assert "top,right" in build_plan["worker"]["command"]
    assert build_plan["writer_type"] == "BasicWriter"
    assert build_plan["annotators"] == ["rgb", "distance_to_image_plane", "semantic_segmentation"]
    assert build_plan["post_render_augmentation"]["rgb"]["strength"] == 0.21
    assert build_plan["post_render_augmentation"]["depth"]["strength"] == 0.31
    assert build_plan["render_products"]["requested_count"] == 12
    assert build_plan["isaac_sim_smoke"]["status"] == "ready_to_probe"
    assert build_plan["depth_units_replicator"]["unit"] == "meters"
    assert build_plan["teleop_sdg_replay_boundary"] == "render_only_not_physics_rollout"

    status = bridge.isaac_lab_status(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
        }
    )

    assert status["replicator"]["status"] == "ready"
    assert status["replicator"]["expected_render_rows"] == 12
    assert status["replicator"]["runtime_probe"]["status"] == "pending"


def test_isaac_lab_build_uses_default_local_isaac_sim_python_when_present(tmp_path: Path, monkeypatch) -> None:
    default_isaac_python = tmp_path / "IsaacSim" / "python.sh"
    default_isaac_python.parent.mkdir(parents=True)
    default_isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr(isaac_lab_synthetic, "DEFAULT_ISAAC_SIM_PYTHON", default_isaac_python, raising=False)
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")

    result = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": True,
            "enable_hdf5_export": False,
            "enable_mimic": False,
            "enable_rl_teacher": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
            "cameras": ["top"],
        }
    )

    assert result["ok"] is True
    assert result["replicator"]["status"] == "ready"
    assert result["replicator"]["runtime_probe"]["python_path"] == str(default_isaac_python.resolve())
    build_plan = json.loads((Path(result["output_root"]) / "replicator" / "build_plan.json").read_text(encoding="utf-8"))
    assert build_plan["worker"]["command"][0] == str(default_isaac_python.resolve())


def test_isaac_lab_compatibility_reports_lab_sim_mimic_and_rl_tools(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    for relative in [
        "scripts/imitation_learning/isaaclab_mimic/generate_dataset.py",
        "scripts/imitation_learning/isaaclab_mimic/annotate_demos.py",
        "scripts/tools/record_demos.py",
        "scripts/imitation_learning/robomimic/train.py",
        "scripts/reinforcement_learning/rsl_rl/train.py",
    ]:
        path = isaac_lab / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    isaac_python = tmp_path / "IsaacSim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (isaac_python.parent / "VERSION").write_text("6.0.0-test+unit\n", encoding="utf-8")
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")

    result = bridge.isaac_lab_prepare(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "isaac_sim_python": str(isaac_python),
            "isaac_sim_docs_version": "6.0.0",
            "stage_path": str(stage),
            "enable_replicator": True,
            "enable_mimic": True,
            "enable_rl_teacher": True,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    compatibility = result["compatibility"]
    assert compatibility["status"] == "ok"
    assert compatibility["lab"]["path"] == str(isaac_lab.resolve())
    assert compatibility["lab"]["exists"] is True
    assert compatibility["sim"]["python_path"] == str(isaac_python.resolve())
    assert compatibility["isaac_sim_version"] == "6.0.0-test+unit"
    assert compatibility["sim"]["version"] == "6.0.0-test+unit"
    assert compatibility["sim"]["version_source"] == str((isaac_python.parent / "VERSION").resolve())
    assert compatibility["sim"]["docs_version"] == "6.0.0"
    assert compatibility["sim"]["status"] == "ok"
    assert compatibility["runtime_detector"]["schema"] == "atr.lerobot.isaac_sim.runtime_detector.v1"
    assert compatibility["runtime_detector"]["isaac_sim_python"] == str(isaac_python.resolve())
    assert compatibility["runtime_detector"]["isaac_sim_version"] == "6.0.0-test+unit"
    assert compatibility["runtime_detector"]["selected_docs_version"] == "6.0.0"
    assert compatibility["runtime_detector"]["physics_backend"]["name"] == "PhysX"
    assert compatibility["runtime_detector"]["physics_backend"]["status"] == "deferred_to_isaac_runtime"
    assert compatibility["runtime_detector"]["sensor_extensions"]["omni.isaac.sensor"]["status"] == "deferred_to_isaac_runtime"
    assert compatibility["runtime_detector"]["sensor_extensions"]["isaacsim.sensors.camera"]["status"] == "deferred_to_isaac_runtime"
    assert compatibility["runtime_detector"]["replicator"]["required_modules"] == ["omni.replicator.core"]
    assert compatibility["runtime_detector"]["replicator"]["status"] == "deferred_to_isaac_runtime"
    assert compatibility["replicator"]["status"] == "unknown_requires_isaac_python"
    assert compatibility["smoke_checks"]["schema"] == "atr.lerobot.isaac_lab.smoke_checks.v1"
    assert compatibility["smoke_checks"]["status"] == "ready_to_probe"
    smoke_checks = {check["id"]: check for check in compatibility["smoke_checks"]["checks"]}
    assert smoke_checks["isaac_lab_import"]["status"] == "deferred_to_isaac_runtime"
    assert smoke_checks["task_registry_probe"]["status"] == "ready_to_probe"
    assert smoke_checks["record_demos_script"]["status"] == "present"
    assert smoke_checks["generate_dataset_script"]["status"] == "present"
    assert smoke_checks["robomimic_train_script"]["status"] == "present"
    assert smoke_checks["rl_train_wrapper"]["status"] == "present"
    assert compatibility["upgrade_plan"]["schema"] == "atr.lerobot.isaac_lab.upgrade_plan.v1"
    assert compatibility["upgrade_plan"]["status"] == "ready"
    assert compatibility["upgrade_plan"]["selected_stack"] == "beta_lab_3_0_sim_6_0"
    assert compatibility["upgrade_plan"]["default_action"] == "record_only_no_mutation"
    assert compatibility["upgrade_plan"]["candidate_stacks"][0]["stack_id"] == "stable_lab_2_3_sim_5_1"
    assert compatibility["upgrade_plan"]["candidate_stacks"][1]["stack_id"] == "beta_lab_3_0_sim_6_0"
    assert compatibility["upgrade_plan"]["manifest_path"].endswith("upgrade/isaac_lab_upgrade_plan.json")
    assert Path(compatibility["upgrade_plan"]["manifest_path"]).is_file()
    assert compatibility["mimic"]["scripts_present"] is True
    assert compatibility["mimic"]["scripts"]["generate_dataset"]["exists"] is True
    assert compatibility["mimic"]["scripts"]["annotate_demos"]["exists"] is True
    assert compatibility["mimic"]["scripts"]["record_demos"]["exists"] is True
    assert compatibility["robomimic"]["train_script_present"] is True
    assert compatibility["rl"]["wrappers"]["rsl_rl_train"]["exists"] is True
    assert compatibility["rl"]["runtime_policy_export_allowed"] is False
    assert compatibility["blockers"] == []


def test_isaac_lab_validate_filters_requested_check_groups(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "runtime-only"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()

    runtime_only = bridge.isaac_lab_validate(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "enable_replicator": False,
            "validation_checks": ["runtime"],
        }
    )

    groups = {check["group"] for check in runtime_only["validation_report"]["checks"]}
    check_ids = {check["id"] for check in runtime_only["validation_report"]["checks"]}
    assert runtime_only["ok"] is True
    assert groups == {"request", "runtime"}
    assert "validate_isaac_lab_import" in check_ids
    assert "validate_stage_loads" not in check_ids
    assert "validate_depth_scale" not in check_ids
    assert "validate_physics_preflight" not in check_ids
    assert "validate_articulation_preflight" not in check_ids


def test_isaac_lab_build_ingests_existing_replicator_manifest_for_source_labels_and_preview(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    payload = {
        "mode": "test",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "isaac_sim_python": str(isaac_python),
        "stage_path": str(stage),
        "enable_replicator": True,
        "enable_hdf5_export": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
        "cameras": ["top"],
        "attempts_per_source_frame": 2,
    }
    initial = bridge.isaac_lab_build_synthetic(payload)
    output_root = Path(initial["output_root"])
    replicator_manifest = output_root / "replicator" / "manifest.jsonl"
    replicator_manifest.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "schema": "atr.lerobot.replicator_frame.v1",
            "source_type": "replicator_render_only",
            "episode_index": 0,
            "frame_index": index,
            "camera": "top",
            "variant_index": 0,
            "rgb_path": f"replicator/rgb/top/e000000_f{index:06d}_v000.png",
            "depth_path": f"replicator/depth/top/e000000_f{index:06d}_v000.png",
            "metadata_path": f"replicator/metadata/top/e000000_f{index:06d}_v000.json",
            "train_eligible": False,
            "train_exclusion_reason": "render_only_same_pose",
        }
        for index in range(2)
    ]
    replicator_manifest.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    for row in rows:
        for key in ("rgb_path", "depth_path", "metadata_path"):
            artifact = output_root / str(row[key])
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"replicator fixture\n")

    result = bridge.isaac_lab_build_synthetic(payload)
    preview = bridge.isaac_lab_preview(payload)

    assert result["replicator"]["status"] == "completed"
    assert result["replicator"]["rendered_count"] == 2
    assert result["replicator"]["render_file_validation"]["valid_row_count"] == 2
    assert result["replicator"]["render_file_validation"]["missing_rgb_count"] == 0
    assert result["replicator"]["render_file_validation"]["missing_depth_count"] == 0
    assert result["source_labels"]["counts"]["replicator_render_only"] == 2
    assert result["source_labels"]["details"]["replicator_render_only"]["available"] is True
    assert result["source_labels"]["details"]["replicator_render_only"]["train_default"] is False
    assert result["training_exposure"]["source_counts"].get("replicator_render_only", 0) == 0
    preview_cards = preview["source_labels"]["cards"]
    assert any(card["source_type"] == "replicator_render_only" for card in preview_cards)
    replicator_card = next(card for card in preview_cards if card["source_type"] == "replicator_render_only")
    assert replicator_card["rgb_path"].endswith("_v000.png")
    assert replicator_card["train_eligible"] is False


def test_isaac_lab_blocks_large_render_only_object_pose_jitter_without_generated_trajectory(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "pose-mismatch"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    payload = {
        "mode": "test",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "isaac_sim_python": str(isaac_python),
        "stage_path": str(stage),
        "enable_replicator": True,
        "enable_hdf5_export": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
        "cameras": ["top"],
    }
    initial = bridge.isaac_lab_build_synthetic(payload)
    output_root = Path(initial["output_root"])
    replicator_manifest = output_root / "replicator" / "manifest.jsonl"
    replicator_manifest.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": "atr.lerobot.replicator_frame.v1",
        "source_type": "replicator_render_only",
        "episode_index": 0,
        "frame_index": 1,
        "camera": "top",
        "variant_index": 0,
        "rgb_path": "replicator/rgb/top/e000000_f000001_v000.png",
        "depth_path": "replicator/depth/top/e000000_f000001_v000.png",
        "metadata_path": "replicator/metadata/top/e000000_f000001_v000.json",
        "train_eligible": True,
        "train_exclusion_reason": "",
        "action_consistency": {
            "uses_original_action": True,
            "object_pose_changed": True,
            "trainable": True,
            "object_pose_delta": {"xy_m": 0.035, "yaw_rad": 0.25},
            "requires_generated_trajectory": True,
        },
    }
    replicator_manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")
    for key in ("rgb_path", "depth_path", "metadata_path"):
        artifact = output_root / str(row[key])
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"replicator fixture\n")

    blocked = bridge.isaac_lab_build_synthetic(payload)

    assert blocked["ok"] is False
    assert blocked["status"] == "BLOCKED"
    assert blocked["replicator"]["blocker"] == "ACTION_LABEL_MISMATCH_RISK"
    action_validation = blocked["replicator"]["action_consistency_validation"]
    assert action_validation["ok"] is False
    assert action_validation["blocked_row_count"] == 1
    assert action_validation["blocked_rows"][0]["requires_generated_trajectory"] is True
    assert any(blocker["code"] == "ACTION_LABEL_MISMATCH_RISK" for blocker in blocked["validation_report"]["blockers"])

    mimic_successes = output_root / "mimic" / "successes.jsonl"
    mimic_successes.parent.mkdir(parents=True, exist_ok=True)
    mimic_successes.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.generated_trajectory.v1",
                "source_type": "isaac_lab_mimic",
                "trajectory_id": "mimic_pose_match",
                "source_episode_index": 0,
                "source_frame_index": 1,
                "metrics": {"success": True},
                "artifacts": {"hdf5_path": "mimic/generated_dataset.hdf5"},
                "training": {"eligible": True, "fidelity_weight": 0.25},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    allowed = bridge.isaac_lab_build_synthetic({**payload, "enable_mimic": True})

    assert allowed["ok"] is True
    assert allowed["replicator"]["action_consistency_validation"]["ok"] is True
    assert allowed["replicator"]["action_consistency_validation"]["blocked_row_count"] == 0
    assert allowed["source_labels"]["counts"]["isaac_lab_mimic"] == 1
    assert allowed["training_exposure"]["source_counts"]["isaac_lab_synthetic"] == 1


def test_isaac_lab_build_blocks_replicator_manifest_rows_missing_rgb_depth_files(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    payload = {
        "mode": "test",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "isaac_sim_python": str(isaac_python),
        "stage_path": str(stage),
        "enable_replicator": True,
        "enable_hdf5_export": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
        "cameras": ["top"],
        "attempts_per_source_frame": 1,
    }
    initial = bridge.isaac_lab_build_synthetic(payload)
    output_root = Path(initial["output_root"])
    replicator_manifest = output_root / "replicator" / "manifest.jsonl"
    replicator_manifest.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": "atr.lerobot.replicator_frame.v1",
        "source_type": "replicator_render_only",
        "episode_index": 0,
        "frame_index": 0,
        "camera": "top",
        "variant_index": 0,
        "rgb_path": "replicator/rgb/top/e000000_f000000_v000.png",
        "depth_path": "replicator/depth/top/e000000_f000000_v000.png",
        "metadata_path": "replicator/metadata/top/e000000_f000000_v000.json",
        "train_eligible": False,
        "train_exclusion_reason": "render_only_same_pose",
    }
    replicator_manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")

    result = bridge.isaac_lab_build_synthetic(payload)

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert result["replicator"]["status"] == "blocked"
    assert result["replicator"]["blocker"] == "REPLICATOR_OUTPUT_FILES_MISSING"
    assert result["replicator"]["rendered_count"] == 1
    assert result["replicator"]["valid_rendered_count"] == 0
    assert result["replicator"]["render_file_validation"]["row_count"] == 1
    assert result["replicator"]["render_file_validation"]["valid_row_count"] == 0
    assert result["replicator"]["render_file_validation"]["missing_rgb_count"] == 1
    assert result["replicator"]["render_file_validation"]["missing_depth_count"] == 1
    assert result["source_labels"]["counts"]["replicator_render_only"] == 0
    assert any(blocker["code"] == "REPLICATOR_OUTPUT_FILES_MISSING" for blocker in result["validation_report"]["blockers"])


def test_isaac_lab_build_synthetic_writes_index_and_training_import(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")

    result = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "enable_hdf5_export": False,
            "enable_mimic": False,
            "enable_rl_teacher": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
            "real_weight": 0.9,
            "isaac_rgbd_weight": 0.35,
            "replicator_render_weight": 0.25,
            "isaac_lab_synthetic_weight": 0.4,
            "legacy_sidecar_weight": 0.0,
        }
    )

    assert result["ok"] is True
    assert result["tool"] == "lerobot.isaac_lab.build_synthetic"
    assert result["status"] == "READY_FOR_TRAINING"
    output_root = Path(result["output_root"])
    canonical_manifest = output_root / "canonical_episode_index" / "manifest.jsonl"
    dataset_canonical_root = dataset / "sidecar" / "canonical_episode_index" / "latest"
    dataset_canonical_manifest = dataset_canonical_root / "manifest.jsonl"
    dataset_canonical_summary_path = dataset_canonical_root / "summary.json"
    training_manifest = output_root / "training_import" / "manifest.jsonl"
    source_config_path = output_root / "training_import" / "lerobot_source_config.json"
    training_validation_path = output_root / "training_import" / "training_import_validation.json"
    assert canonical_manifest.is_file()
    assert dataset_canonical_manifest.is_file()
    assert dataset_canonical_summary_path.is_file()
    assert training_manifest.is_file()
    assert source_config_path.is_file()
    assert training_validation_path.is_file()
    assert sum(1 for _ in canonical_manifest.open(encoding="utf-8")) == 3
    assert dataset_canonical_manifest.read_text(encoding="utf-8") == canonical_manifest.read_text(encoding="utf-8")
    dataset_canonical_summary = json.loads(dataset_canonical_summary_path.read_text(encoding="utf-8"))
    assert dataset_canonical_summary["frame_count"] == 3
    assert dataset_canonical_summary["manifest_path"] == str(dataset_canonical_manifest)
    assert dataset_canonical_summary["isaac_lab_manifest_path"] == str(canonical_manifest)
    assert result["canonical_episode_index"]["dataset_manifest_path"] == str(dataset_canonical_manifest)
    assert result["canonical_episode_index"]["dataset_summary_path"] == str(dataset_canonical_summary_path)
    canonical_rows = [json.loads(line) for line in canonical_manifest.read_text(encoding="utf-8").splitlines()]
    assert canonical_rows[0]["source_availability"]["raw_depth"] is True
    assert canonical_rows[0]["source_availability"]["real_rgb"] is False
    assert canonical_rows[0]["source_availability"]["isaac_rgbd"] is False
    assert canonical_rows[0]["source_completeness"]["required_missing"] == []
    assert canonical_rows[0]["source_completeness"]["optional_missing"] == [
        "real_rgb",
        "isaac_rgbd",
        "active_robot_cam",
        "grasp_diagnostics",
    ]
    assert canonical_rows[0]["missing_sources"] == [
        "real_rgb",
        "isaac_rgbd",
        "active_robot_cam",
        "grasp_diagnostics",
    ]
    training_rows = [json.loads(line) for line in training_manifest.read_text(encoding="utf-8").splitlines()]
    assert training_rows[0]["source_type"] == "real_lerobot"
    assert training_rows[0]["success"] is True
    assert training_rows[0]["effective_weight"] == 0.9
    source_config = json.loads(source_config_path.read_text(encoding="utf-8"))
    source_labels = json.loads((output_root / "source_labels.json").read_text(encoding="utf-8"))
    assert result["training_exposure"]["source_config_path"] == str(source_config_path)
    assert source_config["weights"]["real_lerobot"] == 0.9
    assert source_config["weights"]["isaac_rgbd_render"] == 0.35
    assert source_config["weights"]["replicator_render_only"] == 0.25
    assert source_config["weights"]["isaac_lab_synthetic"] == 0.4
    assert set(source_labels["counts"]) >= {
        "real_lerobot",
        "isaac_rgbd_render",
        "isaac_teleop_replay_render",
        "isaac_lab_mimic",
        "isaac_lab_rl_teacher",
    }
    assert source_config["train_defaults"]["real_lerobot"]["train_default"] is True
    assert source_config["train_defaults"]["replicator_render_only"]["train_default"] is False
    assert source_labels["details"]["isaac_teleop_replay_render"]["render_only"] is True
    assert source_labels["details"]["isaac_teleop_replay_render"]["train_default"] is False
    assert result["replicator"]["teleop_sdg_replay_boundary"] == "render_only_not_physics_rollout"
    assert source_labels["weights"]["real_lerobot"] == 0.9
    assert source_labels["fidelity_weights"]["replicator_render_only"] == 0.4
    assert source_labels["training_import"]["manifest_path"] == str(training_manifest)
    assert source_labels["training_import"]["source_config_path"] == str(source_config_path)
    assert source_labels["training_import"]["row_count"] == 1
    assert source_labels["training_import"]["candidate_row_count"] == 1
    assert source_labels["training_import"]["train_exposed"] is True
    assert source_labels["details"]["real_lerobot"]["source_weight"] == 0.9
    assert source_labels["details"]["real_lerobot"]["fidelity_weight"] == 1.0
    assert source_labels["details"]["real_lerobot"]["effective_weight"] == 0.9
    assert source_labels["details"]["real_lerobot"]["training_row_count"] == 1
    assert result["source_labels"]["training_import"]["row_count"] == 1
    training_validation = json.loads(training_validation_path.read_text(encoding="utf-8"))
    validation_checks = {check["id"]: check for check in result["validation_report"]["checks"]}
    assert result["training_exposure"]["validation_path"] == str(training_validation_path)
    assert result["training_exposure"]["validation_status"] == "passed"
    assert training_validation["ok"] is True
    assert training_validation["status"] == "passed"
    assert training_validation["row_count"] == 1
    assert training_validation["failed_row_count"] == 0
    assert training_validation["blockers"] == []
    assert validation_checks["validate_canonical_episode_index"]["status"] == "passed"
    assert validation_checks["validate_canonical_episode_index"]["evidence"]["frame_count"] == 3
    assert validation_checks["validate_training_import"]["status"] == "passed"
    assert validation_checks["validate_training_import"]["evidence"]["row_count"] == 1


def test_isaac_lab_canonical_index_derives_grasp_event_labels_from_mirror_diagnostics(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset, total_frames=5)
    _write_mirror_grasp_diagnostics(
        dataset,
        [
            {
                "available": True,
                "status": "closed_not_near_object",
                "near_object": False,
                "contact": False,
                "object_lifted": False,
            },
            {
                "available": True,
                "status": "near_closed_without_contact",
                "near_object": True,
                "contact": False,
                "object_lifted": False,
            },
            {
                "available": True,
                "status": "grasp_candidate",
                "near_object": True,
                "contact": True,
                "object_lifted": False,
            },
            {
                "available": True,
                "status": "grasp_candidate",
                "near_object": True,
                "contact": True,
                "object_lifted": True,
            },
            {
                "available": True,
                "status": "released",
                "near_object": True,
                "contact": False,
                "object_lifted": False,
            },
        ],
    )
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")

    result = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "enable_hdf5_export": False,
            "enable_mimic": False,
            "enable_rl_teacher": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    canonical_manifest = Path(result["output_root"]) / "canonical_episode_index" / "manifest.jsonl"
    rows = [json.loads(line) for line in canonical_manifest.read_text(encoding="utf-8").splitlines()]
    assert [row["grasp_event_label"] for row in rows] == [
        "not_near_object",
        "near_closed_without_contact",
        "grasp_candidate",
        "lifted",
        "released",
    ]
    assert all(row["source_availability"]["grasp_diagnostics"] is True for row in rows)
    assert all("grasp_diagnostics" not in row["missing_sources"] for row in rows)
    assert rows[3]["grasp_diagnostics"]["event_label"] == "lifted"
    assert rows[3]["grasp_diagnostics"]["state"] == "lifted"
    assert rows[3]["grasp_diagnostics"]["source_manifest"].endswith("sidecar/isaac_mirror/lr-record-fixture.jsonl")
    assert rows[3]["grasp_diagnostics"]["sample_index"] == 4


def test_isaac_lab_training_import_excludes_failed_real_episodes(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    (dataset / "meta" / "info.json").write_text(
        json.dumps({"codebase_version": "v2.1", "total_episodes": 2, "total_frames": 6}),
        encoding="utf-8",
    )
    (dataset / "meta" / "episodes.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"episode_index": 0, "tasks": ["Pick up the cube"], "length": 3, "success": False}),
                json.dumps({"episode_index": 1, "tasks": ["Pick up the cube"], "length": 3, "success": True}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (dataset / "data" / "chunk-000" / "episode_000001.parquet").write_bytes(b"PAR1")
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")

    result = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "enable_hdf5_export": False,
            "enable_mimic": False,
            "enable_rl_teacher": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    output_root = Path(result["output_root"])
    canonical_rows = [
        json.loads(line)
        for line in (output_root / "canonical_episode_index" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    training_rows = [
        json.loads(line)
        for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert {row["episode_index"] for row in canonical_rows} == {0, 1}
    assert [row["episode_index"] for row in training_rows] == [1]
    assert result["training_exposure"]["row_count"] == 1
    assert result["training_exposure"]["excluded_failed_episode_count"] == 1
    assert result["training_exposure"]["excluded_failed_episodes"] == [0]


def test_isaac_lab_preview_real_cards_show_train_eligibility(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    (dataset / "meta" / "info.json").write_text(
        json.dumps({"codebase_version": "v2.1", "total_episodes": 2, "total_frames": 6}),
        encoding="utf-8",
    )
    (dataset / "meta" / "episodes.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"episode_index": 0, "tasks": ["Pick up the cube"], "length": 3, "success": False}),
                json.dumps({"episode_index": 1, "tasks": ["Pick up the cube"], "length": 3, "success": True}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    payload = {
        "mode": "test",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "stage_path": str(stage),
        "enable_replicator": False,
        "enable_hdf5_export": False,
        "enable_mimic": False,
        "enable_rl_teacher": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    bridge.isaac_lab_build_synthetic(payload)
    preview = bridge.isaac_lab_preview(payload)

    failed_card = next(card for card in preview["source_labels"]["cards"] if card["episode_index"] == 0)
    successful_card = next(card for card in preview["source_labels"]["cards"] if card["episode_index"] == 1)
    assert failed_card["episode_success"] is False
    assert failed_card["train_eligible"] is False
    assert failed_card["train_exclusion_reason"] == "episode_marked_failed"
    assert successful_card["episode_success"] is True
    assert successful_card["train_eligible"] is True
    assert successful_card["train_exclusion_reason"] == ""
    for card in (failed_card, successful_card):
        assert card["row_id"].startswith("real_lerobot:")
        assert card["camera"] == ""
        assert isinstance(card["qa"], dict)
        assert set(card["media"]) == {
            "real_rgb",
            "raw_depth_preview",
            "isaac_rgbd",
            "replicator_rgb",
            "replicator_depth_preview",
        }
        assert card["trajectory"] == {"available": False, "source": ""}


def test_isaac_lab_preview_works_with_summary_only(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "summary-only"
    _make_dataset(dataset)
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    output_root.mkdir(parents=True)
    (output_root / "summary.json").write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.isaac_lab_synthetic.summary.v1",
                "run_id": "latest",
                "status": "READY_FOR_PREVIEW",
                "dataset_path": str(dataset),
                "output_root": str(output_root),
            }
        ),
        encoding="utf-8",
    )

    preview = bridge.isaac_lab_preview(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "enable_replicator": False,
            "enable_hdf5_export": False,
            "enable_mimic": False,
            "enable_rl_teacher": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    assert preview["ok"] is True
    assert preview["status"] == "READY_FOR_PREVIEW"
    assert preview["source_labels"]["preview_count"] == 0
    assert preview["source_labels"]["cards"] == []
    assert preview["source_labels"]["run_summary"]["status"] == "READY_FOR_PREVIEW"


def test_isaac_lab_build_ingests_successful_generated_trajectory_manifests(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    mimic_successes = output_root / "mimic" / "successes.jsonl"
    rl_successes = output_root / "rl_teacher" / "successes.jsonl"
    mimic_successes.parent.mkdir(parents=True, exist_ok=True)
    rl_successes.parent.mkdir(parents=True, exist_ok=True)
    mimic_successes.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "atr.lerobot.generated_trajectory.v1",
                        "source_type": "isaac_lab_mimic",
                        "trajectory_id": "mimic_000001",
                        "source_episode_index": 0,
                        "source_frame_index": 1,
                        "subtasks": {"approach": {"start_frame": 0, "end_frame": 2}},
                        "metrics": {"success": True, "max_penetration_m": 0.001},
                        "artifacts": {"hdf5_path": "mimic/generated_dataset.hdf5", "preview_path": "mimic/previews/mimic_000001.html"},
                        "training": {"eligible": True, "fidelity_weight": 0.25},
                    }
                ),
                json.dumps(
                    {
                        "schema": "atr.lerobot.generated_trajectory.v1",
                        "source_type": "isaac_lab_mimic",
                        "trajectory_id": "mimic_failed",
                        "metrics": {"success": False},
                        "artifacts": {"hdf5_path": "mimic/generated_dataset.hdf5"},
                        "training": {"eligible": True},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rl_successes.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.generated_trajectory.v1",
                "source_type": "isaac_lab_rl_teacher",
                "trajectory_id": "rl_000001",
                "source_episode_index": 0,
                "source_frame_index": 2,
                "metrics": {"success": True},
                "artifacts": {"hdf5_path": "rl_teacher/generated_dataset.hdf5"},
                "training": {"eligible": True, "fidelity_weight": 0.3},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    payload = {
        "mode": "test",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "stage_path": str(stage),
        "enable_replicator": False,
        "enable_hdf5_export": False,
        "enable_mimic": True,
        "enable_rl_teacher": True,
        "require_physics_pass": False,
        "require_articulation_pass": False,
        "isaac_lab_synthetic_weight": 0.4,
    }

    result = bridge.isaac_lab_build_synthetic(payload)
    preview = bridge.isaac_lab_preview(payload)

    training_rows = [
        json.loads(line)
        for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    source_types = [row["source_type"] for row in training_rows]
    assert result["source_labels"]["counts"]["isaac_lab_mimic"] == 1
    assert result["source_labels"]["counts"]["isaac_lab_rl_teacher"] == 1
    assert source_types == ["real_lerobot", "isaac_lab_synthetic", "isaac_lab_synthetic"]
    assert all(row["source_label"] == row["source_type"] for row in training_rows if row["source_type"] == "real_lerobot")
    assert all(row.get("generation_manifest") for row in training_rows)
    assert all("fidelity_weight" in row for row in training_rows)
    mimic_row = next(row for row in training_rows if row.get("source_label") == "isaac_lab_mimic")
    rl_row = next(row for row in training_rows if row.get("source_label") == "isaac_lab_rl_teacher")
    assert mimic_row["source_id"] == "mimic_000001"
    assert mimic_row["artifact_path"] == "mimic/generated_dataset.hdf5"
    assert mimic_row["source_weight"] == 0.4
    assert mimic_row["fidelity_weight"] == 0.25
    assert mimic_row["effective_weight"] == 0.1
    assert rl_row["source_id"] == "rl_000001"
    assert rl_row["fidelity_weight"] == 0.3
    assert result["training_exposure"]["source_counts"]["isaac_lab_synthetic"] == 2
    mimic_card = next(card for card in preview["source_labels"]["cards"] if card["source_type"] == "isaac_lab_mimic")
    rl_card = next(card for card in preview["source_labels"]["cards"] if card["source_type"] == "isaac_lab_rl_teacher")
    assert mimic_card["train_eligible"] is True
    assert mimic_card["row_id"] == "isaac_lab_mimic:mimic_000001"
    assert mimic_card["trajectory"]["available"] is True
    assert mimic_card["trajectory"]["source"] == "isaac_lab_mimic"
    assert mimic_card["trajectory"]["preview_path"] == "mimic/previews/mimic_000001.html"
    assert isinstance(mimic_card["media"], dict)
    assert rl_card["train_eligible"] is True
    assert rl_card["trajectory"]["available"] is True


def test_isaac_lab_build_keeps_rl_teacher_successes_disabled_by_default(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    rl_successes = output_root / "rl_teacher" / "successes.jsonl"
    rl_successes.parent.mkdir(parents=True, exist_ok=True)
    rl_successes.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.generated_trajectory.v1",
                "source_type": "isaac_lab_rl_teacher",
                "trajectory_id": "rl_000001",
                "metrics": {"success": True},
                "artifacts": {"hdf5_path": "rl_teacher/generated_dataset.hdf5"},
                "training": {"eligible": True, "fidelity_weight": 0.3},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "enable_hdf5_export": False,
            "enable_mimic": False,
            "enable_rl_teacher": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    training_rows = [
        json.loads(line)
        for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result["source_labels"]["counts"]["isaac_lab_rl_teacher"] == 1
    assert result["source_labels"]["details"]["isaac_lab_rl_teacher"]["train_default"] is False
    assert [row["source_type"] for row in training_rows] == ["real_lerobot"]


def test_isaac_lab_build_blocks_when_training_import_validation_fails(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    mimic_successes = output_root / "mimic" / "successes.jsonl"
    mimic_successes.parent.mkdir(parents=True, exist_ok=True)
    mimic_successes.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.generated_trajectory.v1",
                "source_type": "isaac_lab_mimic",
                "trajectory_id": "mimic_missing_artifact",
                "metrics": {"success": True},
                "artifacts": {},
                "training": {"eligible": True, "fidelity_weight": 0.25},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "enable_hdf5_export": False,
            "enable_mimic": True,
            "enable_rl_teacher": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert result["training_exposure"]["validation_status"] == "blocked"
    assert result["training_exposure"]["validation_ok"] is False
    assert result["training_exposure"]["train_exposed"] is False
    assert result["training_exposure"]["blockers"][0]["code"] == "TRAINING_IMPORT_ARTIFACT_PATH_MISSING"
    assert result["training_exposure"]["candidate_row_count"] == 2
    assert result["training_exposure"]["exposed_row_count"] == 0
    assert result["training_exposure"]["row_count"] == 0
    assert result["training_exposure"]["source_counts"] == {}
    assert not (output_root / "training_import" / "manifest.jsonl").exists()
    assert result["source_labels"]["details"]["isaac_lab_mimic"]["count"] == 1
    assert result["source_labels"]["details"]["isaac_lab_mimic"]["trainable_count"] == 0
    assert result["source_labels"]["details"]["isaac_lab_mimic"]["train_default"] is False
    validation_path = output_root / "training_import" / "training_import_validation.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["status"] == "blocked"
    assert validation["blockers"][0]["code"] == "TRAINING_IMPORT_ARTIFACT_PATH_MISSING"

    preview = bridge.isaac_lab_preview(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "enable_mimic": True,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )
    generated_card = next(card for card in preview["source_labels"]["cards"] if card.get("source_id") == "mimic_missing_artifact")
    assert generated_card["train_eligible"] is False
    assert generated_card["train_exclusion_reason"] == "artifact_path_missing"


def test_isaac_lab_training_import_validation_requires_synthetic_traceability_fields(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    request = IsaacLabSyntheticRequest.model_validate(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(tmp_path / "IsaacLab"),
            "stage_path": str(tmp_path / "scene.usda"),
        }
    )
    validation = bridge._isaac_lab_synthetic_pipeline()._training_import_validation(  # noqa: SLF001
        request=request,
        output_root=output_root,
        training_rows=[
            {
                "schema": "atr.lerobot.training_import_row.v1",
                "source_type": "isaac_lab_mimic",
                "source_id": "mimic_legacy_shape",
                "dataset_path": str(dataset),
                "artifact_path": "mimic/generated_dataset.hdf5",
                "episode_index": 0,
                "frame_start": 0,
                "frame_end": 10,
                "success": True,
                "source_weight": 0.25,
                "fidelity_weight": 0.5,
                "effective_weight": 0.125,
                "validation_report": "../validation_report.json",
            }
        ],
    )

    assert validation["ok"] is False
    assert validation["status"] == "blocked"
    assert {blocker["code"] for blocker in validation["blockers"]} == {
        "TRAINING_IMPORT_TRACEABILITY_FIELDS_MISSING",
        "TRAINING_IMPORT_SYNTHETIC_SOURCE_TYPE_INVALID",
    }
    assert validation["missing_traceability_count"] == 1
    assert validation["synthetic_source_mismatch_count"] == 1
    assert {"id": "traceability_fields_present", "status": "blocked"} in validation["checks"]
    assert {"id": "isaac_lab_synthetic_source_type", "status": "blocked"} in validation["checks"]


def test_isaac_lab_preview_only_removes_stale_training_import_manifest(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    base_payload = {
        "mode": "test",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "stage_path": str(stage),
        "enable_replicator": False,
        "enable_hdf5_export": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }
    first = bridge.isaac_lab_build_synthetic({**base_payload, "source_intent": "train_ready_success_only"})
    output_root = Path(first["output_root"])
    training_manifest = output_root / "training_import" / "manifest.jsonl"
    training_validation_path = output_root / "training_import" / "training_import_validation.json"
    assert training_manifest.is_file()

    preview = bridge.isaac_lab_build_synthetic({**base_payload, "source_intent": "preview_only"})

    assert preview["ok"] is True
    assert preview["status"] == "READY_FOR_PREVIEW"
    assert preview["training_exposure"]["row_count"] == 0
    assert preview["training_exposure"]["validation_status"] == "skipped"
    assert not training_manifest.exists()
    training_validation = json.loads(training_validation_path.read_text(encoding="utf-8"))
    assert training_validation["ok"] is True
    assert training_validation["status"] == "skipped"
    assert training_validation["train_exposed"] is False
    assert training_validation["manifest_exists"] is False


def test_isaac_lab_export_hdf5_writes_successful_real_episode_in_frame_order(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    _write_mirror_grasp_diagnostics(
        dataset,
        [
            {"available": True, "status": "closed_not_near_object", "near_object": False},
            {"available": True, "status": "near_closed_without_contact", "near_object": True},
            {"available": True, "status": "grasp_candidate", "near_object": True, "contact": True, "object_lifted": True},
        ],
    )
    _write_episode_parquet(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    build = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )
    output_root = Path(build["output_root"])

    result = bridge.isaac_lab_export_hdf5(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    hdf5_path = output_root / "hdf5" / "exported_successful_real_episodes.hdf5"
    assert result["ok"] is True
    assert result["status"] == "READY_FOR_HDF5"
    assert result["hdf5"]["ok"] is True
    assert result["hdf5"]["hdf5_available"] is True
    assert result["hdf5"]["exported_episode_count"] == 1
    assert result["hdf5"]["canonical_frame_count"] == 3
    assert result["hdf5"]["skipped_episodes"] == []
    validation_checks = {check["id"]: check for check in result["validation_report"]["checks"]}
    assert validation_checks["validate_hdf5_export"]["status"] == "passed"
    assert validation_checks["validate_hdf5_export"]["evidence"]["exported_frame_count"] == 3
    assert hdf5_path.is_file()
    with h5py.File(hdf5_path, "r") as handle:
        demo = handle["data"]["demo_000000"]
        assert demo.attrs["episode_index"] == 0
        assert demo.attrs["num_samples"] == 3
        assert demo["actions"][:].tolist() == [[1.0, 1.1, 1.2], [2.0, 2.1, 2.2], [3.0, 3.1, 3.2]]
        assert demo["states"][:].tolist() == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        assert demo["frame_indices"][:].tolist() == [0, 1, 2]
        canonical = demo["canonical"]
        assert canonical.attrs["schema"] == "atr.lerobot.canonical_episode_hdf5_sidecar.v1"
        assert canonical["source_availability"]["raw_depth"][:].tolist() == [True, True, True]
        assert canonical["source_availability"]["grasp_diagnostics"][:].tolist() == [True, True, True]
        labels = [item.decode() if isinstance(item, bytes) else str(item) for item in canonical["grasp_event_labels"][:]]
        assert labels == ["not_near_object", "near_closed_without_contact", "lifted"]
        missing_sources = [item.decode() if isinstance(item, bytes) else str(item) for item in canonical["missing_sources"][:]]
        assert "grasp_diagnostics" not in missing_sources[0]
        assert "real_rgb" in missing_sources[0]
    status = bridge.isaac_lab_status(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
        }
    )
    assert status["hdf5"]["ok"] is True
    assert status["hdf5"]["output_path"] == str(hdf5_path)


def test_isaac_lab_export_hdf5_skips_failed_real_episodes(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    (dataset / "meta" / "info.json").write_text(
        json.dumps({"codebase_version": "v2.1", "total_episodes": 2, "total_frames": 6}),
        encoding="utf-8",
    )
    (dataset / "meta" / "episodes.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"episode_index": 0, "tasks": ["Pick up the cube"], "length": 3, "success": False}),
                json.dumps({"episode_index": 1, "tasks": ["Pick up the cube"], "length": 3, "success": True}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for episode_index in (0, 1):
        table = pa.table(
            {
                "episode_index": pa.array([episode_index, episode_index, episode_index], type=pa.int64()),
                "frame_index": pa.array([0, 1, 2], type=pa.int64()),
                "timestamp": pa.array([0.0, 1.0 / 15.0, 2.0 / 15.0], type=pa.float64()),
                "observation.state": pa.array(
                    [[episode_index, 0.2], [episode_index, 0.4], [episode_index, 0.6]],
                    type=pa.list_(pa.float64()),
                ),
                "action": pa.array(
                    [[episode_index, 1.1, 1.2], [episode_index, 2.1, 2.2], [episode_index, 3.1, 3.2]],
                    type=pa.list_(pa.float64()),
                ),
            }
        )
        pq.write_table(table, dataset / "data" / "chunk-000" / f"episode_{episode_index:06d}.parquet")
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    payload = {
        "mode": "test",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "stage_path": str(stage),
        "enable_replicator": False,
        "enable_hdf5_export": True,
        "enable_mimic": False,
        "enable_rl_teacher": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    bridge.isaac_lab_build_synthetic(payload)
    result = bridge.isaac_lab_export_hdf5(payload)

    hdf5_path = Path(result["hdf5"]["output_path"])
    assert result["hdf5"]["exported_episode_count"] == 1
    assert result["hdf5"]["exported_frame_count"] == 3
    assert result["hdf5"]["skipped_episodes"] == [{"episode_index": 0, "reason": "EPISODE_MARKED_FAILED"}]
    with h5py.File(hdf5_path, "r") as handle:
        assert sorted(handle["data"].keys()) == ["demo_000001"]


def test_isaac_lab_export_hdf5_blocks_invalid_episode_parquet(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    build = bridge.isaac_lab_build_synthetic(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )
    output_root = Path(build["output_root"])

    result = bridge.isaac_lab_export_hdf5(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert result["hdf5"]["ok"] is False
    assert result["hdf5"]["blocker"] == "HDF5_EXPORT_PARQUET_READ_FAILED"
    assert result["hdf5"]["canonical_frame_count"] == 3
    assert result["hdf5"]["skipped_episodes"][0]["reason"] == "PARQUET_READ_FAILED"
    assert (output_root / "hdf5" / "export_summary.json").is_file()
    assert not (output_root / "hdf5" / "exported_successful_real_episodes.hdf5").exists()

    status = bridge.isaac_lab_status(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
        }
    )

    assert status["hdf5"]["blocker"] == "HDF5_EXPORT_PARQUET_READ_FAILED"
    assert status["hdf5"]["canonical_frame_count"] == 3


def test_isaac_lab_mimic_and_rl_hooks_track_hdf5_readiness(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    _write_episode_parquet(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    payload = {
        "mode": "test",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "stage_path": str(stage),
        "enable_replicator": False,
        "enable_mimic": True,
        "enable_rl_teacher": True,
        "mimic_trials": 10,
        "rl_teacher_steps": 32,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    build = bridge.isaac_lab_build_synthetic(payload)

    output_root = Path(build["output_root"])
    assert build["ok"] is True
    assert build["mimic"]["status"] == "blocked"
    assert build["mimic"]["blocker"] == "MIMIC_HDF5_EXPORT_MISSING"
    assert build["mimic"]["required_subtasks"] == ["approach", "grasp", "lift", "place", "release"]
    assert build["rl_teacher"]["status"] == "blocked"
    assert build["rl_teacher"]["blocker"] == "RL_TEACHER_HDF5_EXPORT_MISSING"
    assert (output_root / "mimic" / "summary.json").is_file()
    assert (output_root / "rl_teacher" / "summary.json").is_file()

    export = bridge.isaac_lab_export_hdf5(payload)
    env_manifest_path = output_root / "lab_env" / "robotis_omx_pick_place_env.json"
    event_config_path = output_root / "lab_env" / "domain_randomization_events.json"
    env_manifest = json.loads(env_manifest_path.read_text(encoding="utf-8"))
    event_config = json.loads(event_config_path.read_text(encoding="utf-8"))

    assert export["ok"] is True
    assert export["mimic"]["status"] == "ready"
    assert export["mimic"]["hdf5_path"] == export["hdf5"]["output_path"]
    assert export["mimic"]["env_wrapper"]["status"] == "ready"
    assert export["mimic"]["env_wrapper"]["manifest_path"] == str(env_manifest_path)
    assert export["mimic"]["env_wrapper"]["required_helpers"] == [
        "get_robot_eef_pose",
        "target_eef_pose_to_action",
        "action_to_target_eef_pose",
        "actions_to_gripper_actions",
        "get_object_poses",
        "get_subtask_term_signals",
    ]
    assert export["mimic"]["mimic_trials"] == 10
    assert export["mimic"]["mimic_num_envs"] == 1
    assert export["rl_teacher"]["status"] == "ready"
    assert export["rl_teacher"]["hdf5_path"] == export["hdf5"]["output_path"]
    assert export["rl_teacher"]["env_wrapper"]["status"] == "ready"
    assert export["rl_teacher"]["env_wrapper"]["manifest_path"] == str(env_manifest_path)
    assert export["rl_teacher"]["rl_teacher_steps"] == 32
    assert env_manifest["schema"] == "atr.lerobot.isaac_lab_omx_env_wrapper.v1"
    assert env_manifest["task_name"] == "RobotisOMXPickPlaceLabEnv"
    assert env_manifest["object_pose_contract"]["frame"] == "robot_base"
    assert env_manifest["action_space"]["control_mode"] == "eef_delta_pose_plus_gripper"
    assert env_manifest["gripper_action"]["source"] == "canonical_grasp_event_labels"
    assert env_manifest["subtask_termination_signals"] == ["approach", "grasp", "lift", "place", "release"]
    assert {term["id"] for term in env_manifest["reward_terms"]} == {
        "reach_object",
        "grasp_candidate",
        "lift_object",
        "place_object",
        "safety_limits",
    }
    assert env_manifest["reset_events"]["object_pose_randomization"]["workspace"] == "a4_sheet"
    assert env_manifest["domain_randomization_events_path"] == str(event_config_path)
    assert event_config["schema"] == "atr.lerobot.isaac_lab_domain_randomization_events.v1"
    assert event_config["owner"] == "isaac_lab_reset_events"
    assert [event["name"] for event in event_config["events"]] == [
        "randomize_cube_pose_a4",
        "randomize_physics_materials",
        "randomize_camera_pose",
        "randomize_rgbd_sensor_noise",
    ]
    assert event_config["events"][0]["params"]["workspace"] == "a4_sheet"
    assert event_config["events"][0]["params"]["attempts_per_source_frame"] == 1
    assert event_config["events"][1]["params"]["strength"] == 0.15
    assert event_config["events"][2]["params"]["cameras"] == ["top", "front", "right"]
    assert event_config["events"][3]["params"]["depth_strength"] == 0.15

    status = bridge.isaac_lab_status(payload)

    assert status["mimic"]["status"] == "ready"
    assert status["rl_teacher"]["status"] == "ready"
    mimic_config = json.loads((output_root / "mimic" / "config.json").read_text(encoding="utf-8"))
    rl_config = json.loads((output_root / "rl_teacher" / "config.json").read_text(encoding="utf-8"))
    assert mimic_config["parameters"]["env_wrapper_manifest"] == str(env_manifest_path)
    assert rl_config["parameters"]["env_wrapper_manifest"] == str(env_manifest_path)


def test_isaac_lab_mimic_and_rl_smoke_actions_write_launch_artifacts(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    _write_episode_parquet(dataset)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    payload = {
        "mode": "test",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "stage_path": str(stage),
        "enable_replicator": False,
        "mimic_trials": 8,
        "mimic_num_envs": 2,
        "rl_teacher_steps": 32,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    build = bridge.isaac_lab_build_synthetic(payload)
    blocked = bridge.isaac_lab_run_mimic_smoke(payload)

    output_root = Path(build["output_root"])
    assert blocked["ok"] is False
    assert blocked["tool"] == "lerobot.isaac_lab.run_mimic_smoke"
    assert blocked["mimic"]["status"] == "blocked"
    assert blocked["mimic"]["blocker"] == "MIMIC_HDF5_EXPORT_MISSING"
    assert not (output_root / "mimic" / "smoke_summary.json").exists()

    bridge.isaac_lab_export_hdf5(payload)
    mimic = bridge.isaac_lab_run_mimic_smoke(payload)
    rl = bridge.isaac_lab_run_rl_teacher_smoke(payload)

    assert mimic["ok"] is True
    assert mimic["mimic"]["status"] == "ready"
    assert mimic["mimic"]["smoke"]["status"] == "ready_to_launch"
    assert mimic["mimic"]["smoke"]["dry_run"] is True
    assert mimic["mimic"]["smoke"]["mimic_trials"] == 8
    assert mimic["mimic"]["smoke"]["env_wrapper_manifest"].endswith("lab_env/robotis_omx_pick_place_env.json")
    assert mimic["mimic"]["smoke"]["command_preview"]["env_wrapper"].endswith("lab_env/robotis_omx_pick_place_env.json")
    assert mimic["mimic"]["smoke"]["runtime_smoke"]["contact_smoke"]["status"] == "ready_to_launch"
    assert mimic["mimic"]["smoke"]["runtime_smoke"]["dof_smoke"]["status"] == "ready_to_launch"
    assert mimic["mimic"]["smoke"]["runtime_smoke"]["contact_smoke"]["command_preview"]["operation"] == "contact_smoke"
    assert mimic["mimic"]["smoke"]["runtime_smoke"]["dof_smoke"]["command_preview"]["operation"] == "dof_smoke"
    assert (output_root / "mimic" / "smoke_summary.json").is_file()
    assert (output_root / "runtime_smoke" / "contact_smoke.json").is_file()
    assert (output_root / "runtime_smoke" / "dof_smoke.json").is_file()
    contact_smoke = json.loads((output_root / "runtime_smoke" / "contact_smoke.json").read_text(encoding="utf-8"))
    dof_smoke = json.loads((output_root / "runtime_smoke" / "dof_smoke.json").read_text(encoding="utf-8"))
    assert contact_smoke["schema"] == "atr.lerobot.isaac_lab_runtime.contact_smoke.v1"
    assert contact_smoke["contact_pairs_required"] == ["left_finger:red_cube", "right_finger:red_cube"]
    assert contact_smoke["contact_threshold_n"] == 0.2
    assert dof_smoke["schema"] == "atr.lerobot.isaac_lab_runtime.dof_smoke.v1"
    assert dof_smoke["checks"] == [
        "articulation_root_loads",
        "joint_names_match_lerobot_actions",
        "drive_targets_match_current_pose",
        "mimic_gear_direction_valid",
    ]
    mimic_candidates = [
        json.loads(line)
        for line in (output_root / "mimic" / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    mimic_successes = [
        json.loads(line)
        for line in (output_root / "mimic" / "successes.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    mimic_failures = [
        json.loads(line)
        for line in (output_root / "mimic" / "failures.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(mimic_candidates) == 8
    assert len(mimic_successes) >= 1
    assert len(mimic_failures) >= 1
    assert all(row["metrics"]["success"] is True for row in mimic_successes)
    assert all(row["metrics"]["success"] is False for row in mimic_failures)
    assert mimic["mimic"]["candidate_count"] == len(mimic_candidates)
    assert mimic["mimic"]["success_count"] == len(mimic_successes)
    assert mimic["mimic"]["failure_count"] == len(mimic_failures)
    assert mimic["synthetic_trajectory_metrics"]["mimic"]["candidate_count"] == len(mimic_candidates)
    assert mimic["synthetic_trajectory_metrics"]["mimic"]["success_count"] == len(mimic_successes)
    assert mimic["synthetic_trajectory_metrics"]["mimic"]["failure_count"] == len(mimic_failures)
    mimic_hdf5 = output_root / "mimic" / "generated_dataset.hdf5"
    mimic_small_hdf5 = output_root / "mimic" / "generated_dataset_small.hdf5"
    assert mimic_hdf5.is_file()
    assert mimic_small_hdf5.is_file()
    with h5py.File(mimic_hdf5, "r") as h5:
        assert h5.attrs["schema"] == "atr.lerobot.generated_trajectory_hdf5.v1"
        assert h5.attrs["source_type"] == "isaac_lab_mimic"
        assert h5.attrs["success_count"] == len(mimic_successes)
        assert set(h5["data"].keys()) == {row["trajectory_id"] for row in mimic_successes}
        first = h5["data"][mimic_successes[0]["trajectory_id"]]
        assert bool(first.attrs["success"]) is True
        assert first.attrs["source_type"] == "isaac_lab_mimic"
        assert "actions" in first
        assert "states" in first
        assert "object_pose_randomization" in first
    assert rl["ok"] is True
    assert rl["rl_teacher"]["status"] == "ready"
    assert rl["rl_teacher"]["smoke"]["status"] == "ready_to_launch"
    assert rl["rl_teacher"]["smoke"]["dry_run"] is True
    assert rl["rl_teacher"]["smoke"]["rl_teacher_steps"] == 32
    assert rl["rl_teacher"]["smoke"]["env_wrapper_manifest"].endswith("lab_env/robotis_omx_pick_place_env.json")
    assert rl["rl_teacher"]["smoke"]["command_preview"]["env_wrapper"].endswith("lab_env/robotis_omx_pick_place_env.json")
    assert rl["rl_teacher"]["smoke"]["runtime_smoke"]["contact_smoke"]["path"].endswith("runtime_smoke/contact_smoke.json")
    assert rl["rl_teacher"]["smoke"]["runtime_smoke"]["dof_smoke"]["path"].endswith("runtime_smoke/dof_smoke.json")
    assert (output_root / "rl_teacher" / "smoke_summary.json").is_file()
    rl_successes = [
        json.loads(line)
        for line in (output_root / "rl_teacher" / "successes.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rl_successes) == 1
    assert rl["rl_teacher"]["success_count"] == 1
    assert rl["synthetic_trajectory_metrics"]["rl_teacher"]["success_count"] == 1
    rl_hdf5 = output_root / "rl_teacher" / "generated_dataset.hdf5"
    assert rl_hdf5.is_file()
    with h5py.File(rl_hdf5, "r") as h5:
        assert h5.attrs["schema"] == "atr.lerobot.generated_trajectory_hdf5.v1"
        assert h5.attrs["source_type"] == "isaac_lab_rl_teacher"
        assert h5.attrs["success_count"] == len(rl_successes)
        assert set(h5["data"].keys()) == {row["trajectory_id"] for row in rl_successes}

    rebuilt = bridge.isaac_lab_build_synthetic({**payload, "enable_mimic": True, "enable_rl_teacher": True})
    training_rows = [
        json.loads(line)
        for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    synthetic_rows = [row for row in training_rows if row["source_type"] == "isaac_lab_synthetic"]
    assert rebuilt["source_labels"]["counts"]["isaac_lab_mimic"] == len(mimic_successes)
    assert rebuilt["source_labels"]["counts"]["isaac_lab_rl_teacher"] == len(rl_successes)
    assert len(synthetic_rows) == len(mimic_successes) + len(rl_successes)
    assert all(row["success"] is True for row in synthetic_rows)
    assert {row["source_label"] for row in synthetic_rows} == {"isaac_lab_mimic", "isaac_lab_rl_teacher"}
    assert all((output_root / row["artifact_path"]).is_file() for row in synthetic_rows)
    metrics = rebuilt["synthetic_trajectory_metrics"]
    assert metrics["total"]["candidate_count"] == len(mimic_candidates) + len(rl_successes)
    assert metrics["total"]["success_count"] == len(mimic_successes) + len(rl_successes)
    assert metrics["total"]["failure_count"] == len(mimic_failures)
    assert metrics["total"]["training_row_count"] == len(synthetic_rows)
    assert metrics["total"]["effective_training_samples"] == round(
        sum(row["effective_weight"] for row in synthetic_rows),
        6,
    )
