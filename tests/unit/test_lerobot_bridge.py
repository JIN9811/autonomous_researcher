"""Unit tests for deterministic LeRobot bridge behavior."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path

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


def _make_trainable_lerobot_dataset(path: Path) -> None:
    (path / "meta").mkdir(parents=True, exist_ok=True)
    (path / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (path / "meta" / "info.json").write_text(json.dumps({"codebase_version": "v2.1", "total_episodes": 1, "total_frames": 1}), encoding="utf-8")
    (path / "meta" / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": "Pick up the cylinder"}) + "\n", encoding="utf-8")
    (path / "meta" / "episodes.jsonl").write_text(json.dumps({"episode_index": 0, "tasks": ["Pick up the cylinder"], "length": 1}) + "\n", encoding="utf-8")
    (path / "meta" / "episodes_stats.jsonl").write_text(json.dumps({"episode_index": 0, "stats": {}}) + "\n", encoding="utf-8")
    (path / "data" / "chunk-000" / "episode_000000.parquet").write_bytes(b"PAR1")
    _write_raw_depth_manifest(path)


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
    target_script = tmp_path / "sim" / "robotis_omx" / "tools" / "isaac_omx_mirror_server.py"
    target_script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_script, target_script)
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



def test_mirror_receiver_extension_command_uses_isaac_app_and_extension(tmp_path: Path) -> None:
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
        },
        "http://127.0.0.1:18766/joints",
    )

    assert command_info["ok"] is True
    command = command_info["command"]
    assert command[0] == str(isaac_app)
    assert "--ext-folder" in command
    assert str(tmp_path / "sim" / "robotis_omx" / "extensions") in command
    assert "--enable" in command
    assert "atr.omx.mirror" in command
    assert "--/exts/atr.omx.mirror/host=127.0.0.1" in command
    assert "--/exts/atr.omx.mirror/port=18766" in command
    assert f"--/exts/atr.omx.mirror/scene={scene_path}" in command
    assert "--/exts/atr.omx.mirror/openSceneOnStartup=true" in command
    assert "--/exts/atr.omx.mirror/playTimelineOnStartup=true" in command
    assert str(scene_path) not in command


def test_live_mirror_preflight_blocks_non_isaac_update_tick_receiver(tmp_path: Path) -> None:
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
    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_ISAAC_MIRROR_RECEIVER_NOT_IN_ISAAC_UPDATE_TICK"

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


def test_live_teleoperate_with_isaac_mirror_blocks_when_receiver_unavailable(tmp_path: Path, monkeypatch) -> None:
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
    bridge._start_live_process = lambda **_: (_ for _ in ()).throw(AssertionError("must not start live teleop"))  # type: ignore[method-assign]

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

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_ISAAC_MIRROR_RECEIVER_UNAVAILABLE"
    assert "http://127.0.0.1:8766/health" in result["message"]


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
    bridge.mirror_loop_start = lambda payload: (_ for _ in ()).throw(AssertionError("live teleop mirror must run in-process"))  # type: ignore[method-assign]
    bridge._start_live_process = lambda **kwargs: live_start_kwargs.update(kwargs) or {"ok": True, "session_updates": {"pid": 1234, "log_path": "", "returncode": None}}  # type: ignore[method-assign]

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
    command = [str(item) for item in live_start_kwargs["command"]]  # type: ignore[index]
    assert "teleoperate" in command
    assert any(item.endswith("lerobot_isaac_mirror_runtime_wrapper.py") for item in command)
    env = live_start_kwargs["env_overrides"]  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_ENABLED"] == "1"  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_ENDPOINT"] == "http://127.0.0.1:8766/joints"  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_SOURCE"] == "follower_present_position"  # type: ignore[index]
    assert env["ATR_ISAAC_MIRROR_CALIBRATION_PATH"] == str(tmp_path / "memory" / "isaac_omx_mirror_calibration.json")  # type: ignore[index]


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
        "depth_scale_m_per_unit": 0.001,
        "depth_clip_min_mm": 0.0,
        "depth_clip_max_mm": 2000.0,
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
    assert "--policy.path=lerobot/xvla-base" in started["command_preview"]
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
    assert "--policy.path=lerobot/smolvla_base" in started["command_preview"]
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
    meta_dir.mkdir(parents=True)
    video_dir.mkdir(parents=True)
    (meta_dir / "info.json").write_text('{"fps": 30, "total_episodes": 1}', encoding="utf-8")
    (video_dir / "episode_0.mp4").write_bytes(b"not-real-video")
    bridge = _bridge(tmp_path)

    result = bridge.visualize_dataset(
        {
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_root": str(tmp_path / "datasets"),
            "dataset_repo_id": "atr/demo",
            "episode_index": 0,
        }
    )

    assert result["ok"] is True
    assert result["metadata"]["meta/info.json"]["fps"] == 30
    assert any(item["media_type"] == "video" for item in result["media"])


def test_visualize_start_uses_lerobot_html_visualizer_with_dataset_root(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "hf_datasets" / "jin" / "record-test"
    dataset_dir.mkdir(parents=True)
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
            "visualization_web_port": 9091,
        }
    )

    command = result["command_preview"]
    assert result["ok"] is True
    assert result["tool"] == "lerobot.visualize.start"
    assert result["workflow"] == "visualize"
    assert Path(command[0]).name in {"conda", "conda.exe"}
    assert command[1:7] == ["run", "--no-capture-output", "-n", "lerobot", "python", "-m"]
    assert "lerobot.scripts.visualize_dataset_html" in command
    assert "--repo-id=jin/record-test" in command
    assert "--root=" + str(dataset_dir.resolve()) in command
    assert "--episodes" in command
    assert "2" in command
    assert "--serve=1" in command
    assert "--port=9091" in command
    assert result["visualization"]["viewer_url"] == "http://127.0.0.1:9091/jin/record-test/episode_2"
    assert captured["command"] == command


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
    assert env["ATR_LEROBOT_DEPTH_CLIP_MIN_MM"] == "0.0"
    assert env["ATR_LEROBOT_DEPTH_CLIP_MAX_MM"] == "2000.0"


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
