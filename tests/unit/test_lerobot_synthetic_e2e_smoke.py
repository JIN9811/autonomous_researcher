"""End-to-end smoke tests for LeRobot synthetic intelligence workflow."""

from __future__ import annotations

from pathlib import Path

import h5py

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset, run_e2e_smoke


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


def test_five_by_ten_second_fixture_flows_to_synthetic_hdf5_and_train_smoke(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "five-by-ten"
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    fixture = build_fixture_recording_dataset(dataset, episodes=5, episode_s=10, fps=15)

    report = run_e2e_smoke(
        bridge=bridge,
        dataset_path=dataset,
        isaac_lab_path=isaac_lab,
        stage_path=stage,
        train_steps=2,
        enable_replicator=False,
    )

    assert report["ok"] is True
    assert fixture["episode_count"] == 5
    assert fixture["frame_count"] == 750
    assert report["recording_fixture"]["frame_count"] == 750
    assert report["synthetic"]["status"] == "READY_FOR_TRAINING"
    assert report["synthetic"]["canonical_episode_index"]["frame_count"] == 750
    assert report["hdf5"]["status"] == "READY_FOR_HDF5"
    assert report["hdf5"]["hdf5"]["exported_episode_count"] == 5
    assert report["hdf5"]["hdf5"]["exported_frame_count"] == 750
    assert report["train"]["ok"] is True
    assert report["train"]["status"] == "COMPLETED"
    assert report["train"]["training"]["total_steps"] == 2
    hdf5_path = Path(report["hdf5"]["hdf5"]["output_path"])
    with h5py.File(hdf5_path, "r") as handle:
        assert handle.attrs["total"] == 750
        assert len(handle["data"].keys()) == 5


def test_bridge_runs_five_by_ten_e2e_smoke_with_fixture_creation(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "local" / "gui-five-by-ten"
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")

    report = bridge.isaac_lab_run_e2e_smoke(
        {
            "mode": "test",
            "dataset_path": str(dataset),
            "isaac_lab_path": str(isaac_lab),
            "stage_path": str(stage),
            "enable_replicator": False,
            "e2e_create_fixture": True,
            "e2e_episodes": 5,
            "e2e_episode_s": 10,
            "e2e_fps": 15,
            "e2e_train_steps": 2,
            "require_physics_pass": False,
            "require_articulation_pass": False,
        }
    )

    assert report["ok"] is True
    assert report["tool"] == "lerobot.isaac_lab.e2e_smoke"
    assert report["recording_fixture"]["episode_count"] == 5
    assert report["recording_fixture"]["frame_count"] == 750
    assert report["synthetic"]["canonical_episode_index"]["frame_count"] == 750
    assert report["hdf5"]["hdf5"]["exported_frame_count"] == 750
    assert report["train"]["status"] == "COMPLETED"
    assert report["summary"]["train_steps"] == 2
