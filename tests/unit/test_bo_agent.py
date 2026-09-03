"""Unit tests for BOAgent advisory optimization behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.bo_agent import BOAgent
from learning.bo_parameter_space import BOParameterSpace
from mcp_tools.experiment_tools import register_experiment_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


class _CtxStub:
    def __init__(self) -> None:
        self.tools = ToolRegistry()
        register_experiment_tools(self.tools)


def _add_completed_lhs_observations(state: OrchestratorState, *, count: int = 8) -> None:
    """Seed measured points so tests that target ranking run after LHS initialization."""
    for index in range(count):
        density = 0.21 + (0.26 * index / max(1, count - 1))
        state.experiment_evaluations.append(
            {
                "evaluation_id": f"eval-complete-lhs-{index + 1:03d}",
                "candidate_id": f"candidate-complete-lhs-{index + 1:03d}",
                "source": "analysis_agent",
                "objective_score": 0.35 + density,
                "metrics": {"energy_density_50pct_MJ_per_m3": 0.35 + density},
                "objective": {
                    "metric_name": "energy_density_50pct_MJ_per_m3",
                    "constraints": {
                        "geometry_type": "gyroid",
                        "cell_size_mm": 10.0,
                        "relative_density": density,
                        "wall_thickness_mm": 1.2,
                        "tpms_thickness": 0.0,
                        "orientation_deg": 0.0,
                        "anisotropy_ratio": 1.0,
                        "skin_thickness_mm": 0.8,
                        "bottom_cap_enabled": True,
                        "top_cap_enabled": False,
                        "skirt_enabled": False,
                    }
                },
            }
        )


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
    assert len(bo_result["best_so_far"]) == 1
    assert bo_result["lhs_visualization"]["schema"] == "lhs_design_visualization.v1"
    assert bo_result["lhs_visualization"]["step"] == 1
    assert bo_result["visualization"] == {}
    assert [item["step"] for item in bo_result["lhs_visualization_steps"]] == [1]
    assert bo_result["benchmark"]["strategies"]["bo"]["surrogate_trace"][0]["phase"] == "initial_design"
    assert state.run_metadata["bo_agent"]["recommendation"]["candidate_id"] == bo_result["recommendation"]["candidate_id"]


@pytest.mark.asyncio
async def test_bo_agent_preserves_lhs_proposal_without_acquisition_reranking() -> None:
    state = OrchestratorState(
        run_id="run-lhs-reporting",
        experiment_id="exp-lhs-reporting",
        mode=Mode.TEST,
        stage=Stage.BO,
        active_goal="initialize two-variable gyroid design",
    )
    space = BOParameterSpace.from_mapping(BOAgent.DEFAULT_PARAMETER_SPACE)
    lhs = space.lhs_points(8, seed=7)
    state.experiment_evaluations.append(
        {
            "evaluation_id": "eval-lhs-001",
            "candidate_id": "candidate-lhs-001",
            "source": "analysis_agent",
            "metrics": {"energy_density_50pct_MJ_per_m3": 0.42},
            "objective": {
                "metric_name": "energy_density_50pct_MJ_per_m3",
                "constraints": lhs[0],
            },
        }
    )

    result = await BOAgent().run_with_settings(
        state,
        _CtxStub(),
        {"strategy": "bo", "budget": 1, "bo_backend": "botorch", "random_seed": 7},
    )
    bo_result = result.data["bo_result"]
    recommendation = bo_result["recommendation"]

    assert bo_result["optimization_phase"] == "initial_design"
    assert bo_result["backend_active"] == "lhs"
    assert bo_result["initial_design"] == {
        "sampler": "latin_hypercube",
        "completed": 1,
        "target": 8,
        "next_index": 2,
    }
    assert recommendation["parameters"] == lhs[1]
    assert recommendation["selection_method"] == "latin_hypercube"
    assert recommendation["objective_score"] is None
    assert "combined_score" not in recommendation
    assert "acquisition=" not in recommendation["why_this_candidate"]
    assert bo_result["candidate_ranking"] == []
    assert "Latin Hypercube initial design point 2/8" in result.data["next_design_request"]["rationale"]


def test_initial_design_request_counts_prior_lhs_points_when_derived_fields_changed() -> None:
    """LHS progress is defined by the two active variables, not derived TPMS fields."""
    state = OrchestratorState(
        run_id="run-lhs-derived-fields",
        experiment_id="exp-lhs-derived-fields",
        mode=Mode.TEST,
        stage=Stage.BO,
        active_goal="initialize two-variable gyroid design",
    )
    space = BOParameterSpace.from_mapping(BOAgent.DEFAULT_PARAMETER_SPACE)
    lhs = space.lhs_points(8, seed=7)
    for index, point in enumerate(lhs[:2], start=1):
        state.experiment_evaluations.append(
            {
                "evaluation_id": f"eval-lhs-derived-{index:03d}",
                "candidate_id": f"candidate-lhs-derived-{index:03d}",
                "source": "analysis_agent",
                "status": "measured_analysis_complete",
                "ok": True,
                "objective_score": 0.40 + index * 0.01,
                "metrics": {
                    "geometry_type": "gyroid",
                    "cell_size_mm": point["cell_size_mm"],
                    "relative_density": point["relative_density"],
                    "wall_thickness_mm": 1.2,
                    # This is a derived geometry value and legitimately changes
                    # as relative density changes between LHS observations.
                    "tpms_thickness": 0.31 + index * 0.08,
                    "energy_density_50pct_MJ_per_m3": 0.40 + index * 0.01,
                },
                "objective": {
                    "metric_name": "energy_density_50pct_MJ_per_m3",
                    # The objective contract can still contain the preceding
                    # cycle's fixed manufacturing values.
                    "constraints": {
                        **lhs[max(0, index - 2)],
                        "tpms_thickness": 0.27 + index * 0.03,
                    }
                },
            }
        )

    request = BOAgent.initial_design_request(state, seed=7)

    assert request["phase"] == "initial_design"
    assert request["index"] == 3
    assert request["constraints"]["cell_size_mm"] == lhs[2]["cell_size_mm"]
    assert request["constraints"]["relative_density"] == pytest.approx(lhs[2]["relative_density"])
    assert [point["status"] for point in request["points"][:3]] == ["measured", "measured", "next"]


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
async def test_bo_agent_keeps_cell_size_as_a_feasible_optimization_dimension() -> None:
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
                "cell_size_mm": [5.0, 6.0, 7.5, 10.0],
                "orientation_deg": [0.0],
                "anisotropy_ratio": [1.0],
            },
        },
    )
    bo_result = result.data["bo_result"]

    assert result.success is True
    assert bo_result["parameter_space"]["cell_size_mm"] == [5.0, 6.0, 7.5, 10.0]
    assert bo_result["parameter_space"]["relative_density"][0] == 0.20
    assert bo_result["recommendation"]["parameters"]["cell_size_mm"] in {5.0, 6.0, 7.5, 10.0}
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


def test_bo_agent_restores_full_parameter_vector_from_objective_constraints() -> None:
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.BO,
        active_goal="restore historical BO observations",
    )
    state.experiment_evaluations.append(
        {
            "evaluation_id": "eval-001",
            "objective_score": 0.82,
            "objective": {
                "constraints": {
                    "geometry_type": "gyroid",
                    "relative_density": 0.31,
                    "wall_thickness_mm": 1.4,
                    "cell_size_mm": 10.0,
                    "tpms_thickness": 0.36,
                    "orientation_deg": 30.0,
                    "anisotropy_ratio": 1.2,
                    "skin_thickness_mm": 0.6,
                    "bottom_cap_enabled": True,
                    "top_cap_enabled": False,
                    "skirt_enabled": False,
                }
            },
            "metrics": {
                "relative_density": 0.33,
                "wall_thickness_mm": 1.5,
                "cell_size_mm": 10.0,
                "tpms_thickness": 0.38,
            },
        }
    )

    priors = BOAgent._prior_evaluations_from_state(state)

    assert len(priors) == 1
    assert priors[0]["parameters"] == {
        "geometry_type": "gyroid",
        "relative_density": 0.33,
        "wall_thickness_mm": 1.5,
        "cell_size_mm": 10.0,
        "tpms_thickness": 0.38,
        "orientation_deg": 30.0,
        "anisotropy_ratio": 1.2,
        "skin_thickness_mm": 0.6,
        "bottom_cap_enabled": True,
        "top_cap_enabled": False,
        "skirt_enabled": False,
    }


def test_bo_agent_uses_analysis_scores_without_inventing_observation_noise() -> None:
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.BO,
        active_goal="fit measured experiment outcomes",
    )
    parameters = {
        "geometry_type": "gyroid",
        "relative_density": 0.31,
        "wall_thickness_mm": 1.4,
        "cell_size_mm": 10.0,
        "tpms_thickness": 0.36,
    }
    state.experiment_evaluations.extend(
        [
            {
                "evaluation_id": "eval-design",
                "candidate_id": "cand-001",
                "objective_score": 0.84,
                "objective": {"constraints": parameters},
            },
            {
                "source": "analysis_agent",
                "evaluation_id": "eval-analysis",
                "candidate_id": "specimen-cand-001",
                "objective_score": 0.27,
                "metrics": {"energy_density_50pct_MJ_per_m3": 0.27},
                "objective": {
                    "metric_name": "energy_density_50pct_MJ_per_m3",
                    "constraints": parameters,
                },
            },
        ]
    )

    priors = BOAgent._prior_evaluations_from_state(state)
    design = next(item for item in priors if item.get("candidate_id") == "cand-001")
    measured = next(item for item in priors if item.get("candidate_id") == "specimen-cand-001")

    assert "score" not in design
    assert measured["score"] == 0.27
    assert "uncertainty" not in measured


def test_bo_agent_does_not_treat_generic_objective_uncertainty_as_sea_noise() -> None:
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.BO,
        active_goal="fit measured SEA observations",
        latest_analysis={
            "bo_handoff": {
                "schema": "analysis_bo_handoff.v2",
                "candidate_id": "specimen-001",
                "parameters": {
                    "geometry_type": "gyroid",
                    "cell_size_mm": 7.5,
                    "relative_density": 0.31,
                },
                "metrics": {"energy_density_50pct_MJ_per_m3": 0.0124},
                "objective": {
                    "metric_name": "energy_density_50pct_MJ_per_m3",
                    "uncertainty": 0.17,
                },
            }
        },
    )

    records = BOAgent._analysis_handoff_records(state)

    assert records[0]["score"] == pytest.approx(0.0124)
    assert "uncertainty" not in records[0]


def test_bo_agent_does_not_treat_top_level_analysis_uncertainty_as_sea_noise() -> None:
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.BO,
        active_goal="fit measured SEA observations",
    )
    state.experiment_evaluations.append(
        {
            "source": "analysis_agent",
            "evaluation_id": "eval-analysis-001",
            "candidate_id": "specimen-001",
            "objective_score": 0.0124,
            "uncertainty": 0.17,
            "objective": {"metric_name": "energy_density_50pct_MJ_per_m3"},
            "metrics": {
                "energy_density_50pct_MJ_per_m3": 0.0124,
                "cell_size_mm": 7.5,
                "relative_density": 0.31,
                "geometry_type": "gyroid",
            },
        }
    )

    records = BOAgent._prior_evaluations_from_state(state)
    measured = next(item for item in records if item.get("candidate_id") == "specimen-001")

    assert measured["score"] == pytest.approx(0.0124)
    assert "uncertainty" not in measured


@pytest.mark.asyncio
async def test_bo_agent_uses_current_fixed_surface_settings_for_botorch_history() -> None:
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.BO,
        active_goal="fit the measured closed-loop history",
        current_experiment_spec={
            "geometry_type": "gyroid",
            "cell_size_mm": 10.0,
            "bottom_cap_enabled": False,
            "top_cap_enabled": False,
            "skirt_enabled": False,
        },
    )
    state.run_metadata["latest_mission_contract"] = {
        "safety_budget": {"max_loop_count": 5},
    }
    initial_points = (
        (5.0, 0.215),
        (6.0, 0.245),
        (7.5, 0.275),
        (10.0, 0.305),
        (5.0, 0.335),
        (6.0, 0.365),
        (7.5, 0.405),
        (10.0, 0.455),
    )
    for index, (cell_size, density) in enumerate(initial_points, start=1):
        state.experiment_evaluations.append(
            {
                "evaluation_id": f"eval-{index:03d}",
                "candidate_id": f"candidate-{index:03d}",
                "source": "analysis_agent",
                "objective_score": 0.4 + density,
                "metrics": {"energy_density_50pct_MJ_per_m3": 0.4 + density},
                "objective": {
                    "metric_name": "energy_density_50pct_MJ_per_m3",
                    "constraints": {
                        "geometry_type": "gyroid",
                        "relative_density": density,
                            "wall_thickness_mm": 1.2,
                            "cell_size_mm": cell_size,
                            "tpms_thickness": 0.0,
                            "orientation_deg": 0.0,
                            "anisotropy_ratio": 1.0,
                            "skin_thickness_mm": 0.8,
                        "bottom_cap_enabled": False,
                        "top_cap_enabled": False,
                        "skirt_enabled": False,
                    }
                },
            }
        )

    result = await BOAgent().run_with_settings(
        state,
        _CtxStub(),
        {
            "strategy": "bo",
            "budget": 1,
            "bo_backend": "botorch",
        },
    )
    trace = result.data["bo_result"]["benchmark"]["strategies"]["bo"]["surrogate_trace"][-1]

    assert trace["phase"] == "acquisition"
    assert trace["backend_active"] == "botorch"
    assert trace["model"]["class"] == "SingleTaskGP"


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
    assert settings["bo_backend"] == "botorch"
    assert warnings


def test_bo_agent_normalize_settings_accepts_botorch_optional_backend() -> None:
    settings, warnings = BOAgent.normalize_settings({"bo_backend": "botorch_optional", "top_k": 99})

    assert settings["bo_backend"] == "botorch"
    assert settings["top_k"] == 12
    assert warnings == []


def test_bo_agent_auto_initial_design_requires_eight_valid_observations() -> None:
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.BO,
    )
    state.run_metadata["latest_mission_contract"] = {
        "safety_budget": {"max_loop_count": 5},
    }

    assert BOAgent._initial_design_size_for_run("auto", state) == 8
    assert BOAgent._initial_design_size_for_run(7, state) == 7


def test_bo_agent_initial_design_uses_configured_contract_size() -> None:
    state = OrchestratorState(
        run_id="run-configured-lhs",
        experiment_id="exp-configured-lhs",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    state.run_metadata["orchestrator_design_contract"] = {
        "optimization": {
            "initial_design": {
                "sampler": "latin_hypercube",
                "size": 3,
                "seed": 11,
            }
        }
    }

    request = BOAgent.initial_design_request(state, seed=11)

    assert BOAgent._initial_design_size_for_run("auto", state) == 3
    assert BOAgent._initial_design_size_for_run(8, state) == 3
    assert request["target"] == 3
    assert len(request["points"]) == 3


def test_bo_agent_default_space_is_two_variable_gyroid_problem() -> None:
    settings, _warnings = BOAgent.normalize_settings({})
    space = BOParameterSpace.from_mapping(settings["parameter_space"])

    assert [item.name for item in space.active_dimensions] == ["cell_size_mm", "relative_density"]
    assert settings["parameter_space"]["cell_size_mm"] == [5.0, 6.0, 7.5, 10.0]
    assert settings["parameter_space"]["relative_density"] == [0.20, 0.48]
    assert settings["parameter_space"]["orientation_deg"] == [0.0]
    assert settings["parameter_space"]["anisotropy_ratio"] == [1.0]
    assert settings["initial_design_size"] == 8


def test_bo_agent_initial_design_request_advances_through_canonical_lhs() -> None:
    state = OrchestratorState(
        run_id="run-initial-lhs",
        experiment_id="exp-initial-lhs",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    space = BOParameterSpace.from_mapping(BOAgent.DEFAULT_PARAMETER_SPACE)
    expected = space.lhs_points(8, seed=7)

    first = BOAgent.initial_design_request(state, seed=7)
    state.experiment_evaluations.append(
        {
            "candidate_id": "lhs-observation-001",
            "source": "analysis_agent",
            "metrics": {"energy_density_50pct_MJ_per_m3": 0.42},
            "objective": {
                "metric_name": "energy_density_50pct_MJ_per_m3",
                "constraints": first["constraints"],
            },
        }
    )
    second = BOAgent.initial_design_request(state, seed=7)

    assert first["phase"] == "initial_design"
    assert first["sampler"] == "latin_hypercube"
    assert first["index"] == 1
    assert first["target"] == 8
    assert first["constraints"] == expected[0]
    assert len(first["points"]) == 8
    assert first["points"][0] == {
        "index": 1,
        "status": "next",
        "parameters": expected[0],
    }
    assert first["points"][1] == {
        "index": 2,
        "status": "planned",
        "parameters": expected[1],
    }
    assert second["index"] == 2
    assert second["constraints"] == expected[1]
    assert second["points"][0]["status"] == "measured"
    assert second["points"][1]["status"] == "next"


def test_eight_observations_complete_lhs_phase() -> None:
    state = OrchestratorState(
        run_id="run-eight-point-lhs",
        experiment_id="exp-eight-point-lhs",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    state.run_metadata["latest_mission_contract"] = {
        "safety_budget": {"max_loop_count": 20},
    }

    for cycle in range(1, 9):
        request = BOAgent.initial_design_request(state, seed=7)
        assert request["phase"] == "initial_design"
        assert request["sampler"] == "latin_hypercube"
        assert request["index"] == cycle
        assert request["target"] == 8
        state.experiment_evaluations.append(
            {
                "evaluation_id": f"eval-{cycle:03d}",
                "candidate_id": f"candidate-{cycle:03d}",
                "source": "analysis_agent",
                "metrics": {"energy_density_50pct_MJ_per_m3": 0.4 + cycle * 0.01},
                "objective": {
                    "metric_name": "energy_density_50pct_MJ_per_m3",
                    "constraints": request["constraints"],
                },
            }
        )

    next_request = BOAgent.initial_design_request(state, seed=7)
    assert next_request["phase"] == "acquisition_ready"
    assert next_request["index"] == 8
    assert next_request["target"] == 8


def test_bo_agent_uses_declared_energy_density_instead_of_composite_objective_score() -> None:
    state = OrchestratorState(
        run_id="run-sea",
        experiment_id="exp-sea",
        mode=Mode.TEST,
        stage=Stage.BO,
    )
    state.experiment_evaluations.append(
        {
            "source": "analysis_agent",
            "evaluation_id": "eval-sea",
            "candidate_id": "candidate-sea",
            "objective_score": 0.91,
            "parameters": {"cell_size_mm": 7.5, "relative_density": 0.34},
            "metrics": {"energy_density_50pct_MJ_per_m3": 0.237},
            "objective": {
                "metric_name": "energy_density_50pct_MJ_per_m3",
                "unit": "MJ/m3",
            },
        }
    )

    prior = next(item for item in BOAgent._prior_evaluations_from_state(state) if item.get("candidate_id") == "candidate-sea")

    assert prior["score"] == pytest.approx(0.237)
    assert prior["metric_name"] == "energy_density_50pct_MJ_per_m3"
    assert prior["unit"] == "MJ/m3"


def test_bo_agent_uses_declared_50pct_energy_from_analysis_handoff() -> None:
    state = OrchestratorState(
        run_id="run-energy-50pct",
        experiment_id="exp-energy-50pct",
        mode=Mode.TEST,
        stage=Stage.BO,
    )
    state.latest_analysis = {
        "bo_handoff": {
            "schema_version": "analysis_bo_handoff_v2",
            "ok_for_bo": True,
            "candidate_id": "candidate-energy-50pct",
            "parameters": {"cell_size_mm": 7.5, "relative_density": 0.34},
            "objective": {
                "metric_name": "energy_absorption_50pct_mJ",
                "unit": "mJ",
                "direction": "maximize",
                "score": 1125.0,
            },
            "metrics": {"energy_absorption_50pct_mJ": 1125.0},
        }
    }

    prior = next(
        item
        for item in BOAgent._prior_evaluations_from_state(state)
        if item.get("candidate_id") == "candidate-energy-50pct"
    )

    assert prior["score"] == pytest.approx(1125.0)
    assert prior["metric_name"] == "energy_absorption_50pct_mJ"
    assert prior["unit"] == "mJ"


def test_bo_agent_deduplicates_analysis_envelopes_for_one_50pct_observation() -> None:
    state = OrchestratorState(
        run_id="run-one-observation",
        experiment_id="exp-one-observation",
        mode=Mode.TEST,
        stage=Stage.BO,
        current_experiment_spec={"cell_size_mm": 7.5, "relative_density": 0.34},
    )
    objective = {
        "metric_name": "energy_absorption_50pct_mJ",
        "unit": "mJ",
        "score": 1125.0,
    }
    common = {
        "observation_id": "run-one-observation:exp-one-observation:analysis",
        "candidate_id": "candidate-one",
        "parameters": {"cell_size_mm": 7.5, "relative_density": 0.34},
    }
    state.latest_analysis = {
        "bo_handoff": {
            **common,
            "schema_version": "analysis_bo_handoff_v2",
            "ok_for_bo": True,
            "objective": objective,
        },
        "bo_observation": {
            **common,
            "schema": "bo_observation.v1",
            "status": "ready",
            "metric_name": "energy_absorption_50pct_mJ",
            "unit": "mJ",
            "objective_score": 1125.0,
        },
        "experiment_evaluation": {
            **common,
            "schema": "experiment_evaluation.v1",
            "source": "analysis_agent",
            "ok": True,
            "objective": objective,
            "objective_score": 1125.0,
        },
    }
    state.experiment_evaluations.append(dict(state.latest_analysis["experiment_evaluation"]))

    measured = [
        item
        for item in BOAgent._prior_evaluations_from_state(state)
        if isinstance(item.get("score"), (int, float))
    ]

    assert len(measured) == 1
    assert measured[0]["score"] == pytest.approx(1125.0)


def test_bo_agent_never_promotes_design_proxy_when_analysis_observation_is_blocked() -> None:
    state = OrchestratorState(
        run_id="run-no-proxy-fallback",
        experiment_id="exp-no-proxy-fallback",
        mode=Mode.TEST,
        stage=Stage.BO,
        current_experiment_spec={"cell_size_mm": 7.5, "relative_density": 0.34},
        current_experiment_objective={
            "metric_name": "energy_density_50pct_MJ_per_m3",
            "direction": "maximize",
        },
    )
    state.experiment_evaluations.append(
        {
            "source": "specimen_agent",
            "evaluation_id": "printability-proxy",
            "candidate_id": "candidate-proxy",
            "objective_score": 0.91,
            "parameters": {"cell_size_mm": 7.5, "relative_density": 0.34},
            "metrics": {"printability_score": 0.91},
            "objective": {
                "metric_name": "printability_score",
                "score": 0.91,
            },
        }
    )
    state.latest_analysis = {
        "bo_observation": {
            "schema": "bo_observation.v1",
            "status": "blocked",
            "ok_for_bo": False,
            "candidate_id": "candidate-proxy",
            "parameters": {"cell_size_mm": 7.5, "relative_density": 0.34},
            "metric_name": "energy_density_50pct_MJ_per_m3",
            "objective_score": None,
        }
    }

    priors = BOAgent._prior_evaluations_from_state(state)

    assert not any(isinstance(item.get("score"), (int, float)) for item in priors)


@pytest.mark.asyncio
async def test_bo_agent_blocks_after_analysis_when_exact_metric_observation_is_missing() -> None:
    state = OrchestratorState(
        run_id="run-exact-objective-required",
        experiment_id="exp-exact-objective-required",
        mode=Mode.TEST,
        stage=Stage.BO,
        current_experiment_spec={"cell_size_mm": 7.5, "relative_density": 0.34},
        current_experiment_objective={
            "metric_name": "energy_density_50pct_MJ_per_m3",
            "direction": "maximize",
        },
    )
    state.latest_analysis = {
        "bo_observation": {
            "schema": "bo_observation.v1",
            "status": "blocked",
            "ok_for_bo": False,
            "candidate_id": "candidate-blocked",
            "parameters": {"cell_size_mm": 7.5, "relative_density": 0.34},
            "metric_name": "energy_density_50pct_MJ_per_m3",
            "objective_score": None,
        }
    }

    result = await BOAgent().run_with_settings(state, _CtxStub(), {"strategy": "bo", "budget": 1})

    assert result.success is False
    assert result.data["bo_result"]["status"] == "blocked"
    assert result.data["bo_result"]["failure_code"] == "BO_EXACT_OBJECTIVE_OBSERVATION_REQUIRED"

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
    _add_completed_lhs_observations(state)
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
            "objective": {
                "metric_name": "energy_density_50pct_MJ_per_m3",
                "score": 0.71,
                "uncertainty": 0.12,
            },
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
    selected_cell = bo_result["next_design_request"]["constraints"]["cell_size_mm"]
    assert selected_cell in {5.0, 6.0, 7.5, 10.0}
    assert state.run_metadata["bo_recommended_constraints"]["cell_size_mm"] == selected_cell
    for path in bo_result["artifacts"].values():
        assert Path(path).exists()


def test_bo_agent_reads_analysis_handoff_v2_trust_context() -> None:
    state = OrchestratorState(
        run_id="run-bo-trust",
        experiment_id="exp-bo-trust",
        mode=Mode.TEST,
        stage=Stage.BO,
        current_experiment_spec={"cell_size_mm": 5.0},
    )
    state.latest_analysis = {
        "bo_handoff": {
            "schema_version": "analysis_bo_handoff_v2",
            "ok_for_bo": False,
            "candidate_id": "specimen-trust-hold",
            "parameters": {
                "geometry_type": "gyroid",
                "relative_density": 0.34,
                "wall_thickness_mm": 1.5,
                "cell_size_mm": 5.0,
            },
            "objective": {"score": 0.62, "uncertainty": 0.24},
            "trust_score": {
                "schema": "trust_score.v1",
                "score": 0.61,
                "gate": "calibrate_only",
                "components": {"q_data": 0.9, "q_agreement": 0.35, "q_physics": 0.65, "q_uq": 0.76, "q_provenance": 0.8},
                "reasons": ["stiffness_error_high"],
            },
            "fidelity_records": {
                "utm_high": {"schema": "utm_record.v1"},
                "fea_mid": {"schema": "fea_result.v1"},
                "pinn_low_or_surrogate": {"status": "unavailable"},
            },
            "failure_tags": [],
        }
    }

    records = BOAgent._analysis_handoff_records(state)

    assert records[0]["source"] == "analysis_bo_handoff_v2"
    assert records[0]["trust_score"]["score"] == 0.61
    assert records[0]["trust_gate"] == "calibrate_only"
    assert records[0]["ok_for_bo"] is False
    assert records[0]["quality_score"] == 0.61


def test_bo_agent_filters_live_observations_by_hash_fidelity_and_lineage() -> None:
    def observation(observation_id: str, objective_hash: str, fidelity: str) -> dict:
        return {
            "observation_id": observation_id,
            "objective_hash": objective_hash,
            "score": 0.7,
            "feasible": True,
            "fidelity": fidelity,
            "parameters": {"cell_size_mm": 7.5, "relative_density": 0.32},
            "provenance_refs": [f"artifact:{observation_id}"],
            "ok_for_bo": True,
        }

    accepted, rejected = BOAgent.objective_observations(
        [
            observation("measured-a", "sha256:a", "measured"),
            observation("measured-b", "sha256:b", "measured"),
            observation("synthetic-a", "sha256:a", "synthetic"),
        ],
        objective_hash="sha256:a",
        mode=Mode.LIVE,
    )

    assert [item["observation_id"] for item in accepted] == ["measured-a"]
    assert {item["reason"] for item in rejected} == {"objective_hash_mismatch", "synthetic_live_proxy"}


def test_bo_agent_test_mode_accepts_explicit_synthetic_observation() -> None:
    accepted, rejected = BOAgent.objective_observations(
        [
            {
                "observation_id": "synthetic-a",
                "objective_hash": "sha256:a",
                "score": 0.5,
                "feasible": True,
                "fidelity": "synthetic",
                "parameters": {"relative_density": 0.3},
                "provenance_refs": ["synthetic-fixture"],
                "ok_for_bo": True,
            },
            {
                "observation_id": "implicit-fidelity",
                "objective_hash": "sha256:a",
                "score": 0.4,
                "feasible": True,
                "parameters": {"relative_density": 0.28},
                "provenance_refs": ["fixture"],
                "ok_for_bo": True,
            },
        ],
        objective_hash="sha256:a",
        mode=Mode.TEST,
    )

    assert [item["observation_id"] for item in accepted] == ["synthetic-a"]
    assert rejected[0]["reason"] == "fidelity_required"


@pytest.mark.asyncio
async def test_live_bo_blocks_without_hash_matched_measured_observation() -> None:
    state = OrchestratorState(
        run_id="run-live-objective",
        experiment_id="exp-live-objective",
        mode=Mode.LIVE,
        stage=Stage.BO,
        current_experiment_objective={
            "schema_version": "objective_spec.v1",
            "objective_id": "active-objective",
            "version": 2,
            "objective_hash": "sha256:active",
        },
    )
    state.latest_analysis = {
        "bo_handoff": {
            "schema_version": "analysis_bo_handoff_v2",
            "ok_for_bo": True,
            "candidate_id": "wrong-objective",
            "parameters": {"cell_size_mm": 7.5, "relative_density": 0.32},
            "metric_name": "energy_density_50pct_MJ_per_m3",
            "observed_metrics": {"energy_density_50pct_MJ_per_m3": 0.8},
            "objective_evaluation": {
                "observation_id": "obs-wrong",
                "objective_hash": "sha256:other",
                "score": 0.8,
                "feasible": True,
                "fidelity": "measured",
                "provenance_refs": ["analysis-artifact"],
            },
        }
    }

    result = await BOAgent().run_with_settings(state, _CtxStub(), {"strategy": "bo", "budget": 2})

    assert result.success is False
    assert result.data["bo_result"]["failure_code"] == "BO_EXACT_OBJECTIVE_OBSERVATION_REQUIRED"
    assert result.data["bo_result"]["observation_integrity"]["rejected"][0]["reason"] == "objective_hash_mismatch"


@pytest.mark.asyncio
async def test_next_design_request_carries_active_objective_identity() -> None:
    state = OrchestratorState(
        run_id="run-objective-design",
        experiment_id="exp-objective-design",
        mode=Mode.TEST,
        stage=Stage.BO,
        current_experiment_objective={
            "schema_version": "objective_spec.v1",
            "objective_id": "active-objective",
            "version": 4,
            "objective_hash": "sha256:active-4",
            "direction": "maximize",
        },
    )
    state.latest_analysis = {
        "bo_handoff": {
            "schema_version": "analysis_bo_handoff_v2",
            "ok_for_bo": True,
            "candidate_id": "measured-a",
            "parameters": {"cell_size_mm": 7.5, "relative_density": 0.32},
            "metric_name": "energy_density_50pct_MJ_per_m3",
            "observed_metrics": {"energy_density_50pct_MJ_per_m3": 0.8},
            "objective_evaluation": {
                "observation_id": "obs-a",
                "objective_id": "active-objective",
                "objective_version": 4,
                "objective_hash": "sha256:active-4",
                "score": 0.8,
                "feasible": True,
                "fidelity": "measured",
                "provenance_refs": ["analysis-artifact"],
            },
        }
    }

    result = await BOAgent().run_with_settings(state, _CtxStub(), {"strategy": "bo", "budget": 2})

    request = result.data["next_design_request"]
    assert request["objective_id"] == "active-objective"
    assert request["objective_version"] == 4
    assert request["objective_hash"] == "sha256:active-4"


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
    _add_completed_lhs_observations(state)
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
