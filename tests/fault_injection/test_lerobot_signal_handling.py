"""Fault-oriented tests for LeRobot bridge safety signals."""

from __future__ import annotations

from pathlib import Path

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from utils.config_loader import load_all_configs


def _bridge(tmp_path: Path) -> LeRobotBridge:
    cfg = load_all_configs(Path("configs"))
    return LeRobotBridge(LeRobotBridgeConfig.from_config(cfg.get("lerobot", {}), repo_root=tmp_path))


def test_live_rollout_is_blocked_without_saved_live_ports(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.rollout_start({"mode": "live", "profile_id": "fake_omx_ai", "policy_path": "fake://policy"})

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["failure_code"] == "LEROBOT_DEVICE_PORT_UNAVAILABLE"


def test_command_argument_injection_is_rejected(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.train_start({"mode": "test", "profile_id": "fake_omx_ai", "output_dir": "out && bad"})

    assert result["ok"] is False
    assert result["failure_code"] == "LEROBOT_UNSAFE_ARGUMENT"
