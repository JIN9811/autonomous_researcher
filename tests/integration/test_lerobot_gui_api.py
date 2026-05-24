"""Integration tests for LeRobot GUI routes and API workflow."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import app.main as main_module
from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from utils.config_loader import load_all_configs
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

    home = client.get("/")
    assert home.status_code == 200
    assert "Open LeRobot GUI" in home.text

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
