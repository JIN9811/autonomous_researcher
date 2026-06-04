"""Unit tests for deterministic LeRobot bridge behavior."""

from __future__ import annotations

import json
import subprocess
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


def _mark_lerobot_dataset_v30(path: Path) -> None:
    info_path = path / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["codebase_version"] = "v3.0"
    info_path.write_text(json.dumps(info), encoding="utf-8")
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


def test_port_baseline_detect_persists_follower_port(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0"]  # type: ignore[method-assign]

    baseline = bridge.ports_baseline({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0", "/dev/ttyUSB9"]  # type: ignore[method-assign]
    detected = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "follower"})
    teleop = bridge.teleoperate_start({"mode": "test", "profile_id": "fake_omx_ai", "camera_enabled": True})

    assert baseline["ok"] is True
    assert detected["selected_port"] == "/dev/ttyUSB9"
    assert detected["saved_devices"]["follower"]["port"] == "/dev/ttyUSB9"
    assert "--robot.port=/dev/ttyUSB9" in teleop["command_preview"]


def test_port_detect_accepts_removed_port_like_lerobot_find_port(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0", "/dev/ttyUSB1"]  # type: ignore[method-assign]

    bridge.ports_baseline({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader"})
    bridge._scan_serial_ports = lambda: ["/dev/ttyUSB0"]  # type: ignore[method-assign]
    detected = bridge.ports_detect({"mode": "live", "profile_id": "fake_omx_ai", "device_role": "leader"})

    assert detected["ok"] is True
    assert detected["change_type"] == "removed"
    assert detected["selected_port"] == "/dev/ttyUSB1"


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
    assert "--batch_size=32" in started["command_preview"]
    assert "--num_workers=12" in started["command_preview"]
    assert "--eval_freq=500" in started["command_preview"]
    assert "--save_freq=500" in started["command_preview"]
    assert all(not arg.startswith("--eval.batch_size=") for arg in started["command_preview"])
    assert "--policy.n_obs_steps=1" in started["command_preview"]
    assert "--policy.chunk_size=50" in started["command_preview"]
    assert "--policy.n_action_steps=50" in started["command_preview"]
    assert "--policy.compile_model=false" in started["command_preview"]
    assert "--policy.gradient_checkpointing=true" in started["command_preview"]
    assert "--policy.dtype=bfloat16" in started["command_preview"]
    assert "--policy.freeze_vision_encoder=false" in started["command_preview"]
    assert "--policy.train_expert_only=false" in started["command_preview"]
    assert "--wandb.enable=true" in started["command_preview"]
    assert all(not arg.startswith("--policy.use_amp=") for arg in started["command_preview"])
    assert "--wandb.mode=offline" in started["command_preview"]


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


def test_train_progress_uses_sample_count_when_step_is_rounded(tmp_path: Path) -> None:
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
    assert status["training"]["current_step"] == 1031
    assert status["training"]["progress_percent"] == 34.37
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
    assert started["dataset_path"].endswith(fresh_repo)
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
    assert result["dataset_path"].endswith("jin/eval_pick_and_place_cube_rollout")


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
    assert "scripts/lerobot_pi05_rollout_wrapper.py" in " ".join(result["command_preview"])
    assert "--policy.path=fake://pi05_policy" in result["command_preview"]
    assert "--policy.type=pi05" not in result["command_preview"]
    assert "--device=cuda" in result["command_preview"]
    assert "--policy.device=cuda" in result["command_preview"]
    assert "--rtc.enabled=true" in result["command_preview"]
    assert "--rtc.execution_horizon=20" in result["command_preview"]
    assert "--rtc.max_guidance_weight=1.0" in result["command_preview"]
    assert "--action_queue_size_to_get_new_actions=60" in result["command_preview"]
    assert "--task=Move specimen from 3DP to UTM" in result["command_preview"]
    assert f"--duration={int(86400.0)}" in result["command_preview"]
    camera_arg = next(item for item in result["command_preview"] if item.startswith("--robot.cameras="))
    cameras = json.loads(camera_arg.split("=", 1)[1])
    assert all(camera["fps"] == 30 for camera in cameras.values())


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
    assert command[:7] == ["conda", "run", "--no-capture-output", "-n", "lerobot", "python", "-m"]
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
    assert captured["env_overrides"] == {
        "LEROBOT_TTS_ENGINE": "espeak-ng",
        "LEROBOT_TTS_RATE": "-60",
    }


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
    assert result["runtime"]["max_abs_delta"] == 2.866
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
