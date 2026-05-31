"""Integration tests for LeRobot GUI routes and API workflow."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import app.main as main_module
from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from utils.config_loader import load_all_configs
import utils.manipulation_profile as manipulation_profile_module
from utils.paths import resolve_path


def test_lerobot_gui_and_test_mode_api_workflow(tmp_path: Path, monkeypatch: Any) -> None:
    cfg = copy.deepcopy(load_all_configs(resolve_path("configs")).get("lerobot", {}))
    cfg["device_memory_path"] = str(tmp_path / "memory" / "lerobot_device_ports.json")
    cfg["fake_dataset_root"] = str(tmp_path / "fake_datasets")
    cfg["fake_checkpoint_root"] = str(tmp_path / "fake_checkpoints")
    cfg["dataset_root"] = str(tmp_path / "datasets")
    cfg["output_root"] = str(tmp_path / "outputs")
    cfg["policy_root"] = str(tmp_path / "outputs")
    cfg["session_log_root"] = str(tmp_path / "logs")
    monkeypatch.setattr(main_module, "_LEROBOT_BRIDGE", LeRobotBridge(LeRobotBridgeConfig.from_config(cfg, repo_root=tmp_path)))
    manipulation_profile_path = tmp_path / "memory" / "manipulation_agent_bridge.json"
    monkeypatch.setattr(manipulation_profile_module, "MANIPULATION_AGENT_PROFILE_PATH", manipulation_profile_path)
    monkeypatch.setattr(main_module, "MANIPULATION_AGENT_PROFILE_PATH", manipulation_profile_path)
    client = TestClient(main_module.app)

    page = client.get("/lerobot")
    assert page.status_code == 200
    assert "LeRobot / ROBOTIS Workspace" in page.text
    assert "Device Port Setup" in page.text
    assert "+ Camera" in page.text
    assert "jin/record-test" in page.text
    assert "Pick up the cylinder" in page.text
    assert "lerobot-action-status" in page.text
    assert "Batch Size" in page.text
    assert "Additional Train CLI Args" in page.text
    assert "Manipulation Agent Bridge" in page.text
    assert "lerobot-manipulation-task-id-input" in page.text
    assert "Pi0.5 RTC Execution Horizon" in page.text
    assert "Manipulation Agent Runtime Report" in page.text
    assert "Save Agent Defaults" in page.text
    assert "Test Agent Bridge" in page.text

    home = client.get("/")
    assert home.status_code == 200
    assert "Open LeRobot GUI" in home.text
    assert "Manipulation Agent" in home.text

    config = client.get("/api/lerobot/config").json()
    assert config["ok"] is True
    assert any(profile["profile_id"] == "fake_omx_ai" for profile in config["profiles"])

    selected = client.post("/api/lerobot/config", json={"profile_id": "fake_omx_ai", "mode": "test"}).json()
    assert selected["selected_profile_id"] == "fake_omx_ai"

    ports = client.get("/api/lerobot/ports", params={"profile_id": "fake_omx_ai", "mode": "test"}).json()
    assert ports["ok"] is True
    assert ports["ports"][0]["detected"] is True

    baseline = client.post(
        "/api/lerobot/ports/baseline",
        json={"mode": "test", "profile_id": "fake_omx_ai", "device_role": "leader"},
    ).json()
    assert baseline["ok"] is True

    detected = client.post(
        "/api/lerobot/ports/detect",
        json={"mode": "test", "profile_id": "fake_omx_ai", "device_role": "leader"},
    ).json()
    assert detected["ok"] is True
    assert detected["saved_devices"]["leader"]["port"]

    camera = client.post(
        "/api/lerobot/camera/test",
        json={"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "port": "/dev/video0", "camera_key": "top"},
    ).json()
    assert camera["ok"] is True
    assert camera["capture"]["synthetic"] is True

    side_camera = client.post(
        "/api/lerobot/ports/save",
        json={"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "port": "/dev/video4", "camera_key": "side"},
    ).json()
    assert side_camera["ok"] is True
    deleted_side_camera = client.post(
        "/api/lerobot/ports/delete",
        json={"mode": "test", "profile_id": "fake_omx_ai", "device_role": "camera", "camera_key": "side"},
    ).json()
    assert deleted_side_camera["ok"] is True
    assert "side" not in deleted_side_camera["saved_devices"]["cameras"]

    teleop = client.post("/api/lerobot/teleoperate/start", json={"mode": "test", "profile_id": "fake_omx_ai"}).json()
    assert teleop["ok"] is True
    assert teleop["workflow"] == "teleoperate"

    record = client.post(
        "/api/lerobot/record/start",
        json={"mode": "test", "profile_id": "fake_omx_ai", "dataset_repo_id": "local/fake_dataset", "task_instruction": "Pick up the cylinder"},
    ).json()
    assert record["ok"] is True
    assert record["workflow"] == "record"
    assert "--dataset.single_task=Pick up the cylinder" in record["command_preview"]

    finished = client.post(
        "/api/lerobot/record/control",
        json={"mode": "test", "profile_id": "fake_omx_ai", "session_id": record["session_id"], "action": "finish"},
    ).json()
    assert finished["status"] == "DATASET_COMPLETE"

    train = client.post(
        "/api/lerobot/train/start",
        json={
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "dataset_repo_id": "jin/record-test",
            "policy_type": "act",
            "device": "cuda",
            "batch_size": 32,
            "steps": 20000,
            "num_workers": 16,
            "policy_repo_id": "jin/robotis_omx_ai_act_policy",
        },
    ).json()
    assert train["ok"] is True
    assert train["workflow"] == "train"
    assert "--steps=20000" in train["command_preview"]
    assert train["training"]["progress_percent"] == 100.0

    rollout = client.post(
        "/api/lerobot/rollout/start",
        json={"mode": "test", "profile_id": "fake_omx_ai", "policy_path": "fake://policy"},
    ).json()
    assert rollout["ok"] is True
    assert rollout["workflow"] == "rollout"

    manipulation_config = client.get("/api/lerobot/manipulation-agent/config").json()
    assert manipulation_config["ok"] is True
    assert manipulation_config["profile"]["manipulation_strategy"] == "pi05_lerobot_policy"

    manipulation_save = client.post(
        "/api/lerobot/manipulation-agent/config",
        json={
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "manipulation_strategy": "pi05_lerobot_policy",
            "task_id": "transfer_to_utm",
            "skill_id": "transfer_to_utm",
            "policy_backend": "lerobot_cli",
            "policy_type": "pi05",
            "policy_path": "fake://pi05_policy_saved",
            "rollout_rtc_execution_horizon": 10,
            "rollout_rtc_max_guidance_weight": 1.0,
            "max_duration_s": 30,
            "task_instruction": "Saved 3DP to UTM manipulation default",
            "source_location": "3dp_output_area",
            "target_location": "utm_fixture",
            "camera_enabled": True,
            "continuous_rollout": True,
        },
    ).json()
    assert manipulation_save["ok"] is True
    assert manipulation_save["tool"] == "manipulation_agent.config.save"
    assert manipulation_save["profile"]["policy_path"] == "fake://pi05_policy_saved"
    assert manipulation_save["profile"]["task_id"] == "transfer_to_utm"
    assert manipulation_save["profile"]["policy_backend"] == "lerobot_cli"
    assert manipulation_save["profile"]["rollout_rtc_execution_horizon"] == 10
    assert manipulation_profile_path.exists()

    manipulation_test = client.post(
        "/api/lerobot/manipulation-agent/test",
        json={
            "mode": "live",
            "profile_id": "fake_omx_ai",
            "manipulation_strategy": "pi05_lerobot_policy",
            "task_id": "transfer_to_utm",
            "policy_backend": "lerobot_cli",
            "policy_type": "pi05",
            "policy_path": "fake://pi05_policy",
            "rollout_rtc_execution_horizon": 10,
            "rollout_rtc_max_guidance_weight": 1.0,
            "max_duration_s": 30,
            "task_instruction": "Test 3DP to UTM manipulation bridge",
            "source_location": "3dp_output_area",
            "target_location": "utm_fixture",
            "camera_enabled": True,
            "continuous_rollout": True,
            "specimen_result": {
                "ok": True,
                "specimen_id": "specimen-test-001",
                "candidate_id": "candidate-test-001",
                "handoff_status": "ready",
            },
        },
    ).json()
    assert manipulation_test["ok"] is True
    assert manipulation_test["tool"] == "manipulation_agent.test"
    assert manipulation_test["test_mode_forced"] is True
    assert manipulation_test["mode"] == "test"
    assert manipulation_test["manipulation"]["strategy"] == "pi05_lerobot_policy"
    assert manipulation_test["manipulation_report"]["schema"] == "manipulation_report.v1"
    assert manipulation_test["robot_task_result"]["schema"] == "robot_task_result.v1"
    assert manipulation_test["robot_task_result"]["handoff_status"] == "needs_post_place_vision"
    assert "--policy.type=pi05" in manipulation_test["manipulation"]["command_preview"]

    manipulation = client.post(
        "/api/lerobot/manipulation-agent/run",
        json={
            "mode": "test",
            "profile_id": "fake_omx_ai",
            "manipulation_strategy": "pi05_lerobot_policy",
            "task_id": "transfer_to_utm",
            "policy_backend": "lerobot_cli",
            "policy_type": "pi05",
            "policy_path": "fake://pi05_policy",
            "rollout_rtc_execution_horizon": 10,
            "rollout_rtc_max_guidance_weight": 1.0,
            "max_duration_s": 30,
            "task_instruction": "Move test specimen from 3DP to UTM",
            "source_location": "3dp_output_area",
            "target_location": "utm_fixture",
            "camera_enabled": True,
            "continuous_rollout": True,
            "specimen_result": {
                "ok": True,
                "specimen_id": "specimen-api-001",
                "candidate_id": "candidate-api-001",
                "handoff_status": "ready",
            },
            "observation": {
                "observation_id": "obs-api-001",
                "anomaly": False,
                "transfer_readiness": {"ready": True, "pose_confidence": 0.82},
            },
        },
    ).json()
    assert manipulation["ok"] is True
    assert manipulation["tool"] == "manipulation_agent.run"
    assert manipulation["manipulation"]["strategy"] == "pi05_lerobot_policy"
    assert manipulation["manipulation"]["transfer_task"]["source"] == "3dp_output_area"
    assert manipulation["manipulation"]["transfer_task"]["target"] == "utm_fixture"
    assert manipulation["manipulation_report"]["task"]["task_id"] == "transfer_to_utm"
    assert manipulation["manipulation_report"]["policy_plan"]["rtc_execution_horizon"] == 10
    assert manipulation["robot_task_result"]["terminal_pose"] == "standby_clear_of_utm"
    assert "--policy.type=pi05" in manipulation["manipulation"]["command_preview"]
    assert any(
        event.get("type") == "node.completed"
        and event.get("node_id") == "manipulation"
        and event.get("payload", {}).get("workspace") == "lerobot"
        for event in main_module.controller.recent_events()
    )

    sessions = client.get("/api/lerobot/sessions").json()
    assert sessions["ok"] is True
    assert len(sessions["sessions"]) >= 3

    policies = client.get("/api/lerobot/policies").json()
    assert policies["ok"] is True
    assert policies["policies"]

    browse = client.post("/api/lerobot/files/browse", json={"kind": "dataset", "path": ""}).json()
    assert browse["ok"] is True
    assert "allowed_roots" in browse

    visual = client.post(
        "/api/lerobot/visualize/dataset",
        json={"mode": "test", "profile_id": "fake_omx_ai", "dataset_repo_id": "local/fake_dataset"},
    ).json()
    assert visual["ok"] is True
    assert visual["tool"] == "lerobot.dataset.visualize"


def test_lerobot_rollout_api_hardware_alert_is_guardian_ready(monkeypatch: Any) -> None:
    def fake_call(name: str, payload: dict[str, object]) -> dict[str, object]:
        return {
            "ok": False,
            "tool": name,
            "mode": payload.get("mode", "live"),
            "profile_id": payload.get("profile_id", "robotis_omx_ai"),
            "session_id": "",
            "workflow": "rollout",
            "status": "blocked",
            "failure_code": "LEROBOT_DEVICE_PORT_REQUIRED",
            "message": "Save required LeRobot device ports before live rollout: follower",
            "command_preview": [],
            "step_trace": [{"step": "PRECHECK", "status": "blocked", "detail": "LEROBOT_DEVICE_PORT_REQUIRED"}],
            "events": [{"step": "PRECHECK", "status": "blocked", "detail": "LEROBOT_DEVICE_PORT_REQUIRED"}],
        }

    monkeypatch.setattr(main_module.controller._deps.agent_context.tools, "call", fake_call)
    client = TestClient(main_module.app)

    result = client.post(
        "/api/lerobot/rollout/start",
        json={"mode": "live", "profile_id": "robotis_omx_ai", "policy_path": "fake://pi05"},
    ).json()

    assert result["ok"] is False
    alert = result["hardware_alert"]
    assert alert["schema"] == "hardware_alert.v1"
    assert alert["device_class"] == "robot"
    assert alert["component"] == "robot_io_port"
    assert alert["reason_code"] == "MISSING_REQUIRED_INPUT"
    assert alert["blocks_workflow"] is True
    assert alert["requires_ack"] is True
    assert alert["guardian_contract"]["schema_version"] == "guardian_contract.v1"
    assert alert["guardian_contract"]["ok_for_next_stage"] is False
    assert alert["guardian_decision"]["schema"] == "guardian_decision.v1"
    assert alert["guardian_decision"]["decision"] == "block"
    assert alert["incident_record"]["schema"] == "incident_record.v1"

    guardian_log = main_module.controller._logger_bundle.run_dir / "guardian_events.jsonl"
    assert guardian_log.exists()
    records = [json.loads(line) for line in guardian_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(record.get("incident_id") == alert["alert_id"] for record in records)
    assert any(
        event.get("event_type") == "hardware.alert"
        and event.get("payload", {}).get("hardware_alert", {}).get("alert_id") == alert["alert_id"]
        for event in main_module.controller.recent_events()
    )


def test_lerobot_rollout_api_uses_backend_tool_registry(monkeypatch: Any) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(name: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((name, payload))
        return {
            "ok": True,
            "tool": name,
            "mode": payload.get("mode", "test"),
            "profile_id": payload.get("profile_id", ""),
            "session_id": "lr-rollout-api-registry",
            "workflow": "rollout",
            "status": "POLICY_ACTIVE",
            "command_preview": ["backend-tool-registry"],
            "step_trace": [{"step": "QUEUE", "status": "ok", "detail": "backend tool registry"}],
            "events": [{"step": "QUEUE", "status": "ok", "detail": "backend tool registry"}],
        }

    monkeypatch.setattr(main_module.controller._deps.agent_context.tools, "call", fake_call)
    client = TestClient(main_module.app)

    result = client.post(
        "/api/lerobot/rollout/start",
        json={"mode": "test", "profile_id": "fake_omx_ai", "policy_path": "fake://policy"},
    ).json()

    assert result["ok"] is True
    assert result["command_preview"] == ["backend-tool-registry"]
    assert calls and calls[0][0] == "lerobot.rollout.start"
    assert calls[0][1]["policy_path"] == "fake://policy"
