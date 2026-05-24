"""Unit tests for ManipulationAgent LeRobot policy path."""

from __future__ import annotations

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


class _CtxStub:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools
        self.events: list[dict[str, Any]] = []
        self.prompts: list[str] = []

    async def complete(self, task_type: str, prompt: str, timeout_s: float | None = None) -> Any:
        self.prompts.append(prompt)
        return SimpleNamespace(text="policy rollout command ready", raw={}, model="mock-e2b")

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


def _tools(tmp_path: Path) -> ToolRegistry:
    cfg = load_all_configs(Path("configs"))
    tools = ToolRegistry()
    register_mock_tools(tools)
    register_lerobot_tools(tools, cfg.get("lerobot", {}), repo_root=tmp_path)
    return tools


@pytest.mark.asyncio
async def test_manipulation_agent_calls_lerobot_rollout(tmp_path: Path) -> None:
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
    assert result.data["sarm"]["stage_name"] == "policy_rollout"
    assert result.data["sarm"]["failure_precursor"] >= 0
    assert ctx.events
    assert ctx.events[0]["tool"] == "lerobot.rollout.start"
