"""Tests for the LeRobot Isaac Lab synthetic pipeline contracts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import h5py
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

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


def _write_mirror_joint_targets(path: Path, targets_by_frame: list[list[float]]) -> None:
    mirror_dir = path / "sidecar" / "isaac_mirror"
    mirror_dir.mkdir(parents=True, exist_ok=True)
    joint_names = ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper"]
    rows = []
    for frame_index, targets in enumerate(targets_by_frame):
        rows.append(
            {
                "schema": "atr.lerobot.isaac_mirror.sample.v1",
                "episode_index": 0,
                "record_episode_index": 0,
                "sample_index": frame_index + 1,
                "render_queue": {"episode_index": 0, "frame_index": frame_index},
                "joint_state": [
                    {
                        "motor_id": 11 + index,
                        "motor_name": f"joint_{index + 1}",
                        "isaac_joint_name": joint_names[index],
                        "target_value": value,
                        "source_value": value + 100.0,
                        "unit": "deg" if index < 5 else "percent",
                    }
                    for index, value in enumerate(targets)
                ],
            }
        )
    (mirror_dir / "lr-record-targets.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_isaac_rgbd_render_queue_with_specimen_pose(
    path: Path,
    *,
    attempt_id: str = "attempt_post",
    position_mm: tuple[float, float, float] = (417.0, 311.0, 15.2),
    yaw_deg: float = -22.9,
) -> Path:
    mirror_dir = path / "sidecar" / "isaac_mirror"
    output_dir = path / "sidecar" / "isaac_rgbd" / "episode_000" / attempt_id
    specimen_pose_path = path / "sidecar" / "attempts" / "episode_000" / attempt_id / "specimen_pose.json"
    specimen_pose_path.parent.mkdir(parents=True, exist_ok=True)
    specimen_pose_path.write_text(
        json.dumps(
            {
                "ok": True,
                "source": "record_attempt_specimen_pose",
                "pose": {
                    "schema": "specimen_pose.v1",
                    "position_isaac_world_mm": {
                        "x": position_mm[0],
                        "y": position_mm[1],
                        "z": position_mm[2],
                    },
                    "orientation_deg": {"yaw": yaw_deg},
                },
            }
        ),
        encoding="utf-8",
    )
    mirror_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for frame_index, sample_index in [(0, 1), (1, 2), (2, 3)]:
        request = {
            "schema": "atr.isaac_rgbd.render_request.v1",
            "enabled": True,
            "session_id": "record-one",
            "attempt_id": attempt_id,
            "episode_index": 0,
            "frame_index": frame_index,
            "sample_index": sample_index,
            "target_fps": 15.0,
            "cameras": ["top", "front", "right"],
            "output_dir": str(output_dir),
        }
        rows.append(
            {
                "schema": "atr.lerobot.isaac_mirror.sample.v1",
                "session_id": "record-one",
                "episode_index": 0,
                "record_episode_index": 0,
                "sample_index": sample_index,
                "joint_state": [],
                "render_queue": {
                    "status": "deferred_after_record",
                    "attempt_id": attempt_id,
                    "episode_index": 0,
                    "frame_index": frame_index,
                    "sample_index": sample_index,
                    "endpoint": "http://127.0.0.1:8766/render",
                    "render_request": request,
                },
            }
        )
    (mirror_dir / "lr-record-render-queue.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return specimen_pose_path


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


def _make_multi_episode_dataset(path: Path, *, episode_count: int = 2, frames_per_episode: int = 3) -> None:
    (path / "meta").mkdir(parents=True, exist_ok=True)
    (path / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (path / "meta" / "info.json").write_text(
        json.dumps(
            {
                "codebase_version": "v2.1",
                "total_episodes": episode_count,
                "total_frames": episode_count * frames_per_episode,
                "fps": 15,
            }
        ),
        encoding="utf-8",
    )
    (path / "meta" / "tasks.jsonl").write_text(
        json.dumps({"task_index": 0, "task": "Pick up the cube"}) + "\n",
        encoding="utf-8",
    )
    (path / "meta" / "episodes.jsonl").write_text(
        "".join(
            json.dumps({"episode_index": index, "tasks": ["Pick up the cube"], "length": frames_per_episode}) + "\n"
            for index in range(episode_count)
        ),
        encoding="utf-8",
    )
    for episode_index in range(episode_count):
        base = float(episode_index)
        table = pa.table(
            {
                "episode_index": pa.array([episode_index] * frames_per_episode, type=pa.int64()),
                "frame_index": pa.array(list(range(frames_per_episode)), type=pa.int64()),
                "timestamp": pa.array([index / 15.0 for index in range(frames_per_episode)], type=pa.float64()),
                "observation.state": pa.array(
                    [[base + 0.1 + index, base + 0.2 + index] for index in range(frames_per_episode)],
                    type=pa.list_(pa.float64()),
                ),
                "action": pa.array(
                    [[base + 1.0 + index, base + 1.1 + index, base + 1.2 + index] for index in range(frames_per_episode)],
                    type=pa.list_(pa.float64()),
                ),
            }
        )
        pq.write_table(table, path / "data" / "chunk-000" / f"episode_{episode_index:06d}.parquet")
    depth_dir = path / "sidecar" / "depth_raw"
    depth_dir.mkdir(parents=True, exist_ok=True)
    (depth_dir / "transform_manifest.json").write_text(
        json.dumps({"camera_keys": ["top", "wrist"], "depth_encoding": "png16", "depth_scale_m_per_unit": 0.001}),
        encoding="utf-8",
    )


def _write_isaac_rgbd_render_frames(path: Path, *, cameras: tuple[str, ...] = ("top", "front", "right")) -> None:
    render_dir = path / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_visual"
    rows = []
    for frame_index in range(3):
        files = []
        for camera_index, camera in enumerate(cameras):
            rgb_path = render_dir / camera / f"frame_{frame_index:06d}_rgb.png"
            depth_path = render_dir / camera / f"frame_{frame_index:06d}_depth.png"
            rgb = np.full((4, 4, 3), [40 + frame_index, 80 + camera_index, 120], dtype=np.uint8)
            depth = np.full((4, 4), 300 + frame_index + camera_index, dtype=np.uint16)
            rgb_path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgb, mode="RGB").save(rgb_path)
            Image.fromarray(depth).save(depth_path)
            files.extend(
                [
                    {
                        "camera": camera,
                        "kind": "rgb",
                        "path": str(rgb_path),
                        "encoding": "png",
                    },
                    {
                        "camera": camera,
                        "kind": "depth",
                        "path": str(depth_path),
                        "encoding": "png16",
                        "unit": "raw_uint16",
                        "depth_scale_m_per_unit": 0.001,
                    },
                ]
            )
        rows.append(
            {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "episode_index": 0,
                "frame_index": frame_index,
                "depth_scale_m_per_unit": 0.001,
                "files": files,
            }
        )
    (render_dir / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _write_partial_isaac_rgbd_render_frames_with_npy_depth(
    path: Path,
    *,
    cameras: tuple[str, ...] = ("top", "front", "right"),
) -> None:
    render_dir = path / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_visual"
    rows = []
    for frame_index in (0, 2):
        files = []
        for camera_index, camera in enumerate(cameras):
            rgb_path = render_dir / camera / f"frame_{frame_index:06d}_rgb.png"
            depth_path = render_dir / camera / f"frame_{frame_index:06d}_depth_m.npy"
            rgb = np.full((4, 4, 3), [30 + frame_index, 70 + camera_index, 110], dtype=np.uint8)
            depth = np.full((4, 4), 0.40 + (frame_index * 0.01) + (camera_index * 0.001), dtype=np.float32)
            rgb_path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgb, mode="RGB").save(rgb_path)
            np.save(depth_path, depth)
            files.extend(
                [
                    {
                        "camera": camera,
                        "kind": "rgb",
                        "path": str(rgb_path),
                        "encoding": "png",
                    },
                    {
                        "camera": camera,
                        "kind": "depth_m",
                        "path": str(depth_path),
                        "encoding": "npy",
                        "unit": "m",
                    },
                ]
            )
        rows.append(
            {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "episode_index": 0,
                "frame_index": frame_index,
                "depth_scale_m_per_unit": 1.0,
                "files": files,
            }
        )
    (render_dir / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_isaac_lab_synthetic_request_defaults() -> None:
    request = IsaacLabSyntheticRequest.model_validate({"dataset_path": "/tmp/demo"})

    assert request.pipeline_mode == IsaacSyntheticPipelineMode.ISAAC_LAB_REPLICATOR
    assert request.fallback_policy == IsaacSyntheticFallbackPolicy.BLOCK_ON_PRIMARY_FAILURE
    assert request.source_intent == IsaacSyntheticSourceIntent.TRAIN_READY_SUCCESS_ONLY
    assert request.cameras == ["top", "front", "right"]
    assert request.mimic_trials == 10
    assert request.mimic_num_envs == 10
    assert request.mimic_enable_cameras is True
    assert request.domain_randomization_profile == "standard"
    assert request.real_weight == 1.0
    assert request.isaac_rgbd_weight == 0.6
    assert request.isaac_lab_synthetic_weight == 0.35
    assert request.legacy_sidecar_weight == 0.0


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


def test_isaac_lab_build_can_request_visual_replicator_generation(tmp_path: Path) -> None:
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
            "require_physics_pass": False,
            "require_articulation_pass": False,
            "isaac_lab_visualize_generation": True,
        }
    )

    output_root = Path(result["output_root"])
    build_plan = json.loads((output_root / "replicator" / "build_plan.json").read_text(encoding="utf-8"))

    assert result["replicator"]["visualization"]["enabled"] is True
    assert result["replicator"]["visualization"]["headless"] is False
    assert build_plan["worker"]["visualization"]["enabled"] is True
    assert build_plan["worker"]["visualization"]["headless"] is False
    assert "--visualize-generation" in build_plan["worker"]["command"]


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


def test_isaac_lab_training_import_exposes_isaac_rgbd_render_rows_for_vla_mix(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset)
    _write_isaac_rgbd_render_frames(dataset, cameras=("top", "front", "right"))
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
            "real_weight": 1.0,
            "isaac_rgbd_weight": 0.35,
        }
    )

    output_root = Path(result["output_root"])
    training_rows = [
        json.loads(line)
        for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    source_types = [row["source_type"] for row in training_rows]
    assert source_types == ["real_lerobot", "isaac_rgbd_render"]
    rgbd_row = training_rows[1]
    assert rgbd_row["source_label"] == "isaac_rgbd_render"
    assert rgbd_row["source_id"] == "isaac_rgbd_episode_000000"
    assert rgbd_row["artifact_path"] == "sidecar/isaac_rgbd"
    assert rgbd_row["episode_index"] == 0
    assert rgbd_row["frame_start"] == 0
    assert rgbd_row["frame_end"] == 2
    assert rgbd_row["render_frame_count"] == 3
    assert rgbd_row["cameras"] == ["front", "right", "top"]
    assert rgbd_row["source_weight"] == 0.35
    assert rgbd_row["fidelity_weight"] == 0.35
    assert rgbd_row["effective_weight"] == 0.1225
    assert result["training_exposure"]["source_counts"]["isaac_rgbd_render"] == 1


def test_isaac_lab_build_default_does_not_truncate_recorded_episodes(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "demo"
    _make_dataset(dataset, total_frames=300)
    (dataset / "meta" / "info.json").write_text(
        json.dumps({"codebase_version": "v2.1", "total_episodes": 2, "total_frames": 300}),
        encoding="utf-8",
    )
    (dataset / "meta" / "episodes.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"episode_index": 0, "tasks": ["Pick up the cube"], "length": 150}),
                json.dumps({"episode_index": 1, "tasks": ["Pick up the cube"], "length": 150}),
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

    assert result["canonical_episode_index"]["frame_count"] == 300
    assert result["training_exposure"]["source_counts"]["real_lerobot"] == 2
    output_root = Path(result["output_root"])
    training_rows = [
        json.loads(line)
        for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["episode_index"] for row in training_rows] == [0, 1]


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


def test_isaac_lab_training_import_excludes_contact_flagged_episodes(tmp_path: Path) -> None:
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
                json.dumps({"episode_index": 0, "tasks": ["Pick up the cube"], "length": 3, "success": True}),
                json.dumps({"episode_index": 1, "tasks": ["Pick up the cube"], "length": 3, "success": True}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (dataset / "data" / "chunk-000" / "episode_000001.parquet").write_bytes(b"PAR1")
    _write_isaac_rgbd_render_frames(dataset, cameras=("top", "front", "right"))
    exclusion_path = dataset / "sidecar" / "train_exclusions" / "contact_audit.json"
    exclusion_path.parent.mkdir(parents=True, exist_ok=True)
    exclusion_path.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.training_exclusions.contact_audit.v1",
                "policy": "exclude_severe_contact_episodes",
                "source": "isaac_rgbd_contact_audit",
                "episode_indices": [0],
                "episode_count": 1,
                "original_data_preserved": True,
            }
        ),
        encoding="utf-8",
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
            "dataset_exclude_flagged_episodes": True,
        }
    )

    output_root = Path(result["output_root"])
    training_rows = [
        json.loads(line)
        for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert [row["source_type"] for row in training_rows] == ["real_lerobot", "real_lerobot"]
    assert [row["episode_index"] for row in training_rows] == [0, 1]
    assert result["training_exposure"]["excluded_flagged_episode_count"] == 1
    assert result["training_exposure"]["excluded_flagged_episodes"] == [0]
    assert result["training_exposure"]["exclusion_manifest_path"] == str(exclusion_path)


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


def test_isaac_lab_training_import_preserves_joint_replay_demo_episode_and_frame_range(tmp_path: Path) -> None:
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
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                        "source_type": "isaac_lab_mimic",
                        "trajectory_id": "joint_replay_000000",
                        "episode_index": 0,
                        "generated_demo": "demo_000000",
                        "frame_count": 150,
                        "metrics": {"success": True, "joint_replay": True, "lab_step_replay": True},
                        "artifacts": {"hdf5_path": "mimic/generated_dataset.hdf5"},
                        "training": {"eligible": True, "fidelity_weight": 1.0},
                    }
                ),
                json.dumps(
                    {
                        "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                        "source_type": "isaac_lab_mimic",
                        "trajectory_id": "joint_replay_000001",
                        "episode_index": 1,
                        "generated_demo": "demo_000001",
                        "frame_count": 150,
                        "metrics": {"success": True, "joint_replay": True, "lab_step_replay": True},
                        "artifacts": {"hdf5_path": "mimic/generated_dataset.hdf5"},
                        "training": {"eligible": True, "fidelity_weight": 1.0},
                    }
                ),
                json.dumps(
                    {
                        "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                        "source_type": "isaac_lab_mimic",
                        "trajectory_id": "joint_plan_only_000002",
                        "episode_index": 2,
                        "generated_demo": "demo_000002",
                        "frame_count": 150,
                        "metrics": {"success": True, "joint_replay": True},
                        "artifacts": {"hdf5_path": "mimic/generated_dataset_joint_plan.hdf5"},
                        "training": {"eligible": True, "fidelity_weight": 1.0},
                    }
                ),
                json.dumps(
                    {
                        "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                        "source_type": "isaac_lab_mimic",
                        "trajectory_id": "official_unvalidated_000003",
                        "episode_index": 3,
                        "generated_demo": "demo_000003",
                        "frame_count": 150,
                        "metrics": {"success": True, "official_mimic": True, "replay_required": True},
                        "artifacts": {"hdf5_path": "mimic/generated_dataset.hdf5"},
                        "training": {"eligible": True, "fidelity_weight": 0.25},
                    }
                ),
            ]
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
            "isaac_lab_synthetic_weight": 0.4,
        }
    )

    output_root = Path(result["output_root"])
    synthetic_rows = [
        row
        for row in (
            json.loads(line)
            for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        )
        if row["source_type"] == "isaac_lab_synthetic"
    ]
    assert [(row["episode_index"], row["frame_start"], row["frame_end"]) for row in synthetic_rows] == [
        (0, 0, 149),
        (1, 0, 149),
    ]
    assert [row["generated_demo"] for row in synthetic_rows] == ["demo_000000", "demo_000001"]
    assert all(row["source_id"] != "joint_plan_only_000002" for row in synthetic_rows)
    assert all(row["source_id"] != "official_unvalidated_000003" for row in synthetic_rows)


def test_isaac_lab_training_import_uses_mimic_rgbd_post_render_not_joint_plan(tmp_path: Path) -> None:
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
    mimic_rgbd_successes = output_root / "mimic_rgbd" / "successes.jsonl"
    mimic_successes.parent.mkdir(parents=True, exist_ok=True)
    mimic_rgbd_successes.parent.mkdir(parents=True, exist_ok=True)
    mimic_successes.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                "source_type": "isaac_lab_mimic",
                "trajectory_id": "joint_plan_only_000000",
                "episode_index": 0,
                "generated_demo": "demo_000000",
                "frame_count": 150,
                "metrics": {"success": True, "joint_replay": True},
                "artifacts": {"hdf5_path": "mimic/generated_dataset_joint_plan.hdf5"},
                "training": {"eligible": True, "fidelity_weight": 1.0},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mimic_rgbd_successes.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.isaac_lab_mimic_rgbd.success.v1",
                "source_type": "isaac_lab_mimic_rgbd",
                "trajectory_id": "mimic_rgbd_000000",
                "source_episode_index": 0,
                "generated_demo": "demo_000000",
                "frame_count": 150,
                "metrics": {"success": True, "rgbd_render": True, "camera_count": 3},
                "artifacts": {
                    "hdf5_path": "mimic_rgbd/generated_dataset_rgbd.hdf5",
                    "render_manifest_path": "mimic_rgbd/manifest.jsonl",
                    "render_root": "mimic_rgbd/renders",
                },
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
            "isaac_lab_synthetic_weight": 0.4,
        }
    )

    output_root = Path(result["output_root"])
    training_rows = [
        json.loads(line)
        for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    synthetic_rows = [row for row in training_rows if row["source_type"] == "isaac_lab_synthetic"]

    assert len(synthetic_rows) == 1
    row = synthetic_rows[0]
    assert row["source_label"] == "isaac_lab_mimic_rgbd"
    assert row["generator_source_type"] == "isaac_lab_mimic_rgbd"
    assert row["source_id"] == "mimic_rgbd_000000"
    assert row["artifact_path"] == "mimic_rgbd/generated_dataset_rgbd.hdf5"
    assert row["generated_demo"] == "demo_000000"
    assert row["fidelity_weight"] == 0.25
    assert row["effective_weight"] == 0.1
    assert result["source_labels"]["counts"]["isaac_lab_mimic"] == 1
    assert result["source_labels"]["counts"]["isaac_lab_mimic_rgbd"] == 1
    assert result["source_labels"]["details"]["isaac_lab_mimic_rgbd"]["trainable_count"] == 1
    assert result["source_labels"]["details"]["isaac_lab_mimic_rgbd"]["train_default"] is True


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
    assert result["hdf5"]["contract_ok"] is True
    assert result["hdf5"]["contract_blockers"] == []
    validation_checks = {check["id"]: check for check in result["validation_report"]["checks"]}
    assert validation_checks["validate_hdf5_export"]["status"] == "passed"
    assert validation_checks["validate_hdf5_export"]["evidence"]["exported_frame_count"] == 3
    assert hdf5_path.is_file()
    with h5py.File(hdf5_path, "r") as handle:
        assert handle.attrs["format_version"] == 1
        env_args = json.loads(handle["data"].attrs["env_args"])
        assert env_args["env_name"] == "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0"
        demo = handle["data"]["demo_000000"]
        assert demo.attrs["episode_index"] == 0
        assert demo.attrs["num_samples"] == 3
        assert demo["initial_state"]["articulation"]["robot"]["root_pose"].shape == (1, 7)
        assert demo["initial_state"]["articulation"]["robot"]["root_velocity"].shape == (1, 6)
        assert demo["initial_state"]["articulation"]["robot"]["joint_position"].shape == (1, 7)
        assert demo["initial_state"]["articulation"]["robot"]["joint_velocity"].shape == (1, 7)
        assert demo["initial_state"]["rigid_object"]["red_cube"]["root_pose"].shape == (1, 7)
        assert demo["initial_state"]["rigid_object"]["red_cube"]["root_velocity"].shape == (1, 6)
        assert demo["actions"].dtype == np.dtype("float32")
        assert demo["states"].dtype == np.dtype("float32")
        assert demo["obs"]["object_pose"].dtype == np.dtype("float32")
        assert demo["obs"]["datagen_info"]["object_pose"]["red_cube"].dtype == np.dtype("float32")
        np.testing.assert_allclose(
            demo["actions"][:],
            [
                [1.0, 1.1, 1.2, 0.0, 0.0, 0.0, 1.2],
                [2.0, 2.1, 2.2, 0.0, 0.0, 0.0, 2.2],
                [3.0, 3.1, 3.2, 0.0, 0.0, 0.0, 3.2],
            ],
        )
        np.testing.assert_allclose(demo["states"][:], [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
        assert demo["frame_indices"][:].tolist() == [0, 1, 2]
        np.testing.assert_allclose(demo["obs"]["joint_pos"][:], [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
        np.testing.assert_allclose(demo["obs"]["gripper_state"][:], [[1.2], [2.2], [3.2]])
        assert demo["obs"]["object_pose"].shape == (3, 4, 4)
        assert demo["obs"]["eef_pose"].shape == (3, 4, 4)
        datagen = demo["obs"]["datagen_info"]
        assert datagen["object_pose"]["red_cube"].shape == (3, 4, 4)
        assert datagen["eef_pose"]["omx"].shape == (3, 4, 4)
        assert datagen["target_eef_pose"]["omx"].shape == (3, 4, 4)
        assert set(datagen["subtask_term_signals"].keys()) == {
            "approach",
            "grasp",
            "lift",
            "place",
            "cube_lifted",
            "released_at_target",
        }
        canonical = handle["canonical_sidecar"]["demo_000000"]
        assert handle["canonical_sidecar"].attrs["schema"] == "atr.lerobot.canonical_episode_hdf5_sidecar.v1"
        assert canonical.attrs["episode_index"] == 0
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


def test_isaac_lab_export_hdf5_prefers_isaac_mirror_targets_for_robot_pose(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "mirror-target-demo"
    _make_dataset(dataset)
    _write_episode_parquet(dataset)
    _write_mirror_joint_targets(
        dataset,
        [
            [10.0, -20.0, 30.0, -40.0, 50.0, 35.0],
            [11.0, -21.0, 31.0, -41.0, 51.0, 34.0],
            [12.0, -22.0, 32.0, -42.0, 52.0, 33.0],
        ],
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
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }
    bridge.isaac_lab_build_synthetic(payload)

    result = bridge.isaac_lab_export_hdf5(payload)

    hdf5_path = Path(result["hdf5"]["output_path"])
    expected = np.deg2rad(
        np.asarray(
            [
                [10.0, -20.0, 30.0, -40.0, 50.0, 35.0, -35.0],
                [11.0, -21.0, 31.0, -41.0, 51.0, 34.0, -34.0],
                [12.0, -22.0, 32.0, -42.0, 52.0, 33.0, -33.0],
            ],
            dtype=np.float32,
        )
    )
    assert result["ok"] is True
    with h5py.File(hdf5_path, "r") as handle:
        demo = handle["data"]["demo_000000"]
        np.testing.assert_allclose(demo["actions"][:], expected, rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(
            demo["initial_state"]["articulation"]["robot"]["joint_position"][:],
            expected[:1],
            rtol=1e-6,
            atol=1e-6,
        )
        np.testing.assert_allclose(demo["obs"]["joint_pos"][:], expected, rtol=1e-6, atol=1e-6)
        canonical = handle["canonical_sidecar"]["demo_000000"]
        action_sources = [
            item.decode() if isinstance(item, bytes) else str(item)
            for item in canonical["action_source_labels"][:]
        ]
        assert action_sources == ["isaac_mirror_target", "isaac_mirror_target", "isaac_mirror_target"]


def test_isaac_lab_export_hdf5_uses_rgbd_render_attempt_specimen_pose_for_lab_scene(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "specimen-pose-demo"
    _make_dataset(dataset)
    _write_episode_parquet(dataset)
    specimen_pose_path = _write_isaac_rgbd_render_queue_with_specimen_pose(
        dataset,
        attempt_id="attempt_post",
        position_mm=(417.0, 311.0, 15.2),
        yaw_deg=-30.0,
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
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }
    build = bridge.isaac_lab_build_synthetic(payload)

    result = bridge.isaac_lab_export_hdf5(payload)

    assert result["ok"] is True
    hdf5_path = Path(build["output_root"]) / "hdf5" / "exported_successful_real_episodes.hdf5"
    yaw = float(np.deg2rad(-30.0))
    expected_quat = [0.0, 0.0, float(np.sin(yaw / 2.0)), float(np.cos(yaw / 2.0))]
    expected_root_pose = np.asarray([[0.417, 0.311, 0.0152, *expected_quat]], dtype=np.float32)
    expected_object_pose = np.eye(4, dtype=np.float32)
    expected_object_pose[:3, 3] = [0.417, 0.311, 0.0152]
    expected_object_pose[0, 0] = np.cos(yaw)
    expected_object_pose[0, 1] = -np.sin(yaw)
    expected_object_pose[1, 0] = np.sin(yaw)
    expected_object_pose[1, 1] = np.cos(yaw)
    with h5py.File(hdf5_path, "r") as handle:
        demo = handle["data"]["demo_000000"]
        np.testing.assert_allclose(
            demo["initial_state"]["rigid_object"]["red_cube"]["root_pose"][:],
            expected_root_pose,
            rtol=1e-6,
            atol=1e-6,
        )
        np.testing.assert_allclose(
            demo["obs"]["object_pose"][0],
            expected_object_pose,
            rtol=1e-6,
            atol=1e-6,
        )
        np.testing.assert_allclose(
            demo["obs"]["datagen_info"]["object_pose"]["red_cube"][0],
            expected_object_pose,
            rtol=1e-6,
            atol=1e-6,
        )
        canonical = handle["canonical_sidecar"]["demo_000000"]
        assert canonical.attrs["specimen_pose_attempt_id"] == "attempt_post"
        assert canonical.attrs["specimen_pose_source_path"] == str(specimen_pose_path)


def test_isaac_lab_export_hdf5_embeds_isaac_rgbd_observations_and_depth_metadata(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "visual-demo"
    _make_dataset(dataset)
    _write_episode_parquet(dataset)
    _write_isaac_rgbd_render_frames(dataset)
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
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    build = bridge.isaac_lab_build_synthetic(payload)
    export = bridge.isaac_lab_export_hdf5(payload)
    hdf5_path = Path(build["output_root"]) / "hdf5" / "exported_successful_real_episodes.hdf5"

    assert export["ok"] is True
    with h5py.File(hdf5_path, "r") as handle:
        obs = handle["data"]["demo_000000"]["obs"]
        for camera in ("top", "front", "right"):
            rgb = obs[f"{camera}_rgb"]
            depth = obs[f"{camera}_depth"]
            assert rgb.shape == (3, 4, 4, 3)
            assert depth.shape == (3, 4, 4, 1)
            assert rgb.dtype == np.dtype("uint8")
            assert depth.dtype == np.dtype("uint16")
            assert depth.attrs["encoding"] == "png16"
            assert depth.attrs["depth_scale_m_per_unit"] == 0.001
        assert obs["top_rgb"][0, 0, 0, :].tolist() == [40, 80, 120]
        assert int(obs["right_depth"][2, 0, 0, 0]) == 304
        canonical = handle["canonical_sidecar"]["demo_000000"]
        assert "isaac_rgbd_paths" in canonical
        assert "top_rgb" in canonical["isaac_rgbd_paths"]
        assert len(canonical["isaac_rgbd_paths"]["top_rgb"]) == 3


def test_isaac_lab_export_hdf5_downscales_rgbd_observations_to_requested_camera_size(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "resized-visual-demo"
    _make_dataset(dataset)
    _write_episode_parquet(dataset)
    _write_isaac_rgbd_render_frames(dataset, cameras=("top",))
    render_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_visual" / "top"
    for frame_index in range(3):
        rgb = np.full((96, 80, 3), [40 + frame_index, 80, 120], dtype=np.uint8)
        depth = np.full((96, 80), 300 + frame_index, dtype=np.uint16)
        Image.fromarray(rgb, mode="RGB").save(render_dir / f"frame_{frame_index:06d}_rgb.png")
        Image.fromarray(depth).save(render_dir / f"frame_{frame_index:06d}_depth.png")
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
        "require_physics_pass": False,
        "require_articulation_pass": False,
        "mimic_camera_width": 64,
        "mimic_camera_height": 64,
    }

    build = bridge.isaac_lab_build_synthetic(payload)
    export = bridge.isaac_lab_export_hdf5(payload)
    hdf5_path = Path(build["output_root"]) / "hdf5" / "exported_successful_real_episodes.hdf5"

    assert export["ok"] is True
    with h5py.File(hdf5_path, "r") as handle:
        obs = handle["data"]["demo_000000"]["obs"]
        assert obs["top_rgb"].shape == (3, 64, 64, 3)
        assert obs["top_depth"].shape == (3, 64, 64, 1)
        assert obs["top_depth"].attrs["depth_scale_m_per_unit"] == 0.001


def test_isaac_lab_export_hdf5_keeps_partial_npy_isaac_rgbd_with_valid_masks(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "partial-visual-demo"
    _make_dataset(dataset)
    _write_episode_parquet(dataset)
    _write_partial_isaac_rgbd_render_frames_with_npy_depth(dataset)
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
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    build = bridge.isaac_lab_build_synthetic(payload)
    export = bridge.isaac_lab_export_hdf5(payload)
    hdf5_path = Path(build["output_root"]) / "hdf5" / "exported_successful_real_episodes.hdf5"

    assert export["ok"] is True
    with h5py.File(hdf5_path, "r") as handle:
        obs = handle["data"]["demo_000000"]["obs"]
        for camera in ("top", "front", "right"):
            rgb = obs[f"{camera}_rgb"]
            depth = obs[f"{camera}_depth"]
            rgb_valid = obs[f"{camera}_rgb_valid"]
            depth_valid = obs[f"{camera}_depth_valid"]
            assert rgb.shape == (3, 4, 4, 3)
            assert depth.shape == (3, 4, 4, 1)
            assert depth.dtype == np.dtype("float32")
            assert depth.attrs["encoding"] == "npy_meters"
            assert depth.attrs["depth_scale_m_per_unit"] == 1.0
            assert rgb_valid[:].reshape(-1).tolist() == [True, False, True]
            assert depth_valid[:].reshape(-1).tolist() == [True, False, True]
        assert obs["top_rgb"][1, 0, 0, :].tolist() == obs["top_rgb"][0, 0, 0, :].tolist()
        assert float(obs["front_depth"][1, 0, 0, 0]) == float(obs["front_depth"][0, 0, 0, 0])


def test_isaac_lab_export_hdf5_large_rgbd_session_keeps_paths_without_loading_frames(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "large-visual-demo"
    frame_count = 1001
    _make_multi_episode_dataset(dataset, episode_count=1, frames_per_episode=frame_count)
    render_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_visual"
    render_dir.mkdir(parents=True)
    manifest_rows = []
    for frame_index in range(frame_count):
        manifest_rows.append(
            {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "episode_index": 0,
                "frame_index": frame_index,
                "depth_scale_m_per_unit": 0.001,
                "files": [
                    {
                        "camera": "top",
                        "kind": "rgb",
                        "path": f"top/frame_{frame_index:06d}_rgb.png",
                        "encoding": "png",
                    },
                    {
                        "camera": "top",
                        "kind": "depth",
                        "path": f"top/frame_{frame_index:06d}_depth.png",
                        "encoding": "png16",
                        "unit": "raw_uint16",
                        "depth_scale_m_per_unit": 0.001,
                    },
                ],
            }
        )
    (render_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in manifest_rows),
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
        "enable_hdf5_export": True,
        "require_physics_pass": False,
        "require_articulation_pass": False,
        "max_source_frames": 0,
        "cameras": ["top"],
    }

    def fail_if_large_export_reads_rgbd(*args, **kwargs):
        raise AssertionError("large HDF5 export should keep RGB-D as paths instead of loading arrays")

    monkeypatch.setattr("device_bridges.isaac_lab_hdf5._load_rgb_array", fail_if_large_export_reads_rgbd)
    monkeypatch.setattr("device_bridges.isaac_lab_hdf5._load_depth_array", fail_if_large_export_reads_rgbd)

    build = bridge.isaac_lab_build_synthetic(payload)
    export = bridge.isaac_lab_export_hdf5(payload)
    hdf5_path = Path(build["output_root"]) / "hdf5" / "exported_successful_real_episodes.hdf5"

    assert export["ok"] is True
    assert export["hdf5"]["exported_frame_count"] == frame_count
    assert export["hdf5"]["isaac_rgbd_embedded"] is False
    with h5py.File(hdf5_path, "r") as handle:
        obs = handle["data"]["demo_000000"]["obs"]
        assert "top_rgb" not in obs
        assert "top_depth" not in obs
        canonical = handle["canonical_sidecar"]["demo_000000"]
        assert canonical.attrs["isaac_rgbd_embedded"] == 0
        assert canonical.attrs["isaac_rgbd_embedding_reason"] == "frame_count_exceeds_limit"
        assert "isaac_rgbd_paths" in canonical
        assert len(canonical["isaac_rgbd_paths"]["top_rgb"]) == frame_count


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


def test_isaac_lab_export_hdf5_resolves_v3_chunk_file_dataset(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "v3_demo"
    (dataset / "meta").mkdir(parents=True, exist_ok=True)
    (dataset / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (dataset / "meta" / "info.json").write_text(
        json.dumps(
            {
                "codebase_version": "v3.0",
                "total_episodes": 2,
                "total_frames": 6,
                "chunks_size": 1000,
                "fps": 15,
                "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
            }
        ),
        encoding="utf-8",
    )
    (dataset / "meta" / "tasks.parquet").write_bytes(b"PAR1")
    (dataset / "sidecar" / "depth_raw").mkdir(parents=True, exist_ok=True)
    (dataset / "sidecar" / "depth_raw" / "transform_manifest.json").write_text(
        json.dumps({"camera_keys": ["top", "wrist"], "depth_encoding": "png16", "depth_scale_m_per_unit": 0.001}),
        encoding="utf-8",
    )
    table = pa.table(
        {
            "episode_index": pa.array([0, 0, 0, 1, 1, 1], type=pa.int64()),
            "frame_index": pa.array([0, 1, 2, 0, 1, 2], type=pa.int64()),
            "timestamp": pa.array([0.0, 1 / 15.0, 2 / 15.0, 0.0, 1 / 15.0, 2 / 15.0], type=pa.float64()),
            "observation.state": pa.array(
                [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6], [1.1, 1.2], [1.3, 1.4], [1.5, 1.6]],
                type=pa.list_(pa.float64()),
            ),
            "action": pa.array(
                [[2.1, 2.2, 2.3], [2.4, 2.5, 2.6], [2.7, 2.8, 2.9], [3.1, 3.2, 3.3], [3.4, 3.5, 3.6], [3.7, 3.8, 3.9]],
                type=pa.list_(pa.float64()),
            ),
        }
    )
    pq.write_table(table, dataset / "data" / "chunk-000" / "file-000.parquet")
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

    build = bridge.isaac_lab_build_synthetic(payload)
    result = bridge.isaac_lab_export_hdf5(payload)

    output_root = Path(result["output_root"])
    canonical_rows = [
        json.loads(line)
        for line in (output_root / "canonical_episode_index" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert build["canonical_episode_index"]["episode_count"] == 2
    assert build["canonical_episode_index"]["frame_count"] == 6
    assert {row["lerobot"]["observation_path"] for row in canonical_rows} == {"data/chunk-000/file-000.parquet"}
    assert result["hdf5"]["ok"] is True
    assert result["hdf5"]["exported_episode_count"] == 2
    with h5py.File(result["hdf5"]["output_path"], "r") as handle:
        assert sorted(handle["data"].keys()) == ["demo_000000", "demo_000001"]
        assert handle["data"]["demo_000000"]["actions"].shape == (3, 7)
        assert handle["data"]["demo_000001"]["actions"][0, 0] == 3.1


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
    assert export["mimic"]["mimic_num_envs"] == 10
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
    assert env_manifest["subtask_termination_signals"] == [
        "approach",
        "grasp",
        "lift",
        "place",
        "cube_lifted",
        "released_at_target",
    ]
    assert {term["id"] for term in env_manifest["reward_terms"]} == {
        "reach_object",
        "grasp_candidate",
        "lift_object",
        "place_object",
        "safety_limits",
    }
    assert env_manifest["reset_events"]["object_pose_randomization"]["enabled"] is False
    assert env_manifest["reset_events"]["object_pose_randomization"]["source"] == "recorded_specimen_pose"
    assert env_manifest["reset_events"]["object_pose_randomization"]["xy_bounds_m"] == {"x": [0.0, 0.0], "y": [0.0, 0.0]}
    assert env_manifest["reset_events"]["object_pose_randomization"]["yaw_bounds_rad"] == [0.0, 0.0]
    assert env_manifest["reset_events"]["physics_material_randomization"]["enabled"] is False
    assert env_manifest["reset_events"]["physics_material_randomization"]["source"] == "recorded_physics_materials"
    assert env_manifest["domain_randomization_events_path"] == str(event_config_path)
    assert event_config["schema"] == "atr.lerobot.isaac_lab_domain_randomization_events.v1"
    assert event_config["owner"] == "isaac_lab_environment_visual_events"
    assert [event["name"] for event in event_config["events"]] == [
        "randomize_environment_lighting",
        "randomize_environment_appearance",
        "randomize_camera_sensor",
        "randomize_rgbd_sensor_noise",
    ]
    assert event_config["events"][0]["params"]["cube_pose_locked"] is True
    assert event_config["events"][0]["params"]["cube_material_locked"] is True
    assert event_config["events"][0]["params"]["lighting_intensity_scale"] == [0.75, 1.25]
    assert event_config["events"][1]["params"]["table_color_brightness"] == [0.85, 1.15]
    assert event_config["events"][2]["params"]["camera_exposure_scale"] == [0.9, 1.1]
    assert event_config["events"][3]["params"]["depth_noise_mm"] == [0.0, 1.5]
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
    assert len(mimic_successes) == len(mimic_candidates)
    assert len(mimic_failures) == 0
    assert all(row["metrics"]["success"] is True for row in mimic_successes)
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
    mimic_preview_summary = mimic["mimic"]["preview"]
    assert mimic_preview_summary["frame_selection"] == "first_middle_last"
    assert mimic_preview_summary["demo_count"] == min(3, len(mimic_successes))
    assert mimic_preview_summary["total_demo_count"] == len(mimic_successes)
    assert mimic_preview_summary["rgb_contact_sheet_path"].endswith("previews/mimic_generated_rgb_contact_sheet.png")
    assert mimic_preview_summary["depth_contact_sheet_path"].endswith("previews/mimic_generated_depth_contact_sheet.png")
    assert Path(mimic_preview_summary["rgb_contact_sheet_path"]).is_file()
    assert Path(mimic_preview_summary["depth_contact_sheet_path"]).is_file()
    assert Image.open(mimic_preview_summary["rgb_contact_sheet_path"]).mode == "RGB"
    assert Image.open(mimic_preview_summary["depth_contact_sheet_path"]).mode == "RGB"
    with h5py.File(mimic_hdf5, "r") as h5:
        assert h5.attrs["schema"] == "atr.lerobot.generated_trajectory_hdf5.v1"
        assert h5.attrs["source_type"] == "isaac_lab_mimic"
        assert h5.attrs["success_count"] == len(mimic_successes)
        assert h5.attrs["total"] == sum(row["num_frames"] for row in mimic_successes)
        assert json.loads(h5["data"].attrs["env_args"])["env_name"] == "ATR-Robotis-OMX-PickPlace-Physical-v0"
        assert h5["data"].attrs["total"] == h5.attrs["total"]
        expected_demo_names = {f"demo_{index}" for index in range(len(mimic_successes))}
        assert set(h5["data"].keys()) == expected_demo_names
        first = h5["data"]["demo_0"]
        assert first.attrs["trajectory_id"] == mimic_successes[0]["trajectory_id"]
        assert bool(first.attrs["success"]) is True
        assert first.attrs["source_type"] == "isaac_lab_mimic"
        assert "actions" in first
        assert "states" in first
        assert set(first["obs"].keys()) >= {
            "joint_pos",
            "gripper_state",
            "object_pose",
            "eef_pose",
            "top_rgb",
            "front_rgb",
            "right_rgb",
            "top_depth",
            "front_depth",
            "right_depth",
        }
        num_samples = first["actions"].shape[0]
        assert num_samples >= 32
        assert first["obs"]["joint_pos"].shape[0] == num_samples
        assert first["obs"]["gripper_state"].shape == (num_samples, 1)
        assert first["obs"]["object_pose"].shape == (num_samples, 4, 4)
        assert first["obs"]["eef_pose"].shape == (num_samples, 4, 4)
        assert first["obs"]["top_rgb"].shape == (num_samples, 84, 84, 3)
        assert first["obs"]["top_rgb"].dtype == "uint8"
        assert first["obs"]["top_depth"].shape == (num_samples, 84, 84, 1)
        assert first["obs"]["top_depth"].attrs["encoding"] == "float32_meters"
        assert first["obs"]["top_depth"].attrs["depth_scale_m_per_unit"] == 1.0
        assert "object_pose_randomization" in first
    preview = bridge.isaac_lab_preview(payload)
    limited_preview = bridge.isaac_lab_preview({**payload, "isaac_data_augmentation_preview_count": 2})
    mimic_card = next(card for card in preview["source_labels"]["cards"] if card["source_type"] == "isaac_lab_mimic")
    assert mimic_card["media"]["generated_rgb_preview"]["available"] is True
    assert mimic_card["media"]["generated_depth_preview"]["available"] is True
    assert mimic_card["media"]["generated_rgb_preview"]["serve_url"]
    assert mimic_card["media"]["generated_depth_preview"]["serve_url"]
    assert any(card["source_type"] == "isaac_lab_mimic" for card in limited_preview["source_labels"]["cards"])
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
        assert json.loads(h5["data"].attrs["env_args"])["env_name"] == "ATR-Robotis-OMX-PickPlace-Physical-v0"
        assert set(h5["data"].keys()) == {f"demo_{index}" for index in range(len(rl_successes))}
        assert h5["data"]["demo_0"].attrs["trajectory_id"] == rl_successes[0]["trajectory_id"]
        assert h5["data"]["demo_0"]["actions"].shape[0] >= 32
        assert "top_rgb" in h5["data"]["demo_0"]["obs"]
        assert "right_depth" in h5["data"]["demo_0"]["obs"]

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


def test_isaac_lab_domain_mimic_expands_every_episode_by_domain_and_mimic_counts(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "multi_episode_demo"
    _make_multi_episode_dataset(dataset, episode_count=2, frames_per_episode=3)
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
        "max_source_frames": 0,
        "attempts_per_source_frame": 3,
        "mimic_trials": 3,
        "mimic_num_envs": 3,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    build = bridge.isaac_lab_build_synthetic(payload)
    export = bridge.isaac_lab_export_hdf5(payload)
    mimic = bridge.isaac_lab_run_mimic_smoke(payload)

    output_root = Path(build["output_root"])
    candidates = [
        json.loads(line)
        for line in (output_root / "mimic" / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    successes = [
        json.loads(line)
        for line in (output_root / "mimic" / "successes.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert build["canonical_episode_index"]["episode_count"] == 2
    assert export["hdf5"]["exported_episode_count"] == 2
    assert mimic["mimic"]["candidate_count"] == 18
    assert mimic["mimic"]["success_count"] == 18
    assert len(candidates) == 2 * 3 * 3
    assert len(successes) == len(candidates)
    assert Counter(row["source_episode_index"] for row in candidates) == {0: 9, 1: 9}
    for episode_index in (0, 1):
        tuples = {
            (row["domain_variant_index"], row["mimic_trial_index"])
            for row in candidates
            if row["source_episode_index"] == episode_index
        }
        assert tuples == {(domain_index, trial_index) for domain_index in range(3) for trial_index in range(3)}


def test_isaac_lab_joint_replay_rgbd_render_runs_after_headless_generation(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "preview_after_generation"
    _make_multi_episode_dataset(dataset, episode_count=2, frames_per_episode=3)
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
        "mimic_generation_backend": "joint_replay",
        "mimic_annotation_mode": "preannotated_passthrough",
        "mimic_trials": 3,
        "mimic_num_envs": 3,
        "isaac_mirror_endpoint": "http://127.0.0.1:18766/joints",
        "domain_randomization_profile": "standard",
        "isaac_lab_visualize_generation": True,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    bridge.isaac_lab_build_synthetic(payload)
    bridge.isaac_lab_export_hdf5(payload)
    bridge._isaac_lab_synthetic_pipeline().annotate_source(  # noqa: SLF001 - keep this test on the pipeline contract.
        IsaacLabSyntheticRequest.model_validate(payload)
    )
    result = bridge.isaac_lab_run_mimic(payload)

    runner = result["mimic"]["runner"]
    command = runner["command"]
    rgbd_render = runner["post_run"]
    rgbd_command = rgbd_render["command"]

    assert result["mimic"]["mimic_generation_backend"] == "joint_replay"
    assert result["mimic"]["backend_contract"]["backend"] == "joint_replay"
    assert result["mimic"]["backend_contract"]["trajectory_source"] == "recorded_leader_joint_targets"
    assert runner["backend"] == "joint_replay"
    assert runner["backend_contract"]["backend"] == "joint_replay"
    assert runner["generation_config"]["backend_contract"]["backend"] == "joint_replay"
    assert runner["generation_config"]["backend_contract"]["is_official_isaac_lab_mimic"] is False
    assert "--sim-step-generation" in command
    assert "--visualize-generation" not in command
    assert "--viz" in command
    assert command[command.index("--viz") + 1] == "none"
    assert "--visual-fps" in command
    assert command[command.index("--visual-fps") + 1] == "0"
    assert "--visual-max-demos" in command
    assert command[command.index("--visual-max-demos") + 1] == "0"

    assert rgbd_render["enabled"] is True
    assert rgbd_render["stage"] == "rgbd_render_after_generation"
    assert "--rgbd-render-only" in rgbd_command
    assert "--rgbd-render-backend" in rgbd_command
    assert rgbd_command[rgbd_command.index("--rgbd-render-backend") + 1] == "mirror_http"
    assert "--mirror-endpoint" in rgbd_command
    assert rgbd_command[rgbd_command.index("--mirror-endpoint") + 1] == "http://127.0.0.1:18766/render"
    assert "--preview-only" not in rgbd_command
    assert "--sim-step-generation" not in rgbd_command
    assert "--visualize-generation" not in rgbd_command
    assert "--viz" in rgbd_command
    assert rgbd_command[rgbd_command.index("--viz") + 1] == "kit"
    assert "--rendering-mode" in rgbd_command
    assert rgbd_command[rgbd_command.index("--rendering-mode") + 1] == "balanced"
    assert "--kit-args" in rgbd_command
    assert "--visual-fps" in rgbd_command
    assert rgbd_command[rgbd_command.index("--visual-fps") + 1] == "0"
    assert "--visual-max-demos" in rgbd_command
    assert rgbd_command[rgbd_command.index("--visual-max-demos") + 1] == "0"
    assert "--input-file" in rgbd_command
    assert rgbd_command[rgbd_command.index("--input-file") + 1].endswith("mimic/generated_dataset.hdf5")
    assert "--output-file" in rgbd_command
    assert rgbd_command[rgbd_command.index("--output-file") + 1].endswith("mimic_rgbd/generated_dataset_rgbd.hdf5")
    assert "--rgbd-output-dir" in rgbd_command
    assert rgbd_command[rgbd_command.index("--rgbd-output-dir") + 1].endswith("mimic_rgbd/renders")
    assert result["mimic"]["runner"]["generation_config"]["rgbd_render_after_generation"]["enabled"] is True


def test_isaac_lab_output_check_validates_domain_mimic_artifacts(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "lab_check_demo"
    _make_multi_episode_dataset(dataset, episode_count=2, frames_per_episode=3)
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
        "max_source_frames": 0,
        "attempts_per_source_frame": 3,
        "mimic_trials": 3,
        "mimic_num_envs": 3,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    bridge.isaac_lab_run_e2e(payload)
    result = bridge.isaac_lab_check_outputs(payload)

    assert result["ok"] is True
    assert result["tool"] == "lerobot.isaac_lab.check_outputs"
    assert result["status"] == "PASSED"
    assert result["check_summary"]["episode_count"] == 2
    assert result["check_summary"]["expected_mimic_candidates"] == 18
    assert result["check_summary"]["mimic_candidate_count"] == 18
    assert result["check_summary"]["mimic_success_count"] == 18
    assert result["check_summary"]["mimic_failure_count"] == 0
    assert result["check_summary"]["training_row_count"] >= 18
    assert {check["status"] for check in result["checks"]} == {"passed"}


def test_isaac_lab_output_check_reports_mimic_count_mismatch(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "lab_check_mismatch"
    _make_multi_episode_dataset(dataset, episode_count=2, frames_per_episode=3)
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
        "max_source_frames": 0,
        "attempts_per_source_frame": 3,
        "mimic_trials": 3,
        "mimic_num_envs": 3,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    e2e = bridge.isaac_lab_run_e2e(payload)
    output_root = Path(e2e["output_root"])
    candidates_path = output_root / "mimic" / "candidates.jsonl"
    candidate_lines = candidates_path.read_text(encoding="utf-8").splitlines()
    candidates_path.write_text("\n".join(candidate_lines[:-1]) + "\n", encoding="utf-8")

    result = bridge.isaac_lab_check_outputs(payload)

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert any(issue["code"] == "MIMIC_CANDIDATE_COUNT_MISMATCH" for issue in result["issues"])
    check = {item["id"]: item for item in result["checks"]}["validate_mimic_generation"]
    assert check["status"] == "blocked"
    assert check["evidence"]["candidate_manifest_count"] == 17


def test_isaac_lab_output_check_reports_official_mimic_replay_failures(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "lab_check_replay_failure"
    _make_multi_episode_dataset(dataset, episode_count=1, frames_per_episode=3)
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
        "max_source_frames": 0,
        "attempts_per_source_frame": 1,
        "mimic_trials": 1,
        "mimic_num_envs": 1,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    e2e = bridge.isaac_lab_run_e2e(payload)
    output_root = Path(e2e["output_root"])
    replay_failures_path = output_root / "mimic" / "replay_failures.jsonl"
    replay_failures_path.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
                "source_type": "isaac_lab_mimic",
                "trajectory_id": "official_mimic_demo_000000_demo_0",
                "source_episode_index": 0,
                "generated_demo": "demo_0",
                "metrics": {"success": True, "official_mimic": True, "lab_step_replay": False},
                "training": {"eligible": False, "exclusion_reason": "official_replay_validation_failed"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = bridge.isaac_lab_check_outputs(payload)

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert any(issue["code"] == "MIMIC_REPLAY_FAILURES_PRESENT" for issue in result["issues"])
    check = {item["id"]: item for item in result["checks"]}["validate_mimic_replay"]
    assert check["status"] == "blocked"
    assert check["evidence"]["replay_failure_count"] == 1
    assert check["evidence"]["failed_generated_demos"] == ["demo_0"]


def test_isaac_lab_output_check_accepts_partial_official_mimic_after_replay_promotion(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "lab_check_official_partial_success"
    _make_multi_episode_dataset(dataset, episode_count=3, frames_per_episode=3)
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
        "attempts_per_source_frame": 3,
        "mimic_trials": 1,
        "mimic_num_envs": 1,
        "mimic_generation_backend": "official",
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    e2e = bridge.isaac_lab_run_e2e(payload)
    output_root = Path(e2e["output_root"])
    mimic_dir = output_root / "mimic"
    candidates = [
        {"source_type": "isaac_lab_mimic", "trajectory_id": f"candidate_{index:02d}"}
        for index in range(9)
    ]
    successes = [
        {
            "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
            "source_type": "isaac_lab_mimic",
            "trajectory_id": f"official_mimic_demo_{episode_index:06d}_demo_0",
            "source_episode_index": episode_index,
            "episode_index": episode_index,
            "generated_demo": f"demo_{ordinal}",
            "frame_start": 0,
            "frame_end": 2,
            "metrics": {
                "success": True,
                "official_mimic": True,
                "replay_validated": True,
                "replay_required": False,
                "lab_step_replay": True,
            },
            "training": {"eligible": True, "fidelity_weight": 0.25, "exclusion_reason": ""},
            "artifacts": {"hdf5_path": str(mimic_dir / "generated_dataset.hdf5")},
        }
        for ordinal, episode_index in enumerate((0, 2))
    ]
    failures = [
        {
            "source_type": "isaac_lab_mimic",
            "source_episode_index": 1,
            "status": "annotation_failed",
            "training": {"eligible": False, "exclusion_reason": "annotation_failed"},
        }
    ]
    (mimic_dir / "candidates.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in candidates),
        encoding="utf-8",
    )
    (mimic_dir / "successes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in successes),
        encoding="utf-8",
    )
    (mimic_dir / "replay_successes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in successes),
        encoding="utf-8",
    )
    (mimic_dir / "failures.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in failures),
        encoding="utf-8",
    )
    (mimic_dir / "replay_failures.jsonl").write_text("", encoding="utf-8")

    bridge.isaac_lab_build_synthetic({**payload, "force_rebuild": False, "overwrite_latest": False, "resume": True})
    result = bridge.isaac_lab_check_outputs(payload)

    assert result["ok"] is True
    assert result["status"] == "PASSED"
    assert result["check_summary"]["mimic_candidate_count"] == 9
    assert result["check_summary"]["mimic_success_count"] == 2
    assert result["check_summary"]["mimic_failure_count"] == 1
    assert result["training_exposure"]["source_counts"]["isaac_lab_synthetic"] == 2
    manifest_rows = [
        json.loads(line)
        for line in (output_root / "training_import" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    mimic_training_rows = [
        row
        for row in manifest_rows
        if row.get("source_type") == "isaac_lab_synthetic" and row.get("source_label") == "isaac_lab_mimic"
    ]
    assert len(mimic_training_rows) == 2


def test_isaac_lab_output_check_requires_mimic_rows_in_training_import(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "lab_check_missing_mimic_training_rows"
    _make_multi_episode_dataset(dataset, episode_count=3, frames_per_episode=3)
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
        "attempts_per_source_frame": 1,
        "mimic_trials": 1,
        "mimic_num_envs": 1,
        "mimic_generation_backend": "official",
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    e2e = bridge.isaac_lab_run_e2e(payload)
    output_root = Path(e2e["output_root"])
    mimic_dir = output_root / "mimic"
    successes = [
        {
            "schema": "atr.lerobot.isaac_lab_mimic.success.v1",
            "source_type": "isaac_lab_mimic",
            "trajectory_id": f"official_mimic_demo_{episode_index:06d}_demo_0",
            "source_episode_index": episode_index,
            "episode_index": episode_index,
            "generated_demo": f"demo_{episode_index}",
            "frame_start": 0,
            "frame_end": 2,
            "metrics": {
                "success": True,
                "official_mimic": True,
                "replay_validated": True,
                "replay_required": False,
                "lab_step_replay": True,
            },
            "training": {"eligible": True, "fidelity_weight": 0.25, "exclusion_reason": ""},
            "artifacts": {"hdf5_path": str(mimic_dir / "generated_dataset.hdf5")},
        }
        for episode_index in (0, 2)
    ]
    (mimic_dir / "candidates.jsonl").write_text(
        "".join(json.dumps({"source_type": "isaac_lab_mimic", "trajectory_id": f"candidate_{index}"}) + "\n" for index in range(3)),
        encoding="utf-8",
    )
    (mimic_dir / "successes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in successes),
        encoding="utf-8",
    )
    (mimic_dir / "replay_successes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in successes),
        encoding="utf-8",
    )
    (mimic_dir / "failures.jsonl").write_text("", encoding="utf-8")
    (mimic_dir / "replay_failures.jsonl").write_text("", encoding="utf-8")
    summary = json.loads((mimic_dir / "summary.json").read_text(encoding="utf-8"))
    summary.update({"candidate_count": 3, "success_count": 2, "failure_count": 0})
    (mimic_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    training_dir = output_root / "training_import"
    real_rows = [
        {
            "schema": "atr.lerobot.training_import.row.v1",
            "source_type": "real_lerobot",
            "source_label": "real_lerobot",
            "source_id": f"real_episode_{episode_index:06d}",
            "artifact_path": f"data/chunk-000/episode_{episode_index:06d}.parquet",
            "success": True,
            "fidelity_weight": 1.0,
            "generation_manifest": "../canonical_episode_index/manifest.jsonl",
        }
        for episode_index in range(3)
    ]
    (training_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in real_rows),
        encoding="utf-8",
    )
    training_summary = json.loads((training_dir / "summary.json").read_text(encoding="utf-8"))
    training_summary.update(
        {
            "status": "passed",
            "row_count": 3,
            "candidate_row_count": 3,
            "source_counts": {"real_lerobot": 3},
            "candidate_source_counts": {"real_lerobot": 3},
            "train_exposed": True,
        }
    )
    (training_dir / "summary.json").write_text(json.dumps(training_summary), encoding="utf-8")

    result = bridge.isaac_lab_check_outputs(payload)

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    issue = next(issue for issue in result["issues"] if issue["code"] == "TRAINING_IMPORT_SYNTHETIC_ROWS_MISSING")
    assert issue["evidence"]["mimic_training_row_count"] == 0
    assert issue["evidence"]["required_mimic_success_rows"] == 2


def test_isaac_lab_episode_indices_filter_domain_mimic_outputs(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "lab_episode_filter"
    _make_multi_episode_dataset(dataset, episode_count=3, frames_per_episode=4)
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
        "max_source_frames": 0,
        "attempts_per_source_frame": 2,
        "mimic_trials": 2,
        "mimic_num_envs": 2,
        "isaac_lab_episode_indices": "1",
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    bridge.isaac_lab_run_e2e(payload)
    result = bridge.isaac_lab_check_outputs(payload)

    output_root = Path(result["output_root"])
    canonical_rows = [
        json.loads(line)
        for line in (output_root / "canonical_episode_index" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    candidates = [
        json.loads(line)
        for line in (output_root / "mimic" / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["ok"] is True
    assert result["check_summary"]["episode_count"] == 1
    assert result["check_summary"]["canonical_frame_count"] == 4
    assert result["check_summary"]["expected_mimic_candidates"] == 4
    assert result["check_summary"]["mimic_candidate_count"] == 4
    assert {row["episode_index"] for row in canonical_rows} == {1}
    assert {row["source_episode_index"] for row in candidates} == {1}


def test_isaac_lab_force_rebuild_overwrites_only_latest_synthetic_output(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "lab_overwrite_demo"
    _make_multi_episode_dataset(dataset, episode_count=1, frames_per_episode=3)
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
        "attempts_per_source_frame": 1,
        "mimic_trials": 1,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    first = bridge.isaac_lab_run_e2e(payload)
    output_root = Path(first["output_root"])
    stale_file = output_root / "mimic" / "stale_marker.txt"
    stale_file.write_text("old synthetic output", encoding="utf-8")

    second = bridge.isaac_lab_run_e2e({**payload, "force_rebuild": True, "overwrite_latest": True, "resume": False})

    assert second["ok"] is True
    assert stale_file.exists() is False
    assert (dataset / "meta" / "episodes.jsonl").is_file()


def test_isaac_lab_zero_max_source_frames_means_all_recorded_episodes(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "unlimited_demo"
    _make_multi_episode_dataset(dataset, episode_count=3, frames_per_episode=4)
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
            "max_source_frames": 0,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    assert result["ok"] is True
    assert result["canonical_episode_index"]["episode_count"] == 3
    assert result["canonical_episode_index"]["frame_count"] == 12
