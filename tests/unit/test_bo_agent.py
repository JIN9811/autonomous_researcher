"""Unit tests for BOAgent advisory optimization behavior."""

from __future__ import annotations

import pytest

from agents.bo_agent import BOAgent
from mcp_tools.experiment_tools import register_experiment_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


class _CtxStub:
    def __init__(self) -> None:
        self.tools = ToolRegistry()
        register_experiment_tools(self.tools)


@pytest.mark.asyncio
async def test_bo_agent_returns_recommendation_and_curve() -> None:
    agent = BOAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="optimize gyroid specimen",
    )
    state.run_metadata["knowledge"] = {
        "retrieval_coverage": 0.8,
        "local_chunks": 3,
        "web_results": 0,
        "memory_summary": "Prefer FDM-printable gyroid with bottom cap only.",
    }

    result = await agent.run_with_settings(
        state,
        _CtxStub(),
        {
            "strategy": "bo",
            "acquisition": "upper_confidence_bound",
            "budget": 4,
            "random_seed": 11,
        },
    )

    bo_result = result.data["bo_result"]

    assert result.success is True
    assert bo_result["tool"] == "bo.agent"
    assert bo_result["strategy"] == "bo"
    assert bo_result["acquisition"] == "upper_confidence_bound"
    assert bo_result["recommendation"]["candidate_id"]
    assert bo_result["recommendation"]["parameters"]
    assert bo_result["knowledge_context"]["memory_summary"].startswith("Prefer FDM-printable")
    assert len(bo_result["best_so_far"]) == 4
    assert state.run_metadata["bo_agent"]["recommendation"]["candidate_id"] == bo_result["recommendation"]["candidate_id"]


@pytest.mark.asyncio
async def test_bo_agent_mbo_without_priors_degrades_to_bo() -> None:
    agent = BOAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="mbo without priors",
    )

    result = await agent.run_with_settings(state, _CtxStub(), {"strategy": "mbo", "budget": 2})
    bo_result = result.data["bo_result"]

    assert result.success is True
    assert bo_result["strategy"] == "mbo"
    assert any("degraded" in item for item in bo_result["warnings"])
    assert set(bo_result["benchmark"]["strategies"]) == {"bo"}


@pytest.mark.asyncio
async def test_bo_agent_locks_current_cell_size_between_cycles() -> None:
    agent = BOAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="optimize gyroid specimen",
        current_experiment_spec={
            "cell_size_mm": 10.0,
            "constraints": {"cell_size_mm": 10.0},
        },
    )

    result = await agent.run_with_settings(
        state,
        _CtxStub(),
        {
            "strategy": "bo",
            "budget": 4,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "relative_density": [0.18, 0.48],
                "wall_thickness_mm": [1.2, 2.0],
                "cell_size_mm": [5.0, 10.0],
            },
        },
    )
    bo_result = result.data["bo_result"]

    assert result.success is True
    assert bo_result["parameter_space"]["cell_size_mm"] == [10.0]
    assert bo_result["parameter_space"]["relative_density"][0] == 0.20
    assert bo_result["recommendation"]["parameters"]["cell_size_mm"] == 10.0
    assert bo_result["recommendation"]["parameters"]["relative_density"] >= 0.20
    assert result.data["experiment_spec_update"]["cell_size_mm"] == 10.0


@pytest.mark.asyncio
async def test_bo_agent_uses_prior_shape_to_avoid_repeat_recommendation() -> None:
    agent = BOAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="closed loop gyroid specimen",
        current_experiment_spec={
            "geometry_type": "gyroid",
            "cell_size_mm": 10.0,
            "relative_density": 0.32,
            "wall_thickness_mm": 1.2,
            "tpms_thickness": 0.34,
            "orientation_deg": 0.0,
            "anisotropy_ratio": 1.0,
        },
    )
    state.experiment_evaluations.append(
        {
            "objective_score": 0.84,
            "metrics": {
                "geometry_type": "gyroid",
                "cell_size_mm": 10.0,
                "relative_density": 0.32,
                "wall_thickness_mm": 1.2,
                "tpms_thickness": 0.34,
                "orientation_deg": 0.0,
                "anisotropy_ratio": 1.0,
            },
        }
    )

    result = await agent.run_with_settings(state, _CtxStub(), {"strategy": "bo", "budget": 5})
    params = result.data["bo_result"]["recommendation"]["parameters"]

    assert result.success is True
    assert params["cell_size_mm"] == 10.0
    signature = (
        float(params.get("relative_density", 0.0)),
        float(params.get("wall_thickness_mm", 0.0)),
        float(params.get("orientation_deg", 0.0)),
        float(params.get("anisotropy_ratio", 0.0)),
        float(params.get("tpms_thickness", 0.0)),
    )
    assert signature != (0.32, 1.2, 0.0, 1.0, 0.34)


def test_bo_agent_normalize_settings_fallbacks() -> None:
    settings, warnings = BOAgent.normalize_settings(
        {
            "strategy": "bad",
            "acquisition": "bad",
            "budget": "0",
            "random_seed": "not-int",
        }
    )

    assert settings["strategy"] == "bo"
    assert settings["acquisition"] == "expected_improvement"
    assert settings["budget"] == 1
    assert settings["random_seed"] == 7
    assert warnings
