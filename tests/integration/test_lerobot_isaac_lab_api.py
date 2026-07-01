"""Integration tests for LeRobot Isaac Lab synthetic API routes."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import app.main as main_module
from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from utils.config_loader import load_all_configs
from utils.paths import resolve_path


def _test_client(tmp_path: Path, monkeypatch: Any) -> tuple[TestClient, LeRobotBridge]:
    cfg = copy.deepcopy(load_all_configs(resolve_path("configs")).get("lerobot", {}))
    cfg["device_memory_path"] = str(tmp_path / "memory" / "lerobot_device_ports.json")
    cfg["fake_dataset_root"] = str(tmp_path / "fake_datasets")
    cfg["dataset_root"] = str(tmp_path / "datasets")
    cfg["output_root"] = str(tmp_path / "outputs")
    cfg["policy_root"] = str(tmp_path / "policies")
    cfg["session_log_root"] = str(tmp_path / "logs")
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config(cfg, repo_root=tmp_path))
    monkeypatch.setattr(main_module, "_LEROBOT_BRIDGE", bridge)
    return TestClient(main_module.app), bridge


def test_lerobot_isaac_lab_api_routes_call_bridge(tmp_path: Path, monkeypatch: Any) -> None:
    client, bridge = _test_client(tmp_path, monkeypatch)
    calls: list[tuple[str, dict[str, Any]]] = []

    def _response(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((tool, payload))
        return {
            "ok": True,
            "tool": tool,
            "schema": "atr.lerobot.isaac_lab_synthetic.response.v1",
            "status": "READY_TO_BUILD",
            "dataset_path": payload.get("dataset_path", ""),
            "output_root": "/tmp/out",
            "run_id": "test-run",
            "step_trace": [],
            "error": None,
        }

    monkeypatch.setattr(bridge, "isaac_lab_validate", lambda payload: _response("lerobot.isaac_lab.validate", payload))
    monkeypatch.setattr(bridge, "isaac_lab_prepare", lambda payload: _response("lerobot.isaac_lab.prepare", payload))
    monkeypatch.setattr(bridge, "isaac_lab_build_synthetic", lambda payload: _response("lerobot.isaac_lab.build_synthetic", payload))
    monkeypatch.setattr(bridge, "isaac_lab_run_replicator_worker", lambda payload: _response("lerobot.isaac_lab.run_replicator_worker", payload))
    monkeypatch.setattr(bridge, "isaac_lab_preview", lambda payload: _response("lerobot.isaac_lab.preview", payload))
    monkeypatch.setattr(bridge, "isaac_lab_export_hdf5", lambda payload: _response("lerobot.isaac_lab.export_hdf5", payload))
    monkeypatch.setattr(bridge, "isaac_lab_run_mimic", lambda payload: _response("lerobot.isaac_lab.run_mimic", payload))
    monkeypatch.setattr(bridge, "isaac_lab_run_mimic_smoke", lambda payload: _response("lerobot.isaac_lab.run_mimic_smoke", payload))
    monkeypatch.setattr(bridge, "isaac_lab_mimic_status", lambda payload: _response("lerobot.isaac_lab.mimic.status", payload))
    monkeypatch.setattr(bridge, "isaac_lab_mimic_stop", lambda payload: _response("lerobot.isaac_lab.mimic.stop", payload))
    monkeypatch.setattr(bridge, "isaac_lab_run_rl_teacher", lambda payload: _response("lerobot.isaac_lab.run_rl_teacher", payload))
    monkeypatch.setattr(bridge, "isaac_lab_run_rl_teacher_smoke", lambda payload: _response("lerobot.isaac_lab.run_rl_teacher_smoke", payload))
    monkeypatch.setattr(bridge, "isaac_lab_rl_teacher_status", lambda payload: _response("lerobot.isaac_lab.rl_teacher.status", payload))
    monkeypatch.setattr(bridge, "isaac_lab_rl_teacher_stop", lambda payload: _response("lerobot.isaac_lab.rl_teacher.stop", payload))
    monkeypatch.setattr(bridge, "isaac_lab_run_e2e_smoke", lambda payload: _response("lerobot.isaac_lab.e2e_smoke", payload))
    monkeypatch.setattr(bridge, "isaac_lab_status", lambda payload: _response("lerobot.isaac_lab.status", payload))

    payload = {
        "mode": "test",
        "dataset_path": str(tmp_path / "datasets" / "demo"),
        "pipeline_mode": "isaac_lab_replicator",
        "fallback_policy": "block_on_primary_failure",
        "source_intent": "train_ready_success_only",
    }
    endpoints = [
        ("/api/lerobot/isaac-lab/validate", "lerobot.isaac_lab.validate"),
        ("/api/lerobot/isaac-lab/prepare", "lerobot.isaac_lab.prepare"),
        ("/api/lerobot/isaac-lab/build-synthetic", "lerobot.isaac_lab.build_synthetic"),
        ("/api/lerobot/isaac-lab/run-replicator-worker", "lerobot.isaac_lab.run_replicator_worker"),
        ("/api/lerobot/isaac-lab/preview", "lerobot.isaac_lab.preview"),
        ("/api/lerobot/isaac-lab/export-hdf5", "lerobot.isaac_lab.export_hdf5"),
        ("/api/lerobot/isaac-lab/run-mimic", "lerobot.isaac_lab.run_mimic"),
        ("/api/lerobot/isaac-lab/run-mimic-smoke", "lerobot.isaac_lab.run_mimic_smoke"),
        ("/api/lerobot/isaac-lab/mimic/status", "lerobot.isaac_lab.mimic.status"),
        ("/api/lerobot/isaac-lab/mimic/stop", "lerobot.isaac_lab.mimic.stop"),
        ("/api/lerobot/isaac-lab/run-rl-teacher", "lerobot.isaac_lab.run_rl_teacher"),
        ("/api/lerobot/isaac-lab/run-rl-teacher-smoke", "lerobot.isaac_lab.run_rl_teacher_smoke"),
        ("/api/lerobot/isaac-lab/rl-teacher/status", "lerobot.isaac_lab.rl_teacher.status"),
        ("/api/lerobot/isaac-lab/rl-teacher/stop", "lerobot.isaac_lab.rl_teacher.stop"),
        ("/api/lerobot/isaac-lab/e2e-smoke", "lerobot.isaac_lab.e2e_smoke"),
        ("/api/lerobot/isaac-lab/status", "lerobot.isaac_lab.status"),
    ]

    for endpoint, expected_tool in endpoints:
        response = client.post(endpoint, json=payload).json()
        assert response["ok"] is True
        assert response["tool"] == expected_tool

    assert [tool for tool, _payload in calls] == [tool for _endpoint, tool in endpoints]
    assert all(call_payload["pipeline_mode"] == "isaac_lab_replicator" for _tool, call_payload in calls)
