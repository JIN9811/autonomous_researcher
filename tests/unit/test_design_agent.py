"""
Unit tests for DesignAgent resilience behavior.
"""

from __future__ import annotations

import pytest

from agents.design_agent import DesignAgent
from orchestrator.state import Mode, OrchestratorState, Stage


class _FailureMemoryStub:
    def recent(self, limit: int = 5):
        return []


class _CtxStub:
    force_real_llm_in_test = True
    failure_memory = _FailureMemoryStub()

    async def complete(self, task_type: str, user_prompt: str):
        raise TimeoutError("simulated model timeout")


class _DeterministicCtxStub(_CtxStub):
    force_real_llm_in_test = False


@pytest.mark.asyncio
async def test_design_agent_degrades_gracefully_on_test_timeout() -> None:
    agent = DesignAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="test",
    )
    result = await agent.run(state, _CtxStub())
    assert result.success is True
    assert "experiment_spec" in result.data
    assert "degraded" in str(result.data["rationale"]).lower()


@pytest.mark.asyncio
async def test_design_agent_returns_specimen_design_schema() -> None:
    agent = DesignAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="maximize compression energy absorption per unit mass",
    )
    result = await agent.run(state, _DeterministicCtxStub())
    spec = result.data["experiment_spec"]

    required = {
        "candidate_id",
        "specimen_id",
        "objective_type",
        "objective_direction",
        "geometry_type",
        "specimen_size_mm",
        "cell_size_mm",
        "wall_thickness_mm",
        "relative_density",
        "porosity",
        "anisotropy_ratio",
        "orientation_deg",
        "defect_seed",
        "defect_ratio",
        "skin_thickness_mm",
        "top_cap_enabled",
        "bottom_cap_enabled",
        "top_bottom_cap",
        "material",
        "printer_profile",
        "slicer_profile_hint",
        "layer_height_mm",
        "bed_temperature_c",
        "first_layer_bed_temperature_c",
        "nozzle_diameter_mm",
        "expected_mass_g",
        "expected_volume_mm3",
        "expected_print_time_min",
        "expected_manufacturability_score",
        "expected_objective_proxy_score",
        "generation_strategy",
        "generation_reason",
    }
    assert required.issubset(spec)
    assert spec["geometry_type"] in DesignAgent.SUPPORTED_GEOMETRIES
    assert spec["geometry_type"] == DesignAgent.TEST_DEFAULT_GEOMETRY
    assert len(spec["specimen_size_mm"]) == 3
    assert spec["cell_size_mm"] == 10.0
    assert spec["cell_size_mm"] >= 3.0 * spec["wall_thickness_mm"]
    assert spec["layer_height_mm"] == 0.2
    assert spec["bed_temperature_c"] == 60.0
    assert spec["first_layer_bed_temperature_c"] == 60.0
    assert spec["slicer_profile_hint"] == "0.2mm_quality"
    assert 0.0 <= spec["expected_objective_proxy_score"] <= 1.0
    assert spec["expected_print_time_min"] <= spec["constraints"]["max_print_time_min"]


@pytest.mark.asyncio
async def test_design_agent_respects_state_constraints() -> None:
    agent = DesignAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="test constrained specimen",
        current_experiment_spec={
            "constraints": {
                "material": "PETG",
                "max_specimen_size_mm": [20, 22, 24],
                "max_print_time_min": 90,
                "max_mass_g": 20,
            }
        },
    )
    result = await agent.run(state, _DeterministicCtxStub())
    spec = result.data["experiment_spec"]

    assert spec["material"] == "PETG"
    assert spec["specimen_size_mm"] == [20.0, 22.0, 24.0]
    assert spec["expected_mass_g"] <= 20
    assert spec["expected_print_time_min"] <= 90


@pytest.mark.asyncio
async def test_design_agent_uses_orchestrator_requested_parameters_as_authority() -> None:
    agent = DesignAgent()
    state = OrchestratorState(
        run_id="run-orchestrator-contract",
        experiment_id="exp-orchestrator-contract",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="maximize gyroid SEA",
        current_experiment_spec={
            "constraints": {
                "geometry_type": "gyroid",
                "cell_size_mm": 10.0,
                "relative_density": 0.24,
            }
        },
        run_metadata={
            "bo_recommended_constraints": {
                "cell_size_mm": 7.5,
                "relative_density": 0.29,
            },
            "orchestrator_design_contract": {
                "schema": "orchestrator_design_contract.v1",
                "contract_id": "design-run-orchestrator-contract-c001",
                "phase": "initial_design",
                "requested_parameters": {
                    "cell_size_mm": 6.0,
                    "relative_density": 0.37,
                },
            },
        },
    )

    result = await agent.run(state, _DeterministicCtxStub())
    spec = result.data["experiment_spec"]

    assert spec["cell_size_mm"] == 6.0
    assert spec["relative_density"] == pytest.approx(0.37)
    assert spec["requested_parameters"] == {
        "cell_size_mm": 6.0,
        "relative_density": pytest.approx(0.37),
    }
    assert spec["orchestrator_design_contract_ref"] == "design-run-orchestrator-contract-c001"


@pytest.mark.asyncio
async def test_design_agent_keeps_preferred_geometry_when_bo_candidate_is_invalid() -> None:
    agent = DesignAgent()
    state = OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="closed loop gyroid specimen",
        current_experiment_spec={
            "constraints": {
                "geometry_type": "gyroid",
                "preferred_geometry_type": "gyroid",
                "cell_size_mm": 10.0,
            }
        },
        run_metadata={
            "bo_recommended_constraints": {
                "geometry_type": "gyroid",
                "relative_density": 0.18,
                "cell_size_mm": 5.0,
            }
        },
    )

    result = await agent.run(state, _DeterministicCtxStub())
    spec = result.data["experiment_spec"]

    assert result.success is True
    assert spec["geometry_type"] == "gyroid"
    assert spec["cell_size_mm"] == 10.0
    assert spec["relative_density"] >= 0.20
    assert "honeycomb" not in spec["specimen_id"]


@pytest.mark.asyncio
async def test_design_agent_returns_structured_design_report_and_handoff_packet() -> None:
    agent = DesignAgent()
    state = OrchestratorState(
        run_id="run-report",
        experiment_id="exp-report",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="maximize compression energy absorption per unit mass",
    )

    result = await agent.run(state, _DeterministicCtxStub())
    data = result.data
    spec = data["experiment_spec"]
    report = data["design_report"]
    screen_report = data["design_agent_report"]
    handoff = data["handoff_packet"]

    assert report["schema"] == "design_report.v1"
    assert screen_report["schema"] == "design_agent_report.v1"
    assert screen_report["source_report_id"] == report["report_id"]
    assert handoff["schema"] == "design_candidate.v1"
    assert handoff["experiment_spec"] == spec
    assert handoff["status"] == "ready"
    assert report["handoff_to_specimen"]["required_fields_present"] is True
    assert report["candidate_evaluation"]["selected_candidate_id"] == spec["candidate_id"]
    assert report["candidate_evaluation"]["selected_candidate_fingerprint"] == spec["candidate_fingerprint"]
    assert report["hypothesis"]["statement"]
    assert report["objective"]["primary_metric"] == "energy_absorption_per_mass"
    assert report["candidate_generation"]["candidate_count"] == 12
    assert report["candidate_generation"]["valid_count"] >= 1
    assert len(report["candidate_generation"]["candidate_ledger"]) >= 12
    expected_sections = {
        "design_brief",
        "candidate_board",
        "candidate_ranking",
        "parameter_sweep",
        "expected_performance",
        "manufacturability",
        "bambu_autoejection_readiness",
        "material_notes",
        "handoff_to_specimen",
        "artifact_ledger",
    }
    assert expected_sections.issubset(screen_report)
    assert screen_report["candidate_ranking"]["rows"][0]["candidate_id"] == spec["candidate_id"]
    assert screen_report["parameter_sweep"]["heatmap_cells"]
    heatmap_coordinates = [
        (item["x_relative_density"], item["y_wall_thickness_mm"])
        for item in screen_report["parameter_sweep"]["heatmap_cells"]
    ]
    assert len(heatmap_coordinates) == len(set(heatmap_coordinates))
    assert screen_report["expected_performance"]["scatter_points"]
    assert screen_report["expected_performance"]["radar"]
    readiness = spec["bambu_autoejection_readiness"]
    assert readiness["schema"] == "bambu_autoejection_design_readiness.v1"
    assert readiness["ejection_contact_edge"] in {"front", "left", "right", "object_center"}
    assert 0.0 < readiness["bed_contact_area_ratio"] <= 1.0
    assert readiness["pushable_edge_height_mm"] == readiness["object_height_mm"]
    assert readiness["minimum_pushable_height_mm"] >= 5.0
    assert readiness["skirt_brim_raft_policy"] == {
        "skirt_enabled": False,
        "brim_enabled": False,
        "raft_enabled": False,
    }
    assert screen_report["bambu_autoejection_readiness"] == readiness
    assert report["manufacturability"]["bambu_autoejection_readiness"] == readiness
    assert screen_report["handoff_to_specimen"]["packet_status"] == "ready"
    assert {item["type"] for item in screen_report["visualization_manifest"]} >= {
        "candidate_cards",
        "ranking_bar_chart",
        "heatmap",
        "scatter_plot",
        "radar_chart",
    }
    assert data["metrics"]["selected_score"] == spec["expected_objective_proxy_score"]
    assert data["decisions"] == report["decision_register"]


def test_design_parameter_range_uses_full_numeric_design_space() -> None:
    row = DesignAgent._parameter_range("orientation_deg", {"orientation_deg": 90})

    assert row["min"] == 0
    assert row["max"] == 90
    assert row["values"] == [0, 15, 30, 45, 60, 90]


def test_design_heatmap_cells_group_duplicate_coordinates_with_selected_representative() -> None:
    agent = DesignAgent()
    cells = agent._group_heatmap_cells(
        [
            {
                "candidate_id": "cand-2-05",
                "x_relative_density": 0.34,
                "y_wall_thickness_mm": 1.6,
                "value": 0.8633,
                "status": "valid",
            },
            {
                "candidate_id": "cand-2-12",
                "x_relative_density": 0.34,
                "y_wall_thickness_mm": 1.6,
                "value": 0.8884,
                "status": "selected",
            },
        ]
    )

    assert len(cells) == 1
    assert cells[0]["candidate_id"] == "cand-2-12"
    assert cells[0]["value"] == 0.8884
    assert cells[0]["member_count"] == 2
    assert [item["candidate_id"] for item in cells[0]["members"]] == ["cand-2-12", "cand-2-05"]


class _ExperimentRecord:
    run_id = "prior-run"
    experiment_id = "prior-exp"
    score = 0.83
    uncertainty = 0.12
    summary = "Prior gyroid showed stable compression response."


class _ExperimentDbStub:
    def list_recent(self, limit: int = 20):
        return [_ExperimentRecord()]


class _FailureRecord:
    failure_type = "print_detached"
    context = {"geometry_type": "random_voronoi"}


class _FailureMemoryWithRecord:
    def recent(self, limit: int = 10):
        return [_FailureRecord()]


class _FeedbackCtxStub(_DeterministicCtxStub):
    experiment_db = _ExperimentDbStub()
    failure_memory = _FailureMemoryWithRecord()


@pytest.mark.asyncio
async def test_design_agent_records_bo_knowledge_and_failure_feedback_context() -> None:
    agent = DesignAgent()
    state = OrchestratorState(
        run_id="run-feedback",
        experiment_id="exp-feedback",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="explore compression metamaterial design space",
        run_metadata={
            "knowledge": {"summary": "Avoid disconnected Voronoi specimens after bed adhesion failures."},
            "bo_agent": {
                "strategy": "single_objective_ei",
                "acquisition": "expected_improvement",
                "recommendation": {"geometry_type": "gyroid", "relative_density": 0.34},
            },
            "bo_recommended_constraints": {"geometry_type": "gyroid", "relative_density": 0.34},
        },
    )

    result = await agent.run(state, _FeedbackCtxStub())
    report = result.data["design_report"]
    prior = report["prior_context"]

    assert prior["prior_count"] == 1
    assert prior["best_prior"]["score"] == 0.83
    assert prior["knowledge_summary"]["available"] is True
    assert prior["bo_recommendation"]["available"] is True
    assert prior["bo_recommendation"]["acquisition"] == "expected_improvement"
    assert "random_voronoi" in prior["failure_memory"]["failed_geometry_types"]
    assert result.data["experiment_spec"]["geometry_type"] == "gyroid"
    assert result.data["experiment_spec"]["relative_density"] == 0.34


@pytest.mark.asyncio
async def test_design_agent_applies_both_bo_design_variables_without_changing_fixed_orientation() -> None:
    state = OrchestratorState(
        run_id="run-two-variable",
        experiment_id="exp-two-variable",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
        active_goal="maximize measured SEA",
        run_metadata={
            "bo_recommended_constraints": {
                "geometry_type": "gyroid",
                "cell_size_mm": 7.5,
                "relative_density": 0.41,
            }
        },
    )

    result = await DesignAgent().run(state, _DeterministicCtxStub())
    spec = result.data["experiment_spec"]

    assert spec["cell_size_mm"] == 7.5
    assert spec["relative_density"] == 0.41
    assert spec["orientation_deg"] == 0.0
    assert spec["anisotropy_ratio"] == 1.0
