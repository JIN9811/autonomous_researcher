"""Unit tests for deterministic LeRobot bridge behavior."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from mcp_tools.lerobot_schemas import LeRobotSessionRequest


def _bridge(tmp_path: Path) -> LeRobotBridge:
    config = {
        "lerobot": {
            "default_profile_id": "fake_omx_ai",
            "session_memory_path": str(tmp_path / "memory" / "sessions.json"),
            "fake_dataset_root": str(tmp_path / "datasets"),
            "dataset_root": str(tmp_path / "hf_datasets"),
            "fake_checkpoint_root": str(tmp_path / "checkpoints"),
            "pi05_hf_home": str(tmp_path / "hf_home_pi05"),
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
                    "safety_limits": {
                        "live_enabled": False,
                        "require_operator_confirm": True,
                        "allow_policy_rollout": False,
                        "allow_recording": False,
                        "allow_training": False,
                        "allow_teleoperation": False,
                    },
                    "command_templates": {
                        "find_ports": ["lerobot-find-port"],
                        "teleoperate": ["python", "-m", "lerobot.teleoperate"],
                        "record": ["lerobot-record"],
                        "train": ["lerobot-train"],
                        "rollout": ["lerobot-rollout"],
                    },
                }
            },
        }
    }
    return LeRobotBridge(LeRobotBridgeConfig.from_config(config, repo_root=tmp_path))


def test_record_attempt_default_rgbd_render_cameras_are_top_front_right(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    request = LeRobotSessionRequest.model_validate(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/default-rgbd-cameras",
        }
    )

    attempt = bridge._record_attempt_summary(request, "lr-record-test")  # noqa: SLF001

    assert attempt["isaac_rgbd_render"]["cameras"] == ["top", "front", "right"]


def _make_trainable_lerobot_dataset(path: Path) -> None:
    (path / "meta").mkdir(parents=True, exist_ok=True)
    (path / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (path / "meta" / "info.json").write_text(json.dumps({"codebase_version": "v2.1", "total_episodes": 1, "total_frames": 1}), encoding="utf-8")
    (path / "meta" / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": "Pick up the cylinder"}) + "\n", encoding="utf-8")
    (path / "meta" / "episodes.jsonl").write_text(json.dumps({"episode_index": 0, "tasks": ["Pick up the cylinder"], "length": 1}) + "\n", encoding="utf-8")
    (path / "meta" / "episodes_stats.jsonl").write_text(json.dumps({"episode_index": 0, "stats": {}}) + "\n", encoding="utf-8")
    (path / "data" / "chunk-000" / "episode_000000.parquet").write_bytes(b"PAR1")
    _write_raw_depth_manifest(path)
    _write_raw_depth_frames(path, count=1)


def _write_raw_depth_manifest(path: Path) -> None:
    manifest = path / "sidecar" / "depth_raw" / "transform_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "camera_keys": ["top", "wrist"],
                "aligned_to": "color",
                "depth_encoding": "png16",
                "depth_scale_m_per_unit": 0.001,
                "depth_clip_min_mm": 0.0,
                "depth_clip_max_mm": 2000.0,
            }
        ),
        encoding="utf-8",
    )


def _write_raw_depth_frames(path: Path, *, cameras: tuple[str, ...] = ("top", "wrist"), count: int = 2) -> None:
    for camera in cameras:
        camera_dir = path / "sidecar" / "depth_raw" / camera
        camera_dir.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            Image.fromarray(np.full((8, 8), 420 + index, dtype=np.uint16)).save(camera_dir / f"frame_{index:06d}.png")


def _write_isaac_rgbd_render_fixture(path: Path, *, camera: str = "wrist") -> tuple[Path, Path]:
    render_dir = path / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_aug"
    camera_dir = render_dir / camera
    camera_dir.mkdir(parents=True, exist_ok=True)
    rgb_path = camera_dir / "frame_000000_rgb.png"
    depth_path = camera_dir / "frame_000000_depth.png"
    Image.fromarray(np.full((8, 8, 3), [80, 120, 160], dtype=np.uint8), mode="RGB").save(rgb_path)
    Image.fromarray(np.full((8, 8), 430, dtype=np.uint16)).save(depth_path)
    (render_dir / "manifest.jsonl").write_text(
        json.dumps(
            {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "status": "rendered",
                "attempt_id": "attempt_aug",
                "episode_index": 0,
                "frame_index": 0,
                "cameras": [camera],
                "output_dir": str(render_dir),
                "specimen_pose": {"a4_xy_mm": [105.0, 148.0], "yaw_deg": 0.0},
                "files": [
                    {"camera": camera, "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
                    {"camera": camera, "kind": "depth", "path": str(depth_path), "encoding": "png16", "unit": "mm"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return rgb_path, depth_path


def _write_isaac_rgbd_manifest_rows(path: Path, *, count: int, camera: str = "wrist") -> None:
    render_dir = path / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_mix"
    render_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "schema": "atr.isaac_rgbd.render_manifest.v1",
            "status": "metadata_only",
            "attempt_id": "attempt_mix",
            "episode_index": 0,
            "frame_index": index,
            "cameras": [camera],
            "files": [],
        }
        for index in range(count)
    ]
    (render_dir / "manifest.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _write_isaac_augmentation_summary(path: Path, *, variant_count: int, valid_variant_count: int, failed_variant_count: int = 0) -> None:
    output_dir = path / "sidecar" / "isaac_augmentation" / "latest"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.jsonl"
    rows = [
        {
            "schema": "atr.isaac_data_augmentation.variant.v1",
            "variant_id": f"mix_{index:03d}",
            "qa_ok": index < valid_variant_count,
            "source": {"episode_index": 0, "frame_index": index},
            "image_outputs": {},
        }
        for index in range(variant_count)
    ]
    manifest_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "ok": True,
                "dataset_path": str(path),
                "output_dir": str(output_dir),
                "manifest_path": str(manifest_path),
                "summary_path": str(summary_path),
                "qa_summary_path": str(output_dir / "qa_summary.json"),
                "source_frame_count": 1,
                "variant_count": variant_count,
                "valid_variant_count": valid_variant_count,
                "failed_variant_count": failed_variant_count,
            }
        ),
        encoding="utf-8",
    )


def _write_isaac_lab_synthetic_training_import(path: Path, *, row_count: int) -> None:
    output_dir = path / "sidecar" / "isaac_lab_synthetic" / "latest"
    manifest_path = output_dir / "training_import" / "manifest.jsonl"
    summary_path = output_dir / "training_import" / "summary.json"
    rows = [
        {
            "schema": "atr.lerobot.training_import_row.v1",
            "source_type": "isaac_lab_synthetic",
            "episode_index": index,
            "frame_index": 0,
            "success": True,
            "source_manifest": str(output_dir / "canonical_episode_index" / "manifest.jsonl"),
        }
        for index in range(row_count)
    ]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.training_import.summary.v1",
                "status": "passed",
                "row_count": row_count,
                "source_counts": {"isaac_lab_synthetic": row_count},
                "manifest_path": str(manifest_path),
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.isaac_lab_synthetic.summary.v1",
                "status": "READY_FOR_TRAINING",
                "dataset_path": str(path),
                "output_root": str(output_dir),
                "counts": {"training_rows": row_count},
                "artifacts": {"training_import_summary": str(summary_path), "training_import_manifest": str(manifest_path)},
            }
        ),
        encoding="utf-8",
    )


def _write_real_only_isaac_lab_training_import(path: Path, *, row_count: int) -> None:
    output_dir = path / "sidecar" / "isaac_lab_synthetic" / "latest"
    manifest_path = output_dir / "training_import" / "manifest.jsonl"
    summary_path = output_dir / "training_import" / "summary.json"
    rows = [
        {
            "schema": "atr.lerobot.training_import_row.v1",
            "source_type": "real_lerobot",
            "episode_index": index,
            "success": True,
        }
        for index in range(row_count)
    ]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "schema": "atr.lerobot.training_import.summary.v1",
                "status": "passed",
                "row_count": row_count,
                "source_counts": {"real_lerobot": row_count},
                "manifest_path": str(manifest_path),
            }
        ),
        encoding="utf-8",
    )


def _mark_lerobot_dataset_v30(path: Path) -> None:
    info_path = path / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["codebase_version"] = "v3.0"
    info_path.write_text(json.dumps(info), encoding="utf-8")
    _write_raw_depth_manifest(path)
    (path / "meta" / "tasks.parquet").write_bytes(b"PAR1")
    (path / "meta" / "stats.json").write_text(
        json.dumps({"observation.state": {"q01": [0.0], "q99": [1.0], "count": [1]}, "action": {"q01": [0.0], "q99": [1.0], "count": [1]}}),
        encoding="utf-8",
    )
    for rel in (
        "meta/episodes/chunk-000/file_000.parquet",
    ):
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"PAR1")


def _make_policy_checkpoint(path: Path, *, repo_id: str = "jin/demo_policy") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(json.dumps({"type": "act", "repo_id": repo_id}), encoding="utf-8")
    (path / "model.safetensors").write_bytes(b"SAFE")
    (path / "train_config.json").write_text(json.dumps({"policy": {"repo_id": repo_id}}), encoding="utf-8")


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_find_ports_returns_deterministic_test_ports(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.find_ports({"mode": "test", "profile_id": "fake_omx_ai"})

    assert result["ok"] is True
    assert result["tool"] == "lerobot.find_ports"
    assert result["ports"][0]["port"] == "/dev/ttyUSB_FAKE_FOLLOWER"
    assert result["ports"][1]["port"] == "/dev/ttyUSB_FAKE_LEADER"
    assert result["ports"][2]["role"] == "camera"
    assert {item["camera_key"] for item in result["ports"] if item["role"] == "camera"} == {"top", "wrist"}
    assert result["step_trace"][-1]["step"] == "DONE"


def test_config_status_suggests_date_scoped_recording_and_training_defaults(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    today = datetime.now().strftime("%Y%m%d")
    existing_dataset = tmp_path / "hf_datasets" / "jin" / f"{today}_1"
    existing_dataset.mkdir(parents=True)

    result = bridge.config_status()

    defaults = result["workflow_defaults"]
    assert defaults["dataset_repo_id"] == f"jin/{today}_2"
    assert defaults["run_name"] == f"{today}_2"
    assert defaults["train_name"] == f"{today}_2_train(smolvla)"
    assert defaults["output_dir"] == str(tmp_path / "outputs" / "train" / f"{today}_2_train(smolvla)")
    assert defaults["job_name"] == f"{today}_2_train(smolvla)"
    assert defaults["record_task_instruction"] == "Pick up the cube and place it"
    assert defaults["rollout_task_instruction"] == "Pick up the cube and place it"
    assert defaults["record_num_episodes"] == 60


def test_config_status_exposes_observation_pipeline_options(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.config_status()

    assert result["selected_observation_pipeline_id"] == "raw_depth_adapter"
    assert result["default_observation_pipeline_id"] == "raw_depth_adapter"
    assert [item["pipeline_id"] for item in result["observation_pipelines"]] == [
        "legacy_lerobot",
        "rgbd_sidecar",
        "raw_depth_adapter",
    ]


def test_mirror_joint_mapping_returns_isaac_omx_contract(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.mirror_joint_mapping({"mode": "test", "profile_id": "fake_omx_ai"})

    assert result["ok"] is True
    assert result["tool"] == "lerobot.mirror.joint_mapping"
    assert result["scene_path"].endswith("sim/robotis_omx/scene/omx_table_layout.usda")
    assert result["articulation_root"] == "/World/Robot/Geometry/link0"
    assert [item["motor_id"] for item in result["joint_map"]] == [11, 12, 13, 14, 15, 16]
    assert [item["isaac_joint_name"] for item in result["joint_map"]] == ["Joint1", "Joint2", "Joint3", "Joint4", "Joint5", "Gripper"]
    assert result["joint_map"][0]["isaac_joint_path"].endswith("/Joint1")
    assert result["step_trace"][0]["step"] == "MIRROR_MAPPING"


def test_mirror_joint_state_probe_test_mode_returns_fake_positions(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.mirror_joint_state_probe({"mode": "test", "profile_id": "fake_omx_ai"})

    assert result["ok"] is True
    assert result["tool"] == "lerobot.mirror.state_probe"
    assert result["probe_source"] == "deterministic_test_state"
    assert result["joint_state"][0]["motor_id"] == 11
    assert result["joint_state"][0]["position_deg"] == 0.0
    assert len(result["joint_state"]) == 6
    assert all("isaac_joint_path" in item for item in result["joint_state"])
    assert result["step_trace"][-1]["step"] == "STATE_READY"


def test_mirror_joint_state_probe_live_reads_saved_follower_port(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "follower",
            "port": "test-follower-port",
        }
    )
    bridge._read_follower_joint_positions = lambda port, motor_ids: {motor_id: float(motor_id) for motor_id in motor_ids}  # type: ignore[method-assign]

    result = bridge.mirror_joint_state_probe({"mode": "live", "profile_id": "fake_omx_ai"})

    assert result["ok"] is True
    assert result["probe_source"] == "live_dynamixel_present_position"
    assert result["follower_port"] == "test-follower-port"
    assert [item["position_deg"] for item in result["joint_state"]] == [11.0, 12.0, 13.0, 14.0, 15.0, 16.0]


def test_mirror_loop_start_test_mode_posts_and_records_samples(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    posted: list[tuple[str, dict[str, object]]] = []
    bridge._post_isaac_mirror_state = lambda endpoint, payload, timeout_s=0.5: posted.append((endpoint, payload)) or {"ok": True, "status_code": 200}  # type: ignore[method-assign]

    result = bridge.mirror_loop_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
            "isaac_mirror_sample_hz": 30,
            "isaac_mirror_max_samples": 3,
        }
    )

    assert result["ok"] is True
    assert result["tool"] == "lerobot.mirror.loop_start"
    assert result["workflow"] == "isaac_mirror"
    assert result["status"] == "COMPLETED"
    assert result["sample_count"] == 3
    assert len(posted) == 3
    assert posted[0][0] == "http://127.0.0.1:8766/joints"
    assert len(posted[0][1]["joint_state"]) == 6  # type: ignore[arg-type]
    record_path = Path(str(result["mirror_record_path"]))
    assert record_path.exists()
    records = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 3
    assert records[0]["joint_state"][0]["motor_id"] == 11
    assert records[-1]["isaac_post"]["ok"] is True
    assert records[0]["sync_metrics"]["target_sample_hz"] == 30
    assert records[0]["sync_metrics"]["sample_period_s"] == 1 / 30
    assert records[0]["sync_metrics"]["post_latency_ms"] >= 0
    assert records[0]["sync_metrics"]["loop_lag_ms"] >= 0
    assert result["sync_summary"]["target_sample_hz"] == 30
    assert result["sync_summary"]["sample_count"] == 3
    assert result["sync_summary"]["mean_post_latency_ms"] >= 0
    assert result["sync_summary"]["effective_sample_hz"] > 0


def test_mirror_loop_start_live_reuses_persistent_joint_reader(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    follower = tmp_path / "omx_follower"
    follower.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    posted: list[dict[str, object]] = []
    reader_events: list[str] = []

    class FakeReader:
        def __enter__(self) -> "FakeReader":
            reader_events.append("open")
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            reader_events.append("close")

        def read(self) -> dict[int, float]:
            reader_events.append("read")
            return {motor_id: float(motor_id) for motor_id in [11, 12, 13, 14, 15, 16]}

    bridge._open_follower_joint_position_reader = lambda port, motor_ids: FakeReader()  # type: ignore[attr-defined, method-assign]
    bridge._read_follower_joint_positions = lambda port, motor_ids: (_ for _ in ()).throw(AssertionError("per-sample subprocess reader must not be used"))  # type: ignore[method-assign]
    bridge._post_isaac_mirror_state = lambda endpoint, payload, timeout_s=0.5: posted.append(payload) or {"ok": True, "status_code": 200}  # type: ignore[method-assign]

    result = bridge.mirror_loop_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
            "isaac_mirror_sample_hz": 30,
            "isaac_mirror_max_samples": 3,
        }
    )

    assert result["ok"] is True
    assert result["status"] == "COMPLETED"
    assert result["sample_count"] == 3
    assert reader_events == ["open", "read", "read", "read", "close"]
    assert len(posted) == 3
    assert posted[0]["follower_port"] == str(follower)
    assert posted[0]["joint_state"][0]["position_deg"] == 11.0  # type: ignore[index]


def test_mirror_receiver_health_checks_endpoint_health_url(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    requested: list[tuple[str, float]] = []
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_health",
        lambda endpoint, timeout_s=0.5: requested.append((endpoint, timeout_s))
        or {
            "ok": True,
            "health_url": "http://127.0.0.1:8766/health",
            "apply_mode": "deferred_update_tick",
            "sample_count": 12,
        },
    )

    result = bridge.mirror_receiver_health(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
            "isaac_mirror_timeout_s": 0.25,
        }
    )

    assert result["ok"] is True
    assert result["tool"] == "lerobot.mirror.receiver_health"
    assert result["health_url"] == "http://127.0.0.1:8766/health"
    assert result["apply_mode"] == "deferred_update_tick"
    assert requested == [("http://127.0.0.1:8766/joints", 0.25)]


def test_mirror_receiver_verify_posts_one_sample_and_confirms_receiver_state(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    posted: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_health",
        lambda endpoint, timeout_s=0.5: {
            "ok": True,
            "health_url": "http://127.0.0.1:8766/health",
            "apply_mode": "deferred_update_tick",
            "sample_count": 4,
        },
        raising=False,
    )
    bridge._post_isaac_mirror_state = lambda endpoint, payload, timeout_s=0.5: posted.append((endpoint, payload)) or {"ok": True, "status_code": 200}  # type: ignore[method-assign]
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_state",
        lambda endpoint, timeout_s=0.5: {
            "ok": True,
            "health_url": "http://127.0.0.1:8766/state",
            "sample_count": 5,
            "last_payload_summary": {
                "session_id": posted[-1][1]["session_id"],
                "sample_index": posted[-1][1]["sample_index"],
                "joint_count": 6,
                "target_count": 6,
            },
        },
        raising=False,
    )

    result = bridge.mirror_receiver_verify(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
            "isaac_mirror_timeout_s": 0.25,
        }
    )

    assert result["ok"] is True
    assert result["tool"] == "lerobot.mirror.receiver_verify"
    assert result["verification"]["receiver_sample_count_before"] == 4
    assert result["verification"]["receiver_sample_count_after"] == 5
    assert result["verification"]["session_id"] == result["isaac_mirror"]["session_id"]
    assert result["verification"]["sample_index"] == 1
    assert posted[0][0] == "http://127.0.0.1:8766/joints"


def test_mirror_receiver_verify_fails_on_stale_receiver_state(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_health",
        lambda endpoint, timeout_s=0.5: {"ok": True, "health_url": "http://127.0.0.1:8766/health", "sample_count": 10},
        raising=False,
    )
    bridge._post_isaac_mirror_state = lambda endpoint, payload, timeout_s=0.5: {"ok": True, "status_code": 200}  # type: ignore[method-assign]
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_state",
        lambda endpoint, timeout_s=0.5: {
            "ok": True,
            "health_url": "http://127.0.0.1:8766/state",
            "sample_count": 10,
            "last_payload_summary": {"session_id": "older-session", "sample_index": 1, "joint_count": 6, "target_count": 6},
        },
        raising=False,
    )

    result = bridge.mirror_receiver_verify({"mode": "test", "profile_id": "fake_omx_ai"})

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_ISAAC_MIRROR_VERIFY_STALE_STATE"
    assert "older-session" in result["message"]


def test_mirror_receiver_process_start_status_and_stop(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    source_script = Path(__file__).resolve().parents[2] / "sim" / "robotis_omx" / "tools" / "isaac_omx_mirror_server.py"
    source_mapping = Path(__file__).resolve().parents[2] / "utils" / "isaac_omx_mirror_mapping.py"
    target_script = tmp_path / "sim" / "robotis_omx" / "tools" / "isaac_omx_mirror_server.py"
    target_mapping = tmp_path / "utils" / "isaac_omx_mirror_mapping.py"
    target_script.parent.mkdir(parents=True, exist_ok=True)
    target_mapping.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_script, target_script)
    shutil.copy2(source_mapping, target_mapping)
    port = _free_tcp_port()
    endpoint = f"http://127.0.0.1:{port}/joints"
    try:
        started = bridge.mirror_receiver_process_start(
            {
                "mode": "test",
                "profile_id": "fake_omx_ai",
                "isaac_mirror_endpoint": endpoint,
                "isaac_mirror_receiver_python": sys.executable,
                "isaac_mirror_receiver_start_timeout_s": 5.0,
            }
        )

        assert started["ok"] is True
        assert started["status"] == "RUNNING"
        assert started["pid"] > 0
        assert started["health"]["ok"] is True

        status = bridge.mirror_receiver_process_status({"mode": "test", "profile_id": "fake_omx_ai", "isaac_mirror_endpoint": endpoint})
        assert status["ok"] is True
        assert status["status"] == "RUNNING"
        assert status["health"]["ok"] is True
    finally:
        stopped = bridge.mirror_receiver_process_stop({"mode": "test", "profile_id": "fake_omx_ai", "isaac_mirror_endpoint": endpoint})
    assert stopped["ok"] is True
    assert stopped["status"] == "STOPPED"
    time.sleep(0.1)
    assert bridge.mirror_receiver_process_status({"mode": "test", "profile_id": "fake_omx_ai", "isaac_mirror_endpoint": endpoint})["status"] in {
        "STOPPED",
        "IDLE",
    }


def test_mirror_receiver_process_start_reports_exited_process_before_timeout(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    target_script = tmp_path / "sim" / "robotis_omx" / "tools" / "isaac_omx_mirror_server.py"
    target_script.parent.mkdir(parents=True, exist_ok=True)
    target_script.write_text("# receiver fixture\n", encoding="utf-8")
    exit_script = tmp_path / "exit_receiver.sh"
    exit_script.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    exit_script.chmod(0o755)
    port = _free_tcp_port()

    result = bridge.mirror_receiver_process_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_endpoint": f"http://127.0.0.1:{port}/joints",
            "isaac_mirror_receiver_python": str(exit_script),
            "isaac_mirror_receiver_start_timeout_s": 5.0,
        }
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["failure_code"] == "LEROBOT_ISAAC_MIRROR_RECEIVER_EXITED"
    assert result["health"]["returncode"] == 7



def test_mirror_receiver_extension_command_uses_isaac_app_and_extension(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    isaac_app = tmp_path / "IsaacSim" / "isaac-sim.sh"
    isaac_app.parent.mkdir(parents=True, exist_ok=True)
    isaac_app.write_text("#!/bin/sh\n", encoding="utf-8")
    isaac_app.chmod(0o755)
    site_packages = isaac_app.parent / "kit" / "python" / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    extension_manifest = tmp_path / "sim" / "robotis_omx" / "extensions" / "atr.omx.mirror" / "config" / "extension.toml"
    extension_manifest.parent.mkdir(parents=True, exist_ok=True)
    extension_manifest.write_text("[package]\ntitle = \"ATR ROBOTIS OMX Mirror Receiver\"\n", encoding="utf-8")
    scene_path = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text("#usda 1.0\n", encoding="utf-8")

    command_info = bridge._isaac_mirror_receiver_command(
        {
            "isaac_mirror_receiver_launch_mode": "isaac_extension",
            "isaac_mirror_receiver_isaac_sim_executable": str(isaac_app),
            "isaac_mirror_receiver_scene": str(scene_path),
        },
        "http://127.0.0.1:18766/joints",
    )

    assert command_info["ok"] is True
    command = command_info["command"]
    assert command[0] == str(isaac_app)
    assert f"--/app/python/extraPaths/0={site_packages}" in command
    assert "--ext-folder" in command
    assert str(tmp_path / "sim" / "robotis_omx" / "extensions") in command
    assert "--enable" in command
    assert "atr.omx.mirror" in command
    assert "--/exts/atr.omx.mirror/host=127.0.0.1" in command
    assert "--/exts/atr.omx.mirror/port=18766" in command
    assert f"--/exts/atr.omx.mirror/scene={scene_path}" in command
    assert "--/exts/atr.omx.mirror/openSceneOnStartup=true" in command
    assert "--/exts/atr.omx.mirror/playTimelineOnStartup=false" in command
    assert "--/exts/atr.omx.mirror/specimenPoseActiveRobotCamOnMissing=true" in command
    assert str(scene_path) not in command


def test_mirror_receiver_extension_command_can_start_with_timeline_playing(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    isaac_app = tmp_path / "IsaacSim" / "isaac-sim.sh"
    isaac_app.parent.mkdir(parents=True, exist_ok=True)
    isaac_app.write_text("#!/bin/sh\n", encoding="utf-8")
    isaac_app.chmod(0o755)
    extension_manifest = tmp_path / "sim" / "robotis_omx" / "extensions" / "atr.omx.mirror" / "config" / "extension.toml"
    extension_manifest.parent.mkdir(parents=True, exist_ok=True)
    extension_manifest.write_text("[package]\ntitle = \"ATR ROBOTIS OMX Mirror Receiver\"\n", encoding="utf-8")
    scene_path = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text("#usda 1.0\n", encoding="utf-8")

    command_info = bridge._isaac_mirror_receiver_command(
        {
            "isaac_mirror_receiver_launch_mode": "isaac_extension",
            "isaac_mirror_receiver_isaac_sim_executable": str(isaac_app),
            "isaac_mirror_receiver_scene": str(scene_path),
            "isaac_mirror_receiver_play_timeline_on_startup": True,
            "active_robot_cam_enabled": False,
        },
        "http://127.0.0.1:18766/joints",
    )

    assert command_info["ok"] is True
    assert "--/exts/atr.omx.mirror/playTimelineOnStartup=true" in command_info["command"]
    assert "--/exts/atr.omx.mirror/specimenPoseActiveRobotCamOnMissing=false" in command_info["command"]


def test_mirror_receiver_extension_command_can_disable_active_robot_cam(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    isaac_app = tmp_path / "IsaacSim" / "isaac-sim.sh"
    isaac_app.parent.mkdir(parents=True, exist_ok=True)
    isaac_app.write_text("#!/bin/sh\n", encoding="utf-8")
    isaac_app.chmod(0o755)
    extension_manifest = tmp_path / "sim" / "robotis_omx" / "extensions" / "atr.omx.mirror" / "config" / "extension.toml"
    extension_manifest.parent.mkdir(parents=True, exist_ok=True)
    extension_manifest.write_text("[package]\ntitle = \"ATR ROBOTIS OMX Mirror Receiver\"\n", encoding="utf-8")
    scene_path = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text("#usda 1.0\n", encoding="utf-8")

    command_info = bridge._isaac_mirror_receiver_command(
        {
            "isaac_mirror_receiver_launch_mode": "isaac_extension",
            "isaac_mirror_receiver_isaac_sim_executable": str(isaac_app),
            "isaac_mirror_receiver_scene": str(scene_path),
            "active_robot_cam_enabled": False,
        },
        "http://127.0.0.1:18766/joints",
    )

    assert command_info["ok"] is True
    assert "--/exts/atr.omx.mirror/specimenPoseActiveRobotCamOnMissing=false" in command_info["command"]


def test_mirror_receiver_process_start_restarts_when_active_robot_cam_option_changes(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    endpoint = "http://127.0.0.1:18766/joints"
    started_commands: list[list[str]] = []
    terminated: list[int] = []

    class FakeProcess:
        next_pid = 7000

        def __init__(self, command: list[str], **_kwargs: object) -> None:
            FakeProcess.next_pid += 1
            self.pid = FakeProcess.next_pid
            self.command = command
            self.returncode = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            self.returncode = 0
            return 0

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        started_commands.append(list(command))
        return FakeProcess(command, **kwargs)

    def fake_command(payload: dict[str, object], _endpoint: str) -> dict[str, object]:
        active = "1" if payload.get("active_robot_cam_enabled") else "0"
        return {"ok": True, "launch_mode": "isaac_extension", "command": ["isaac-sim", f"active={active}"]}

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    bridge._isaac_mirror_receiver_command = fake_command  # type: ignore[method-assign]
    bridge._wait_for_isaac_mirror_receiver = lambda *_args, **_kwargs: {"ok": True, "health_url": "http://127.0.0.1:18766/health"}  # type: ignore[method-assign]
    bridge._fetch_isaac_mirror_receiver_health = lambda *_args, **_kwargs: {"ok": True}  # type: ignore[method-assign]
    bridge._terminate_live_process = lambda process, _signal: terminated.append(process.pid)  # type: ignore[method-assign]

    first = bridge.mirror_receiver_process_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_endpoint": endpoint,
            "active_robot_cam_enabled": False,
        }
    )
    second = bridge.mirror_receiver_process_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_endpoint": endpoint,
            "active_robot_cam_enabled": True,
        }
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert started_commands == [["isaac-sim", "active=0"], ["isaac-sim", "active=1"]]
    assert terminated == [first["pid"]]


def test_live_mirror_preflight_warns_non_isaac_update_tick_receiver(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    profile = bridge._profile("fake_omx_ai")
    assert profile is not None
    request = LeRobotSessionRequest.model_validate(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_enabled": True,
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
        }
    )
    bridge._fetch_isaac_mirror_receiver_health = lambda endpoint, timeout_s=0.5: {  # type: ignore[method-assign]
        "ok": True,
        "health_url": "http://127.0.0.1:8766/health",
        "apply_mode": "direct_http_thread",
    }

    result = bridge._live_isaac_mirror_preflight_if_needed(
        tool="lerobot.teleoperate.start",
        mode="live",
        profile=profile,
        workflow="teleoperate",
        request=request,
    )

    assert result is not None
    assert result["ok"] is True
    assert result["status"] == "warning"
    assert result["warning_code"] == "LEROBOT_ISAAC_MIRROR_RECEIVER_NOT_IN_ISAAC_UPDATE_TICK"

def test_teleoperate_start_can_attach_isaac_mirror_loop(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    posted: list[tuple[str, dict[str, object]]] = []
    bridge._post_isaac_mirror_state = lambda endpoint, payload, timeout_s=0.5: posted.append((endpoint, payload)) or {"ok": True, "status_code": 200}  # type: ignore[method-assign]

    started = bridge.teleoperate_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_enabled": True,
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
            "isaac_mirror_max_samples": 2,
        }
    )

    assert started["ok"] is True
    assert started["workflow"] == "teleoperate"
    assert started["isaac_mirror"]["status"] == "COMPLETED"
    assert started["isaac_mirror"]["sample_count"] == 2
    assert started["isaac_mirror_session_id"]
    assert all(payload["attached_to_session_id"] == started["session_id"] for _, payload in posted)


def test_teleoperate_stop_stops_attached_isaac_mirror_loop(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._post_isaac_mirror_state = lambda endpoint, payload, timeout_s=0.5: {"ok": True, "status_code": 200}  # type: ignore[method-assign]
    started = bridge.teleoperate_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "isaac_mirror_enabled": True,
            "isaac_mirror_max_samples": 2,
        }
    )

    stopped = bridge.teleoperate_stop({"mode": "test", "session_id": started["session_id"]})

    assert stopped["ok"] is True
    assert stopped["status"] == "STOPPED"
    assert stopped["isaac_mirror_stop"]["status"] in {"STOPPED", "COMPLETED"}
    assert stopped["isaac_mirror_stop"]["attached_to_session_id"] == started["session_id"]


def test_live_teleoperate_with_isaac_mirror_starts_when_receiver_unavailable(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    bridge.config.profiles["fake_omx_ai"]["safety_limits"].update({"live_enabled": True, "allow_teleoperation": True})
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_health",
        lambda endpoint, timeout_s=0.5: {
            "ok": False,
            "health_url": "http://127.0.0.1:8766/health",
            "message": "connection refused",
        },
        raising=False,
    )
    live_start_kwargs: dict[str, object] = {}
    bridge._start_live_process = lambda **kwargs: live_start_kwargs.update(kwargs) or {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    result = bridge.teleoperate_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "confirm_live_execute": True,
            "isaac_mirror_enabled": True,
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
        }
    )

    assert result["ok"] is True
    assert result["status"] == "TELEOP_ACTIVE"
    assert result["isaac_mirror"]["status"] == "IN_PROCESS"
    assert any(
        item["step"] == "ISAAC_MIRROR_RECEIVER_PENDING"
        and item["status"] == "warning"
        and "http://127.0.0.1:8766/health" in item["detail"]
        for item in result["step_trace"]
    )
    command = [str(item) for item in live_start_kwargs["command"]]  # type: ignore[index]
    assert any(item.endswith("lerobot_isaac_mirror_runtime_wrapper.py") for item in command)


def test_live_teleoperate_with_isaac_mirror_starts_when_receiver_ready(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    bridge.config.profiles["fake_omx_ai"]["safety_limits"].update({"live_enabled": True, "allow_teleoperation": True})
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_health",
        lambda endpoint, timeout_s=0.5: {
            "ok": True,
            "health_url": "http://127.0.0.1:8766/health",
            "apply_mode": "deferred_update_tick",
            "sample_count": 0,
        },
        raising=False,
    )
    live_start_kwargs: dict[str, object] = {}
    viewport_frame_calls: list[dict[str, object]] = []
    bridge.mirror_loop_start = lambda payload: (_ for _ in ()).throw(AssertionError("live teleop mirror must run in-process"))  # type: ignore[method-assign]
    bridge._start_live_process = lambda **kwargs: live_start_kwargs.update(kwargs) or {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}  # type: ignore[method-assign]
    bridge._post_isaac_mirror_viewport_frame = lambda endpoint, reason, timeout_s=0.5: viewport_frame_calls.append(  # type: ignore[method-assign]
        {"endpoint": endpoint, "reason": reason, "timeout_s": timeout_s}
    ) or {"ok": True, "status": "viewport_frame_queued", "viewport_frame_url": "http://127.0.0.1:8766/viewport/frame"}

    result = bridge.teleoperate_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "confirm_live_execute": True,
            "isaac_mirror_enabled": True,
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
            "isaac_mirror_max_samples": 1,
        }
    )

    assert result["ok"] is True
    assert result["status"] == "TELEOP_ACTIVE"
    assert result["isaac_mirror"]["status"] == "IN_PROCESS"
    assert result["isaac_mirror"]["attached_to_session_id"] == result["session_id"]
    assert result["isaac_viewport_frame"]["status"] == "viewport_frame_queued"
    assert viewport_frame_calls == [
        {
            "endpoint": "http://127.0.0.1:8766/joints",
            "reason": "teleoperate_start",
            "timeout_s": 0.5,
        }
    ]
    command = [str(item) for item in live_start_kwargs["command"]]  # type: ignore[index]
    assert "teleoperate" in command
    assert any(item.endswith("lerobot_isaac_mirror_runtime_wrapper.py") for item in command)
    env = live_start_kwargs["env_overrides"]  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_ENABLED"] == "1"  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_ENDPOINT"] == "http://127.0.0.1:8766/joints"  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_SOURCE"] == "leader_action"  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_CALIBRATION_PATH"] == str(tmp_path / "memory" / "isaac_omx_mirror_calibration.json")  # type: ignore[index]


def test_live_teleoperate_active_robot_cam_uses_wrapper_and_d405_direct_env(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge.config.profiles["fake_omx_ai"]["safety_limits"].update({"live_enabled": True, "allow_teleoperation": True})
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    bridge._live_camera_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    captured: dict[str, object] = {}

    def fake_start_live_process(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start_live_process  # type: ignore[method-assign]

    result = bridge.teleoperate_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "confirm_live_execute": True,
            "camera_enabled": True,
            "active_robot_cam_enabled": True,
            "isaac_mirror_enabled": False,
        }
    )

    command = result["command_preview"]
    env = captured["env_overrides"]
    assert result["ok"] is True
    assert any(Path(item).name == "lerobot_isaac_mirror_runtime_wrapper.py" for item in command)
    assert env["ATR_ACTIVE_ROBOT_CAM_ENABLED"] == "1"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_CAMERA_PRIORITY"] == "d405,d455f"  # type: ignore[index]
    assert env["ATR_LEROBOT_SPECIMEN_CAMERA_KEY"] == "wrist"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_D405_A4_CAMERA_TO_ISAAC_TRANSFORM"] == "direct"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_D405_A4_WIDTH_MM"] == "297.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_D405_A4_HEIGHT_MM"] == "210.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_D405_A4_WORLD_OFFSET_X_MM"] == "0.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_D405_A4_WORLD_OFFSET_Y_MM"] == "0.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_D455F_A4_WORLD_OFFSET_X_MM"] == "0.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_D455F_A4_WORLD_OFFSET_Y_MM"] == "0.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_SPEED_SCALE"] == "0.7"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_RESUME_SPEED_SCALE"] == "0.5"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_TELEOP_TRANSITION_MAX_STEP"] == "3.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_CAPTURE_WAIT_TIMEOUT_S"] == "4.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_CAPTURE_WAIT_POLL_S"] == "0.05"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_CAPTURE_WAIT_TOLERANCE_DEG"] == "2.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_TIMEOUT_S"] == "4.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_POLL_S"] == "0.05"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_RESUME_WAIT_TOLERANCE_DEG"] == "2.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_SETTLE_S"] == "1.0"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_HOLD_AFTER_CAPTURE_S"] == "1.0"  # type: ignore[index]
    assert env["ATR_SPECIMEN_POSE_PENDING_PATH"] == "/tmp/atr_specimen_pose_pending/latest_specimen_pose_payload.json"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_REQUEST_PATH"] == "/tmp/atr_active_robot_cam_request/request.json"  # type: ignore[index]


def test_live_record_active_robot_cam_metadata_and_home_resume_env(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge.config.profiles["fake_omx_ai"]["safety_limits"].update({"live_enabled": True, "allow_recording": True})
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    bridge._live_camera_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    captured: dict[str, object] = {}

    def fake_start_live_process(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start_live_process  # type: ignore[method-assign]

    result = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/active-cam-test",
            "confirm_live_execute": True,
            "camera_enabled": True,
            "active_robot_cam_enabled": True,
            "active_robot_cam_resume_mode": "home_pose",
        }
    )

    env = captured["env_overrides"]
    assert result["ok"] is True
    assert result["active_robot_cam"]["enabled"] is True
    assert result["active_robot_cam"]["primary_camera"] == "d405"
    assert env["ATR_ACTIVE_ROBOT_CAM_ENABLED"] == "1"  # type: ignore[index]
    assert env["ATR_ACTIVE_ROBOT_CAM_RESUME_MODE"] == "home_pose"  # type: ignore[index]


def test_live_record_active_robot_cam_enables_saved_cameras_when_camera_flag_omitted(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge.config.profiles["fake_omx_ai"]["safety_limits"].update({"live_enabled": True, "allow_recording": True})
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "top",
            "port": "341522300873",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "wrist",
            "port": "352122273019",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    bridge._live_camera_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    result = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/active-cam-test",
            "confirm_live_execute": True,
            "active_robot_cam_enabled": True,
        }
    )

    camera_arg = next(arg for arg in result["command_preview"] if arg.startswith("--robot.cameras="))
    cameras = json.loads(camera_arg.removeprefix("--robot.cameras="))
    assert cameras["top"]["type"] == "intelrealsense"
    assert cameras["top"]["use_depth"] is True
    assert cameras["wrist"]["type"] == "intelrealsense"
    assert cameras["wrist"]["use_depth"] is True


def test_port_baseline_detect_persists_follower_port(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0"]  # type: ignore[method-assign]
    bridge._serial_motor_ids = lambda port: {"/dev/ttyUSB9": [11, 12, 13, 14, 15, 16]}.get(port, [])  # type: ignore[attr-defined, method-assign]

    baseline = bridge.ports_baseline({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0", "/dev/ttyUSB9"]  # type: ignore[method-assign]
    detected = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})
    teleop = bridge.teleoperate_start({"mode": "test", "profile_id": "fake_omx_ai", "camera_enabled": True})

    assert baseline["ok"] is True
    assert detected["selected_port"] == "/dev/ttyUSB9"
    assert detected["saved_devices"]["follower"]["port"] == "/dev/ttyUSB9"
    assert "--robot.port=/dev/ttyUSB9" in teleop["command_preview"]


def test_port_detect_rejects_removed_live_robot_port_without_role_probe(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0", "/dev/ttyUSB1"]  # type: ignore[method-assign]

    bridge.ports_baseline({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader"})
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0"]  # type: ignore[method-assign]
    detected = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader"})

    assert detected["ok"] is False
    assert detected["failure_code"] == "LEROBOT_PORT_REMOVED_UNVERIFIED"
    assert "leader" not in detected.get("saved_devices", {})


def test_port_detect_uses_added_robot_candidate_and_keeps_serial_id_mapping(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    stable_map = {
        "/dev/ttyUSB0": "/dev/serial/by-id/leader-openrb",
        "/dev/ttyUSB1": "/dev/serial/by-id/follower-openrb",
    }
    bridge._stable_device_port = lambda port, role: stable_map.get(port, port)  # type: ignore[method-assign]
    bridge._serial_motor_ids = lambda port: {"/dev/ttyUSB1": [11, 12, 13, 14, 15, 16]}.get(port, [])  # type: ignore[attr-defined, method-assign]
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": "/dev/ttyUSB0"})
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0"]  # type: ignore[method-assign]
    bridge.ports_baseline({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0", "/dev/ttyUSB1"]  # type: ignore[method-assign]
    detected = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})

    assert detected["ok"] is True
    assert detected["change_type"] == "added"
    assert detected["candidates"] == ["/dev/ttyUSB1"]
    assert detected["raw_selected_port"] == "/dev/ttyUSB1"
    assert detected["selected_port"] == "/dev/serial/by-id/follower-openrb"
    assert detected["saved_devices"]["follower"]["port"] == "/dev/serial/by-id/follower-openrb"
    teleop = bridge.teleoperate_start({"mode": "test", "profile_id": "fake_omx_ai", "camera_enabled": False})
    assert "--robot.port=/dev/serial/by-id/follower-openrb" in teleop["command_preview"]
    assert "--teleop.port=/dev/serial/by-id/leader-openrb" in teleop["command_preview"]


def test_port_detect_does_not_blindly_save_other_saved_role_when_unverified(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._stable_device_port = lambda port, role: "/dev/serial/by-id/shared-openrb" if port == "/dev/ttyUSB0" else port  # type: ignore[method-assign]
    bridge._serial_motor_ids = lambda port: []  # type: ignore[attr-defined, method-assign]
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": "/dev/ttyUSB0"})
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0"]  # type: ignore[method-assign]

    detected = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})

    assert detected["ok"] is False
    assert detected["failure_code"] == "LEROBOT_PORT_ROLE_NOT_VERIFIED"
    assert detected["saved_devices"]["leader"]["port"] == "/dev/serial/by-id/shared-openrb"
    assert "follower" not in detected["saved_devices"]


def test_live_robot_port_detect_uses_motor_ids_when_no_delta_exists(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    leader = "/dev/serial/by-id/leader-openrb"
    follower = "/dev/serial/by-id/follower-openrb"
    bridge._scan_serial_ports = lambda: [leader, follower]  # type: ignore[method-assign]
    bridge._serial_motor_ids = lambda port: {  # type: ignore[attr-defined, method-assign]
        leader: [1, 2, 3, 4, 5, 6],
        follower: [11, 12, 13, 14, 15, 16],
    }.get(port, [])

    follower_result = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})
    leader_result = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader"})

    assert follower_result["ok"] is True
    assert follower_result["selected_port"] == follower
    assert follower_result["saved_devices"]["follower"]["port"] == follower
    assert leader_result["ok"] is True
    assert leader_result["selected_port"] == leader
    assert leader_result["saved_devices"]["leader"]["port"] == leader


def test_live_robot_port_detect_accepts_partial_role_motor_ids(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    leader = "/dev/serial/by-id/leader-openrb"
    follower = "/dev/serial/by-id/follower-openrb"
    bridge._scan_serial_ports = lambda: [leader, follower]  # type: ignore[method-assign]
    bridge._serial_motor_ids = lambda port: {  # type: ignore[attr-defined, method-assign]
        leader: [1, 2, 3, 4, 5, 6],
        follower: [11, 13, 14, 15, 16],
    }.get(port, [])

    follower_result = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})

    assert follower_result["ok"] is True
    assert follower_result["selected_port"] == follower
    assert follower_result["saved_device"]["source"] == "id_detect:partial"
    assert follower_result["saved_devices"]["follower"]["port"] == follower
    assert follower_result["role_verification"]["matched_motor_ids"] == [11, 13, 14, 15, 16]


def test_removed_robot_port_does_not_save_baseline_serial_identity_without_live_role_probe(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    baseline_phase = True

    def matching_symlink(device_path: str, patterns: list[str]) -> str:
        if baseline_phase and device_path == "/dev/ttyACM0" and patterns == ["/dev/serial/by-id/*"]:
            return "/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_FOLLOWER123-if00"
        return ""

    bridge._matching_symlink = matching_symlink  # type: ignore[method-assign]
    bridge._scan_serial_ports = lambda: ["/dev/ttyACM0"]  # type: ignore[method-assign]
    bridge.ports_baseline({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})
    baseline_phase = False
    bridge._scan_serial_ports = lambda: []  # type: ignore[method-assign]

    detected = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})

    assert detected["ok"] is False
    assert detected["failure_code"] == "LEROBOT_PORT_REMOVED_UNVERIFIED"
    assert detected["candidates"] == ["/dev/ttyACM0"]
    assert "follower" not in detected.get("saved_devices", {})


def test_camera_paths_are_preserved_for_opencv(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    by_id = "/dev/v4l/by-id/usb-Camera-video-index0"

    assert bridge._runtime_device_port(by_id, "camera", live=True) == by_id
    assert bridge._opencv_camera_config("/dev/video1", 30)["index_or_path"] == "/dev/video1"
    assert bridge._opencv_capture_ref("/dev/video1") == "/dev/video1"


def test_camera_test_returns_synthetic_preview_in_test_mode(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.camera_test({"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "port": "/dev/video0", "camera_key": "wrist"})

    assert result["ok"] is True
    assert result["tool"] == "lerobot.camera.test"
    assert result["camera_key"] == "wrist"
    assert result["capture"]["synthetic"] is True
    assert Path(result["capture"]["path"]).exists()


def test_multiple_camera_ports_are_saved_per_key_and_used_in_commands(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    top = bridge.ports_save({"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "camera_key": "top", "port": "/dev/video0"})
    wrist = bridge.ports_save({"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "camera_key": "wrist", "port": "/dev/video2"})
    teleop = bridge.teleoperate_start({"mode": "test", "profile_id": "fake_omx_ai", "camera_enabled": True})

    assert top["saved_devices"]["cameras"]["top"]["raw_port"] == "/dev/video0" if top["saved_devices"]["cameras"]["top"].get("raw_port") else top["saved_devices"]["cameras"]["top"]["port"] == "/dev/video0"
    assert wrist["saved_devices"]["cameras"]["wrist"]["raw_port"] == "/dev/video2" if wrist["saved_devices"]["cameras"]["wrist"].get("raw_port") else wrist["saved_devices"]["cameras"]["wrist"]["port"] == "/dev/video2"
    camera_arg = next(arg for arg in teleop["command_preview"] if arg.startswith("--robot.cameras="))
    cameras = json.loads(camera_arg.removeprefix("--robot.cameras="))
    assert cameras["top"]["type"] == "opencv"
    assert cameras["top"]["index_or_path"] == "/dev/video0"
    assert cameras["wrist"]["type"] == "opencv"
    assert cameras["wrist"]["index_or_path"] == "/dev/video2"


def test_realsense_camera_mode_uses_depth_rgb_for_top_and_wrist_at_default_15fps(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)

    class FakeDevice:
        def __init__(self, *, name: str, serial: str, product_line: str = "D400") -> None:
            self.values = {
                "name": name,
                "serial_number": serial,
                "product_line": product_line,
            }

        def supports(self, info: str) -> bool:
            return info in self.values

        def get_info(self, info: str) -> str:
            return self.values[info]

    class FakeContext:
        def query_devices(self):
            return [
                FakeDevice(name="Intel RealSense D405", serial="352122273019"),
                FakeDevice(name="Intel RealSense D455F", serial="341522300873"),
            ]

    fake_rs = SimpleNamespace(
        camera_info=SimpleNamespace(name="name", serial_number="serial_number", product_line="product_line"),
        context=lambda: FakeContext(),
    )
    monkeypatch.setitem(sys.modules, "pyrealsense2", fake_rs)

    top = bridge.ports_save(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "top",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    wrist = bridge.ports_save(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "wrist",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    teleop = bridge.teleoperate_start({"mode": "test", "profile_id": "fake_omx_ai", "camera_enabled": True, "camera_fps": 15})

    assert top["saved_devices"]["cameras"]["top"]["backend"] == "intelrealsense"
    assert wrist["saved_devices"]["cameras"]["wrist"]["backend"] == "intelrealsense"
    assert top["saved_devices"]["cameras"]["top"]["color_format"] == "rgb8"
    assert wrist["saved_devices"]["cameras"]["wrist"]["color_format"] == "bgr8"
    assert top["saved_devices"]["cameras"]["top"]["depth_scale_m_per_unit"] == 0.001
    assert wrist["saved_devices"]["cameras"]["wrist"]["depth_scale_m_per_unit"] == 0.0001
    camera_arg = next(arg for arg in teleop["command_preview"] if arg.startswith("--robot.cameras="))
    cameras = json.loads(camera_arg.removeprefix("--robot.cameras="))
    assert cameras["top"] == {
        "type": "intelrealsense",
        "serial_number_or_name": "341522300873",
        "width": 640,
        "height": 480,
        "fps": 15,
        "color_format": "rgb8",
        "use_depth": True,
        "align_depth_to_color": True,
        "depth_scale_m_per_unit": 0.001,
        "depth_clip_min_mm": 0.0,
        "depth_clip_max_mm": 2000.0,
        "warmup_s": 5,
    }
    assert cameras["wrist"] == {
        "type": "intelrealsense",
        "serial_number_or_name": "352122273019",
        "width": 640,
        "height": 480,
        "fps": 15,
        "color_format": "bgr8",
        "use_depth": True,
        "align_depth_to_color": True,
        "depth_scale_m_per_unit": 0.0001,
        "depth_clip_min_mm": 50.0,
        "depth_clip_max_mm": 150.0,
        "warmup_s": 5,
    }


def test_record_session_fails_if_requested_realsense_depth_is_missing_from_dataset(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "rgb_only"
    (dataset / "meta").mkdir(parents=True)
    (dataset / "meta" / "info.json").write_text(
        json.dumps(
            {
                "features": {
                    "observation.images.top": {"dtype": "video", "shape": [480, 640, 3]},
                    "observation.images.wrist": {"dtype": "video", "shape": [480, 640, 3]},
                }
            }
        ),
        encoding="utf-8",
    )
    session = {
        "session_id": "record-depth-missing",
        "workflow": "record",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "COMPLETED",
        "dataset_path": str(dataset),
        "expected_depth_features": ["observation.images.top_depth", "observation.images.wrist_depth"],
        "command_preview": [],
        "step_trace": [],
        "log_path": "",
        "returncode": 0,
    }

    result = bridge._session_response("lerobot.record.status", "live", session, [])

    assert result["ok"] is False
    assert result["status"] == "FAILED"
    assert result["failure_code"] == "LEROBOT_REALSENSE_DEPTH_FEATURE_MISSING"
    assert result["dataset_depth_validation"]["missing_depth_features"] == [
        "observation.images.top_depth",
        "observation.images.wrist_depth",
    ]


def test_dataset_inspect_reads_real_metadata_and_depth_features(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "depth_dataset"
    _make_trainable_lerobot_dataset(dataset)
    info_path = dataset / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info.update(
        {
            "total_episodes": 2,
            "fps": 15,
            "features": {
                "observation.images.top": {"dtype": "video", "shape": [480, 640, 3]},
                "observation.images.top_depth": {"dtype": "video", "shape": [480, 640, 3]},
                "observation.images.wrist": {"dtype": "video", "shape": [480, 640, 3]},
                "observation.images.wrist_depth": {"dtype": "video", "shape": [480, 640, 3]},
                "observation.state": {"dtype": "float32", "shape": [6]},
                "action": {"dtype": "float32", "shape": [6]},
            },
        }
    )
    info_path.write_text(json.dumps(info), encoding="utf-8")

    result = bridge.dataset_inspect(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
        }
    )

    assert result["ok"] is True
    assert result["dataset"]["episode_count"] == 2
    assert result["dataset"]["fps"] == 15
    assert result["dataset"]["has_depth_features"] is True
    assert result["dataset"]["depth_features"] == [
        "observation.images.top_depth",
        "observation.images.wrist_depth",
    ]
    assert "observation.images.top_depth" in result["dataset"]["features"]


def test_dataset_inspect_restores_profile_and_pipeline_from_metadata(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "recorded"
    _make_trainable_lerobot_dataset(dataset)
    (dataset / "meta" / "atr_pipeline.json").write_text(
        json.dumps(
            {
                "version": 1,
                "profile_id": "fake_omx_ai",
                "observation_pipeline_id": "raw_depth_adapter",
                "dataset_repo_id": "jin/recorded",
            }
        ),
        encoding="utf-8",
    )

    result = bridge.dataset_inspect({"mode": "test", "profile_id": "fake_omx_ai", "dataset_path": str(dataset)})

    assert result["ok"] is True
    assert result["dataset"]["robot_profile_id"] == "fake_omx_ai"
    assert result["dataset"]["observation_pipeline_id"] == "raw_depth_adapter"
    assert result["dataset"]["profile_restored_from_metadata"] is True
    assert result["dataset"]["pipeline_metadata_path"] == str(dataset / "meta" / "atr_pipeline.json")


def test_dataset_inspect_health_is_ok_for_complete_sidecars(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "health_complete"
    _make_trainable_lerobot_dataset(dataset)
    _write_raw_depth_frames(dataset)
    _write_isaac_rgbd_render_fixture(dataset, camera="wrist")
    augmented = bridge.augment_isaac_dataset(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/health_complete",
            "isaac_data_augmentation_variants": 1,
            "isaac_data_augmentation_max_frames": 1,
            "isaac_data_augmentation_cameras": "wrist",
        }
    )
    assert augmented["ok"] is True

    result = bridge.dataset_inspect(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    health = result["dataset_health"]
    assert health["severity"] == "ok"
    assert health["blocking_count"] == 0
    assert health["metrics"]["episodes"] == 1
    assert health["metrics"]["original_frames"] == 1
    assert health["sidecars"]["raw_depth"]["camera_counts"] == {"top": 2, "wrist": 2}
    assert health["sidecars"]["isaac_rgbd"]["manifest_count"] == 1
    assert health["sidecars"]["isaac_rgbd"]["rendered_count"] == 1
    assert health["sidecars"]["isaac_augmentation"]["valid_variant_count"] == 1


def test_dataset_raw_depth_health_counts_episode_scoped_frames(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "episode_scoped_raw"
    _write_raw_depth_manifest(dataset)
    for camera in ("top", "wrist"):
        camera_dir = dataset / "sidecar" / "depth_raw" / camera / "episode_000000"
        camera_dir.mkdir(parents=True, exist_ok=True)
        for index in range(3):
            Image.fromarray(np.full((8, 8), 420 + index, dtype=np.uint16)).save(camera_dir / f"frame_{index:06d}.png")

    health = bridge._dataset_raw_depth_health(dataset)  # noqa: SLF001

    assert health["camera_counts"] == {"top": 3, "wrist": 3}
    assert health["total_frame_count"] == 6


def test_record_raw_depth_sidecar_status_counts_episode_scoped_frames(tmp_path: Path) -> None:
    root = tmp_path / "sidecar" / "depth_raw"
    for camera in ("top", "wrist"):
        episode_dir = root / camera / "episode_000000"
        episode_dir.mkdir(parents=True, exist_ok=True)
        for frame_index in range(2):
            (episode_dir / f"frame_{frame_index:06d}.png").write_bytes(f"{camera}-{frame_index}".encode("utf-8"))

    status = LeRobotBridge._record_raw_depth_sidecar_status(
        {
            "enabled": True,
            "root": str(root),
            "expected_camera_keys": ["top", "wrist"],
            "format": "png16",
        }
    )

    assert status["status"] == "ok"
    assert status["file_counts"] == {"top": 2, "wrist": 2}
    assert status["missing_camera_keys"] == []


def test_dataset_inspect_health_warns_for_missing_optional_sidecars(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "health_partial"
    _make_trainable_lerobot_dataset(dataset)
    _write_raw_depth_frames(dataset)

    result = bridge.dataset_inspect(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    health = result["dataset_health"]
    assert health["severity"] == "warning"
    issue_codes = {item["code"] for item in health["issues"]}
    assert "LEROBOT_ISAAC_RGBD_SIDECAR_MISSING" in issue_codes
    assert "LEROBOT_ISAAC_AUGMENTATION_MISSING" in issue_codes
    assert health["blocking_count"] == 0


def test_dataset_inspect_health_blocks_raw_depth_adapter_without_raw_depth(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "health_missing"
    _make_trainable_lerobot_dataset(dataset)
    shutil.rmtree(dataset / "sidecar")

    result = bridge.dataset_inspect(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    health = result["dataset_health"]
    assert health["severity"] == "blocking"
    assert health["blocking_count"] == 1
    assert health["sidecars"]["raw_depth"]["available"] is False
    assert health["issues"][0]["code"] == "LEROBOT_RAW_DEPTH_SIDECAR_MISSING"


def test_realsense_scan_does_not_fallback_to_v4l_by_id_when_sdk_query_fails(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)

    class BrokenContext:
        def query_devices(self):
            raise RuntimeError("UVCIOC_CTRL_QUERY failed")

    monkeypatch.setitem(sys.modules, "pyrealsense2", SimpleNamespace(context=lambda: BrokenContext()))

    def fake_glob(pattern: str) -> list[str]:
        if pattern == "/dev/v4l/by-id/*RealSense*":
            return [
                "/dev/v4l/by-id/usb-Intel_R__RealSense_TM__Depth_Camera_405_Intel_R__RealSense_TM__Depth_Camera_405_352122273019-video-index0",
                "/dev/v4l/by-id/usb-Intel_R__RealSense_TM__Depth_Camera_455f_Intel_R__RealSense_TM__Depth_Camera_455f-video-index0",
            ]
        return []

    monkeypatch.setattr("device_bridges.lerobot_bridge.glob.glob", fake_glob)

    assert bridge._scan_realsense_camera_ids() == []


def test_realsense_wrist_detect_does_not_save_top_camera_when_d405_missing(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)

    monkeypatch.setattr(bridge, "_scan_realsense_camera_ids", lambda: ["341522300873"], raising=False)
    monkeypatch.setattr(
        bridge,
        "_scan_realsense_camera_entries",
        lambda: [{"name": "Intel RealSense D455F", "serial": "341522300873", "product_line": "D400"}],
        raising=False,
    )

    result = bridge.ports_detect(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "wrist",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_REALSENSE_ROLE_CAMERA_NOT_FOUND"
    assert "expected=352122273019" in result["message"]
    assert "341522300873" in result["message"]


def test_realsense_live_save_prefers_sdk_serial_for_top_d455(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)

    class FakeDevice:
        def __init__(self, *, name: str, serial: str, product_line: str = "D400") -> None:
            self.values = {
                "name": name,
                "serial_number": serial,
                "product_line": product_line,
            }

        def supports(self, info: str) -> bool:
            return info in self.values

        def get_info(self, info: str) -> str:
            return self.values[info]

    class FakeContext:
        def query_devices(self):
            return [
                FakeDevice(name="Intel RealSense D405", serial="352122273019"),
                FakeDevice(name="Intel RealSense D455F", serial="341522300873"),
            ]

    fake_rs = SimpleNamespace(
        camera_info=SimpleNamespace(name="name", serial_number="serial_number", product_line="product_line"),
        context=lambda: FakeContext(),
    )
    monkeypatch.setitem(sys.modules, "pyrealsense2", fake_rs)

    result = bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "top",
            "camera_backend": "realsense",
        }
    )

    assert result["saved_devices"]["cameras"]["top"]["serial_number_or_name"] == "341522300873"
    assert result["saved_devices"]["cameras"]["top"]["port"] == "341522300873"


def test_realsense_live_save_replaces_non_sdk_identifier_with_role_serial(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)

    class FakeDevice:
        def __init__(self, *, name: str, serial: str, product_line: str = "D400") -> None:
            self.values = {
                "name": name,
                "serial_number": serial,
                "product_line": product_line,
            }

        def supports(self, info: str) -> bool:
            return info in self.values

        def get_info(self, info: str) -> str:
            return self.values[info]

    class FakeContext:
        def query_devices(self):
            return [
                FakeDevice(name="Intel RealSense D405", serial="352122273019"),
                FakeDevice(name="Intel RealSense D455F", serial="341522300873"),
            ]

    fake_rs = SimpleNamespace(
        camera_info=SimpleNamespace(name="name", serial_number="serial_number", product_line="product_line"),
        context=lambda: FakeContext(),
    )
    monkeypatch.setitem(sys.modules, "pyrealsense2", fake_rs)

    result = bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "wrist",
            "camera_backend": "realsense",
            "port": "/dev/v4l/by-id/usb-Intel_R__RealSense_TM__Depth_Camera_405-video-index0",
        }
    )

    assert result["ok"] is True
    assert result["saved_devices"]["cameras"]["wrist"]["serial_number_or_name"] == "352122273019"
    assert result["saved_devices"]["cameras"]["wrist"]["port"] == "352122273019"
    assert result["raw_selected_port"].startswith("/dev/v4l/by-id/")


def test_realsense_live_detect_prefers_role_specific_sdk_serial(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)

    class FakeDevice:
        def __init__(self, *, name: str, serial: str, product_line: str = "D400") -> None:
            self.values = {
                "name": name,
                "serial_number": serial,
                "product_line": product_line,
            }

        def supports(self, info: str) -> bool:
            return info in self.values

        def get_info(self, info: str) -> str:
            return self.values[info]

    class FakeContext:
        def query_devices(self):
            # D455F sorts before D405 by serial, so detect must use the camera_key hint.
            return [
                FakeDevice(name="Intel RealSense D405", serial="352122273019"),
                FakeDevice(name="Intel RealSense D455F", serial="341522300873"),
            ]

    fake_rs = SimpleNamespace(
        camera_info=SimpleNamespace(name="name", serial_number="serial_number", product_line="product_line"),
        context=lambda: FakeContext(),
    )
    monkeypatch.setitem(sys.modules, "pyrealsense2", fake_rs)

    result = bridge.ports_detect(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "wrist",
            "camera_backend": "realsense",
        }
    )

    assert result["ok"] is True
    assert result["saved_devices"]["cameras"]["wrist"]["serial_number_or_name"] == "352122273019"
    assert result["saved_devices"]["cameras"]["wrist"]["port"] == "352122273019"


def test_teleoperate_omits_cameras_until_enabled(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    bridge.ports_save({"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "camera_key": "top", "port": "/dev/video0"})
    teleop = bridge.teleoperate_start({"mode": "test", "profile_id": "fake_omx_ai"})

    assert not any(arg.startswith("--robot.cameras=") for arg in teleop["command_preview"])


def test_manual_save_prefers_stable_device_path_when_available(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._stable_device_port = lambda port, role: "/dev/serial/by-id/mock-follower" if port == "/dev/ttyACM0" else port  # type: ignore[method-assign]

    saved = bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": "/dev/ttyACM0"})

    assert saved["ok"] is True
    assert saved["saved_device"]["port"] == "/dev/serial/by-id/mock-follower"
    assert saved["saved_device"]["raw_port"] == "/dev/ttyACM0"
    assert saved["saved_devices"]["follower"]["port"] == "/dev/serial/by-id/mock-follower"


def test_custom_udev_style_device_name_is_preserved(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    saved = bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": "/dev/omx_follower"})

    assert saved["ok"] is True
    assert saved["saved_device"]["port"] == "/dev/omx_follower"
    assert "raw_port" not in saved["saved_device"]


def test_leader_and_follower_save_does_not_block_same_serial_port(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    follower = bridge.ports_save({"mode": "test", "profile_id": "fake_omx_ai", "device_role": "follower", "port": "/dev/ttyUSB0"})
    leader = bridge.ports_save({"mode": "test", "profile_id": "fake_omx_ai", "device_role": "leader", "port": "/dev/ttyUSB0"})

    assert follower["ok"] is True
    assert leader["ok"] is True
    assert leader["saved_devices"]["follower"]["port"] == "/dev/ttyUSB0"
    assert leader["saved_devices"]["leader"]["port"] == "/dev/ttyUSB0"


def test_live_rollout_blocks_unavailable_saved_follower_port(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    policy_dir = tmp_path / "outputs" / "train" / "job" / "checkpoints" / "last" / "pretrained_model"
    _make_policy_checkpoint(policy_dir)
    missing_port = tmp_path / "missing-follower"
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(missing_port)})
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: (_ for _ in ()).throw(AssertionError("must not start live rollout"))  # type: ignore[method-assign]

    result = bridge.rollout_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "policy_path": str(policy_dir),
            "confirm_live_execute": True,
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_DEVICE_PORT_UNAVAILABLE"
    assert str(missing_port) in result["message"]


def test_live_teleoperate_blocks_missing_saved_realsense_camera_before_process_start(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "top",
            "port": "341522300873",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "wrist",
            "port": "352122273019",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    monkeypatch.setattr(bridge, "_live_block_if_needed", lambda **_: None)
    monkeypatch.setattr(
        bridge,
        "_scan_live_realsense_camera_entries",
        lambda: [{"name": "Intel RealSense D455F", "serial": "341522300873", "product_line": "D400"}],
        raising=False,
    )
    bridge._start_live_process = lambda **_: (_ for _ in ()).throw(AssertionError("must not start live teleop"))  # type: ignore[method-assign]

    result = bridge.teleoperate_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "camera_enabled": True,
            "confirm_live_execute": True,
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_REALSENSE_CAMERA_UNAVAILABLE"
    assert "wrist=352122273019" in result["message"]
    assert "visible RealSense devices: 341522300873" in result["message"]


def test_live_rollout_blocks_missing_saved_realsense_camera_before_policy_process_start(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    follower = tmp_path / "omx_follower"
    follower.touch()
    policy_dir = tmp_path / "outputs" / "train" / "job" / "checkpoints" / "last" / "pretrained_model"
    _make_policy_checkpoint(policy_dir)
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "top",
            "port": "341522300873",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "wrist",
            "port": "352122273019",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    monkeypatch.setattr(bridge, "_live_block_if_needed", lambda **_: None)
    monkeypatch.setattr(
        bridge,
        "_scan_live_realsense_camera_entries",
        lambda: [{"name": "Intel RealSense D455F", "serial": "341522300873", "product_line": "D400"}],
        raising=False,
    )
    bridge._start_live_process = lambda **_: (_ for _ in ()).throw(AssertionError("must not start live rollout"))  # type: ignore[method-assign]

    result = bridge.rollout_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "policy_path": str(policy_dir),
            "camera_enabled": True,
            "confirm_live_execute": True,
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_REALSENSE_CAMERA_UNAVAILABLE"
    assert "wrist=352122273019" in result["message"]


def test_pi05_live_rollout_omits_realsense_color_format_for_pi05_runtime(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    follower = tmp_path / "omx_follower"
    follower.touch()
    policy_dir = tmp_path / "outputs" / "train" / "job" / "checkpoints" / "000500" / "pretrained_model"
    _make_policy_checkpoint(policy_dir)
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "top",
            "port": "341522300873",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    bridge.ports_save(
        {
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "device_role": "camera",
            "camera_key": "wrist",
            "port": "352122273019",
            "camera_backend": "realsense",
            "camera_use_depth": True,
        }
    )
    monkeypatch.setattr(bridge, "_live_block_if_needed", lambda **_: None)
    monkeypatch.setattr(
        bridge,
        "_scan_live_realsense_camera_entries",
        lambda: [
            {"name": "Intel RealSense D455F", "serial": "341522300873", "product_line": "D400"},
            {"name": "Intel RealSense D405", "serial": "352122273019", "product_line": "D400"},
        ],
        raising=False,
    )
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    result = bridge.rollout_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "policy_type": "pi05",
            "policy_path": str(policy_dir),
            "camera_enabled": True,
            "camera_fps": 15,
            "confirm_live_execute": True,
        }
    )

    camera_arg = next(arg for arg in result["command_preview"] if arg.startswith("--robot.cameras="))
    cameras = json.loads(camera_arg.removeprefix("--robot.cameras="))
    assert result["ok"] is True
    assert cameras["top"]["type"] == "intelrealsense"
    assert cameras["wrist"]["type"] == "intelrealsense"
    assert "color_format" not in cameras["top"]
    assert "color_format" not in cameras["wrist"]
    assert cameras["top"]["use_depth"] is True
    assert cameras["wrist"]["use_depth"] is True


def test_live_train_starts_passive_monitor_for_gui_training(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset)
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": str(tmp_path / "train.log"), "returncode": None}}  # type: ignore[method-assign]
    bridge._start_training_monitor = lambda session, request: {"status": "running", "pid": 456, "log_path": str(tmp_path / "watch.jsonl")}  # type: ignore[attr-defined]

    result = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "policy_type": "act",
            "steps": 1,
            "confirm_live_execute": True,
        }
    )

    assert result["ok"] is True
    assert result["workflow"] == "train"
    assert result["monitor"]["status"] == "running"
    assert result["monitor"]["pid"] == 456


def test_extra_camera_can_be_deleted_but_default_camera_is_protected(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    saved = bridge.ports_save({"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "camera_key": "side", "port": "/dev/video4"})
    deleted = bridge.ports_delete({"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "camera_key": "side"})
    protected = bridge.ports_delete({"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "camera_key": "top"})

    assert saved["ok"] is True
    assert deleted["ok"] is True
    assert "side" not in deleted["saved_devices"]["cameras"]
    assert protected["ok"] is False
    assert protected["failure_code"] == "LEROBOT_DEFAULT_CAMERA_DELETE_BLOCKED"


def test_teleoperate_start_stop_session(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.teleoperate_start({"mode": "test", "profile_id": "fake_omx_ai"})
    stopped = bridge.teleoperate_stop({"mode": "test", "session_id": started["session_id"]})

    assert started["ok"] is True
    assert started["workflow"] == "teleoperate"
    assert started["status"] == "TELEOP_ACTIVE"
    assert stopped["ok"] is True
    assert stopped["status"] == "STOPPED"
    assert bridge.sessions_recent()[0]["session_id"] == started["session_id"]


def test_record_command_includes_required_single_task(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.record_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "task_instruction": "Pick up the cylinder",
            "num_episodes": 5,
        }
    )

    assert started["ok"] is True
    assert "--dataset.repo_id=jin/record-test" in started["command_preview"]
    assert "--dataset.single_task=Pick up the cylinder" in started["command_preview"]
    assert "--dataset.num_episodes=5" in started["command_preview"]


def test_train_command_includes_runtime_parameters_and_progress(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "act",
            "output_dir": "outputs/train/robotis_omx_ai_act_record-test",
            "job_name": "robotis_omx_ai_act_record-test",
            "device": "cuda",
            "policy_repo_id": "jin/robotis_omx_ai_act_policy",
            "batch_size": 32,
            "steps": 20000,
            "num_workers": 16,
            "eval_freq": 2000,
            "log_freq": 100,
            "save_freq": 2000,
            "save_checkpoint": True,
            "optimizer_type": "adamw",
            "policy_use_amp": True,
        }
    )

    assert started["ok"] is True
    assert started["workflow"] == "train"
    assert "--dataset.repo_id=jin/record-test" in started["command_preview"]
    assert "--dataset.video_backend=torchcodec" in started["command_preview"]
    assert "--policy.type=act" in started["command_preview"]
    assert "--output_dir=outputs/train/robotis_omx_ai_act_record-test" in started["command_preview"]
    assert "--job_name=robotis_omx_ai_act_record-test" in started["command_preview"]
    assert "--policy.device=cuda" in started["command_preview"]
    assert "--policy.repo_id=jin/robotis_omx_ai_act_policy" in started["command_preview"]
    assert "--batch_size=32" in started["command_preview"]
    assert "--steps=20000" in started["command_preview"]
    assert "--num_workers=16" in started["command_preview"]
    assert "--policy.use_amp=true" in started["command_preview"]
    assert started["training"]["current_step"] == 20000
    assert started["training"]["total_steps"] == 20000
    assert started["training"]["progress_percent"] == 100.0
    assert started["training_preflight"]["stage"] == "ready_to_start"
    assert started["training_preflight"]["done"] == started["training_preflight"]["total"]
    assert started["training_preflight"]["percent"] == 100.0
    assert "resolve_dataset" in [item["stage"] for item in started["training_preflight"]["stages"]]


def test_act_train_uses_huggingface_lerobot_defaults(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "act",
        }
    )

    assert started["ok"] is True
    assert "--policy.type=act" in started["command_preview"]
    assert "--policy.device=cuda" in started["command_preview"]
    assert "--batch_size=8" in started["command_preview"]
    assert "--steps=100000" in started["command_preview"]
    assert "--num_workers=4" in started["command_preview"]
    assert "--eval_freq=20000" in started["command_preview"]
    assert "--log_freq=200" in started["command_preview"]
    assert "--save_freq=20000" in started["command_preview"]
    assert all(not arg.startswith("--optimizer.type=") for arg in started["command_preview"])


def test_pi05_train_uses_dedicated_runtime_and_hf_base_policy(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "job_name": "atr_lerobot_pi05_train",
            "steps": 3000,
        }
    )

    assert started["ok"] is True
    assert "-n" in started["command_preview"]
    assert started["command_preview"][started["command_preview"].index("-n") + 1] == "lerobot-pi05-torch211"
    assert "--policy.type=pi05" in started["command_preview"]
    assert "--policy.pretrained_path=lerobot/pi05_base" in started["command_preview"]
    assert "--batch_size=16" in started["command_preview"]
    assert "--num_workers=12" in started["command_preview"]
    assert "--eval_freq=500" in started["command_preview"]
    assert "--log_freq=50" in started["command_preview"]
    assert "--save_freq=500" in started["command_preview"]
    assert all(not arg.startswith("--eval.batch_size=") for arg in started["command_preview"])
    assert "--policy.n_obs_steps=1" in started["command_preview"]
    assert "--policy.chunk_size=50" in started["command_preview"]
    assert "--policy.n_action_steps=50" in started["command_preview"]
    assert "--policy.compile_model=true" in started["command_preview"]
    assert "--policy.gradient_checkpointing=true" in started["command_preview"]
    assert "--policy.dtype=bfloat16" in started["command_preview"]
    assert "--policy.freeze_vision_encoder=false" in started["command_preview"]
    assert "--policy.train_expert_only=false" in started["command_preview"]
    assert "--wandb.enable=true" in started["command_preview"]
    assert all(not arg.startswith("--policy.use_amp=") for arg in started["command_preview"])
    assert "--wandb.mode=offline" in started["command_preview"]


def test_xvla_train_uses_lerobot_runtime_and_soft_prompt_defaults(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "xvla",
        }
    )

    assert started["ok"] is True
    assert "-n" in started["command_preview"]
    assert started["command_preview"][started["command_preview"].index("-n") + 1] == "lerobot-pi05-torch211"
    assert "--policy.type=xvla" in started["command_preview"]
    assert "--policy.pretrained_path=lerobot/xvla-base" in started["command_preview"]
    assert "--steps=20000" in started["command_preview"]
    assert "--policy.dtype=bfloat16" in started["command_preview"]
    assert "--policy.action_mode=auto" in started["command_preview"]
    assert "--policy.freeze_vision_encoder=false" in started["command_preview"]
    assert "--policy.freeze_language_encoder=false" in started["command_preview"]
    assert "--policy.train_policy_transformer=true" in started["command_preview"]
    assert "--policy.train_soft_prompts=true" in started["command_preview"]
    assert "--dataset.video_backend=torchcodec" in started["command_preview"]
    assert "--policy.type=pi05" not in started["command_preview"]


def test_smolvla_train_uses_lerobot_runtime_and_base_policy_defaults(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "smolvla",
        }
    )

    assert started["ok"] is True
    assert "-n" in started["command_preview"]
    assert started["command_preview"][started["command_preview"].index("-n") + 1] == "lerobot-pi05-torch211"
    assert "--policy.type=smolvla" in started["command_preview"]
    assert "--policy.pretrained_path=lerobot/smolvla_base" in started["command_preview"]
    assert "--steps=20000" in started["command_preview"]
    assert "--batch_size=8" in started["command_preview"]
    assert "--policy.n_obs_steps=1" in started["command_preview"]
    assert "--policy.chunk_size=50" in started["command_preview"]
    assert "--policy.n_action_steps=50" in started["command_preview"]
    assert "--policy.freeze_vision_encoder=true" in started["command_preview"]
    assert "--policy.train_expert_only=true" in started["command_preview"]
    assert "--policy.train_state_proj=true" in started["command_preview"]
    assert "--dataset.video_backend=torchcodec" in started["command_preview"]
    assert "--policy.type=pi05" not in started["command_preview"]
    assert all("xvla" not in str(item).lower() for item in started["command_preview"])


def test_policy_presets_include_xvla_base(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.policies_list({"mode": "test"})

    assert result["ok"] is True
    assert any(
        policy["value"] == "lerobot/xvla-base" and policy["policy_type"] == "xvla"
        for policy in result["policies"]
    )


def test_policy_presets_include_smolvla_base(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.policies_list({"mode": "test"})

    assert result["ok"] is True
    assert any(
        policy["value"] == "lerobot/smolvla_base" and policy["policy_type"] == "smolvla"
        for policy in result["policies"]
    )


def test_pi05_train_replaces_stale_act_log_freq_default_with_stable_pi05_default(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "log_freq": 200,
        }
    )

    assert started["ok"] is True
    assert "--log_freq=50" in started["command_preview"]

def test_pi05_train_forces_stale_wandb_request_offline(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "wandb_enable": True,
            "wandb_mode": "",
        }
    )

    assert started["ok"] is True
    assert "--wandb.enable=true" in started["command_preview"]
    assert "--wandb.mode=offline" in started["command_preview"]


def test_pi05_train_uses_local_wandb_base_url_when_requested(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "wandb_enable": True,
            "wandb_mode": "online",
            "wandb_base_url": "http://127.0.0.1:8081",
        }
    )

    assert started["ok"] is True
    assert "--wandb.enable=true" in started["command_preview"]
    assert "--wandb.mode=online" in started["command_preview"]
    assert started["training"]["wandb_base_url"] == "http://127.0.0.1:8081"


def test_train_local_wandb_mode_maps_to_online_cli_mode(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "wandb_enable": True,
            "wandb_mode": "local",
            "wandb_base_url": "http://127.0.0.1:8081",
        }
    )

    assert started["ok"] is True
    assert "--wandb.mode=online" in started["command_preview"]
    assert "--wandb.mode=local" not in started["command_preview"]
    assert started["training"]["wandb_base_url"] == "http://127.0.0.1:8081"


def test_wandb_local_start_returns_conda_server_command_in_test_mode(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.wandb_local_start({"mode": "test", "wandb_base_url": "http://127.0.0.1:8081"})

    assert result["ok"] is True
    assert result["tool"] == "lerobot.wandb_local.start"
    assert result["status"] == "WANDB_LOCAL_READY"
    assert result["url"] == "http://127.0.0.1:8081"
    assert result["command_preview"][:4] == [bridge.config.conda_executable, "run", "--no-capture-output", "-n"]
    assert result["command_preview"][result["command_preview"].index("-n") + 1] == "lerobot-pi05-torch211"
    assert result["command_preview"][-6:] == ["wandb", "server", "start", "--port", "8081", "--no-daemon"]


def test_wandb_local_log_exec_format_error_is_reported_as_failure(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    failure = bridge._wandb_local_failure_from_log("exec /usr/sbin/my_init: exec format error")

    assert failure is not None
    assert failure[0] == "WANDB_LOCAL_PLATFORM_EMULATION_REQUIRED"


def test_pi05_train_respects_explicit_wandb_disabled(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "wandb_enable": False,
            "wandb_mode": "offline",
        }
    )

    assert started["ok"] is True
    assert "--wandb.enable=false" in started["command_preview"]
    assert "--wandb.mode=disabled" in started["command_preview"]


def test_pi05_train_uses_compatible_local_base_snapshot_when_available(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    snapshots = tmp_path / "hf_home_pi05" / "hub" / "models--lerobot--pi05_base" / "snapshots"
    stale = snapshots / "old"
    compatible = snapshots / "new"
    stale.mkdir(parents=True)
    compatible.mkdir(parents=True)
    (stale / "model.safetensors").write_bytes(b"SAFE")
    (stale / "policy_preprocessor.json").write_text('{"steps":[{"registry_name":"relative_actions_processor"}]}', encoding="utf-8")
    (compatible / "model.safetensors").write_bytes(b"SAFE")
    (compatible / "config.json").write_text("{}", encoding="utf-8")
    (compatible / "policy_postprocessor.json").write_text('{"steps":[]}', encoding="utf-8")
    (compatible / "policy_preprocessor.json").write_text('{"steps":[{"registry_name":"normalizer_processor"}]}', encoding="utf-8")

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "policy_pretrained_path": "lerobot/pi05_base",
        }
    )

    assert started["ok"] is True
    assert f"--policy.pretrained_path={compatible}" in started["command_preview"]
    assert not any(arg == "--policy.pretrained_path=lerobot/pi05_base" for arg in started["command_preview"])


def test_pi05_train_rejects_shifted_gui_payload(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "policy_pretrained_path": "atr_lerobot_pi05_train",
            "batch_size": 3000,
            "steps": 4,
            "num_workers": 20000,
            "eval_freq": 200,
            "log_freq": 20000,
            "scheduler_decay_lr": 1.0,
        }
    )

    assert started["ok"] is False
    assert started["failure_code"] == "LEROBOT_TRAIN_CONFIG_INVALID"
    assert "batch_size=3000" in started["message"]
    assert "num_workers=20000" in started["message"]


def test_pi05_train_rejects_stale_memory_heavy_gui_payload(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "batch_size": 200,
            "num_workers": 200,
            "eval_batch_size": 50,
            "policy_n_obs_steps": 100,
            "policy_chunk_size": 50,
            "policy_n_action_steps": 50,
            "train_extra_args": [
                "--policy.compile_model=false",
                "--policy.freeze_vision_encoder=false",
                "--policy.train_expert_only=true",
                '--policy.normalization_mapping={"ACTION":"MEAN_STD","STATE":"MEAN_STD","VISUAL":"IDENTITY"}',
            ],
        }
    )

    assert started["ok"] is False
    assert started["failure_code"] == "LEROBOT_TRAIN_CONFIG_INVALID"
    assert "payload rejected" in started["message"]
    assert "batch_size=200" in started["message"]
    assert "num_workers=200" in started["message"]
    assert "policy.n_obs_steps=100" in started["message"]


def test_train_ignores_optimizer_and_scheduler_values_without_type(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "act",
            "optimizer_lr": 1e-4,
            "scheduler_decay_lr": 1.0,
        }
    )

    assert started["ok"] is True
    assert all(not arg.startswith("--optimizer.") for arg in started["command_preview"])
    assert all(not arg.startswith("--scheduler.") for arg in started["command_preview"])


def test_pi05_live_train_uses_dedicated_hf_cache(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset)
    _mark_lerobot_dataset_v30(dataset)
    captured: dict[str, object] = {}
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]

    def fake_start_live_process(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "session_updates": {"pid": 1234, "log_path": str(tmp_path / "train.log")}}

    bridge._start_live_process = fake_start_live_process  # type: ignore[method-assign]

    started = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "pi05",
            "confirm_live_execute": True,
            "steps": 3000,
        }
    )

    hf_home = tmp_path / "hf_home_pi05"
    assert started["ok"] is True
    env = captured["env_overrides"]
    assert env["HF_HOME"] == str(hf_home)
    assert env["HF_HUB_CACHE"] == str(hf_home / "hub")
    assert env["HF_HUB_DISABLE_XET"] == "1"
    assert env["WANDB_MODE"] == "offline"


def test_vla_live_train_uses_standard_data_pipeline_env(tmp_path: Path) -> None:
    dataset = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset)
    _mark_lerobot_dataset_v30(dataset)
    rgbd_manifest = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_a" / "manifest.jsonl"
    rgbd_manifest.parent.mkdir(parents=True, exist_ok=True)
    rgbd_manifest.write_text(
        json.dumps(
            {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "attempt_id": "attempt_a",
                "episode_index": 0,
                "frame_index": 0,
                "cameras": ["wrist"],
                "files": [{"camera": "wrist", "kind": "rgb", "path": "wrist/rgb.png"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    for policy_type in ("pi05", "xvla", "smolvla"):
        bridge = _bridge(tmp_path)
        bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
        captured: dict[str, object] = {}

        def fake_start_live_process(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"ok": True, "session_updates": {"pid": 1234, "log_path": str(tmp_path / f"{policy_type}.log")}}

        bridge._start_live_process = fake_start_live_process  # type: ignore[method-assign]
        started = bridge.train_start(
            {
                "mode": "live",
                "runtime_mode": "live",
                "profile_id": "fake_omx_ai",
                "dataset_repo_id": "jin/record-test",
                "policy_type": policy_type,
                "confirm_live_execute": True,
                "steps": 1,
            }
        )

        assert started["ok"] is True
        env = captured["env_overrides"]
        assert env["HF_HOME"] == str(tmp_path / "hf_home_pi05")  # type: ignore[index]
        assert env["ATR_LEROBOT_STANDARD_DATA_PIPELINE"] == "1"  # type: ignore[index]
        assert env["ATR_LEROBOT_RAW_DEPTH_ADAPTER"] == "1"  # type: ignore[index]
        assert env["ATR_LEROBOT_ISAAC_RGBD_SOURCE_ADAPTER"] == "1"  # type: ignore[index]
        assert env["ATR_LEROBOT_ISAAC_RGBD_SOURCE_ROOT"] == str(dataset / "sidecar" / "isaac_rgbd")  # type: ignore[index]


def test_pi05_live_train_converts_v21_dataset_copy_to_v30(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset)
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    def fake_convert(converted_repo_id: str, converted_root: Path) -> None:
        _mark_lerobot_dataset_v30(converted_root / converted_repo_id)

    bridge._run_pi05_v30_dataset_conversion = fake_convert  # type: ignore[method-assign]

    started = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "policy_type": "pi05",
            "confirm_live_execute": True,
            "steps": 1,
        }
    )

    converted = tmp_path / "hf_datasets" / "local-pi05-v30" / "jin-record-test"
    assert started["ok"] is True
    assert json.loads((dataset / "meta" / "info.json").read_text(encoding="utf-8"))["codebase_version"] == "v2.1"
    assert json.loads((converted / "meta" / "info.json").read_text(encoding="utf-8"))["codebase_version"] == "v3.0"
    assert "--dataset.repo_id=local-pi05-v30/jin-record-test" in started["command_preview"]
    assert f"--dataset.root={converted}" in started["command_preview"]
    assert started["dataset_repo_id"] == "local-pi05-v30/jin-record-test"
    assert started["dataset_path"] == str(converted)
    assert "Pi0.5 converted jin/record-test v2.1 -> local-pi05-v30/jin-record-test v3.0" in started["step_trace"][1]["detail"]


def test_vla_live_train_converts_v21_dataset_copy_to_v30(tmp_path: Path) -> None:
    for policy_type, label in (("xvla", "X-VLA"), ("smolvla", "SmolVLA")):
        bridge = _bridge(tmp_path)
        dataset = tmp_path / "hf_datasets" / "jin" / f"record-test-{policy_type}"
        _make_trainable_lerobot_dataset(dataset)
        bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
        bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
        bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

        def fake_convert(converted_repo_id: str, converted_root: Path) -> None:
            _mark_lerobot_dataset_v30(converted_root / converted_repo_id)

        bridge._run_pi05_v30_dataset_conversion = fake_convert  # type: ignore[method-assign]

        started = bridge.train_start(
            {
                "mode": "live",
                "runtime_mode": "live",
                "profile_id": "fake_omx_ai",
                "dataset_repo_id": f"jin/record-test-{policy_type}",
                "dataset_root": str(tmp_path / "hf_datasets"),
                "policy_type": policy_type,
                "confirm_live_execute": True,
                "steps": 1,
            }
        )

        converted = tmp_path / "hf_datasets" / "local-pi05-v30" / f"jin-record-test-{policy_type}"
        assert started["ok"] is True
        assert json.loads((dataset / "meta" / "info.json").read_text(encoding="utf-8"))["codebase_version"] == "v2.1"
        assert json.loads((converted / "meta" / "info.json").read_text(encoding="utf-8"))["codebase_version"] == "v3.0"
        assert f"--dataset.repo_id=local-pi05-v30/jin-record-test-{policy_type}" in started["command_preview"]
        assert f"--dataset.root={converted}" in started["command_preview"]
        assert f"{label} converted jin/record-test-{policy_type} v2.1 -> local-pi05-v30/jin-record-test-{policy_type} v3.0" in started["step_trace"][1]["detail"]


def test_pi05_live_train_augments_missing_quantile_stats(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset)
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]
    calls: list[tuple[str, Path]] = []

    def fake_convert(converted_repo_id: str, converted_root: Path) -> None:
        converted = converted_root / converted_repo_id
        _mark_lerobot_dataset_v30(converted)
        (converted / "meta" / "stats.json").write_text(json.dumps({"action": {"mean": [0.0]}}), encoding="utf-8")

    def fake_augment(repo_id: str, root: Path) -> None:
        calls.append((repo_id, root))
        stats_path = root / repo_id / "meta" / "stats.json"
        stats_path.write_text(json.dumps({"observation.state": {"q01": [0.0], "q99": [1.0]}, "action": {"q01": [0.0], "q99": [1.0]}}), encoding="utf-8")

    bridge._run_pi05_v30_dataset_conversion = fake_convert  # type: ignore[method-assign]
    bridge._run_pi05_quantile_stats_augmentation = fake_augment  # type: ignore[method-assign]

    started = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "policy_type": "pi05",
            "confirm_live_execute": True,
            "steps": 1,
        }
    )

    assert started["ok"] is True
    assert calls == [("local-pi05-v30/jin-record-test", tmp_path / "hf_datasets")]


def test_live_train_uses_latest_completed_local_dataset_and_exact_root(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    base = tmp_path / "hf_datasets" / "jin" / "record-test"
    base.mkdir(parents=True)
    (base / "meta").mkdir()
    (base / "meta" / "info.json").write_text("{}", encoding="utf-8")
    latest = tmp_path / "hf_datasets" / "jin" / "record-test-20260507T080347Z"
    _make_trainable_lerobot_dataset(latest)
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    started = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "policy_type": "act",
            "device": "cuda",
            "steps": 1,
            "confirm_live_execute": True,
        }
    )

    assert started["ok"] is True
    assert "--dataset.repo_id=jin/record-test-20260507T080347Z" in started["command_preview"]
    assert f"--dataset.root={latest}" in started["command_preview"]
    assert "--dataset.video_backend=pyav" in started["command_preview"]
    assert started["dataset_path"] == str(latest)
    assert bridge.sessions_recent()[0]["training"]["dataset_repo_id"] == "jin/record-test-20260507T080347Z"
    assert bridge.sessions_recent()[0]["training"]["dataset_video_backend"] == "pyav"


def test_live_train_existing_output_dir_uses_fresh_output_dir_when_resume_unchecked(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset)
    existing = tmp_path / "outputs" / "train" / "atr_lerobot_train"
    existing.mkdir(parents=True)
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    started = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "output_dir": str(existing),
            "job_name": "atr_lerobot_train",
            "resume": False,
            "steps": 1,
            "confirm_live_execute": True,
        }
    )

    output_arg = next(arg for arg in started["command_preview"] if arg.startswith("--output_dir="))
    output_dir = output_arg.split("=", 1)[1]
    assert started["ok"] is True
    assert output_arg.startswith(f"--output_dir={existing}-")
    assert output_arg != f"--output_dir={existing}"
    assert "--resume=false" in started["command_preview"]
    assert started["output_dir"] == output_dir
    assert started["job_name"] == "atr_lerobot_train"
    assert started["training"]["config"]["output_dir"] == output_dir
    assert started["checkpoint_path"] == str(Path(output_dir) / "checkpoints" / "last" / "pretrained_model")
    assert started["step_trace"][0]["detail"].startswith("training output_dir exists; using fresh output_dir ")


def test_live_train_strips_generated_output_suffix_before_creating_fresh_dir(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset)
    base = tmp_path / "outputs" / "train" / "atr_lerobot_train"
    timestamped = tmp_path / "outputs" / "train" / "atr_lerobot_train-20260507T080347Z"
    base.mkdir(parents=True)
    timestamped.mkdir(parents=True)
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    started = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "output_dir": str(timestamped),
            "job_name": "atr_lerobot_train",
            "resume": False,
            "steps": 1,
            "confirm_live_execute": True,
        }
    )

    output_arg = next(arg for arg in started["command_preview"] if arg.startswith("--output_dir="))
    output_dir = Path(output_arg.split("=", 1)[1])
    assert started["ok"] is True
    assert output_dir.name.startswith("atr_lerobot_train-")
    assert "20260507T080347Z-" not in output_dir.name
    assert not output_arg.startswith(f"--output_dir={timestamped}-")


def test_live_train_resume_keeps_existing_output_dir(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset)
    existing = tmp_path / "outputs" / "train" / "atr_lerobot_train"
    resume_config = existing / "checkpoints" / "001000" / "pretrained_model" / "train_config.json"
    resume_config.parent.mkdir(parents=True)
    resume_config.write_text(json.dumps({"policy": {"type": "act"}}), encoding="utf-8")
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    started = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "output_dir": str(existing),
            "job_name": "atr_lerobot_train",
            "resume": True,
            "steps": 1,
            "confirm_live_execute": True,
        }
    )

    assert started["ok"] is True
    assert f"--output_dir={existing}" in started["command_preview"]
    assert "--resume=true" in started["command_preview"]
    assert f"--config_path={resume_config}" in started["command_preview"]


def test_live_train_resume_requires_existing_train_config(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset)
    existing = tmp_path / "outputs" / "train" / "atr_lerobot_train"
    existing.mkdir(parents=True)
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]

    result = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "output_dir": str(existing),
            "job_name": "atr_lerobot_train",
            "resume": True,
            "steps": 1,
            "confirm_live_execute": True,
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_TRAIN_CONFIG_INVALID"
    assert "train_config.json" in result["message"]


def test_train_status_without_session_returns_idle(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    status = bridge.train_status({"mode": "live", "profile_id": "fake_omx_ai"})

    assert status["ok"] is True
    assert status["workflow"] == "train"
    assert status["status"] == "IDLE"
    assert status["runtime_phase"] == "IDLE"
    assert status["error"] is None


def test_train_progress_parses_live_log_tail(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    log_path = tmp_path / "train.log"
    log_path.write_text("step=250 loss=0.42\n250/1000 [00:10<00:30]\n", encoding="utf-8")
    bridge._sessions["train-active"] = {
        "session_id": "train-active",
        "workflow": "train",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "TRAINING",
        "created_at": "2026-05-06T00:00:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "log_path": str(log_path),
        "pid": None,
        "returncode": None,
        "train_config": {"steps": 1000},
    }

    status = bridge.train_status({"mode": "live", "profile_id": "fake_omx_ai", "session_id": "train-active"})

    assert status["ok"] is True
    assert status["training"]["current_step"] == 250
    assert status["training"]["total_steps"] == 1000
    assert status["training"]["progress_percent"] == 25.0
    assert status["training"]["last_loss"] == 0.42


def test_train_progress_eta_uses_active_step_rate_not_startup_elapsed(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    log_path = tmp_path / "train.log"
    log_path.write_text(
        "\n".join(
            [
                "INFO 2026-06-30 23:09:37 ot_train.py:270 Creating dataset",
                "INFO 2026-06-30 23:09:59 ot_train.py:458 Start offline training on a fixed dataset",
                "INFO 2026-06-30 23:10:00 ot_train.py:488 step:1 smpl:1 ep:0 epch:0.00 loss:0.166 updt_s:1.000 data_s:0.000",
                "INFO 2026-06-30 23:10:01 ot_train.py:488 step:2 smpl:2 ep:0 epch:0.00 loss:0.473 updt_s:0.500 data_s:0.000",
            ]
        ),
        encoding="utf-8",
    )
    bridge._sessions["train-active"] = {
        "session_id": "train-active",
        "workflow": "train",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "TRAINING",
        "created_at": "2026-05-06T00:00:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "log_path": str(log_path),
        "pid": None,
        "returncode": None,
        "train_config": {"steps": 100},
    }

    status = bridge.train_status({"mode": "live", "profile_id": "fake_omx_ai", "session_id": "train-active"})

    assert status["ok"] is True
    assert status["training"]["current_step"] == 2
    assert status["training"]["steps_per_sec"] == 1.3333
    assert status["training"]["eta_sec"] == 73.5
    assert status["training"]["last_loss"] == 0.473


def test_refresh_process_status_preserves_cancelled_status(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    session = {
        "session_id": "train-cancelled",
        "workflow": "train",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "CANCELLED",
        "returncode": None,
    }

    class FinishedProcess:
        returncode = -15

        @staticmethod
        def poll() -> int:
            return -15

    bridge._processes["train-cancelled"] = FinishedProcess()  # type: ignore[assignment]
    bridge._refresh_process_status(session)

    assert session["returncode"] == -15
    assert session["status"] == "CANCELLED"


def test_train_progress_parses_compact_k_step_log(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    log_path = tmp_path / "train.log"
    log_path.write_text("INFO step:1K smpl:32K ep:27 loss:0.019\n", encoding="utf-8")
    bridge._sessions["train-active"] = {
        "session_id": "train-active",
        "workflow": "train",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "TRAINING",
        "created_at": "2026-05-06T00:00:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "log_path": str(log_path),
        "pid": None,
        "returncode": None,
        "train_config": {"steps": 3000},
    }

    status = bridge.train_status({"mode": "live", "profile_id": "fake_omx_ai", "session_id": "train-active"})

    assert status["ok"] is True
    assert status["training"]["current_step"] == 1000
    assert status["training"]["total_steps"] == 3000
    assert status["training"]["progress_percent"] == 33.33
    assert status["training"]["last_loss"] == 0.019


def test_train_progress_does_not_inflate_step_from_sample_count(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    log_path = tmp_path / "train.log"
    log_path.write_text("INFO step:1K smpl:33K ep:28 loss:0.017\n", encoding="utf-8")
    bridge._sessions["train-active"] = {
        "session_id": "train-active",
        "workflow": "train",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "TRAINING",
        "created_at": "2026-05-06T00:00:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "log_path": str(log_path),
        "pid": None,
        "returncode": None,
        "train_config": {"steps": 3000, "batch_size": 32},
    }

    status = bridge.train_status({"mode": "live", "profile_id": "fake_omx_ai", "session_id": "train-active"})

    assert status["ok"] is True
    assert status["training"]["current_step"] == 1000
    assert status["training"]["progress_percent"] == 33.33
    assert status["training"]["last_loss"] == 0.017


def test_train_progress_ignores_config_step_summary(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    log_path = tmp_path / "train.log"
    log_path.write_text("INFO cfg.steps=20000 (20K)\nINFO dataset.num_frames=1500\n", encoding="utf-8")
    bridge._sessions["train-active"] = {
        "session_id": "train-active",
        "workflow": "train",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "TRAINING",
        "created_at": "2026-05-06T00:00:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "log_path": str(log_path),
        "pid": None,
        "returncode": None,
        "train_config": {"steps": 20000},
    }

    status = bridge.train_status({"mode": "live", "profile_id": "fake_omx_ai", "session_id": "train-active"})

    assert status["ok"] is True
    assert status["training"]["current_step"] == 0
    assert status["training"]["total_steps"] == 20000
    assert status["training"]["progress_percent"] == 0.0


def test_live_train_start_returns_existing_active_session(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._sessions["train-active"] = {
        "session_id": "train-active",
        "workflow": "train",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "TRAINING",
        "created_at": "2026-05-06T00:00:00+00:00",
        "command_preview": ["lerobot-train"],
        "step_trace": [{"step": "PROCESS_STARTED", "status": "active", "detail": "pid=123"}],
        "log_path": "",
        "pid": 123,
        "returncode": None,
        "dataset_path": "/tmp/dataset",
        "checkpoint_path": "/tmp/checkpoint",
        "train_config": {"steps": 20000},
    }
    bridge._start_live_process = lambda **_: (_ for _ in ()).throw(AssertionError("must not start duplicate train"))  # type: ignore[method-assign]
    bridge._pid_alive = lambda _pid: True  # type: ignore[method-assign]

    result = bridge.train_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "confirm_live_execute": True,
        }
    )

    assert result["ok"] is True
    assert result["idempotent"] is True
    assert result["session_id"] == "train-active"
    assert "already active" in result["message"]


def test_record_existing_dataset_keeps_test_resume_false(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    existing = tmp_path / "hf_datasets" / "jin" / "record-test"
    existing.mkdir(parents=True)

    started = bridge.record_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "task_instruction": "Pick up the cylinder",
        }
    )

    assert started["ok"] is True
    assert "--dataset.repo_id=jin/record-test" in started["command_preview"]
    assert "--resume=false" in started["command_preview"]
    assert started["step_trace"][0]["detail"] == "existing dataset detected; test mode keeps resume=false"


def test_live_record_existing_dataset_uses_fresh_dataset_when_resume_unchecked(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    existing = tmp_path / "hf_datasets" / "jin" / "record-test"
    existing.mkdir(parents=True)
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "task_instruction": "Pick up the cylinder",
            "confirm_live_execute": True,
        }
    )

    assert started["ok"] is True
    repo_arg = next(arg for arg in started["command_preview"] if arg.startswith("--dataset.repo_id="))
    fresh_repo = repo_arg.split("=", 1)[1]
    assert fresh_repo.startswith("jin/record-test-")
    assert started["dataset_repo_id"] == fresh_repo
    assert Path(started["dataset_path"]).parts[-2:] == tuple(fresh_repo.split("/"))
    assert "--resume=false" in started["command_preview"]
    assert started["step_trace"][0]["detail"].startswith("existing dataset detected; recording to fresh dataset ")


def test_live_record_strips_generated_dataset_suffix_before_creating_fresh_dataset(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    existing = tmp_path / "hf_datasets" / "jin" / "record-test-20260507T080347Z"
    existing.mkdir(parents=True)
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test-20260507T080347Z",
            "task_instruction": "Pick up the cylinder",
            "confirm_live_execute": True,
        }
    )

    repo_arg = next(arg for arg in started["command_preview"] if arg.startswith("--dataset.repo_id="))
    fresh_repo = repo_arg.split("=", 1)[1]
    assert started["ok"] is True
    assert fresh_repo.startswith("jin/record-test-")
    assert "20260507T080347Z-" not in fresh_repo
    assert started["dataset_repo_id"] == fresh_repo


def test_live_record_control_sends_lerobot_key_without_marking_complete(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    started = bridge.record_start({"mode": "test", "profile_id": "fake_omx_ai", "dataset_repo_id": "jin/record-test"})
    bridge._sessions[started["session_id"]]["mode"] = "live"
    bridge._send_lerobot_record_control_key = lambda action: {"ok": True, "detail": f"sent {action}"}  # type: ignore[method-assign]

    result = bridge.record_control({"mode": "live", "profile_id": "fake_omx_ai", "session_id": started["session_id"], "action": "next"})

    assert result["ok"] is True
    assert result["status"] == "RECORDING"
    assert result["control"]["detail"] == "sent next"
    assert result["step_trace"][0]["step"] == "SEND_LEROBOT_RECORD_CONTROL"


def test_live_record_control_prefers_active_session_over_stopped_latest(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._sessions["active"] = {
        "session_id": "active",
        "workflow": "record",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "RECORDING",
        "created_at": "2026-05-06T00:00:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "pid": None,
        "returncode": None,
    }
    bridge._sessions["stopped"] = {
        "session_id": "stopped",
        "workflow": "record",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "STOPPED",
        "created_at": "2026-05-06T00:01:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "pid": None,
        "returncode": -15,
    }
    bridge._send_lerobot_record_control_key = lambda action: {"ok": True, "detail": f"sent {action}"}  # type: ignore[method-assign]

    result = bridge.record_control({"mode": "live", "profile_id": "fake_omx_ai", "session_id": "stopped", "action": "retry"})

    assert result["ok"] is True
    assert result["session_id"] == "active"
    assert result["control"]["detail"] == "sent retry"


def test_live_record_control_blocks_next_while_episode_is_saving(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    log_path = tmp_path / "record.log"
    log_path.write_text(
        "INFO Recording episode 0\n"
        "Right arrow key pressed. Exiting loop...\n"
        "INFO Reset the environment\n"
        "Right arrow key pressed. Exiting loop...\n"
        "Map: 100%|##########| 320/320\n"
        "Svt[info]: SVT [version]\n",
        encoding="utf-8",
    )
    bridge._sessions["active"] = {
        "session_id": "active",
        "workflow": "record",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "RECORDING",
        "created_at": "2026-05-06T00:00:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "log_path": str(log_path),
        "pid": None,
        "returncode": None,
    }
    bridge._send_lerobot_record_control_key = lambda action: {"ok": True, "detail": f"sent {action}"}  # type: ignore[method-assign]

    result = bridge.record_control({"mode": "live", "profile_id": "fake_omx_ai", "session_id": "active", "action": "next"})

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_RECORD_CONTROL_WAIT_FOR_NEXT_PHASE"


def test_live_mode_blocks_when_profile_gate_disabled(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.teleoperate_start({"mode": "live", "profile_id": "fake_omx_ai"})

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_LIVE_GATE_DISABLED"
    assert result["step_trace"][0]["status"] == "blocked"


def test_unsafe_arguments_are_rejected(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start({"mode": "test", "profile_id": "fake_omx_ai", "policy_path": "bad;rm -rf"})

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_UNSAFE_ARGUMENT"


def test_policy_list_and_browse_paths_are_gui_ready(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    policies = bridge.policies_list({"mode": "test"})
    browse = bridge.browse_paths({"kind": "dataset", "path": str(tmp_path / "datasets")})

    assert policies["ok"] is True
    assert any(policy["source"] == "huggingface" for policy in policies["policies"])
    assert browse["ok"] is True
    assert browse["path"].endswith("datasets")


def test_policy_browse_filters_to_checkpoint_outputs(tmp_path: Path) -> None:
    policy_dir = tmp_path / "outputs" / "train" / "job" / "checkpoints" / "last" / "pretrained_model"
    _make_policy_checkpoint(policy_dir)
    (policy_dir.parent / "notes.txt").write_text("not a policy output", encoding="utf-8")
    bridge = _bridge(tmp_path)

    browse = bridge.browse_paths({"kind": "policy", "path": str(policy_dir.parent), "include_files": True})

    names = {entry["name"] for entry in browse["entries"]}
    assert "pretrained_model" in names
    assert "notes.txt" not in names


def test_rollout_normalizes_selected_model_file_to_checkpoint_dir(tmp_path: Path) -> None:
    policy_dir = tmp_path / "outputs" / "train" / "job" / "checkpoints" / "last" / "pretrained_model"
    _make_policy_checkpoint(policy_dir, repo_id="jin/pick_and_place_cube_act")
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "policy_path": str(policy_dir / "model.safetensors"),
        }
    )

    assert result["ok"] is True
    assert f"--policy.path={policy_dir}" in result["command_preview"]
    assert "--policy.type=act" not in result["command_preview"]
    assert "--policy.temporal_ensemble_coeff=0.01" in result["command_preview"]
    assert "--policy.n_action_steps=1" in result["command_preview"]
    assert "--robot.max_relative_target=5" in result["command_preview"]
    assert all(not item.startswith("--policy.checkpoint_path=") for item in result["command_preview"])
    assert result["checkpoint_path"] == str(policy_dir)


def test_rollout_uses_eval_dataset_name_and_manual_stop_duration(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "policy_path": "fake://policy",
            "dataset_repo_id": "jin/pick_and_place_cube_rollout",
            "continuous_rollout": True,
            "episode_s": 5.0,
            "num_episodes": 3,
        }
    )

    assert result["ok"] is True
    assert "--dataset.repo_id=jin/eval_pick_and_place_cube_rollout" in result["command_preview"]
    assert f"--dataset.episode_time_s={86400.0}" in result["command_preview"]
    assert "--dataset.num_episodes=1" in result["command_preview"]
    assert "--policy.temporal_ensemble_coeff=0.01" in result["command_preview"]
    assert "--policy.n_action_steps=1" in result["command_preview"]
    assert "--robot.max_relative_target=5" in result["command_preview"]
    assert Path(result["dataset_path"]).parts[-2:] == ("jin", "eval_pick_and_place_cube_rollout")


def test_pi05_rollout_uses_dedicated_runtime_and_rtc_command(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "policy_path": "fake://pi05_policy",
            "policy_type": "pi05",
            "device": "cuda",
            "rollout_rtc_execution_horizon": 20,
            "rollout_rtc_max_guidance_weight": 1.0,
            "rollout_action_queue_size_to_get_new_actions": 60,
            "task_instruction": "Move specimen from 3DP to UTM",
            "continuous_rollout": True,
            "camera_enabled": True,
        }
    )

    assert result["ok"] is True
    assert "-n" in result["command_preview"]
    assert result["command_preview"][result["command_preview"].index("-n") + 1] == "lerobot-pi05-torch211"
    assert any(Path(part).name == "lerobot_pi05_rollout_wrapper.py" for part in result["command_preview"])
    assert "--policy.path=fake://pi05_policy" in result["command_preview"]
    assert "--policy.type=pi05" not in result["command_preview"]
    assert "--device=cuda" in result["command_preview"]
    assert "--policy.device=cuda" in result["command_preview"]
    assert "--rtc.enabled=true" in result["command_preview"]
    assert "--rtc.execution_horizon=20" in result["command_preview"]
    assert "--rtc.max_guidance_weight=1.0" in result["command_preview"]
    assert "--action_queue_size_to_get_new_actions=60" in result["command_preview"]
    assert "--robot.disable_torque_on_disconnect=false" in result["command_preview"]
    assert "--task=Move specimen from 3DP to UTM" in result["command_preview"]
    assert f"--duration={int(86400.0)}" in result["command_preview"]
    camera_arg = next(item for item in result["command_preview"] if item.startswith("--robot.cameras="))
    cameras = json.loads(camera_arg.split("=", 1)[1])
    assert all(camera["fps"] == 30 for camera in cameras.values())


def test_xvla_rollout_uses_generic_lerobot_runtime_without_act_temporal_ensemble(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "policy_path": "fake://xvla_policy",
            "policy_type": "xvla",
            "continuous_rollout": True,
            "camera_enabled": True,
        }
    )

    assert result["ok"] is True
    assert "-n" in result["command_preview"]
    assert result["command_preview"][result["command_preview"].index("-n") + 1] == "lerobot-pi05-torch211"
    assert not any(Path(part).name == "lerobot_pi05_rollout_wrapper.py" for part in result["command_preview"])
    assert "--policy.path=fake://xvla_policy" in result["command_preview"]
    assert "--policy.type=xvla" not in result["command_preview"]
    assert "--policy.temporal_ensemble_coeff=0.01" not in result["command_preview"]
    assert "--policy.n_action_steps=1" not in result["command_preview"]
    assert "--rtc.enabled=true" not in result["command_preview"]
    assert "--robot.max_relative_target=5" in result["command_preview"]


def test_smolvla_rollout_uses_generic_lerobot_runtime_without_act_temporal_ensemble(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "policy_path": "fake://smolvla_policy",
            "policy_type": "smolvla",
            "continuous_rollout": True,
            "camera_enabled": True,
        }
    )

    assert result["ok"] is True
    assert "-n" in result["command_preview"]
    assert result["command_preview"][result["command_preview"].index("-n") + 1] == "lerobot-pi05-torch211"
    assert not any(Path(part).name == "lerobot_pi05_rollout_wrapper.py" for part in result["command_preview"])
    assert "--policy.path=fake://smolvla_policy" in result["command_preview"]
    assert "--policy.type=smolvla" not in result["command_preview"]
    assert "--policy.temporal_ensemble_coeff=0.01" not in result["command_preview"]
    assert "--policy.n_action_steps=1" not in result["command_preview"]
    assert "--rtc.enabled=true" not in result["command_preview"]
    assert "--robot.max_relative_target=5" in result["command_preview"]


def test_rollout_control_fps_can_differ_from_camera_fps(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "policy_path": "fake://pi05_policy",
            "policy_type": "pi05",
            "fps": 60,
            "camera_fps": 30,
            "camera_enabled": True,
        }
    )

    assert result["ok"] is True
    assert "--fps=60" in result["command_preview"]
    camera_arg = next(item for item in result["command_preview"] if item.startswith("--robot.cameras="))
    cameras = json.loads(camera_arg.split("=", 1)[1])
    assert cameras
    assert all(camera["fps"] == 30 for camera in cameras.values())


def test_live_rollout_guard_blocks_duplicate_active_session(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    policy_dir = tmp_path / "outputs" / "train" / "job" / "checkpoints" / "last" / "pretrained_model"
    _make_policy_checkpoint(policy_dir)
    follower_port = tmp_path / "follower-port"
    follower_port.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower_port)})
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._refresh_process_status = lambda session: None  # type: ignore[method-assign]

    def fake_start_live_process(**kwargs: object) -> dict[str, object]:
        return {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start_live_process  # type: ignore[method-assign]
    payload = {
        "mode": "live",
        "runtime_mode": "live",
        "profile_id": "fake_omx_ai",
        "policy_path": str(policy_dir),
        "confirm_live_execute": True,
    }

    first = bridge.rollout_start(payload)
    second = bridge.rollout_start(payload)

    assert first["ok"] is True
    assert first["workflow"] == "rollout"
    assert second["ok"] is False
    assert second["failure_code"] == "LEROBOT_ROLLOUT_ALREADY_ACTIVE"
    assert second["blocked_by_session_id"] == first["session_id"]
    assert second["guard_status"] == "blocked"


def test_rollout_stop_resets_all_tracked_rollout_sessions(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    cleanup_called = []

    bridge._cleanup_lerobot_processes = lambda workflow: cleanup_called.append(workflow) or [  # type: ignore[method-assign]
        {"step": "CLEANUP_LEROBOT_PROCESS_GROUPS", "status": "ok", "detail": workflow}
    ]
    bridge._sessions["rollout-a"] = {
        "session_id": "rollout-a",
        "workflow": "rollout",
        "profile_id": "fake_omx_ai",
        "mode": "live",
        "status": "POLICY_ACTIVE",
        "returncode": None,
        "pid": None,
        "step_trace": [],
        "created_at": "2026-06-04T00:00:00+00:00",
    }
    bridge._sessions["rollout-b"] = {
        "session_id": "rollout-b",
        "workflow": "rollout",
        "profile_id": "fake_omx_ai",
        "mode": "live",
        "status": "POLICY_ACTIVE",
        "returncode": None,
        "pid": None,
        "step_trace": [],
        "created_at": "2026-06-04T00:00:01+00:00",
    }
    bridge._sessions["teleop-active"] = {
        "session_id": "teleop-active",
        "workflow": "teleoperate",
        "profile_id": "fake_omx_ai",
        "mode": "live",
        "status": "TELEOP_ACTIVE",
        "returncode": None,
        "pid": None,
        "step_trace": [],
        "created_at": "2026-06-04T00:00:02+00:00",
    }

    result = bridge.rollout_stop({"mode": "live", "profile_id": "fake_omx_ai"})

    assert result["ok"] is True
    assert result["workflow"] == "rollout"
    assert result["status"] == "STOPPED"
    assert set(result["stopped_session_ids"]) == {"rollout-a", "rollout-b"}
    assert bridge._sessions["rollout-a"]["status"] == "STOPPED"
    assert bridge._sessions["rollout-b"]["status"] == "STOPPED"
    assert bridge._sessions["teleop-active"]["status"] == "TELEOP_ACTIVE"
    assert cleanup_called == ["rollout"]
    assert any(item["step"] == "CLEANUP_LEROBOT_PROCESS_GROUPS" for item in result["step_trace"])


def test_rollout_action_clamp_can_be_disabled(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "policy_path": "fake://policy",
            "rollout_action_clamp": False,
        }
    )

    assert result["ok"] is True
    assert all(not item.startswith("--robot.max_relative_target=") for item in result["command_preview"])


def test_rollout_temporal_ensemble_can_be_disabled(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "policy_path": "fake://policy",
            "rollout_temporal_ensemble": False,
        }
    )

    assert result["ok"] is True
    assert all(not item.startswith("--policy.temporal_ensemble_coeff=") for item in result["command_preview"])
    assert "--policy.n_action_steps=1" not in result["command_preview"]


def test_native_folder_picker_returns_selected_path(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    selected = tmp_path / "datasets"
    selected.mkdir()

    monkeypatch.setattr("device_bridges.lerobot_bridge.shutil.which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    monkeypatch.setattr(
        "device_bridges.lerobot_bridge.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args[0], returncode=0, stdout=str(selected) + "\n", stderr=""),
    )

    picked = bridge.pick_path({"kind": "dataset", "path": str(tmp_path), "select": "directory"})

    assert picked["ok"] is True
    assert picked["tool"] == "lerobot.files.pick"
    assert picked["selected_path"] == str(selected.resolve())


def test_visualize_dataset_returns_metadata_and_media(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "datasets" / "atr" / "demo"
    meta_dir = dataset_dir / "meta"
    video_dir = dataset_dir / "videos" / "chunk-000"
    isaac_rgbd_ep0 = dataset_dir / "sidecar" / "isaac_rgbd" / "episode_000000"
    isaac_rgbd_ep1 = dataset_dir / "sidecar" / "isaac_rgbd" / "episode_000001"
    isaac_mirror_ep1 = dataset_dir / "sidecar" / "isaac_mirror" / "episode_000001"
    meta_dir.mkdir(parents=True)
    video_dir.mkdir(parents=True)
    isaac_rgbd_ep0.mkdir(parents=True)
    isaac_rgbd_ep1.mkdir(parents=True)
    isaac_mirror_ep1.mkdir(parents=True)
    (meta_dir / "info.json").write_text('{"fps": 30, "total_episodes": 3}', encoding="utf-8")
    (video_dir / "episode_0.mp4").write_bytes(b"not-real-video")
    (video_dir / "episode_1.mp4").write_bytes(b"not-real-video")
    (isaac_rgbd_ep0 / "top_rgb.png").write_bytes(b"not-real-png")
    (isaac_rgbd_ep1 / "right_rgb.png").write_bytes(b"not-real-png")
    (isaac_mirror_ep1 / "frames.jsonl").write_text('{"frame": 0}\n', encoding="utf-8")
    bridge = _bridge(tmp_path)

    result = bridge.visualize_dataset(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_root": str(tmp_path / "datasets"),
            "dataset_repo_id": "atr/demo",
            "episode_indices": "0,1",
        }
    )

    assert result["ok"] is True
    assert result["episode_index"] == 0
    assert result["episode_indices"] == [0, 1]
    assert result["metadata"]["meta/info.json"]["fps"] == 30
    assert any(item["media_type"] == "video" for item in result["media"])
    assert sorted(result["media_by_episode"]) == ["0", "1"]
    ep0_paths = [item["path"] for item in result["media_by_episode"]["0"]]
    ep1_paths = [item["path"] for item in result["media_by_episode"]["1"]]
    assert any("episode_0.mp4" in path for path in ep0_paths)
    assert not any("episode_1.mp4" in path for path in ep0_paths)
    assert any("episode_1.mp4" in path for path in ep1_paths)
    sources = {item["source"] for item in result["media"]}
    assert {"isaac_rgbd", "isaac_mirror"}.issubset(sources)
    assert result["summary"]["source_counts"]["isaac_rgbd"] >= 2


def test_isaac_augmentation_writes_sidecar_and_training_exposes_summary(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "augmented"
    _make_trainable_lerobot_dataset(dataset)
    _write_isaac_rgbd_render_fixture(dataset, camera="wrist")

    augmented = bridge.augment_isaac_dataset(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/augmented",
            "isaac_data_augmentation_variants": 2,
            "isaac_data_augmentation_max_frames": 1,
            "isaac_data_augmentation_seed": 11,
            "isaac_data_augmentation_cameras": "wrist",
            "isaac_data_augmentation_camera_pose_enabled": True,
            "isaac_data_augmentation_image_enabled": True,
            "isaac_data_augmentation_profile": "sim2real",
            "isaac_data_augmentation_photometric_enabled": True,
            "isaac_data_augmentation_sensor_noise_enabled": False,
            "isaac_data_augmentation_depth_noise_enabled": True,
            "isaac_data_augmentation_render_domain_enabled": True,
            "isaac_data_augmentation_rgb_strength": 0.75,
            "isaac_data_augmentation_depth_strength": 1.25,
            "isaac_data_augmentation_render_domain_strength": 1.1,
            "isaac_data_augmentation_camera_pose_strength": 0.6,
        }
    )

    assert augmented["ok"] is True
    assert augmented["tool"] == "lerobot.augment.isaac"
    assert augmented["summary"]["variant_count"] == 2
    assert augmented["augmentation_progress"]["stage"] == "complete"
    assert augmented["augmentation_progress"]["done"] == 2
    assert augmented["augmentation_progress"]["total"] == 2
    assert augmented["summary"]["progress"]["percent"] == 100.0
    assert augmented["summary"]["augmentation_profile"] == "sim2real"
    assert augmented["summary"]["augmentation_options"]["sensor_noise_enabled"] is False
    assert augmented["summary"]["augmentation_options"]["depth_strength"] == 1.25
    assert Path(augmented["summary"]["manifest_path"]).is_file()
    assert augmented["command_preview"][0].endswith("python3") or augmented["command_preview"][0].endswith("python")
    assert "--augmentation-profile=sim2real" in augmented["command_preview"]
    assert "--sensor-noise-enabled=0" in augmented["command_preview"]
    assert "--depth-strength=1.25" in augmented["command_preview"]

    train = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/augmented",
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    assert train["ok"] is True
    assert train["isaac_data_augmentation"]["available"] is True
    assert train["isaac_data_augmentation"]["variant_count"] == 2


def test_isaac_augmentation_preview_returns_source_and_augmented_depth_previews(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "previewed"
    _make_trainable_lerobot_dataset(dataset)
    _write_isaac_rgbd_render_fixture(dataset, camera="wrist")
    manifest_path = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_aug" / "manifest.jsonl"
    rendered_row = json.loads(manifest_path.read_text(encoding="utf-8").splitlines()[0])
    pending_row = {**rendered_row, "status": "render_pending", "files": []}
    manifest_path.write_text(
        json.dumps(pending_row) + "\n" + json.dumps(rendered_row) + "\n",
        encoding="utf-8",
    )
    augmented = bridge.augment_isaac_dataset(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/previewed",
            "isaac_data_augmentation_variants": 2,
            "isaac_data_augmentation_max_frames": 1,
            "isaac_data_augmentation_seed": 13,
            "isaac_data_augmentation_cameras": "wrist",
        }
    )
    assert augmented["ok"] is True

    preview = bridge.augment_isaac_preview(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/previewed",
            "isaac_data_augmentation_preview_count": 1,
        }
    )

    assert preview["ok"] is True
    assert preview["tool"] == "lerobot.augment.preview"
    assert preview["preview_count"] == 1
    row = preview["rows"][0]
    assert row["variant_id"] == "e000_f000000_v000"
    assert row["episode_index"] == 0
    assert row["frame_index"] == 0
    assert row["camera"] == "wrist"
    assert row["qa"]["ok"] is True
    assert row["source_rgb"]["serve_url"].startswith("/api/lerobot/visualization/file?path=")
    assert row["augmented_rgb"]["serve_url"].startswith("/api/lerobot/visualization/file?path=")
    assert Path(row["source_depth_preview"]["path"]).is_file()
    assert Path(row["augmented_depth_preview"]["path"]).is_file()
    assert Image.open(row["source_depth_preview"]["path"]).mode == "RGB"
    assert Image.open(row["augmented_depth_preview"]["path"]).mode == "RGB"
    assert row["augmentation_parameters"]["depth"]


def test_visualize_start_defaults_to_official_lerobot_rerun_viewer_with_dataset_root(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset_dir)
    bridge = _bridge(tmp_path)
    captured: dict[str, object] = {}

    def fake_start(*, session_id: str, command: list[str]) -> dict[str, object]:
        captured["session_id"] = session_id
        captured["command"] = command
        return {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start  # type: ignore[method-assign]

    result = bridge.visualize_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "dataset_repo_id": "jin/record-test",
            "episode_index": 2,
            "visualization_web_port": 19091,
            "visualization_ws_port": 19089,
        }
    )

    command = result["command_preview"]
    assert result["ok"] is True
    assert result["tool"] == "lerobot.visualize.start"
    assert result["workflow"] == "visualize"
    assert Path(command[0]).name in {"conda", "conda.exe"}
    assert command[1:7] == ["run", "--no-capture-output", "-n", "lerobot", "python", "-m"]
    assert "lerobot.scripts.visualize_dataset" in command
    assert "lerobot.scripts.visualize_dataset_html" not in command
    assert "--repo-id=jin/record-test" in command
    assert "--root=" + str(dataset_dir.resolve()) in command
    assert "--episode-index=2" in command
    assert "--mode=distant" in command
    assert "--web-port=19091" in command
    assert "--ws-port=19089" in command
    assert result["visualization"]["rerun_web_url"] == "http://localhost:19091"
    assert result["visualization"]["viewer_url"] == "http://localhost:19091/?url=ws://localhost:19089"
    assert captured["command"] == command


def test_visualize_start_auto_selects_free_web_port_when_default_is_occupied(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset_dir)
    bridge = _bridge(tmp_path)
    captured: dict[str, object] = {}

    def fake_start(*, session_id: str, command: list[str]) -> dict[str, object]:
        captured["command"] = command
        return {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start  # type: ignore[method-assign]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied_port = int(sock.getsockname()[1])
        result = bridge.visualize_start(
            {
                "mode": "test",
                "profile_id": "fake_omx_ai",
                "dataset_root": str(tmp_path / "hf_datasets"),
                "dataset_repo_id": "jin/record-test",
                "visualization_web_port": occupied_port,
            }
        )

    selected_port = result["visualization"]["web_port"]
    command = result["command_preview"]
    assert result["ok"] is True
    assert selected_port != occupied_port
    assert result["visualization"]["requested_web_port"] == occupied_port
    assert result["visualization"]["port_auto_selected"] is True
    assert f"--web-port={selected_port}" in command
    assert f"--web-port={occupied_port}" not in command
    assert captured["command"] == command


def test_visualize_start_blocks_incomplete_local_dataset_before_launch(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "hf_datasets" / "jin" / "empty-record-test"
    dataset_dir.mkdir(parents=True)
    bridge = _bridge(tmp_path)
    launched = False

    def fake_start(*, session_id: str, command: list[str]) -> dict[str, object]:
        nonlocal launched
        launched = True
        return {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start  # type: ignore[method-assign]

    result = bridge.visualize_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "dataset_repo_id": "jin/empty-record-test",
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_VISUALIZATION_CONFIG_INVALID"
    assert "meta/info.json" in result["error"]
    assert launched is False


def test_visualize_status_prefers_active_viewer_over_newer_failed_session(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._refresh_process_status = lambda _session: None  # type: ignore[method-assign]
    bridge._sessions["active-viewer"] = {
        "session_id": "active-viewer",
        "workflow": "visualize",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "VISUALIZING",
        "created_at": "2026-06-30T02:00:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "pid": 1234,
        "returncode": None,
        "visualization": {"rerun_web_url": "http://localhost:9092"},
    }
    bridge._sessions["failed-viewer"] = {
        "session_id": "failed-viewer",
        "workflow": "visualize",
        "mode": "live",
        "profile_id": "fake_omx_ai",
        "status": "FAILED",
        "created_at": "2026-06-30T02:10:00+00:00",
        "command_preview": [],
        "step_trace": [],
        "pid": 5678,
        "returncode": 1,
        "visualization": {"stale": True, "stale_reason": "process_returncode_1"},
    }

    status = bridge.visualize_status({"mode": "live", "profile_id": "fake_omx_ai"})

    assert status["session_id"] == "active-viewer"
    assert status["status"] == "VISUALIZING"


def test_visualize_status_marks_dead_viewer_session_as_stale(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "hf_datasets" / "jin" / "record-test"
    _make_trainable_lerobot_dataset(dataset_dir)
    bridge = _bridge(tmp_path)
    bridge._pid_alive = lambda _pid: False  # type: ignore[method-assign]
    bridge._start_live_process = lambda **_: {  # type: ignore[method-assign]
        "ok": True,
        "session_updates": {"pid": 99999999, "log_path": "", "returncode": None},
    }

    started = bridge.visualize_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_root": str(tmp_path / "hf_datasets"),
            "dataset_repo_id": "jin/record-test",
        }
    )
    status = bridge.visualize_status({"mode": "test", "profile_id": "fake_omx_ai", "session_id": started["session_id"]})

    assert status["status"] == "FAILED"
    assert status["visualization"]["stale"] is True
    assert status["visualization"]["stale_reason"] == "process_not_alive"


def test_live_record_passes_tts_env_overrides(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    captured: dict[str, object] = {}
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]

    def fake_start_live_process(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start_live_process  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "confirm_live_execute": True,
            "tts_engine": "espeak-ng",
            "tts_rate": -60,
        }
    )

    assert started["ok"] is True
    assert started["tts"] == {"engine": "espeak-ng", "rate": -60, "voice": ""}
    assert captured["env_overrides"]["LEROBOT_TTS_ENGINE"] == "espeak-ng"
    assert captured["env_overrides"]["LEROBOT_TTS_RATE"] == "-60"
    assert captured["env_overrides"]["ATR_LEROBOT_OBSERVATION_PIPELINE_ID"] == "raw_depth_adapter"


def test_live_record_default_piper_passes_packaged_tts_env(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    captured: dict[str, object] = {}
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]

    def fake_start_live_process(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start_live_process  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "confirm_live_execute": True,
        }
    )

    assert started["ok"] is True
    assert started["tts"]["engine"] == "piper"
    assert started["tts"]["voice"] == "en_US-lessac-medium"
    env = captured["env_overrides"]
    assert env["LEROBOT_TTS_ENGINE"] == "piper"
    assert env["LEROBOT_TTS_RATE"] == "-35"
    assert env["LEROBOT_TTS_VOICE"] == "en_US-lessac-medium"
    assert env["ATR_REPO_ROOT"] == str(tmp_path)
    assert env["LEROBOT_TTS_PIPER_SCRIPT"] == str(tmp_path / "tools" / "tts" / "atr_piper_say.py")
    assert env["LEROBOT_TTS_PIPER_MODEL"] == str(
        tmp_path / "models" / "tts" / "piper" / "en_US-lessac-medium" / "en_US-lessac-medium.onnx"
    )

def test_live_record_enables_raw_depth_sidecar_env_for_realsense_depth(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    captured: dict[str, object] = {}
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_camera_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._saved_camera_device = lambda _profile_id, camera_key: {  # type: ignore[method-assign]
        "backend": "intelrealsense",
        "serial_number_or_name": "341522300873" if camera_key == "top" else "352122273019",
        "use_depth": True,
        "fps": 15,
        "width": 640,
        "height": 480,
    }

    def fake_start_live_process(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start_live_process  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "confirm_live_execute": True,
            "camera_enabled": True,
        }
    )

    raw_depth_dir = tmp_path / "hf_datasets" / "jin" / "record-test" / "sidecar" / "depth_raw"
    assert started["ok"] is True
    assert started["raw_depth_sidecar"]["enabled"] is True
    assert started["raw_depth_sidecar"]["root"] == str(raw_depth_dir)
    assert started["raw_depth_sidecar"]["expected_camera_keys"] == ["top", "wrist"]
    assert captured["env_overrides"]["ATR_LEROBOT_RAW_DEPTH_DIR"] == str(raw_depth_dir)
    assert captured["env_overrides"]["ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS"] == "top,wrist"
    assert captured["env_overrides"]["ATR_LEROBOT_RAW_DEPTH_FORMAT"] == "png16"
    assert captured["env_overrides"]["ATR_LEROBOT_DEPTH_ALIGNED_TO"] == "color"
    assert captured["env_overrides"]["ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT"] == "0.001"
    assert captured["env_overrides"]["ATR_LEROBOT_CAMERA_DEPTH_SCALE_M_PER_UNIT"] == "top=0.001,wrist=0.0001"
    assert captured["env_overrides"]["ATR_LEROBOT_CAMERA_DEPTH_CLIP_MM"] == "wrist=50:150"
    assert captured["env_overrides"]["ATR_LEROBOT_DEPTH_CLIP_MIN_MM"] == "0.0"
    assert captured["env_overrides"]["ATR_LEROBOT_DEPTH_CLIP_MAX_MM"] == "2000.0"


def test_live_record_legacy_pipeline_disables_raw_depth_sidecar_env(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    captured: dict[str, object] = {}
    bridge._live_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_port_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._live_camera_block_if_needed = lambda **_: None  # type: ignore[method-assign]
    bridge._saved_camera_device = lambda _profile_id, camera_key: {  # type: ignore[method-assign]
        "backend": "intelrealsense",
        "serial_number_or_name": f"rs-{camera_key}",
        "use_depth": True,
        "fps": 15,
        "width": 640,
        "height": 480,
    }

    def fake_start_live_process(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "session_updates": {"pid": 123, "log_path": "", "returncode": None}}

    bridge._start_live_process = fake_start_live_process  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "confirm_live_execute": True,
            "camera_enabled": True,
            "observation_pipeline_id": "legacy_lerobot",
        }
    )

    assert started["ok"] is True
    assert started["observation_pipeline_id"] == "legacy_lerobot"
    assert "raw_depth_sidecar" not in started
    assert "ATR_LEROBOT_RAW_DEPTH_DIR" not in captured["env_overrides"]
    assert captured["env_overrides"]["ATR_LEROBOT_OBSERVATION_PIPELINE_ID"] == "legacy_lerobot"


def test_record_writes_dataset_pipeline_metadata_for_raw_depth_adapter(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    started = bridge.record_start(
        {
            "mode": "test",
            "runtime_mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/raw-adapter",
            "camera_enabled": True,
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    metadata_path = tmp_path / "hf_datasets" / "jin" / "raw-adapter" / "meta" / "atr_pipeline.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert started["ok"] is True
    assert started["observation_pipeline_id"] == "raw_depth_adapter"
    assert metadata["profile_id"] == "fake_omx_ai"
    assert metadata["observation_pipeline_id"] == "raw_depth_adapter"
    assert metadata["dataset_repo_id"] == "jin/raw-adapter"
    assert metadata["raw_depth_sidecar"]["required"] is True


def test_record_with_isaac_mirror_stores_mirror_sidecar_in_dataset_metadata(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._post_isaac_mirror_state = lambda endpoint, payload, timeout_s=0.5: {"ok": True, "status_code": 200}  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "test",
            "runtime_mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/mirror-record",
            "camera_enabled": True,
            "observation_pipeline_id": "raw_depth_adapter",
            "isaac_mirror_enabled": True,
            "isaac_mirror_max_samples": 2,
        }
    )

    dataset_path = tmp_path / "hf_datasets" / "jin" / "mirror-record"
    expected_record_path = dataset_path / "sidecar" / "isaac_mirror" / f"{started['session_id']}.jsonl"
    metadata_path = dataset_path / "meta" / "atr_pipeline.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert started["ok"] is True
    assert started["isaac_mirror"]["sample_count"] == 2
    assert Path(started["isaac_mirror"]["mirror_record_path"]) == expected_record_path
    assert expected_record_path.exists()
    assert metadata["isaac_mirror"]["enabled"] is True
    assert metadata["isaac_mirror"]["record_path"] == str(expected_record_path)
    assert metadata["isaac_mirror"]["session_id"] == started["isaac_mirror_session_id"]
    assert metadata["isaac_mirror"]["sync_summary"]["target_sample_hz"] > 0
    assert metadata["isaac_mirror"]["sync_summary"]["sample_count"] == 2


def test_record_stop_refreshes_isaac_mirror_metadata(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._post_isaac_mirror_state = lambda endpoint, payload, timeout_s=0.5: {"ok": True, "status_code": 200}  # type: ignore[method-assign]
    bridge._fetch_isaac_mirror_receiver_state = lambda endpoint, timeout_s=0.5: {  # type: ignore[method-assign]
        "ok": True,
        "state_url": "http://127.0.0.1:8766/state",
        "sample_count": 7,
        "last_payload_summary": {"session_id": "mirror-session-at-stop", "sample_index": 7, "joint_count": 6, "target_count": 6},
    }
    started = bridge.record_start(
        {
            "mode": "test",
            "runtime_mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/mirror-stop",
            "isaac_mirror_enabled": True,
            "isaac_mirror_max_samples": 2,
        }
    )
    mirror_session = bridge._sessions[started["isaac_mirror_session_id"]]
    mirror_session["sample_count"] = 7
    mirror_session["status"] = "STOPPED"

    stopped = bridge.record_control({"mode": "test", "profile_id": "fake_omx_ai", "session_id": started["session_id"], "action": "stop"})

    metadata_path = tmp_path / "hf_datasets" / "jin" / "mirror-stop" / "meta" / "atr_pipeline.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert stopped["ok"] is True
    assert stopped["isaac_mirror_stop"]["sample_count"] == 7
    assert metadata["isaac_mirror"]["sample_count"] == 7
    assert metadata["isaac_mirror"]["status"] == "STOPPED"
    assert metadata["isaac_mirror"]["sync_summary"]["sample_count"] == 7
    assert metadata["isaac_mirror"]["receiver_state_at_stop"]["ok"] is True
    assert metadata["isaac_mirror"]["receiver_state_at_stop"]["last_payload_summary"]["sample_index"] == 7


def test_live_record_status_exposes_in_process_isaac_mirror_sidecar_progress(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    bridge.config.profiles["fake_omx_ai"]["safety_limits"].update({"live_enabled": True, "allow_recording": True})
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_health",
        lambda endpoint, timeout_s=0.5: {
            "ok": True,
            "health_url": "http://127.0.0.1:8766/health",
            "apply_mode": "deferred_update_tick",
            "sample_count": 0,
        },
        raising=False,
    )
    bridge.mirror_receiver_process_start = lambda payload: {  # type: ignore[method-assign]
        "ok": True,
        "status": "RUNNING",
        "pid": 4321,
        "health": {"ok": True, "health_url": "http://127.0.0.1:8766/health", "apply_mode": "deferred_update_tick"},
    }
    bridge._start_live_process = lambda **kwargs: {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/live-mirror-progress",
            "confirm_live_execute": True,
            "camera_enabled": False,
            "isaac_mirror_enabled": True,
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
        }
    )
    sidecar_path = Path(started["isaac_mirror"]["mirror_record_path"])
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(
        "\n".join(json.dumps({"sample_index": idx, "joint_state": []}) for idx in range(1, 4)) + "\n",
        encoding="utf-8",
    )

    status = bridge.record_status({"mode": "live", "profile_id": "fake_omx_ai", "session_id": started["session_id"]})
    metadata = json.loads((tmp_path / "hf_datasets" / "jin" / "live-mirror-progress" / "meta" / "atr_pipeline.json").read_text(encoding="utf-8"))

    assert status["ok"] is True
    assert status["isaac_mirror"]["status"] == "IN_PROCESS"
    assert status["isaac_mirror"]["sample_count"] == 3
    assert status["isaac_mirror"]["sync_summary"]["sample_count"] == 3
    assert metadata["isaac_mirror"]["sample_count"] == 3


def test_live_record_with_isaac_mirror_enables_attempt_and_rgbd_render_env(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    bridge.config.profiles["fake_omx_ai"]["safety_limits"].update({"live_enabled": True, "allow_recording": True})
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_health",
        lambda endpoint, timeout_s=0.5: {
            "ok": True,
            "health_url": "http://127.0.0.1:8766/health",
            "apply_mode": "deferred_update_tick",
            "sample_count": 0,
        },
        raising=False,
    )
    captured: dict[str, object] = {}
    receiver_starts: list[dict[str, object]] = []
    viewport_frame_calls: list[dict[str, object]] = []
    timeline_play_calls: list[dict[str, object]] = []
    bridge._start_live_process = lambda **kwargs: captured.update(kwargs) or {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}  # type: ignore[method-assign]
    bridge.mirror_receiver_process_start = lambda payload: receiver_starts.append(dict(payload)) or {  # type: ignore[method-assign]
        "ok": True,
        "status": "RUNNING",
        "pid": 4321,
        "health": {
            "ok": True,
            "health_url": "http://127.0.0.1:8766/health",
            "apply_mode": "deferred_update_tick",
        },
    }
    bridge._post_isaac_mirror_timeline_play = lambda endpoint, reason, timeout_s=0.5: timeline_play_calls.append(  # type: ignore[attr-defined]
        {"endpoint": endpoint, "reason": reason, "timeout_s": timeout_s}
    ) or {"ok": True, "status": "timeline_play_queued", "timeline_play_url": "http://127.0.0.1:8766/timeline/play"}
    bridge._post_isaac_mirror_viewport_frame = lambda endpoint, reason, timeout_s=0.5: viewport_frame_calls.append(  # type: ignore[method-assign]
        {"endpoint": endpoint, "reason": reason, "timeout_s": timeout_s}
    ) or {"ok": True, "status": "viewport_frame_queued", "viewport_frame_url": "http://127.0.0.1:8766/viewport/frame"}

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/live-attempt-rgbd",
            "confirm_live_execute": True,
            "camera_enabled": False,
            "isaac_mirror_enabled": True,
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
            "isaac_mirror_sample_hz": 15,
        }
    )

    dataset_path = tmp_path / "hf_datasets" / "jin" / "live-attempt-rgbd"
    env = captured["env_overrides"]
    attempt = started["record_attempt"]
    assert started["ok"] is True
    assert receiver_starts
    assert receiver_starts[0]["isaac_mirror_receiver_force_restart"] is True
    assert receiver_starts[0]["isaac_mirror_receiver_play_timeline_on_startup"] is True
    assert receiver_starts[0]["active_robot_cam_enabled"] is False
    assert any(item["step"] == "ISAAC_MIRROR_RECEIVER_RESTARTED" for item in started["step_trace"])
    assert started["isaac_timeline_play"]["status"] == "timeline_play_queued"
    assert timeline_play_calls == [
        {
            "endpoint": "http://127.0.0.1:8766/joints",
            "reason": "record_start",
            "timeout_s": 0.5,
        }
    ]
    trace_steps = [item["step"] for item in started["step_trace"]]
    assert trace_steps.index("ISAAC_TIMELINE_PLAY") < trace_steps.index("PROCESS_STARTED")
    assert started["isaac_viewport_frame"]["status"] == "viewport_frame_queued"
    assert viewport_frame_calls == [
        {
            "endpoint": "http://127.0.0.1:8766/joints",
            "reason": "record_start",
            "timeout_s": 0.5,
        }
    ]
    assert attempt["enabled"] is True
    assert attempt["overwrite"] is True
    assert attempt["attempt_id"].startswith("attempt_")
    assert attempt["attempt_id"].endswith("_ep000")
    assert env["ATR_RECORD_ATTEMPT_ENABLED"] == "1"  # type: ignore[index]
    assert env["ATR_RECORD_ATTEMPT_OVERWRITE"] == "1"  # type: ignore[index]
    assert env["ATR_RECORD_ATTEMPT_ID"] == attempt["attempt_id"]  # type: ignore[index]
    assert env["ATR_RECORD_ATTEMPT_DATASET_PATH"] == str(dataset_path)  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_TIMEOUT_S"] == "0.5"  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_POST_TIMEOUT_S"] == "0.5"  # type: ignore[index]
    assert "ATR_ISAAC_TIMELINE_PLAY_RECORD_START_ENABLED" not in env
    assert env["ATR_ISAAC_RGBD_RENDER_ENABLED"] == "1"  # type: ignore[index]
    assert env["ATR_ISAAC_RGBD_RENDER_MODE"] == "deferred_after_record"  # type: ignore[index]
    assert env["ATR_ISAAC_RGBD_RENDER_TARGET_FPS"] == "15.0"  # type: ignore[index]
    assert env["ATR_ISAAC_RGBD_RENDER_POST_TIMEOUT_S"] == "0.5"  # type: ignore[index]
    assert Path(str(env["ATR_ISAAC_RGBD_RENDER_OUTPUT_DIR"])) == dataset_path / "sidecar" / "isaac_rgbd" / "episode_000" / attempt["attempt_id"]  # type: ignore[index]
    assert Path(str(attempt["attempt_dir"])) == dataset_path / "sidecar" / "attempts" / "episode_000" / attempt["attempt_id"]
    assert Path(str(attempt["isaac_rgbd_render"]["manifest_path"])) == dataset_path / "sidecar" / "isaac_rgbd" / "episode_000" / attempt["attempt_id"] / "manifest.jsonl"
    assert started["isaac_mirror"]["rgbd_render"]["enabled"] is True
    assert not dataset_path.exists()


def test_isaac_rgbd_post_render_start_skips_rendered_and_posts_missing_frames(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "post-render"
    mirror_path = dataset / "sidecar" / "isaac_mirror" / "record-one.jsonl"
    output_dir = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_post"
    (output_dir / "top").mkdir(parents=True, exist_ok=True)
    rendered_rgb = output_dir / "top" / "frame_000000_rgb.png"
    rendered_rgb.write_bytes(b"rgb")
    (output_dir / "manifest.jsonl").write_text(
        json.dumps(
            {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "status": "rendered",
                "attempt_id": "attempt_post",
                "episode_index": 0,
                "frame_index": 0,
                "sample_index": 1,
                "cameras": ["top"],
                "files": [{"camera": "top", "kind": "rgb", "path": str(rendered_rgb)}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for frame_index, sample_index in [(0, 1), (1, 2)]:
        request = {
            "schema": "atr.isaac_rgbd.render_request.v1",
            "enabled": True,
            "session_id": "record-one",
            "attempt_id": "attempt_post",
            "episode_index": 0,
            "frame_index": frame_index,
            "sample_index": sample_index,
            "timestamp": f"2026-06-29T00:00:0{sample_index}+00:00",
            "target_fps": 15.0,
            "cameras": ["top"],
            "output_dir": str(output_dir),
        }
        rows.append(
            {
                "session_id": "record-one",
                "sample_index": sample_index,
                "timestamp": request["timestamp"],
                "joint_state": [{"isaac_joint_path": "/World/Robot/joint", "target_value": float(sample_index)}],
                "render_queue": {
                    "status": "deferred_after_record",
                    "attempt_id": "attempt_post",
                    "episode_index": 0,
                    "frame_index": frame_index,
                    "sample_index": sample_index,
                    "endpoint": "http://127.0.0.1:8766/render",
                    "render_request": request,
                },
            }
        )
    mirror_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    posted: list[int] = []

    def fake_post(payload: dict[str, object], *, endpoint: str, timeout_s: float) -> dict[str, object]:
        posted.append(int(payload["render_request"]["frame_index"]))  # type: ignore[index]
        return {"ok": True, "status_code": 200, "response": {"status": "render_queued"}}

    monkeypatch.setattr(bridge, "_post_isaac_rgbd_render_payload", fake_post)
    monkeypatch.setattr(bridge, "_wait_for_isaac_rgbd_render_completion", lambda candidate, endpoint, timeout_s: {"ok": True, "status": "rendered"})

    started = bridge.isaac_rgbd_render_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "session_id": "record-one",
            "isaac_rgbd_post_render_inline": True,
        }
    )

    assert started["ok"] is True
    assert posted == [1]
    assert started["post_render"]["done"] == 2
    assert started["post_render"]["skipped"] == 1
    assert started["post_render"]["rendered"] == 1
    assert started["post_render"]["percent"] == 100.0


def test_live_record_stop_summarizes_in_process_isaac_mirror_sidecar_metrics(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    bridge.config.profiles["fake_omx_ai"]["safety_limits"].update({"live_enabled": True, "allow_recording": True})
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_health",
        lambda endpoint, timeout_s=0.5: {"ok": True, "health_url": "http://127.0.0.1:8766/health", "apply_mode": "deferred_update_tick", "sample_count": 0},
        raising=False,
    )
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_state",
        lambda endpoint, timeout_s=0.5: {
            "ok": True,
            "state_url": "http://127.0.0.1:8766/state",
            "sample_count": 53,
            "last_payload_summary": {"session_id": "mirror-live", "sample_index": 3, "joint_count": 6, "target_count": 6},
        },
        raising=False,
    )
    bridge.mirror_receiver_process_start = lambda payload: {  # type: ignore[method-assign]
        "ok": True,
        "status": "RUNNING",
        "pid": 4321,
        "health": {"ok": True, "health_url": "http://127.0.0.1:8766/health", "apply_mode": "deferred_update_tick"},
    }
    bridge._start_live_process = lambda **kwargs: {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/live-mirror-summary",
            "confirm_live_execute": True,
            "camera_enabled": False,
            "isaac_mirror_enabled": True,
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
        }
    )
    sidecar_path = Path(started["isaac_mirror"]["mirror_record_path"])
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "sample_index": idx,
                    "sync_metrics": {
                        "target_sample_hz": 15.0,
                        "sample_period_s": 1 / 15,
                        "post_latency_ms": float(idx),
                        "receiver_accepted": idx != 2,
                        "receiver_sample_count": 50 + idx,
                    },
                }
            )
            for idx in range(1, 4)
        )
        + "\n",
        encoding="utf-8",
    )

    stopped = bridge.record_control({"mode": "live", "profile_id": "fake_omx_ai", "session_id": started["session_id"], "action": "stop"})
    metadata = json.loads((tmp_path / "hf_datasets" / "jin" / "live-mirror-summary" / "meta" / "atr_pipeline.json").read_text(encoding="utf-8"))
    summary = metadata["isaac_mirror"]["sync_summary"]

    assert stopped["isaac_mirror_stop"]["sample_count"] == 3
    assert summary["sample_count"] == 3
    assert summary["target_sample_hz"] == 15.0
    assert summary["post_ok_count"] == 2
    assert summary["post_fail_count"] == 1
    assert summary["last_receiver_sample_count"] == 53
    assert summary["mean_post_latency_ms"] == 2.0


def test_live_record_with_in_process_isaac_mirror_does_not_precreate_lerobot_dataset_root(tmp_path: Path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    bridge.config.profiles["fake_omx_ai"]["safety_limits"].update({"live_enabled": True, "allow_recording": True})
    follower = tmp_path / "omx_follower"
    leader = tmp_path / "omx_leader"
    follower.touch()
    leader.touch()
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower", "port": str(follower)})
    bridge.ports_save({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader", "port": str(leader)})
    monkeypatch.setattr(
        bridge,
        "_fetch_isaac_mirror_receiver_health",
        lambda endpoint, timeout_s=0.5: {
            "ok": True,
            "health_url": "http://127.0.0.1:8766/health",
            "apply_mode": "deferred_update_tick",
            "sample_count": 0,
        },
        raising=False,
    )
    bridge.mirror_receiver_process_start = lambda payload: {  # type: ignore[method-assign]
        "ok": True,
        "status": "RUNNING",
        "pid": 4321,
        "health": {"ok": True, "health_url": "http://127.0.0.1:8766/health", "apply_mode": "deferred_update_tick"},
    }
    bridge._start_live_process = lambda **kwargs: {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

    started = bridge.record_start(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/live-root-ownership",
            "confirm_live_execute": True,
            "camera_enabled": False,
            "isaac_mirror_enabled": True,
            "isaac_mirror_endpoint": "http://127.0.0.1:8766/joints",
        }
    )

    assert started["ok"] is True
    assert started["isaac_mirror"]["status"] == "IN_PROCESS"
    assert not Path(started["dataset_path"]).exists()
    assert not (Path(started["dataset_path"]) / "meta" / "atr_pipeline.json").exists()


def test_train_raw_depth_adapter_env_points_to_dataset_sidecar(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "raw-adapter"
    _make_trainable_lerobot_dataset(dataset)
    sidecar_root = dataset / "sidecar" / "depth_raw"
    sidecar_root.mkdir(parents=True, exist_ok=True)
    (sidecar_root / "transform_manifest.json").write_text(
        json.dumps(
            {
                "camera_keys": ["top", "wrist"],
                "aligned_to": "color",
                "depth_encoding": "png16",
                "depth_scale_m_per_unit": 0.001,
                "camera_depth_scale_m_per_unit": {"top": 0.001, "wrist": 0.0001},
                "camera_depth_clip_mm": {"wrist": {"min_mm": 50.0, "max_mm": 150.0}},
                "depth_clip_min_mm": 0.0,
                "depth_clip_max_mm": 2000.0,
            }
        ),
        encoding="utf-8",
    )

    request = LeRobotSessionRequest.model_validate(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    env = bridge._workflow_env_overrides("train", request)

    assert env["ATR_LEROBOT_OBSERVATION_PIPELINE_ID"] == "raw_depth_adapter"
    assert env["ATR_LEROBOT_RAW_DEPTH_ADAPTER"] == "1"
    assert env["ATR_LEROBOT_RAW_DEPTH_SOURCE_DIR"] == str(sidecar_root)
    assert env["ATR_LEROBOT_RAW_DEPTH_ADAPTER_STRICT"] == "1"
    assert env["ATR_LEROBOT_RAW_DEPTH_CAMERA_KEYS"] == "top,wrist"
    assert env["ATR_LEROBOT_DEPTH_SCALE_M_PER_UNIT"] == "0.001"
    assert env["ATR_LEROBOT_CAMERA_DEPTH_SCALE_M_PER_UNIT"] == "top=0.001,wrist=0.0001"
    assert env["ATR_LEROBOT_CAMERA_DEPTH_CLIP_MM"] == "wrist=50:150"
    assert env["ATR_LEROBOT_DEPTH_CLIP_MIN_MM"] == "0.0"
    assert env["ATR_LEROBOT_DEPTH_CLIP_MAX_MM"] == "2000.0"


def test_train_start_blocks_raw_depth_adapter_when_manifest_has_no_frames(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "raw-adapter-empty"
    _make_trainable_lerobot_dataset(dataset)
    shutil.rmtree(dataset / "sidecar" / "depth_raw" / "top", ignore_errors=True)
    shutil.rmtree(dataset / "sidecar" / "depth_raw" / "wrist", ignore_errors=True)

    result = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["failure_code"] == "LEROBOT_RAW_DEPTH_FRAMES_MISSING"


def test_train_preflight_normalizes_raw_depth_sidecar_frame_indices(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "raw-depth-offset"
    _make_trainable_lerobot_dataset(dataset)
    sidecar_root = dataset / "sidecar" / "depth_raw"
    shutil.rmtree(sidecar_root / "top", ignore_errors=True)
    shutil.rmtree(sidecar_root / "wrist", ignore_errors=True)
    for index in (0, 1, 2):
        (sidecar_root / "top").mkdir(parents=True, exist_ok=True)
        (sidecar_root / "top" / f"frame_{index:06d}.png").write_bytes(f"top-{index}".encode("utf-8"))
    for source_index in (12693, 12694, 12696):
        (sidecar_root / "wrist").mkdir(parents=True, exist_ok=True)
        (sidecar_root / "wrist" / f"frame_{source_index:06d}.png").write_bytes(f"wrist-{source_index}".encode("utf-8"))

    request = LeRobotSessionRequest.model_validate(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    normalized = bridge._normalize_train_raw_depth_sidecar(request)  # noqa: SLF001

    assert normalized["ok"] is True
    assert normalized["camera_results"]["top"]["renamed_count"] == 0
    assert normalized["camera_results"]["wrist"]["renamed_count"] == 3
    assert sorted(path.name for path in (sidecar_root / "wrist").glob("frame_*.png")) == [
        "frame_000000.png",
        "frame_000001.png",
        "frame_000002.png",
    ]
    assert (sidecar_root / "wrist" / "frame_000002.png").read_bytes() == b"wrist-12696"


def test_train_env_enables_isaac_augmentation_adapter_when_sidecar_exists(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "isaac-aug-train"
    _make_trainable_lerobot_dataset(dataset)
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"
    manifest_path = output_dir / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr.isaac_data_augmentation.variant.v1",
                "variant_id": "e000_f000000_v000",
                "source": {"episode_index": 0, "frame_index": 0},
                "image_outputs": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "ok": True,
                "dataset_path": str(dataset),
                "output_dir": str(output_dir),
                "manifest_path": str(manifest_path),
                "summary_path": str(summary_path),
                "qa_summary_path": str(output_dir / "qa_summary.json"),
                "source_frame_count": 1,
                "variant_count": 3,
                "valid_variant_count": 2,
                "failed_variant_count": 1,
            }
        ),
        encoding="utf-8",
    )

    request = LeRobotSessionRequest.model_validate(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    env = bridge._workflow_env_overrides("train", request)

    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_ADAPTER"] == "1"
    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_MANIFEST"] == str(manifest_path)
    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_SUMMARY"] == str(summary_path)
    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_INCLUDE_ALL"] == "1"
    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_STRICT"] == "0"
    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_VARIANT_COUNT"] == "3"
    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_REQUIRE_QA_OK"] == "1"
    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_VALID_VARIANT_COUNT"] == "2"
    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_FAILED_VARIANT_COUNT"] == "1"
    assert env["ATR_LEROBOT_ISAAC_AUGMENTATION_QA_SUMMARY"] == str(output_dir / "qa_summary.json")


def test_train_dataset_mix_defaults_are_conservative_and_report_effective_counts(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "mix-default"
    _make_trainable_lerobot_dataset(dataset)
    info_path = dataset / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["total_frames"] = 10
    info_path.write_text(json.dumps(info), encoding="utf-8")
    _write_isaac_rgbd_manifest_rows(dataset, count=4)
    _write_isaac_augmentation_summary(dataset, variant_count=8, valid_variant_count=8)

    request = LeRobotSessionRequest.model_validate(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )
    env = bridge._workflow_env_overrides("train", request)

    assert env["ATR_LEROBOT_DATA_MIX_REAL_ORIGINAL_WEIGHT"] == "1"
    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_RGBD_WEIGHT"] == "0.5"
    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_AUGMENTATION_WEIGHT"] == "0.5"
    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_LAB_SYNTHETIC_WEIGHT"] == "0.5"
    assert env["ATR_LEROBOT_FIDELITY_WEIGHTING_ENABLED"] == "1"
    assert env["ATR_LEROBOT_FIDELITY_REAL_ORIGINAL_WEIGHT"] == "1"
    assert env["ATR_LEROBOT_FIDELITY_ISAAC_RGBD_WEIGHT"] == "0.5"
    assert env["ATR_LEROBOT_FIDELITY_ISAAC_AUGMENTATION_WEIGHT"] == "0.3"
    assert env["ATR_LEROBOT_FIDELITY_ISAAC_LAB_SYNTHETIC_WEIGHT"] == "0.2"
    result = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    assert result["ok"] is True
    assert result["dataset_mix"]["weights"] == {
        "real_original": 1.0,
        "isaac_rgbd": 0.5,
        "isaac_augmentation": 0.5,
        "isaac_lab_synthetic": 0.5,
    }
    assert result["fidelity_weights"] == {
        "schema": "atr.lerobot.fidelity_weights.v1",
        "enabled": True,
        "mode": "source_loss_weight",
        "weights": {"real_original": 1.0, "isaac_rgbd": 0.5, "isaac_augmentation": 0.3, "isaac_lab_synthetic": 0.2},
    }
    assert result["dataset_mix"]["effective_counts"] == {
        "real_original": 10,
        "isaac_rgbd": 4,
        "isaac_augmentation": 5,
        "isaac_lab_synthetic": 0,
        "total": 19,
    }
    status = bridge.train_status({"mode": "test", "profile_id": "fake_omx_ai", "session_id": result["session_id"]})
    assert status["dataset_mix"]["effective_counts"]["total"] == 19
    assert status["fidelity_weights"]["weights"]["isaac_augmentation"] == 0.3
    assert status["training"]["dataset_mix_effective_counts"]["total"] == 19
    assert status["training"]["fidelity_weights"]["weights"]["isaac_augmentation"] == 0.3


def test_train_dataset_mix_operator_override_is_passed_to_env_and_counts(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "mix-override"
    _make_trainable_lerobot_dataset(dataset)
    info_path = dataset / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["total_frames"] = 10
    info_path.write_text(json.dumps(info), encoding="utf-8")
    _write_isaac_rgbd_manifest_rows(dataset, count=9)
    _write_isaac_augmentation_summary(dataset, variant_count=12, valid_variant_count=12)
    payload = {
        "mode": "test",
        "profile_id": "fake_omx_ai",
        "dataset_path": str(dataset),
        "observation_pipeline_id": "raw_depth_adapter",
        "dataset_mix_real_original_weight": 0.8,
        "dataset_mix_isaac_rgbd_weight": 0.3,
        "dataset_mix_isaac_augmentation_weight": 0.2,
        "dataset_mix_isaac_rgbd_max_samples": 2,
        "dataset_mix_isaac_augmentation_max_samples": 1,
        "dataset_mix_seed": 7,
        "fidelity_weighting_enabled": True,
        "fidelity_real_original_weight": 1.0,
        "fidelity_isaac_rgbd_weight": 0.45,
        "fidelity_isaac_augmentation_weight": 0.25,
    }
    request = LeRobotSessionRequest.model_validate({**payload, "mode": "live", "runtime_mode": "live"})
    env = bridge._workflow_env_overrides("train", request)

    assert env["ATR_LEROBOT_DATA_MIX_REAL_ORIGINAL_WEIGHT"] == "0.8"
    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_RGBD_WEIGHT"] == "0.3"
    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_AUGMENTATION_WEIGHT"] == "0.2"
    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_LAB_SYNTHETIC_WEIGHT"] == "0.5"
    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_RGBD_MAX_SAMPLES"] == "2"
    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_AUGMENTATION_MAX_SAMPLES"] == "1"
    assert env["ATR_LEROBOT_DATA_MIX_SEED"] == "7"
    assert env["ATR_LEROBOT_FIDELITY_WEIGHTING_ENABLED"] == "1"
    assert env["ATR_LEROBOT_FIDELITY_REAL_ORIGINAL_WEIGHT"] == "1"
    assert env["ATR_LEROBOT_FIDELITY_ISAAC_RGBD_WEIGHT"] == "0.45"
    assert env["ATR_LEROBOT_FIDELITY_ISAAC_AUGMENTATION_WEIGHT"] == "0.25"
    assert env["ATR_LEROBOT_FIDELITY_ISAAC_LAB_SYNTHETIC_WEIGHT"] == "0.2"
    result = bridge.train_start(payload)

    assert result["dataset_mix"]["effective_counts"] == {
        "real_original": 8,
        "isaac_rgbd": 2,
        "isaac_augmentation": 1,
        "isaac_lab_synthetic": 0,
        "total": 11,
    }
    assert result["fidelity_weights"]["weights"] == {
        "real_original": 1.0,
        "isaac_rgbd": 0.45,
        "isaac_augmentation": 0.25,
        "isaac_lab_synthetic": 0.2,
    }


def test_train_start_exposes_isaac_lab_synthetic_training_import_and_weights(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "isaac-lab-synthetic-train"
    _make_trainable_lerobot_dataset(dataset)
    info_path = dataset / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["total_frames"] = 10
    info_path.write_text(json.dumps(info), encoding="utf-8")
    _write_isaac_lab_synthetic_training_import(dataset, row_count=7)
    payload = {
        "mode": "test",
        "profile_id": "fake_omx_ai",
        "dataset_path": str(dataset),
        "observation_pipeline_id": "raw_depth_adapter",
        "dataset_mix_isaac_lab_synthetic_weight": 0.4,
        "dataset_mix_isaac_lab_synthetic_max_samples": 3,
        "fidelity_isaac_lab_synthetic_weight": 0.2,
    }
    request = LeRobotSessionRequest.model_validate({**payload, "mode": "live", "runtime_mode": "live"})
    env = bridge._workflow_env_overrides("train", request)

    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_LAB_SYNTHETIC_WEIGHT"] == "0.4"
    assert env["ATR_LEROBOT_DATA_MIX_ISAAC_LAB_SYNTHETIC_MAX_SAMPLES"] == "3"
    assert env["ATR_LEROBOT_FIDELITY_ISAAC_LAB_SYNTHETIC_WEIGHT"] == "0.2"
    assert env["ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_ADAPTER"] == "1"
    assert env["ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_REQUIRE_SUCCESS"] == "1"
    assert env["ATR_LEROBOT_ISAAC_LAB_SYNTHETIC_SYNTHETIC_ROW_COUNT"] == "7"

    result = bridge.train_start(payload)

    assert result["ok"] is True
    assert result["isaac_lab_synthetic"]["available"] is True
    assert result["isaac_lab_synthetic"]["row_count"] == 7
    assert result["isaac_lab_synthetic"]["synthetic_row_count"] == 7
    assert result["dataset_mix"]["weights"]["isaac_lab_synthetic"] == 0.4
    assert result["dataset_mix"]["available_counts"]["isaac_lab_synthetic"] == 7
    assert result["dataset_mix"]["effective_counts"]["isaac_lab_synthetic"] == 3
    assert result["training"]["dataset_mix_effective_counts"]["isaac_lab_synthetic"] == 3
    assert result["fidelity_weights"]["weights"]["isaac_lab_synthetic"] == 0.2


def test_train_dataset_mix_does_not_count_real_only_isaac_lab_import_as_synthetic(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "isaac-lab-real-only"
    _make_trainable_lerobot_dataset(dataset)
    info_path = dataset / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["total_frames"] = 10
    info_path.write_text(json.dumps(info), encoding="utf-8")
    _write_real_only_isaac_lab_training_import(dataset, row_count=4)

    result = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    assert result["ok"] is True
    assert result["isaac_lab_synthetic"]["row_count"] == 4
    assert result["isaac_lab_synthetic"]["synthetic_row_count"] == 0
    assert result["isaac_lab_synthetic"]["available"] is False
    assert result["dataset_mix"]["available_counts"]["isaac_lab_synthetic"] == 0
    assert result["dataset_mix"]["effective_counts"]["isaac_lab_synthetic"] == 0


def test_isaac_lab_run_replicator_worker_executes_build_plan_and_refreshes_summary(tmp_path: Path, monkeypatch) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "replicator-worker"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=1, fps=2)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        if "--output-dir" not in command:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        commands.append(list(command))
        output_dir = Path(command[command.index("--output-dir") + 1])
        rgb = output_dir / "rgb" / "top" / "e000000_f000000_v000.png"
        depth = output_dir / "depth" / "top" / "e000000_f000000_v000.png"
        metadata = output_dir / "metadata" / "top" / "e000000_f000000_v000.json"
        for path, payload in [(rgb, b"rgb"), (depth, b"depth16"), (metadata, b"{}")]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        manifest = output_dir / "manifest.jsonl"
        manifest.write_text(
            json.dumps(
                {
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
            )
            + "\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "status": "completed"}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = bridge.isaac_lab_run_replicator_worker(
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
            "cameras": ["top"],
            "attempts_per_source_frame": 1,
        }
    )

    assert result["ok"] is True
    assert result["tool"] == "lerobot.isaac_lab.run_replicator_worker"
    assert commands
    assert commands[0][0] == str(isaac_python)
    assert "scripts/lerobot_isaac_replicator_synthetic.py" in commands[0][1]
    assert result["worker"]["returncode"] == 0
    assert result["worker"]["command"] == commands[0]
    assert result["replicator"]["status"] == "completed"
    assert result["replicator"]["rendered_count"] == 1
    assert result["replicator"]["valid_rendered_count"] == 1
    assert result["source_labels"]["counts"]["replicator_render_only"] == 1


def test_isaac_lab_run_replicator_worker_smoke_limits_canonical_rows(tmp_path: Path, monkeypatch) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "replicator-worker-smoke"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=5, fps=15)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        canonical_index = Path(command[command.index("--canonical-index") + 1])
        canonical_rows = [json.loads(line) for line in canonical_index.read_text(encoding="utf-8").splitlines()]
        assert len(canonical_rows) == 1
        assert command[command.index("--cameras") + 1] == "top"
        assert command[command.index("--variants") + 1] == "1"
        output_dir = Path(command[command.index("--output-dir") + 1])
        rgb = output_dir / "rgb" / "top" / "e000000_f000000_v000.png"
        depth = output_dir / "depth" / "top" / "e000000_f000000_v000.png"
        metadata = output_dir / "metadata" / "top" / "e000000_f000000_v000.json"
        for path, payload in [(rgb, b"rgb"), (depth, b"depth16"), (metadata, b"{}")]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        (output_dir / "manifest.jsonl").write_text(
            json.dumps(
                {
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
            )
            + "\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "status": "completed"}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = bridge.isaac_lab_run_replicator_worker(
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
            "cameras": ["top"],
            "attempts_per_source_frame": 1,
            "max_source_frames": 1,
        }
    )

    assert result["ok"] is True
    assert commands
    assert result["replicator"]["expected_render_rows"] == 1
    assert result["replicator"]["rendered_count"] == 1


def test_isaac_lab_run_replicator_worker_blocks_during_active_teleop(tmp_path: Path, monkeypatch) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "replicator-worker-live-block"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=1, fps=2)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    bridge._sessions["teleop-active"] = {
        "session_id": "teleop-active",
        "workflow": "teleoperate",
        "status": "RUNNING",
        "returncode": None,
    }

    def fail_run(command, **kwargs):
        raise AssertionError(f"replicator worker must not run during live control: {command}")

    monkeypatch.setattr(subprocess, "run", fail_run)

    result = bridge.isaac_lab_run_replicator_worker(
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
            "cameras": ["top"],
            "attempts_per_source_frame": 1,
        }
    )

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert result["worker"]["blocker"] == "REPLICATOR_LIVE_SESSION_ACTIVE"
    assert result["worker"]["active_sessions"][0]["workflow"] == "teleoperate"


def test_isaac_lab_mimic_smoke_creates_queryable_blocked_job(tmp_path: Path) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "mimic-job-blocked"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=1, fps=2)
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
    start = bridge.isaac_lab_run_mimic_smoke(payload)

    assert build["ok"] is True
    assert start["ok"] is False
    assert start["tool"] == "lerobot.isaac_lab.run_mimic_smoke"
    assert start["job_id"].startswith("isaac_lab_mimic_")
    assert start["job"]["status"] == "BLOCKED"
    assert start["job"]["summary"]["mimic"]["blocker"] == "MIMIC_HDF5_EXPORT_MISSING"
    job_manifest = Path(start["job"]["job_manifest_path"])
    assert job_manifest == Path(start["output_root"]) / "mimic" / "job.json"
    assert job_manifest.is_file()
    persisted_job = json.loads(job_manifest.read_text(encoding="utf-8"))
    assert persisted_job["job_id"] == start["job_id"]
    assert persisted_job["kind"] == "mimic"
    assert persisted_job["status"] == "BLOCKED"

    status = bridge.isaac_lab_mimic_status({"job_id": start["job_id"]})
    assert status["ok"] is True
    assert status["tool"] == "lerobot.isaac_lab.mimic.status"
    assert status["status"] == "BLOCKED"
    assert status["job_id"] == start["job_id"]
    assert status["summary"]["mimic"]["blocker"] == "MIMIC_HDF5_EXPORT_MISSING"
    assert status["error"] is None

    stopped = bridge.isaac_lab_mimic_stop({"job_id": start["job_id"]})
    assert stopped["ok"] is True
    assert stopped["tool"] == "lerobot.isaac_lab.mimic.stop"
    assert stopped["status"] == "BLOCKED"
    assert stopped["stop_requested"] is False

    reloaded_bridge = _bridge(tmp_path)
    reloaded_status = reloaded_bridge.isaac_lab_mimic_status(payload)
    assert reloaded_status["ok"] is True
    assert reloaded_status["job_id"] == start["job_id"]
    assert reloaded_status["status"] == "BLOCKED"
    assert reloaded_status["job"]["job_manifest_path"] == str(job_manifest)


def test_isaac_lab_rl_teacher_smoke_creates_queryable_completed_job(tmp_path: Path) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "rl-teacher-job-ready"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=1, fps=2)
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
        "enable_rl_teacher": True,
        "rl_teacher_steps": 16,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    assert bridge.isaac_lab_build_synthetic(payload)["ok"] is True
    assert bridge.isaac_lab_export_hdf5(payload)["ok"] is True
    start = bridge.isaac_lab_run_rl_teacher_smoke(payload)

    assert start["ok"] is True
    assert start["tool"] == "lerobot.isaac_lab.run_rl_teacher_smoke"
    assert start["job_id"].startswith("isaac_lab_rl_teacher_")
    assert start["job"]["status"] == "COMPLETED"
    assert start["job"]["summary"]["rl_teacher"]["smoke"]["rl_teacher_steps"] == 16
    job_manifest = Path(start["job"]["job_manifest_path"])
    assert job_manifest == Path(start["output_root"]) / "rl_teacher" / "job.json"
    assert job_manifest.is_file()
    persisted_job = json.loads(job_manifest.read_text(encoding="utf-8"))
    assert persisted_job["job_id"] == start["job_id"]
    assert persisted_job["kind"] == "rl_teacher"
    assert persisted_job["status"] == "COMPLETED"

    status = bridge.isaac_lab_rl_teacher_status({})
    assert status["ok"] is True
    assert status["tool"] == "lerobot.isaac_lab.rl_teacher.status"
    assert status["status"] == "COMPLETED"
    assert status["job_id"] == start["job_id"]
    assert status["summary"]["rl_teacher"]["smoke"]["status"] == "ready_to_launch"

    stopped = bridge.isaac_lab_rl_teacher_stop({"job_id": start["job_id"]})
    assert stopped["ok"] is True
    assert stopped["status"] == "COMPLETED"
    assert stopped["stop_requested"] is False

    reloaded_bridge = _bridge(tmp_path)
    reloaded_status = reloaded_bridge.isaac_lab_rl_teacher_status(payload)
    assert reloaded_status["ok"] is True
    assert reloaded_status["job_id"] == start["job_id"]
    assert reloaded_status["status"] == "COMPLETED"
    assert reloaded_status["job"]["job_manifest_path"] == str(job_manifest)


def test_isaac_lab_mimic_and_rl_runner_endpoints_generate_training_sources(tmp_path: Path) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "runner-generate"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=1, fps=3)
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
        "mimic_trials": 6,
        "rl_teacher_steps": 16,
        "dry_run": True,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }

    assert bridge.isaac_lab_build_synthetic(payload)["ok"] is True
    assert bridge.isaac_lab_export_hdf5(payload)["ok"] is True
    mimic = bridge.isaac_lab_run_mimic(payload)
    rl = bridge.isaac_lab_run_rl_teacher(payload)

    assert mimic["ok"] is True
    assert mimic["tool"] == "lerobot.isaac_lab.run_mimic"
    assert mimic["job_id"].startswith("isaac_lab_mimic_")
    assert mimic["mimic"]["runner"]["status"] == "completed"
    assert mimic["mimic"]["runner"]["dry_run"] is True
    assert mimic["mimic"]["runner"]["operation"] == "mimic_generate_dataset"
    assert mimic["mimic"]["runner"]["generation_config"]["object_pose_randomization"]["workspace"] == "a4_sheet"
    assert mimic["mimic"]["runner"]["generation_config"]["object_pose_randomization"]["bounds_m"] == {
        "x": [-0.105, 0.105],
        "y": [-0.1485, 0.1485],
    }
    assert mimic["mimic"]["runner"]["generation_config"]["success_filter"]["success_only"] is True
    assert mimic["mimic"]["runner"]["generation_config"]["success_filter"]["excluded_manifest"].endswith("mimic/failures.jsonl")
    assert Path(mimic["mimic"]["generated_dataset_path"]).is_file()
    assert rl["ok"] is True
    assert rl["tool"] == "lerobot.isaac_lab.run_rl_teacher"
    assert rl["job_id"].startswith("isaac_lab_rl_teacher_")
    assert rl["rl_teacher"]["runner"]["status"] == "completed"
    assert rl["rl_teacher"]["runner"]["dry_run"] is True
    assert rl["rl_teacher"]["runner"]["operation"] == "rl_teacher_generate_dataset"
    assert rl["rl_teacher"]["runner"]["generation_config"]["observations"] == ["eef_pose", "joint_pos", "gripper_state", "object_pose"]
    assert rl["rl_teacher"]["runner"]["generation_config"]["success_metrics"] == ["bounded_workspace", "grasp_stable", "place_success", "simulation_only"]
    assert rl["rl_teacher"]["runner"]["generation_config"]["success_filter"]["success_only"] is True
    assert Path(rl["rl_teacher"]["generated_dataset_path"]).is_file()

    rebuilt = bridge.isaac_lab_build_synthetic(payload)
    training_rows = bridge._read_jsonl_file(Path(rebuilt["training_exposure"]["manifest_path"]))  # noqa: SLF001
    synthetic_rows = [row for row in training_rows if row["source_type"] == "isaac_lab_synthetic"]
    assert len(synthetic_rows) == mimic["mimic"]["success_count"] + rl["rl_teacher"]["success_count"]
    assert all((Path(rebuilt["output_root"]) / row["artifact_path"]).is_file() for row in synthetic_rows)


def test_live_isaac_lab_mimic_runner_blocks_during_active_teleop(tmp_path: Path, monkeypatch) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "mimic-runner-live-block"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=1, fps=2)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    bridge._sessions["teleop-active"] = {
        "session_id": "teleop-active",
        "workflow": "teleoperate",
        "status": "RUNNING",
        "returncode": None,
    }

    payload = {
        "mode": "live",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "stage_path": str(stage),
        "enable_replicator": False,
        "enable_mimic": True,
        "mimic_trials": 4,
        "dry_run": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }
    assert bridge.isaac_lab_build_synthetic(payload)["ok"] is True
    assert bridge.isaac_lab_export_hdf5(payload)["ok"] is True

    def fail_popen(command, **kwargs):
        raise AssertionError(f"mimic runner must not launch during live control: {command}")

    monkeypatch.setattr(bridge, "_project_lerobot_pids", lambda workflow: [])
    monkeypatch.setattr(subprocess, "Popen", fail_popen)

    result = bridge.isaac_lab_run_mimic(payload)

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert result["job"]["status"] == "BLOCKED"
    assert result["mimic"]["runner"]["status"] == "blocked"
    assert result["mimic"]["runner"]["blocker"] == "ISAAC_LAB_RUNNER_LIVE_SESSION_ACTIVE"
    assert result["mimic"]["runner"]["active_sessions"][0]["workflow"] == "teleoperate"
    assert result["error"]["code"] == "ISAAC_LAB_RUNNER_LIVE_SESSION_ACTIVE"


def test_live_isaac_lab_mimic_runner_launches_file_backed_job(tmp_path: Path, monkeypatch) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "mimic-runner-live-launch"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=1, fps=2)
    isaac_lab = tmp_path / "IsaacLab"
    mimic_script = isaac_lab / "scripts" / "imitation_learning" / "isaaclab_mimic" / "generate_dataset.py"
    mimic_script.parent.mkdir(parents=True)
    mimic_script.write_text("print('fake mimic')\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    launched: list[list[str]] = []
    processes: list[Any] = []

    class FakePopen:
        pid = 24680
        returncode = None

        def __init__(self, command, **kwargs):
            launched.append(list(command))
            processes.append(self)
            self.kwargs = kwargs
            self.terminated = False
            self.killed = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.killed = True
            self.returncode = -9

    payload = {
        "mode": "live",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "isaac_sim_python": str(isaac_python),
        "stage_path": str(stage),
        "enable_replicator": False,
        "enable_mimic": True,
        "mimic_trials": 4,
        "mimic_num_envs": 2,
        "dry_run": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }
    assert bridge.isaac_lab_build_synthetic(payload)["ok"] is True
    assert bridge.isaac_lab_export_hdf5(payload)["ok"] is True
    monkeypatch.setattr(bridge, "_project_lerobot_pids", lambda workflow: [])
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(os, "getpgid", lambda pid: os.getpgrp())

    result = bridge.isaac_lab_run_mimic(payload)

    assert result["ok"] is True
    assert result["status"] == "RUNNING"
    assert result["job"]["status"] == "RUNNING"
    assert result["job"]["pid"] == 24680
    assert launched
    assert launched[0][0] == str(isaac_python)
    assert launched[0][1] == str(mimic_script)
    assert "--trials" in launched[0]
    assert launched[0][launched[0].index("--trials") + 1] == "4"
    assert "--num-envs" in launched[0]
    assert launched[0][launched[0].index("--num-envs") + 1] == "2"
    job_manifest = Path(result["job"]["job_manifest_path"])
    assert job_manifest.is_file()
    persisted = json.loads(job_manifest.read_text(encoding="utf-8"))
    assert persisted["status"] == "RUNNING"
    assert persisted["pid"] == 24680

    status = bridge.isaac_lab_mimic_status({"job_id": result["job_id"]})
    assert status["status"] == "RUNNING"

    stopped = bridge.isaac_lab_mimic_stop({"job_id": result["job_id"]})
    assert stopped["status"] == "STOPPED"
    assert stopped["stop_requested"] is True
    assert processes[0].terminated is True


def test_live_isaac_lab_mimic_runner_status_refreshes_completed_process(tmp_path: Path, monkeypatch) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "mimic-runner-live-complete"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=1, fps=2)
    isaac_lab = tmp_path / "IsaacLab"
    mimic_script = isaac_lab / "scripts" / "imitation_learning" / "isaaclab_mimic" / "generate_dataset.py"
    mimic_script.parent.mkdir(parents=True)
    mimic_script.write_text("print('fake mimic')\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    processes: list[Any] = []

    class FakePopen:
        pid = 24681

        def __init__(self, command, **kwargs):
            self.returncode = None
            processes.append(self)

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    payload = {
        "mode": "live",
        "dataset_path": str(dataset),
        "isaac_lab_path": str(isaac_lab),
        "isaac_sim_python": str(isaac_python),
        "stage_path": str(stage),
        "enable_replicator": False,
        "enable_mimic": True,
        "mimic_trials": 2,
        "dry_run": False,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }
    assert bridge.isaac_lab_build_synthetic(payload)["ok"] is True
    assert bridge.isaac_lab_export_hdf5(payload)["ok"] is True
    monkeypatch.setattr(bridge, "_project_lerobot_pids", lambda workflow: [])
    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    result = bridge.isaac_lab_run_mimic(payload)
    processes[0].returncode = 0

    status = bridge.isaac_lab_mimic_status({"job_id": result["job_id"]})

    assert status["status"] == "COMPLETED"
    assert status["job"]["returncode"] == 0
    assert status["progress"]["percent"] == 100.0
    persisted = json.loads(Path(status["job"]["job_manifest_path"]).read_text(encoding="utf-8"))
    assert persisted["status"] == "COMPLETED"
    assert persisted["returncode"] == 0


def test_live_isaac_lab_run_replicator_worker_blocks_when_lerobot_process_is_active(tmp_path: Path, monkeypatch) -> None:
    from scripts.lerobot_synthetic_e2e_smoke import build_fixture_recording_dataset

    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "replicator-worker-live-process-block"
    build_fixture_recording_dataset(dataset, episodes=1, episode_s=1, fps=2)
    isaac_lab = tmp_path / "IsaacLab"
    isaac_lab.mkdir()
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_python = tmp_path / "isaac-sim" / "python.sh"
    isaac_python.parent.mkdir(parents=True)
    isaac_python.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr(
        bridge,
        "_project_lerobot_pids",
        lambda workflow: [4321] if workflow == "teleoperate" else [],
    )

    def fail_run(command, **kwargs):
        raise AssertionError(f"replicator worker must not run during live process: {command}")

    monkeypatch.setattr(subprocess, "run", fail_run)

    result = bridge.isaac_lab_run_replicator_worker(
        {
            "mode": "live",
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
            "cameras": ["top"],
            "attempts_per_source_frame": 1,
        }
    )

    assert result["ok"] is False
    assert result["worker"]["blocker"] == "REPLICATOR_LIVE_SESSION_ACTIVE"
    assert result["worker"]["active_sessions"] == [
        {"session_id": "", "workflow": "teleoperate", "status": "PROCESS_ACTIVE", "pid": 4321}
    ]


def test_train_start_blocks_when_isaac_augmentation_has_no_valid_variants(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "isaac-aug-invalid"
    _make_trainable_lerobot_dataset(dataset)
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"
    manifest_path = output_dir / "manifest.jsonl"
    output_dir.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr.isaac_data_augmentation.variant.v1",
                "variant_id": "invalid",
                "qa_ok": False,
                "qa_failure_code": "MISSING_AUGMENTED_RGB",
                "source": {"episode_index": 0, "frame_index": 0},
                "image_outputs": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "ok": True,
                "dataset_path": str(dataset),
                "output_dir": str(output_dir),
                "manifest_path": str(manifest_path),
                "summary_path": str(summary_path),
                "qa_summary_path": str(output_dir / "qa_summary.json"),
                "source_frame_count": 1,
                "variant_count": 1,
                "valid_variant_count": 0,
                "failed_variant_count": 1,
                "qa_failure_counts": {"MISSING_AUGMENTED_RGB": 1},
            }
        ),
        encoding="utf-8",
    )

    result = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_ISAAC_AUGMENTATION_QA_BLOCKED"
    assert "0 valid Isaac augmentation variants" in result["message"]


def test_train_start_warns_when_isaac_augmentation_has_failed_variants(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "isaac-aug-partial"
    _make_trainable_lerobot_dataset(dataset)
    output_dir = dataset / "sidecar" / "isaac_augmentation" / "latest"
    manifest_path = output_dir / "manifest.jsonl"
    output_dir.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr.isaac_data_augmentation.variant.v1",
                "variant_id": "valid",
                "qa_ok": True,
                "source": {"episode_index": 0, "frame_index": 0},
                "image_outputs": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "ok": True,
                "dataset_path": str(dataset),
                "output_dir": str(output_dir),
                "manifest_path": str(manifest_path),
                "summary_path": str(summary_path),
                "qa_summary_path": str(output_dir / "qa_summary.json"),
                "source_frame_count": 2,
                "variant_count": 2,
                "valid_variant_count": 1,
                "failed_variant_count": 1,
                "qa_failure_counts": {"MISSING_AUGMENTED_DEPTH": 1},
            }
        ),
        encoding="utf-8",
    )

    result = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    assert result["ok"] is True
    assert result["isaac_data_augmentation"]["valid_variant_count"] == 1
    assert result["isaac_data_augmentation"]["failed_variant_count"] == 1
    assert any(
        item["step"] == "ISAAC_AUGMENTATION_QA" and item["status"] == "warning"
        for item in result["step_trace"]
    )


def test_train_env_omits_isaac_augmentation_adapter_when_sidecar_missing(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "no-isaac-aug"
    _make_trainable_lerobot_dataset(dataset)
    request = LeRobotSessionRequest.model_validate(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    env = bridge._workflow_env_overrides("train", request)

    assert "ATR_LEROBOT_ISAAC_AUGMENTATION_ADAPTER" not in env
    assert "ATR_LEROBOT_ISAAC_AUGMENTATION_MANIFEST" not in env


def test_train_env_enables_isaac_rgbd_source_adapter_when_sim_original_exists(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "isaac-sim-original-train"
    _make_trainable_lerobot_dataset(dataset)
    manifest_path = dataset / "sidecar" / "isaac_rgbd" / "episode_000" / "attempt_a" / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr.isaac_rgbd.render_manifest.v1",
                "attempt_id": "attempt_a",
                "episode_index": 0,
                "frame_index": 0,
                "cameras": ["wrist"],
                "files": [
                    {"camera": "wrist", "kind": "rgb", "path": "wrist/rgb.png"},
                    {"camera": "wrist", "kind": "depth", "path": "wrist/depth.png"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    request = LeRobotSessionRequest.model_validate(
        {
            "mode": "live",
            "runtime_mode": "live",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "raw_depth_adapter",
        }
    )

    env = bridge._workflow_env_overrides("train", request)

    assert env["ATR_LEROBOT_ISAAC_RGBD_SOURCE_ADAPTER"] == "1"
    assert env["ATR_LEROBOT_ISAAC_RGBD_SOURCE_ROOT"] == str(dataset / "sidecar" / "isaac_rgbd")
    assert env["ATR_LEROBOT_ISAAC_RGBD_SOURCE_INCLUDE_ALL"] == "1"
    assert env["ATR_LEROBOT_ISAAC_RGBD_SOURCE_STRICT"] == "0"


def test_train_start_exposes_record_attempt_manifest_summary(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "attempt-dataset"
    _make_trainable_lerobot_dataset(dataset)
    manifest_path = dataset / "sidecar" / "attempts" / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "atr.record_attempt.event.v1",
                "event": "active_cam_result_written",
                "attempt_id": "attempt_train_ready",
                "episode_index": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = bridge.train_start(
        {
            "mode": "test",
            "runtime_mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/attempt-dataset",
            "observation_pipeline_id": "legacy_lerobot",
        }
    )

    assert result["ok"] is True
    assert result["record_attempts"]["available"] is True
    assert result["record_attempts"]["latest_attempt_id"] == "attempt_train_ready"
    assert result["record_attempts"]["event_count"] == 1


def test_train_blocks_observation_pipeline_mismatch(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "recorded"
    _make_trainable_lerobot_dataset(dataset)
    (dataset / "meta" / "atr_pipeline.json").write_text(
        json.dumps({"profile_id": "fake_omx_ai", "observation_pipeline_id": "rgbd_sidecar"}),
        encoding="utf-8",
    )

    result = bridge.train_start(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_path": str(dataset),
            "observation_pipeline_id": "legacy_lerobot",
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_OBSERVATION_PIPELINE_MISMATCH"


def test_realsense_camera_command_config_carries_depth_transform_contract(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    camera = bridge._realsense_camera_config(
        "341522300873",
        fps=15,
        use_depth=True,
        width=640,
        height=480,
        color_format="rgb8",
    )

    assert camera["type"] == "intelrealsense"
    assert camera["use_depth"] is True
    assert camera["align_depth_to_color"] is True
    assert camera["depth_scale_m_per_unit"] == 0.001
    assert camera["depth_clip_min_mm"] == 0.0
    assert camera["depth_clip_max_mm"] == 2000.0


def test_realsense_d405_camera_command_config_uses_d405_depth_scale(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    camera = bridge._realsense_camera_config(
        "352122273019",
        camera_key="wrist",
        fps=15,
        use_depth=True,
        width=640,
        height=480,
        color_format="bgr8",
    )

    assert camera["type"] == "intelrealsense"
    assert camera["serial_number_or_name"] == "352122273019"
    assert camera["depth_scale_m_per_unit"] == 0.0001


def test_pi05_train_env_passes_hf_token_from_token_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    bridge = _bridge(tmp_path)
    token_path = tmp_path / "hf_token"
    token_path.write_text("hf_fake_token", encoding="utf-8")
    bridge.config.hf_token_path = token_path

    request = LeRobotSessionRequest.model_validate({"mode": "live", "policy_type": "pi05"})
    env = bridge._workflow_env_overrides("train", request)

    assert env["HF_HOME"] == str(bridge.config.pi05_hf_home)
    assert env["HF_HUB_CACHE"] == str(bridge.config.pi05_hf_home / "hub")
    assert env["TOKENIZERS_PARALLELISM"] == "false"
    assert env["OMP_NUM_THREADS"] == "4"
    assert env["OPENBLAS_NUM_THREADS"] == "4"
    assert env["PYTORCH_CUDA_ALLOC_CONF"] == "expandable_segments:True"
    assert env["HF_TOKEN"] == "hf_fake_token"
    assert env["HUGGING_FACE_HUB_TOKEN"] == "hf_fake_token"


def test_rollout_runtime_status_is_inferred_from_action_log(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    log_path = tmp_path / "runs" / "lerobot_sessions" / "lr-rollout-test.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "INFO Using device: cuda\n"
        "Loading model from: /tmp/policy\n"
        "INFO OpenCVCamera(/dev/video0) connected.\n"
        "INFO omx_follower_arm OmxFollower connected.\n"
        "INFO Started actor thread\n"
        "INFO [ATR_ACTION] count=90 max_abs_delta=2.866 goal={} present={} delta={}\n",
        encoding="utf-8",
    )
    session = {
        "session_id": "lr-rollout-test",
        "workflow": "rollout",
        "profile_id": "fake_omx_ai",
        "mode": "live",
        "status": "POLICY_ACTIVE",
        "log_path": str(log_path),
        "pid": 123,
        "returncode": None,
    }

    result = bridge._session_response("lerobot.rollout.status", "live", session, [])

    assert result["runtime_phase"] == "ACTION_ACTIVE"
    assert result["runtime"]["action_count"] == 90
    assert result["action_count"] == 90
    assert result["runtime"]["max_abs_delta"] == 2.866
    assert result["max_abs_delta"] == 2.866
    assert "Robot action stream active" in result["runtime_message"]


def test_record_runtime_status_reports_specimen_preflight_failure(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    session = {
        "session_id": "lr-record-test",
        "workflow": "record",
        "profile_id": "fake_omx_ai",
        "mode": "live",
        "status": "FAILED",
        "log_path": str(tmp_path / "lr-record-test.log"),
        "pid": 123,
        "returncode": 134,
    }
    log_tail = (
        "Traceback (most recent call last):\n"
        "RecordStartPreflightError: SPECIMEN_OUTSIDE_A4: SPECIMEN_OUTSIDE_A4\n"
    )

    runtime = bridge._runtime_status_from_log(session, log_tail)

    assert runtime["phase"] == "FAILED"
    assert runtime["message"] == "Record start blocked: detected specimen is outside the A4 workspace."
    assert runtime["warnings"] == ["record_start_preflight_failed"]


def test_lerobot_cleanup_marker_matching_does_not_match_gui_dom_ids() -> None:
    markers = (
        "lerobot-rollout",
        "lerobot.rollout",
        "lerobot_pi05_rollout_wrapper.py",
        "eval_with_real_robot.py",
        "rtc.enabled",
    )

    assert not LeRobotBridge._cmdline_matches_lerobot_marker(
        ["python", "-", "document.getElementById('lerobot-rollout-action-status')"],
        markers,
    )
    assert LeRobotBridge._cmdline_matches_lerobot_marker(["lerobot-rollout"], markers)
    assert LeRobotBridge._cmdline_matches_lerobot_marker(["python", "-m", "lerobot.rollout"], markers)
    assert LeRobotBridge._cmdline_matches_lerobot_marker(
        ["python", "/home/jin/autonomous_researcher/scripts/lerobot_pi05_rollout_wrapper.py"],
        markers,
    )
    assert LeRobotBridge._cmdline_matches_lerobot_marker(["python", "eval.py", "--rtc.enabled=true"], markers)


def test_project_lerobot_pids_matches_isaac_mirror_runtime_wrapper_by_workflow(tmp_path: Path, monkeypatch) -> None:
    from device_bridges import lerobot_bridge as bridge_module

    bridge = _bridge(tmp_path)
    pid = 99123
    wrapper = tmp_path / "scripts" / "lerobot_isaac_mirror_runtime_wrapper.py"
    raw_cmdline = b"\0".join(
        [
            b"python",
            str(wrapper).encode("utf-8"),
            b"teleoperate",
            b"--fps=15",
        ]
    ) + b"\0"
    original_listdir = bridge_module.os.listdir
    original_readlink = bridge_module.os.readlink
    original_read_bytes = Path.read_bytes

    def fake_listdir(path):
        if Path(path) == Path("/proc"):
            return [str(pid)]
        return original_listdir(path)

    def fake_readlink(path):
        if Path(path) == Path(f"/proc/{pid}/cwd"):
            return str(tmp_path)
        return original_readlink(path)

    def fake_read_bytes(path: Path) -> bytes:
        if path == Path(f"/proc/{pid}/cmdline"):
            return raw_cmdline
        return original_read_bytes(path)

    monkeypatch.setattr(bridge_module.os, "listdir", fake_listdir)
    monkeypatch.setattr(bridge_module.os, "readlink", fake_readlink)
    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    assert bridge._project_lerobot_pids("teleoperate") == [pid]  # noqa: SLF001
    assert bridge._project_lerobot_pids("record") == []  # noqa: SLF001


def test_lerobot_display_viewer_marker_matching_targets_teleop_rerun_only() -> None:
    assert LeRobotBridge._cmdline_matches_lerobot_display_viewer(
        [
            "/home/jin/miniconda3/envs/lerobot/bin/rerun",
            "--port=9876",
            "--memory-limit=10%",
            "--expect-data-soon",
        ]
    )
    assert LeRobotBridge._cmdline_matches_lerobot_display_viewer(
        [
            "rerun",
            "--port",
            "9876",
            "--expect-data-soon",
        ]
    )
    assert not LeRobotBridge._cmdline_matches_lerobot_display_viewer(["rerun", "--port=9090"])
    assert not LeRobotBridge._cmdline_matches_lerobot_display_viewer(["python", "-m", "lerobot.teleoperate"])
