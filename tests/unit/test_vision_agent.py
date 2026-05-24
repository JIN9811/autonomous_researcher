"""Unit tests for VisionAgent pickup observation contract."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agents.vision_agent import VisionAgent
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


class _CtxStub:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    async def complete(self, task_type: str, prompt: str, timeout_s: float | None = None) -> Any:
        return SimpleNamespace(text="capture top camera and estimate pickup readiness", raw={}, model="mock-e2b")


def _state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-vision",
        experiment_id="exp-vision",
        mode=Mode.TEST,
        stage=Stage.VISION,
        current_experiment_spec={"size_mm": [20.0, 20.0, 10.0]},
        run_metadata={
            "specimen_result": {
                "ok": True,
                "specimen_id": "specimen-001",
                "candidate_id": "candidate-001",
                "handoff_status": "ready",
                "stl_path": "runs/specimen-001.stl",
                "sliced_path": "runs/specimen-001.gcode",
            }
        },
    )


@pytest.mark.asyncio
async def test_vision_agent_returns_pickup_observation() -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)
    result = await VisionAgent().run(_state(), _CtxStub(tools))

    observation = result.data["observation"]
    assert result.success is True
    assert observation["transfer_readiness"]["ready"] is True
    assert observation["pickup_target"]["specimen_id"] == "specimen-001"
    assert observation["pickup_target"]["source_location"] == "3dp_output_area"
    assert observation["pickup_target"]["target_location"] == "utm_fixture"
    assert observation["pose_estimate"]["confidence"] >= 0.8

