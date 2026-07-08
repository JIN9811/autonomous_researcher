"""Contract tests for the Isaac Lab Mimic + IL sidecar flow."""

from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from device_bridges.isaac_lab_synthetic import IsaacLabSyntheticPipeline
from mcp_tools.lerobot_schemas import IsaacLabSyntheticRequest


def _bridge(tmp_path: Path) -> LeRobotBridge:
    config = {
        "default_profile_id": "fake_omx_ai",
        "session_memory_path": str(tmp_path / "memory" / "sessions.json"),
        "dataset_root": str(tmp_path / "hf_datasets"),
        "fake_dataset_root": str(tmp_path / "datasets"),
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
            }
        },
    }
    return LeRobotBridge(LeRobotBridgeConfig.from_config(config, repo_root=tmp_path))


def test_isaac_lab_synthetic_request_defaults_to_physical_robotis_tasks() -> None:
    request = IsaacLabSyntheticRequest(dataset_path="/tmp/dataset")

    assert request.isaac_lab_task_name == "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0"
    assert request.isaac_lab_policy_task_name == "ATR-Robotis-OMX-PickPlace-Physical-v0"


def test_mimic_runner_uses_joint_replay_backend_for_physical_joint_actions(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    isaac_lab = tmp_path / "IsaacLab"
    script = tmp_path / "scripts" / "lerobot_isaac_lab_joint_replay_mimic.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('fake')\n", encoding="utf-8")

    request = IsaacLabSyntheticRequest(
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_lab_path=str(isaac_lab),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        enable_mimic=True,
        mimic_trials=3,
        mimic_num_envs=2,
        domain_randomization_profile="standard",
        dry_run=False,
        require_physics_pass=False,
        require_articulation_pass=False,
        isaac_lab_task_name="ATR-Robotis-OMX-PickPlace-Mimic-v0",
        mimic_external_callback="integrations.isaac_lab_robotis_omx.external_callback.register",
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    command = pipeline._runner_command(
        request,
        kind="mimic",
        hook_summary={"hdf5_path": str(output_root / "hdf5" / "source_real_success_annotated.hdf5")},
        smoke_summary={"output_root": str(output_root)},
    )

    assert command[1].endswith("scripts/lerobot_isaac_lab_joint_replay_mimic.py")
    assert "--input-file" in command
    assert command[command.index("--input-file") + 1].endswith("source_real_success_annotated.hdf5")
    assert "--output-file" in command
    assert command[command.index("--output-file") + 1].endswith("mimic/generated_dataset.hdf5")
    assert "--success-manifest" in command
    assert command[command.index("--success-manifest") + 1].endswith("mimic/successes.jsonl")
    assert "--failure-manifest" in command
    assert command[command.index("--failure-manifest") + 1].endswith("mimic/failures.jsonl")
    assert "--trials" in command
    assert command[command.index("--trials") + 1] == "3"
    assert "--env-name" in command
    assert command[command.index("--env-name") + 1] == "ATR-Robotis-OMX-PickPlace-Physical-v0"
    assert "--backend" in command
    assert command[command.index("--backend") + 1] == "joint_replay"
    assert "--task" not in command
    assert "--generation_num_trials" not in command
    assert "--num_envs" not in command
    assert "--external_callback" not in command
    assert "--robotis-domain-randomization-profile" in command
    assert command[command.index("--robotis-domain-randomization-profile") + 1] == "standard"
    assert "--headless" not in command
    assert "--enable_cameras" not in command
    assert "--hdf5" not in command
    assert "--env-wrapper" not in command
    assert "--num-envs" not in command


def test_mimic_runner_generation_config_preserves_robotis_scene_contract(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    stage = tmp_path / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
    stage.parent.mkdir(parents=True)
    stage.write_text("#usda 1.0\n", encoding="utf-8")
    request = IsaacLabSyntheticRequest(
        dataset_path=str(dataset),
        output_root=str(output_root),
        stage_path=str(stage),
        enable_mimic=True,
        mimic_trials=3,
        mimic_num_envs=2,
        domain_randomization_profile="standard",
        require_physics_pass=False,
        require_articulation_pass=False,
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])

    config = pipeline._runner_generation_config(
        request,
        kind="mimic",
        output_root=output_root,
        hook_summary={"success_criteria": ["both_fingers_contact_cube"]},
    )

    scene = config["scene_contract"]
    assert scene["layout_basis"] == "omx_table_layout_usda_static_props"
    assert scene["source_stage_path"] == str(stage)
    assert scene["managed_robot_prim"] == "{ENV_REGEX_NS}/Robot"
    assert scene["managed_red_cube_prim"] == "{ENV_REGEX_NS}/red_cube"
    assert scene["robot_initial_root_pose"] == [0.315, 0.06, -0.02, 0.0, 0.0, 0.7071068, 0.7071068]
    assert scene["red_cube_initial_pose_source"] == "isaac_rgbd_render_attempt_specimen_pose_or_lab_scene_default"
    assert config["rgbd_contract"]["cameras"] == ["top", "front", "right"]
    assert config["action_contract"]["source"] == "leader_joint_targets_exported_from_isaac_mirror"


def test_visual_joint_replay_mimic_runner_replays_actual_generated_process(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    isaac_lab = tmp_path / "IsaacLab"
    script = tmp_path / "scripts" / "lerobot_isaac_lab_joint_replay_mimic.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('fake')\n", encoding="utf-8")

    request = IsaacLabSyntheticRequest(
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_lab_path=str(isaac_lab),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        enable_mimic=True,
        mimic_trials=3,
        mimic_num_envs=2,
        dry_run=False,
        isaac_lab_visualize_generation=True,
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    command = pipeline._runner_command(
        request,
        kind="mimic",
        hook_summary={"hdf5_path": str(output_root / "hdf5" / "source_real_success_annotated.hdf5")},
        smoke_summary={"output_root": str(output_root)},
    )

    assert command[1].endswith("scripts/lerobot_isaac_lab_joint_replay_mimic.py")
    assert "--sim-step-generation" in command
    assert "--visualize-generation" not in command
    assert "--visual-task" in command
    assert command[command.index("--visual-task") + 1] == "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0"
    assert "--visual-num-envs" in command
    assert command[command.index("--visual-num-envs") + 1] == "1"
    assert "--external-callback" in command
    assert command[command.index("--external-callback") + 1] == "integrations.isaac_lab_robotis_omx.external_callback.register"
    assert "--robotis-camera-mode" in command
    assert command[command.index("--robotis-camera-mode") + 1] == "rgbd"
    assert "--viz" in command
    assert command[command.index("--viz") + 1] == "none"
    assert "--visual-fps" in command
    assert command[command.index("--visual-fps") + 1] == "0"
    assert "--visual-max-demos" in command
    assert command[command.index("--visual-max-demos") + 1] == "0"
    assert "--kit-args" not in command


def test_visual_joint_replay_mimic_runner_uses_lab_step_generation_not_preview_only(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    script = tmp_path / "scripts" / "lerobot_isaac_lab_joint_replay_mimic.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('fake')\n", encoding="utf-8")

    request = IsaacLabSyntheticRequest(
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        enable_mimic=True,
        mimic_trials=3,
        mimic_num_envs=3,
        dry_run=False,
        isaac_lab_visualize_generation=True,
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    command = pipeline._runner_command(
        request,
        kind="mimic",
        hook_summary={"hdf5_path": str(output_root / "hdf5" / "source_real_success_annotated.hdf5")},
        smoke_summary={"output_root": str(output_root)},
    )

    assert "--sim-step-generation" in command
    assert "--visual-task" in command
    assert command[command.index("--visual-task") + 1] == "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0"
    assert "--visual-max-demos" in command
    assert command[command.index("--visual-max-demos") + 1] == "0"
    assert "--visual-fps" in command
    assert command[command.index("--visual-fps") + 1] == "0"


def test_headless_joint_replay_mimic_runner_still_generates_lab_step_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    script = tmp_path / "scripts" / "lerobot_isaac_lab_joint_replay_mimic.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('fake')\n", encoding="utf-8")

    request = IsaacLabSyntheticRequest(
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        enable_mimic=True,
        mimic_trials=3,
        mimic_num_envs=3,
        dry_run=False,
        isaac_lab_visualize_generation=False,
        mimic_enable_cameras=True,
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    command = pipeline._runner_command(
        request,
        kind="mimic",
        hook_summary={"hdf5_path": str(output_root / "hdf5" / "source_real_success_annotated.hdf5")},
        smoke_summary={"output_root": str(output_root)},
    )

    assert "--sim-step-generation" in command
    assert "--visual-task" in command
    assert "--enable-cameras" in command
    assert "--viz" in command
    assert command[command.index("--viz") + 1] == "none"
    assert "--visualize-generation" not in command
    assert "--kit-args" not in command


def test_live_e2e_check_command_uses_real_10s_three_episode_preset(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "real-check"
    dataset.mkdir(parents=True)
    request = IsaacLabSyntheticRequest(
        mode="live",
        runtime_mode="live",
        dataset_path=str(dataset),
        isaac_lab_path="/home/jin/IsaacLab",
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        dry_run=False,
        e2e_create_fixture=False,
        e2e_episodes=3,
        e2e_episode_s=10,
        e2e_fps=15,
        mimic_trials=3,
        mimic_num_envs=2,
        isaac_lab_visualize_generation=False,
    )

    command = bridge._isaac_lab_live_e2e_command(request)  # noqa: SLF001

    assert command[0].endswith("/bin/python") or command[0] == "python"
    assert command[1].endswith("scripts/lerobot_isaac_lab_e2e_smoke.py")
    assert "--mode" in command
    assert command[command.index("--mode") + 1] == "live"
    assert "--dataset-path" in command
    assert command[command.index("--dataset-path") + 1] == str(dataset.resolve())
    assert "--trials" in command
    assert command[command.index("--trials") + 1] == "3"
    assert "--num-envs" in command
    assert command[command.index("--num-envs") + 1] == "2"
    assert "--episodes" in command
    assert command[command.index("--episodes") + 1] == "3"
    assert "--episode-s" in command
    assert command[command.index("--episode-s") + 1] == "10"
    assert "--fps" in command
    assert command[command.index("--fps") + 1] == "15"
    assert "--mimic-camera-width" in command
    assert command[command.index("--mimic-camera-width") + 1] == "320"
    assert "--mimic-camera-height" in command
    assert command[command.index("--mimic-camera-height") + 1] == "240"
    assert "--mimic-enable-cameras" in command
    assert "--no-create-fixture" in command
    assert "--visualize-generation" not in command


def test_live_e2e_check_command_preserves_visual_checkbox(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "visual-check"
    dataset.mkdir(parents=True)
    request = IsaacLabSyntheticRequest(
        mode="live",
        runtime_mode="live",
        dataset_path=str(dataset),
        dry_run=False,
        e2e_episodes=3,
        e2e_episode_s=10,
        mimic_trials=3,
        mimic_num_envs=2,
        isaac_lab_visualize_generation=True,
    )

    command = bridge._isaac_lab_live_e2e_command(request)  # noqa: SLF001

    assert "--visualize-generation" in command


def test_live_e2e_request_defaults_to_rgbd_camera_policy(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)
    dataset = tmp_path / "hf_datasets" / "jin" / "camera-policy-check"
    dataset.mkdir(parents=True)

    off_request = bridge._isaac_lab_live_e2e_request(  # noqa: SLF001
        IsaacLabSyntheticRequest(dataset_path=str(dataset), isaac_lab_visualize_generation=False)
    )
    on_request = bridge._isaac_lab_live_e2e_request(  # noqa: SLF001
        IsaacLabSyntheticRequest(dataset_path=str(dataset), isaac_lab_visualize_generation=True)
    )
    camera_request = bridge._isaac_lab_live_e2e_request(  # noqa: SLF001
        IsaacLabSyntheticRequest(
            dataset_path=str(dataset),
            isaac_lab_visualize_generation=True,
            mimic_enable_cameras=True,
        )
    )

    assert off_request.mimic_enable_cameras is True
    assert off_request.isaac_lab_policy_task_name == "ATR-Robotis-OMX-PickPlace-Physical-v0"
    assert on_request.mimic_enable_cameras is True
    assert on_request.isaac_lab_policy_task_name == "ATR-Robotis-OMX-PickPlace-Physical-v0"
    assert camera_request.mimic_enable_cameras is True
    assert camera_request.isaac_lab_policy_task_name == "ATR-Robotis-OMX-PickPlace-Physical-v0"


def test_mimic_runner_zero_success_attempts_are_failed_fast(tmp_path: Path) -> None:
    from device_bridges.lerobot_bridge import LeRobotBridge

    log_path = tmp_path / "mimic.log"
    log_path.write_text(
        "\n".join(
            [
                "0/1 (0.0%) successful demos generated by mimic",
                "0/9 (0.0%) successful demos generated by mimic",
            ]
        ),
        encoding="utf-8",
    )

    failure = LeRobotBridge._isaac_lab_active_runner_failure(  # noqa: SLF001
        "mimic",
        {"log_path": str(log_path)},
    )

    assert failure is not None
    assert failure["code"] == "ISAAC_LAB_MIMIC_ZERO_SUCCESS_ATTEMPTS"


def test_e2e_smoke_cli_forwards_episode_preset_to_bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import lerobot_isaac_lab_e2e_smoke as smoke

    captured: dict[str, object] = {}

    class FakeBridge:
        def isaac_lab_run_e2e(self, payload: dict[str, object]) -> dict[str, object]:
            captured.update(payload)
            return {"ok": True, "status": "COMPLETED"}

    monkeypatch.setattr(smoke, "_bridge", lambda repo_root: FakeBridge())

    rc = smoke.main(
        [
            "--mode",
            "test",
            "--dataset-path",
            str(tmp_path / "dataset"),
            "--episodes",
            "3",
            "--episode-s",
            "10",
            "--fps",
            "15",
            "--trials",
            "3",
            "--visualize-generation",
        ]
    )

    assert rc == 0
    assert captured["e2e_episodes"] == 3
    assert captured["e2e_episode_s"] == 10
    assert captured["e2e_fps"] == 15
    assert captured["max_source_frames"] == 450
    assert captured["mimic_trials"] == 3
    assert captured["isaac_lab_visualize_generation"] is True
    assert captured["mimic_enable_cameras"] is True
    assert captured["mimic_camera_width"] == 320
    assert captured["mimic_camera_height"] == 240
    assert captured["mimic_annotation_mode"] == "preannotated_passthrough"
    assert captured["isaac_lab_policy_task_name"] == "ATR-Robotis-OMX-PickPlace-Physical-v0"


def test_e2e_live_sequence_refreshes_vla_import_without_default_il_train() -> None:
    from scripts import lerobot_isaac_lab_e2e_smoke as smoke

    calls: list[str] = []

    class FakeBridge:
        def isaac_lab_build_synthetic(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("build")
            return {"ok": True}

        def isaac_lab_export_hdf5(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("export")
            return {"ok": True}

        def isaac_lab_annotate(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("annotate")
            return {
                "ok": True,
                "status": "READY_FOR_HDF5",
                "job": {"status": "COMPLETED"},
                "hdf5": {"annotation": {"status": "completed"}},
            }

        def isaac_lab_run_mimic(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("mimic")
            return {"status": "COMPLETED"}

    result = smoke._run_live_sequence(FakeBridge(), {}, timeout_s=1.0)  # noqa: SLF001

    assert result["ok"] is True
    assert calls == ["build", "export", "annotate", "mimic", "build"]
    assert result["status"] == "READY_FOR_VLA_TRAINING_IMPORT"
    assert result["train"] == {}
    assert result["eval"] == {}
    assert result["training_import_refresh"]["ok"] is True


def test_e2e_live_sequence_keeps_il_train_eval_behind_explicit_flag() -> None:
    from scripts import lerobot_isaac_lab_e2e_smoke as smoke

    calls: list[str] = []

    class FakeBridge:
        def isaac_lab_build_synthetic(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("build")
            return {"ok": True}

        def isaac_lab_export_hdf5(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("export")
            return {"ok": True}

        def isaac_lab_annotate(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("annotate")
            return {
                "ok": True,
                "status": "READY_FOR_HDF5",
                "job": {"status": "COMPLETED"},
                "hdf5": {"annotation": {"status": "completed"}},
            }

        def isaac_lab_run_mimic(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("mimic")
            return {"status": "COMPLETED"}

        def isaac_lab_train_il(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("train")
            return {"status": "COMPLETED"}

        def isaac_lab_eval_il(self, payload: dict[str, object]) -> dict[str, object]:
            calls.append("eval")
            return {"status": "COMPLETED"}

    result = smoke._run_live_sequence(FakeBridge(), {}, timeout_s=1.0, include_il_train=True)  # noqa: SLF001

    assert result["ok"] is True
    assert calls == ["build", "export", "annotate", "mimic", "build", "train", "eval"]


def test_api_run_e2e_refreshes_vla_import_without_il_train(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    dataset = tmp_path / "dataset"
    request = IsaacLabSyntheticRequest(
        mode="test",
        dataset_path=str(dataset),
        output_root=str(dataset / "sidecar" / "isaac_lab_synthetic" / "latest"),
        isaac_lab_path=str(tmp_path / "IsaacLab"),
        isaac_sim_python=str(tmp_path / "IsaacSim" / "python.sh"),
        enable_mimic=True,
    )
    calls: list[str] = []

    def fake_build(req: IsaacLabSyntheticRequest) -> dict[str, object]:
        calls.append("build")
        return {
            "ok": True,
            "status": "READY_FOR_TRAINING",
            "validation_report": {},
            "canonical_episode_index": {},
            "training_exposure": {"row_count": 3, "source_counts": {"isaac_lab_synthetic": 3}},
        }

    def fake_export(req: IsaacLabSyntheticRequest) -> dict[str, object]:
        calls.append("export")
        return {"ok": True, "status": "READY_FOR_HDF5", "hdf5": {}}

    def fake_annotate(req: IsaacLabSyntheticRequest) -> dict[str, object]:
        calls.append("annotate")
        return {"ok": True, "status": "READY_FOR_HDF5", "hdf5": {"annotation": {"status": "completed"}}}

    def fake_mimic(req: IsaacLabSyntheticRequest) -> dict[str, object]:
        calls.append("mimic")
        return {"ok": True, "status": "READY_FOR_TRAINING", "mimic": {"status": "completed"}}

    def fail_train(req: IsaacLabSyntheticRequest) -> dict[str, object]:
        raise AssertionError("run_e2e must not launch Isaac Lab IL training by default")

    monkeypatch.setattr(pipeline, "build_synthetic", fake_build)
    monkeypatch.setattr(pipeline, "export_hdf5", fake_export)
    monkeypatch.setattr(pipeline, "annotate_source", fake_annotate)
    monkeypatch.setattr(pipeline, "run_mimic", fake_mimic)
    monkeypatch.setattr(pipeline, "train_il", fail_train)
    monkeypatch.setattr(pipeline, "eval_il", fail_train)

    result = pipeline.run_e2e(request)

    assert result["ok"] is True
    assert calls == ["build", "export", "annotate", "mimic", "build"]
    assert result["training_exposure"]["e2e"]["status"] == "READY_FOR_VLA_TRAINING_IMPORT"
    assert result["training_exposure"]["train"] == {}
    assert result["training_exposure"]["eval"] == {}


def test_visual_mimic_generation_opens_kit_viewport_without_enabling_cameras(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    request = IsaacLabSyntheticRequest(
        mode="live",
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_lab_path=str(tmp_path / "IsaacLab"),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        enable_mimic=True,
        dry_run=False,
        isaac_lab_visualize_generation=True,
        mimic_enable_cameras=False,
        mimic_generation_backend="official",
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])

    command = pipeline._runner_command(
        request,
        kind="mimic",
        hook_summary={"hdf5_path": str(output_root / "hdf5" / "source_real_success_annotated.hdf5")},
        smoke_summary={"output_root": str(output_root)},
    )

    assert "--headless" not in command
    assert "--viz" in command
    assert command[command.index("--viz") + 1] == "kit"
    assert "--kit_args" in command
    assert "--/app/useFabricSceneDelegate=false" in command[command.index("--kit_args") + 1]
    assert "--robotis-camera-mode" in command
    assert command[command.index("--robotis-camera-mode") + 1] == "off"
    assert "--enable_cameras" not in command
    assert "--rendering_mode" in command
    assert command[command.index("--rendering_mode") + 1] == "balanced"


def test_headless_live_annotation_keeps_cameras_enabled(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    request = IsaacLabSyntheticRequest(
        mode="live",
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_lab_path=str(tmp_path / "IsaacLab"),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        dry_run=False,
        isaac_lab_visualize_generation=False,
        mimic_enable_cameras=True,
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])

    command = pipeline._annotation_command(  # noqa: SLF001
        request,
        output_root / "hdf5" / "exported_successful_real_episodes.hdf5",
        output_root / "hdf5" / "source_real_success_annotated.hdf5",
    )

    assert "--headless" in command
    assert "--robotis-camera-mode" in command
    assert command[command.index("--robotis-camera-mode") + 1] == "rgbd"
    assert "--enable_cameras" in command
    assert "--rendering_mode" in command


def test_lerobot_degree_actions_export_as_robotis_joint_targets() -> None:
    from device_bridges.isaac_lab_hdf5 import _lab_action_vector

    action = _lab_action_vector([0.0, 90.0, -90.0, 45.0, 30.0, 60.0])

    assert action == pytest.approx([0.0, 1.5707963, -1.5707963, 0.7853982, 0.5235988, 1.0471976, -1.0471976])


def test_preannotated_hdf5_passthrough_completes_without_runner(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")

    dataset = tmp_path / "dataset"
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    source = output_root / "hdf5" / "exported_successful_real_episodes.hdf5"
    source.parent.mkdir(parents=True)
    env_args = {"env_name": "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0", "type": 2, "env_kwargs": {}}
    frames = 5
    pose = np.tile(np.eye(4, dtype=np.float32), (frames, 1, 1))
    with h5py.File(source, "w") as handle:
        handle.attrs["format_version"] = 1
        handle.attrs["env_args"] = json.dumps(env_args)
        data = handle.create_group("data")
        data.attrs["env_args"] = json.dumps(env_args)
        demo = data.create_group("demo_000000")
        demo.attrs["num_samples"] = frames
        initial = demo.create_group("initial_state")
        robot = initial.create_group("articulation").create_group("robot")
        robot.create_dataset("root_pose", data=np.zeros((1, 7), dtype=np.float32))
        robot.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
        robot.create_dataset("joint_position", data=np.zeros((1, 7), dtype=np.float32))
        robot.create_dataset("joint_velocity", data=np.zeros((1, 7), dtype=np.float32))
        cube = initial.create_group("rigid_object").create_group("red_cube")
        cube.create_dataset("root_pose", data=np.zeros((1, 7), dtype=np.float32))
        cube.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
        demo.create_dataset("actions", data=np.zeros((frames, 7), dtype=np.float32))
        obs = demo.create_group("obs")
        datagen = obs.create_group("datagen_info")
        object_pose = datagen.create_group("object_pose")
        object_pose.create_dataset("red_cube", data=pose)
        datagen.create_group("eef_pose").create_dataset("omx", data=pose)
        datagen.create_group("target_eef_pose").create_dataset("omx", data=pose)
        signals = datagen.create_group("subtask_term_signals")
        signals.create_dataset("lift", data=np.array([[False], [False], [True], [True], [True]]))
        signals.create_dataset("place", data=np.array([[False], [False], [False], [True], [True]]))
    (output_root / "hdf5" / "export_summary.json").write_text(
        json.dumps({"ok": True, "output_path": str(source)}),
        encoding="utf-8",
    )
    request = IsaacLabSyntheticRequest(
        mode="live",
        dry_run=False,
        dataset_path=str(dataset),
        output_root=str(output_root),
        mimic_annotation_mode="preannotated_passthrough",
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])

    result = pipeline.annotate_source(request)

    annotated = output_root / "hdf5" / "source_real_success_annotated.hdf5"
    annotation = result["hdf5"]["annotation"]
    assert result["ok"] is True
    assert annotation["status"] == "completed"
    assert annotation["mode"] == "preannotated_passthrough"
    assert annotation["command"] == []
    assert annotation["datagen_pool_ok"] is True
    assert annotation["datagen_pool_blockers"] == []
    with h5py.File(source, "r") as handle:
        source_signals = handle["data"]["demo_000000"]["obs"]["datagen_info"]["subtask_term_signals"]
        source_object_poses = handle["data"]["demo_000000"]["obs"]["datagen_info"]["object_pose"]
        assert "cube_lifted" not in source_signals
        assert "released_at_target" not in source_signals
        assert "place_target" not in source_object_poses
    with h5py.File(annotated, "r") as handle:
        output_signals = handle["data"]["demo_000000"]["obs"]["datagen_info"]["subtask_term_signals"]
        output_object_poses = handle["data"]["demo_000000"]["obs"]["datagen_info"]["object_pose"]
        assert "cube_lifted" in output_signals
        assert "released_at_target" in output_signals
        assert "place_target" in output_object_poses


def test_hdf5_contract_requires_env_args_and_datagen_info(tmp_path: Path) -> None:
    from device_bridges.isaac_lab_hdf5 import validate_isaac_lab_hdf5_contract

    h5py = pytest.importorskip("h5py")
    hdf5_path = tmp_path / "bad.hdf5"
    with h5py.File(hdf5_path, "w") as handle:
        data = handle.create_group("data")
        demo = data.create_group("demo_000000")
        demo.attrs["num_samples"] = 2
        demo.create_dataset("actions", data=[[0.0], [1.0]])

    report = validate_isaac_lab_hdf5_contract(
        hdf5_path,
        expected_env_name="ATR-Robotis-OMX-PickPlace-Mimic-v0",
    )

    assert report["ok"] is False
    assert "ENV_ARGS_MISSING" in report["blockers"]
    assert "DATAGEN_INFO_MISSING" in report["blockers"]


def test_hdf5_contract_loads_into_official_datagen_info_pool(tmp_path: Path) -> None:
    from device_bridges.isaac_lab_hdf5 import validate_isaac_lab_datagen_pool_contract

    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")

    hdf5_path = tmp_path / "annotated.hdf5"
    env_args = {"env_name": "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0", "type": 2, "env_kwargs": {}}
    frames = 5
    pose = np.tile(np.eye(4, dtype=np.float32), (frames, 1, 1))

    with h5py.File(hdf5_path, "w") as handle:
        handle.attrs["format_version"] = 1
        data = handle.create_group("data")
        data.attrs["env_args"] = json.dumps(env_args)
        data.attrs["total"] = 1
        demo = data.create_group("demo_000000")
        demo.attrs["num_samples"] = frames
        demo.attrs["success"] = True
        initial = demo.create_group("initial_state")
        robot = initial.create_group("articulation").create_group("robot")
        robot.create_dataset("root_pose", data=np.zeros((1, 7), dtype=np.float32))
        robot.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
        robot.create_dataset("joint_position", data=np.zeros((1, 7), dtype=np.float32))
        robot.create_dataset("joint_velocity", data=np.zeros((1, 7), dtype=np.float32))
        cube = initial.create_group("rigid_object").create_group("red_cube")
        cube.create_dataset("root_pose", data=np.zeros((1, 7), dtype=np.float32))
        cube.create_dataset("root_velocity", data=np.zeros((1, 6), dtype=np.float32))
        demo.create_dataset("actions", data=np.zeros((frames, 7), dtype=np.float32))
        obs = demo.create_group("obs")
        datagen = obs.create_group("datagen_info")
        object_pose = datagen.create_group("object_pose")
        object_pose.create_dataset("red_cube", data=pose)
        object_pose.create_dataset("place_target", data=pose)
        datagen.create_group("eef_pose").create_dataset("omx", data=pose)
        datagen.create_group("target_eef_pose").create_dataset("omx", data=pose)
        signals = datagen.create_group("subtask_term_signals")
        signals.create_dataset("cube_lifted", data=np.array([[False], [False], [True], [True], [True]]))
        signals.create_dataset("released_at_target", data=np.array([[False], [False], [False], [True], [True]]))

    report = validate_isaac_lab_datagen_pool_contract(
        hdf5_path,
        expected_env_name="ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0",
        subtask_term_signals=["cube_lifted", "released_at_target", None],
    )

    assert report["ok"] is True
    assert report["num_datagen_infos"] == 1
    assert report["subtask_boundaries"]["omx"] == [[(0, 3), (3, 4), (4, 5)]]


def test_annotation_command_uses_external_callback(tmp_path: Path) -> None:
    request = IsaacLabSyntheticRequest(
        dataset_path=str(tmp_path / "dataset"),
        output_root=str(tmp_path / "out"),
        isaac_lab_path="/home/jin/IsaacLab",
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        isaac_lab_task_name="ATR-Robotis-OMX-PickPlace-Mimic-v0",
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    command = pipeline._annotation_command(request, tmp_path / "source.hdf5", tmp_path / "annotated.hdf5")
    assert "annotate_demos.py" in command[1]
    assert "--auto" in command
    assert "--external_callback" in command


def test_il_train_command_uses_wrapper_because_train_has_no_external_callback(tmp_path: Path) -> None:
    request = IsaacLabSyntheticRequest(
        dataset_path=str(tmp_path / "dataset"),
        output_root=str(tmp_path / "out"),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        isaac_lab_policy_task_name="ATR-Robotis-OMX-PickPlace-v0",
        robomimic_algo="bc",
        domain_randomization_profile="standard",
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    command = pipeline._il_train_command(request, tmp_path / "generated_dataset.hdf5")
    assert command[1].endswith("scripts/lerobot_isaac_lab_robomimic_train.py")
    assert "--task" in command
    assert command[command.index("--task") + 1] == "ATR-Robotis-OMX-PickPlace-v0"
    assert "--dataset" in command
    assert "--epochs" in command
    assert command[command.index("--epochs") + 1] == str(request.e2e_train_steps)
    assert "--robotis-domain-randomization-profile" in command
    assert command[command.index("--robotis-domain-randomization-profile") + 1] == "standard"
    assert "--normalize_training_actions" not in command


def test_mimic_generation_never_applies_stress_profile_to_generated_data(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    request = IsaacLabSyntheticRequest(
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_lab_path=str(tmp_path / "IsaacLab"),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        enable_mimic=True,
        domain_randomization_profile="stress",
        dry_run=False,
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])

    command = pipeline._runner_command(
        request,
        kind="mimic",
        hook_summary={"hdf5_path": str(output_root / "hdf5" / "source_real_success_annotated.hdf5")},
        smoke_summary={"output_root": str(output_root)},
    )

    assert "--robotis-domain-randomization-profile" in command
    assert command[command.index("--robotis-domain-randomization-profile") + 1] == "conservative"
    assert "--process-cooldown-sec" in command
    assert command[command.index("--process-cooldown-sec") + 1] == "3.0"


def test_official_mimic_runner_uses_isaaclab_dash_p_launcher(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    wrapper = scripts_dir / "lerobot_isaac_lab_official_mimic_generate.py"
    replay_promoter = scripts_dir / "lerobot_isaac_lab_official_mimic_replay_promote.py"
    wrapper.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    replay_promoter.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    request = IsaacLabSyntheticRequest(
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_lab_path=str(tmp_path / "IsaacLab"),
        isaac_sim_python="/home/jin/IsaacLab/isaaclab.sh",
        enable_mimic=True,
        mimic_generation_backend="official",
        dry_run=False,
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])

    command = pipeline._runner_command(
        request,
        kind="mimic",
        hook_summary={"hdf5_path": str(output_root / "hdf5" / "exported_successful_real_episodes.hdf5")},
        smoke_summary={"output_root": str(output_root)},
    )

    assert command[:3] == [
        "/home/jin/IsaacLab/isaaclab.sh",
        "-p",
        str(tmp_path / "scripts" / "lerobot_isaac_lab_official_mimic_generate.py"),
    ]
    assert "--isaac-python" in command
    assert command[command.index("--isaac-python") + 1] == "/home/jin/IsaacLab/isaaclab.sh"

    runner = pipeline._runner_summary(  # noqa: SLF001
        request,
        kind="mimic",
        operation="mimic_generate_dataset",
        hook_summary={
            "hdf5_path": str(output_root / "hdf5" / "exported_successful_real_episodes.hdf5"),
            "smoke": {"output_root": str(output_root)},
        },
    )
    assert runner["script_path"] == str(wrapper)
    assert runner["script_exists"] is True
    assert runner["post_run"]["script_path"] == str(replay_promoter)
    assert runner["post_run"]["script_exists"] is True


def test_official_mimic_runner_uses_default_isaac_lab_root_when_path_is_omitted(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    request = IsaacLabSyntheticRequest(
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        enable_mimic=True,
        mimic_generation_backend="official",
        mimic_trials=3,
        attempts_per_source_frame=3,
        require_physics_pass=False,
        require_articulation_pass=False,
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])

    command = pipeline._runner_command(
        request,
        kind="mimic",
        hook_summary={"hdf5_path": str(output_root / "hdf5" / "exported_successful_real_episodes.hdf5")},
        smoke_summary={"output_root": str(output_root)},
    )

    assert command[command.index("--annotate-script") + 1] == (
        "/home/jin/IsaacLab/scripts/imitation_learning/isaaclab_mimic/annotate_demos.py"
    )
    assert command[command.index("--generate-script") + 1] == (
        "/home/jin/IsaacLab/scripts/imitation_learning/isaaclab_mimic/generate_dataset.py"
    )
    replay_command = pipeline._official_mimic_replay_promote_command(  # noqa: SLF001
        request,
        output_root=output_root,
    )
    assert replay_command[replay_command.index("--replay-script") + 1] == (
        "/home/jin/IsaacLab/scripts/tools/replay_demos.py"
    )


def test_eval_il_resolves_nested_robomimic_checkpoint_from_latest_run(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    output_root = tmp_path / "out"
    stale = (
        output_root
        / "il"
        / "robomimic"
        / "ATR-Robotis-OMX-PickPlace-v0"
        / "robotis_omx_pickplace_bc"
        / "20260701010101"
        / "models"
        / "model_epoch_best.pth"
    )
    latest = (
        output_root
        / "il"
        / "robomimic"
        / "ATR-Robotis-OMX-PickPlace-v0"
        / "robotis_omx_pickplace_bc"
        / "20260702020202"
        / "models"
        / "model_epoch_2.pth"
    )
    stale.parent.mkdir(parents=True)
    latest.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")
    latest.write_bytes(b"latest")
    os.utime(stale, (1, 1))
    os.utime(latest, (2, 2))

    request = IsaacLabSyntheticRequest(
        mode="live",
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        isaac_lab_policy_task_name="ATR-Robotis-OMX-PickPlace-v0",
        dry_run=False,
        domain_randomization_profile="stress",
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])

    result = pipeline.eval_il(request)
    summary = result["training_exposure"]["il_eval"]

    assert result["ok"] is True
    assert summary["checkpoint"] == str(latest)
    assert summary["checkpoint_exists"] is True
    assert "--checkpoint" in summary["command"]
    assert summary["command"][summary["command"].index("--checkpoint") + 1] == str(latest)
    assert "--robotis-domain-randomization-profile" in summary["command"]
    assert summary["command"][summary["command"].index("--robotis-domain-randomization-profile") + 1] == "stress"
