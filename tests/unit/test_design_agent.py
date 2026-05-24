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
