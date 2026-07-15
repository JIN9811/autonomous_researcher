"""Unit tests for LeRobot MCP tool registration."""

from __future__ import annotations

from pathlib import Path

from mcp_tools.lerobot_tools import register_lerobot_tools
from mcp_tools.tool_registry import ToolRegistry
from utils.config_loader import load_all_configs


def test_register_lerobot_tools_exposes_runtime_contract(tmp_path: Path) -> None:
    cfg = load_all_configs(Path("configs"))
    tools = ToolRegistry()

    bridge = register_lerobot_tools(tools, cfg.get("lerobot", {}), repo_root=tmp_path)

    names = tools.list_tools()
    assert "lerobot.profiles.list" in names
    assert "lerobot.ports.detect" in names
    assert "lerobot.camera.test" in names
    assert "lerobot.active_robot_cam.capture" in names
    assert "lerobot.rollout.start" in names
    assert bridge.config_status()["ok"] is True
    assert tools.resource("lerobot.bridge") is bridge


def test_lerobot_rollout_tool_runs_in_test_mode(tmp_path: Path) -> None:
    cfg = load_all_configs(Path("configs"))
    tools = ToolRegistry()
    register_lerobot_tools(tools, cfg.get("lerobot", {}), repo_root=tmp_path)

    result = tools.call(
        "lerobot.rollout.start",
        {"mode": "test", "profile_id": "fake_omx_ai", "policy_path": "fake://policy"},
    )

    assert result["ok"] is True
    assert result["tool"] == "lerobot.rollout.start"
    assert result["workflow"] == "rollout"
    assert result["command_preview"][0].endswith("conda")
    assert result["command_preview"][1:5] == ["run", "--no-capture-output", "-n", "lerobot"]
    assert "lerobot-record" in result["command_preview"]


def test_register_lerobot_tools_exposes_isaac_lab_synthetic_contract(tmp_path: Path) -> None:
    cfg = load_all_configs(Path("configs"))
    tools = ToolRegistry()
    register_lerobot_tools(tools, cfg.get("lerobot", {}), repo_root=tmp_path)

    expected = {
        "lerobot.isaac_lab.validate",
        "lerobot.isaac_lab.prepare",
        "lerobot.isaac_lab.build_synthetic",
        "lerobot.isaac_lab.run_replicator_worker",
        "lerobot.isaac_lab.preview",
        "lerobot.isaac_lab.export_hdf5",
        "lerobot.isaac_lab.run_mimic",
        "lerobot.isaac_lab.run_mimic_smoke",
        "lerobot.isaac_lab.mimic.status",
        "lerobot.isaac_lab.mimic.stop",
        "lerobot.isaac_lab.run_rl_teacher",
        "lerobot.isaac_lab.run_rl_teacher_smoke",
        "lerobot.isaac_lab.rl_teacher.status",
        "lerobot.isaac_lab.rl_teacher.stop",
        "lerobot.isaac_lab.e2e_smoke",
        "lerobot.isaac_lab.status",
    }

    assert expected.issubset(set(tools.list_tools()))
    result = tools.call("lerobot.isaac_lab.validate", {"mode": "test", "dataset_path": str(tmp_path / "missing")})

    assert result["tool"] == "lerobot.isaac_lab.validate"
    assert result["status"] == "BLOCKED"
    assert result["validation_report"]["blockers"][0]["code"] == "REQ_INVALID_DATASET"
