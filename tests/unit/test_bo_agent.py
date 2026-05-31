"""Unit tests for BOAgent advisory optimization behavior."""

from __future__ import annotations

from pathlib import Path

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
    assert settings["bo_backend"] == "lightweight_pool"
    assert warnings


def test_bo_agent_normalize_settings_accepts_botorch_optional_backend() -> None:
    settings, warnings = BOAgent.normalize_settings({"bo_backend": "botorch_optional", "top_k": 99})

    assert settings["bo_backend"] == "botorch_optional"
    assert settings["top_k"] == 12
    assert warnings == []

class _LLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _CtxWithLLM(_CtxStub):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.calls: list[tuple[str, str]] = []

    async def complete(self, task_type: str, user_prompt: str, *, timeout_s: float | None = None) -> _LLMResponse:
        self.calls.append((task_type, user_prompt))
        return _LLMResponse(self.text)


@pytest.mark.asyncio
async def test_bo_agent_emits_reasoning_ranking_handoff_and_artifacts() -> None:
    agent = BOAgent()
    state = OrchestratorState(
        run_id="run-bo-reasoning",
        experiment_id="exp-bo-reasoning",
        mode=Mode.TEST,
        stage=Stage.BO,
        active_goal="reasoning augmented BO",
        current_experiment_spec={"cell_size_mm": 10.0, "constraints": {"cell_size_mm": 10.0}},
    )
    state.latest_analysis = {
        "bo_handoff": {
            "schema_version": "analysis_bo_handoff_v1",
            "ok_for_bo": True,
            "candidate_id": "specimen-prior-001",
            "parameters": {
                "geometry_type": "gyroid",
                "relative_density": 0.32,
                "wall_thickness_mm": 1.4,
                "cell_size_mm": 10.0,
                "tpms_thickness": 0.34,
                "orientation_deg": 0,
                "anisotropy_ratio": 1.0,
            },
            "objective": {"score": 0.71, "uncertainty": 0.12},
            "quality": {"score": 0.91},
            "failure_tags": [],
        }
    }

    result = await agent.run_with_settings(state, _CtxStub(), {"strategy": "llm_preference_bo", "budget": 4})
    bo_result = result.data["bo_result"]

    assert result.success is True
    assert bo_result["reasoning"]["schema_version"] == "bo_reasoning_v1"
    assert bo_result["prior_summary"]["measured_count"] >= 1
    assert bo_result["candidate_ranking"]
    assert bo_result["recommendation"]["why_this_candidate"]
    assert bo_result["next_design_request"]["schema"] == "next_design_request.v1"
    assert bo_result["next_design_request"]["constraints"]["cell_size_mm"] == 10.0
    assert state.run_metadata["bo_recommended_constraints"]["cell_size_mm"] == 10.0
    for path in bo_result["artifacts"].values():
        assert Path(path).exists()


@pytest.mark.asyncio
async def test_bo_agent_uses_llm_reasoning_as_soft_preference() -> None:
    agent = BOAgent()
    state = OrchestratorState(
        run_id="run-bo-llm",
        experiment_id="exp-bo-llm",
        mode=Mode.TEST,
        stage=Stage.BO,
        active_goal="prefer high density safe region",
        current_experiment_spec={"cell_size_mm": 10.0},
    )
    llm_json = """
    {
      "schema_version": "bo_reasoning_v1",
      "hypotheses": [
        {"id": "h-density", "claim": "Higher density with sufficient wall thickness may improve stiffness.", "evidence": ["prior trend"], "confidence": 0.7, "testable_by_next_candidate": true}
      ],
      "strategy_recommendation": {
        "strategy": "llm_preference_bo",
        "acquisition": "expected_improvement",
        "exploration_weight": 0.25,
        "exploitation_weight": 0.75,
        "reason": "bias toward safe high-density region"
      },
      "search_space_patch": {
        "narrow": {}, "expand": {}, "lock": {},
        "forbid": [{"condition": "relative_density < 0.20", "reason": "FDM continuous shell"}]
      },
      "preference_regions": [
        {"condition": "relative_density between 0.34 and 0.48 and wall_thickness_mm >= 1.2", "preference_score": 0.9, "reason": "test denser shell hypothesis"}
      ],
      "risk_flags": [],
      "operator_summary": "Prefer safe high-density candidates, but keep acquisition gate active."
    }
    """
    ctx = _CtxWithLLM(llm_json)

    result = await agent.run_with_settings(state, ctx, {"strategy": "llm_preference_bo", "budget": 5, "random_seed": 3})
    bo_result = result.data["bo_result"]

    assert ctx.calls and ctx.calls[0][0] == "bo_policy"
    assert bo_result["reasoning"]["source"] == "llm"
    assert bo_result["reasoning"]["hypotheses"][0]["id"] == "h-density"
    assert any(item["llm"]["preference_score"] > 0.0 for item in bo_result["candidate_ranking"])
    assert bo_result["recommendation"]["bo_hypothesis_ids"] == ["h-density"]
