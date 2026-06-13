"""Unit tests for ManipulationAgent LeRobot policy path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.manipulation_agent import ManipulationAgent
from mcp_tools.lerobot_tools import register_lerobot_tools
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage
from utils.config_loader import load_all_configs
import utils.manipulation_profile as manipulation_profile_module


class _CtxStub:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools
        self.events: list[dict[str, Any]] = []
        self.prompts: list[str] = []

    async def complete(self, task_type: str, prompt: str, timeout_s: float | None = None) -> Any:
        self.prompts.append(prompt)
        return SimpleNamespace(text="policy rollout command ready", raw={}, model="mock-e4b")

    def on_tool_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-lerobot",
        experiment_id="exp-lerobot",
        mode=Mode.TEST,
        stage=Stage.MANIPULATION,
        active_goal="pick and place specimen with LeRobot",
        current_experiment_spec={
            "manipulation_strategy": "lerobot_policy",
            "lerobot_profile_id": "fake_omx_ai",
            "lerobot_policy_path": "fake://policy",
            "rollout_dataset_repo_id": "jin/pick_and_place_cube_rollout",
            "manipulation_task": "pick specimen from fixture",
        },
        latest_observations={"frame_id": "frame-1", "anomaly": False, "status": "clear"},
    )


def _post_specimen_state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-pi05-transfer",
        experiment_id="exp-pi05-transfer",
        mode=Mode.TEST,
        stage=Stage.MANIPULATION,
        active_goal="transfer printed specimen to UTM",
        current_experiment_spec={},
        latest_observations={
            "frame_id": "frame-transfer",
            "anomaly": False,
            "transfer_readiness": {"ready": True, "pose_confidence": 0.82},
            "pose_estimate": {"x_mm": 0.0, "y_mm": 0.0, "z_mm": 5.0, "confidence": 0.82},
        },
        run_metadata={
            "specimen_result": {
                "ok": True,
                "specimen_id": "specimen-transfer-001",
                "candidate_id": "candidate-transfer-001",
                "handoff_status": "ready",
                "stl_path": "runs/specimen-transfer-001.stl",
                "sliced_path": "runs/specimen-transfer-001.gcode",
            }
        },
    )


def _tools(tmp_path: Path) -> ToolRegistry:
    cfg = load_all_configs(Path("configs"))
    tools = ToolRegistry()
    register_mock_tools(tools)
    register_lerobot_tools(tools, cfg.get("lerobot", {}), repo_root=tmp_path)
    return tools


def _isolate_manipulation_profile(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        manipulation_profile_module,
        "MANIPULATION_AGENT_PROFILE_PATH",
        tmp_path / "memory" / "manipulation_agent_bridge.json",
    )


@pytest.mark.asyncio
async def test_manipulation_agent_calls_lerobot_rollout(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(_state(), ctx)

    assert result.success is True
    assert result.data["manipulation"]["tool"] == "lerobot.rollout.start"
    assert result.data["manipulation"]["strategy"] == "lerobot_policy"
    assert result.data["manipulation"]["profile_id"] == "fake_omx_ai"
    assert "--dataset.repo_id=jin/eval_pick_and_place_cube_rollout" in result.data["manipulation"]["command_preview"]
    assert "--dataset.episode_time_s=86400.0" in result.data["manipulation"]["command_preview"]
    assert "--policy.temporal_ensemble_coeff=0.01" in result.data["manipulation"]["command_preview"]
    assert "--policy.n_action_steps=1" in result.data["manipulation"]["command_preview"]
    assert "--robot.max_relative_target=5" in result.data["manipulation"]["command_preview"]
    assert result.data["sarm"]["stage_name"] == "post_place_verify"
    assert result.data["sarm"]["failure_precursor"] >= 0
    assert result.data["manipulation_report"]["schema"] == "manipulation_report.v1"
    assert result.data["robot_task_result"]["schema"] == "robot_task_result.v1"
    assert result.data["robot_task_result"]["handoff_status"] == "needs_post_place_vision"
    assert ctx.events
    assert ctx.events[0]["tool"] == "lerobot.rollout.start"


@pytest.mark.asyncio
async def test_manipulation_agent_defaults_to_pi05_transfer_after_specimen(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(_post_specimen_state(), ctx)

    manipulation = result.data["manipulation"]
    assert result.success is True
    assert manipulation["tool"] == "lerobot.rollout.start"
    assert manipulation["strategy"] == "pi05_lerobot_policy"
    assert manipulation["transfer_task"]["policy_type"] == "pi05"
    assert manipulation["transfer_task"]["source"] == "3dp_output_area"
    assert manipulation["transfer_task"]["target"] == "utm_fixture"
    assert manipulation["transfer_task"]["specimen_id"] == "specimen-transfer-001"
    assert manipulation["completion_status"] == "reported_complete"
    assert manipulation["handoff_status"] == "needs_post_place_vision"
    assert result.data["manipulation_report"]["task"]["task_id"] == "transfer_to_utm"
    assert result.data["manipulation_report"]["policy_plan"]["policy_type"] == "pi05"
    assert result.data["robot_task_result"]["terminal_pose"] == "standby_clear_of_utm"
    assert "-n" in manipulation["command_preview"]
    assert manipulation["command_preview"][manipulation["command_preview"].index("-n") + 1] == "lerobot-pi05-torch211"
    assert any(Path(item).name == "lerobot_pi05_rollout_wrapper.py" for item in manipulation["command_preview"])
    assert "--policy.type=pi05" not in manipulation["command_preview"]
    assert "--rtc.enabled=true" in manipulation["command_preview"]
    assert any(item.startswith("--task=Move specimen-transfer-001") for item in manipulation["command_preview"])


def test_manipulation_agent_test_mode_accepts_recently_expired_vision_signal() -> None:
    state = _post_specimen_state()
    expires_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    state.latest_observations["transfer_readiness"]["expires_at"] = expires_at
    state.latest_observations["vision_signal"] = {
        "schema": "vision_signal.v1",
        "signal_id": "sig-recently-expired",
        "expires_at": expires_at,
    }

    freshness = ManipulationAgent._vision_signal_freshness(state)

    assert freshness["fresh"] is True
    assert freshness["reason"] == "fresh_with_test_mode_grace"
    assert freshness["grace_s"] == 120

@pytest.mark.asyncio
async def test_manipulation_agent_blocks_expired_vision_signal(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    state = _post_specimen_state()
    state.latest_observations["transfer_readiness"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    state.latest_observations["vision_signal"] = {
        "schema": "vision_signal.v1",
        "signal_id": "sig-expired",
        "expires_at": "2000-01-01T00:00:00+00:00",
    }
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(state, ctx)

    assert result.success is False
    assert result.data["manipulation"]["failure_code"] == "STALE_VISION_SIGNAL"
    assert result.data["manipulation"]["freshness"]["reason"] == "stale_vision_signal"
    assert result.data["sarm"]["stage_name"] == "vision_signal_gate"
    assert result.data["manipulation_report"]["preflight"]["status"] == "fail"
    assert result.data["robot_task_result"]["handoff_status"] == "blocked"
