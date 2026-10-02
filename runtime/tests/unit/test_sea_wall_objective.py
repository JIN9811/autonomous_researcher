"""SEA is a mass-normalized observation, not volumetric energy density."""
import pytest

from agents.analysis.agent import AnalysisAgent
from agents.bo.agent import BOAgent
from agents.design.agent import DesignAgent
from app.controller import MainController
from orchestrator.state import Mode, OrchestratorState
from utils.research_objective import SEA_METRIC, uses_sea


def test_sea_name_is_not_matched_inside_research():
    assert uses_sea({}, "maximize SEA")
    assert not uses_sea({}, "research compression")
    assert MainController._extract_objective_from_text("maximize SEA")[0] == "maximize_energy_absorption_per_mass"


def test_sea_is_energy_in_joules_divided_by_grams():
    curve = [{"displacement_mm": float(x), "force_N": 100.0} for x in range(11)]
    metrics = AnalysisAgent()._metrics(curve, {
        "cross_section_area_mm2": 100, "gauge_length_mm": 20, "mass_g": 2,
    })
    # 100 N * 10 mm = 1 J; 1 J / 2 g = 0.5 J/g.
    assert metrics[SEA_METRIC] == pytest.approx(0.5)


def test_anl_bo_and_design_use_same_sea_metric():
    state = OrchestratorState(run_id="sea-unit", experiment_id="sea-unit", mode=Mode.TEST,
        active_goal="maximize SEA", current_experiment_spec={
            "wall_thickness_mm": 1.2, "cell_size_mm": 7.5, "gyroid_parameterization": "wall_cell_v1"})
    result = AnalysisAgent()._handoff_payloads(state=state,
        analysis={"ok": True, "quality_gate": {"ok_for_metrics": True}},
        metrics={SEA_METRIC: 0.5, "energy_density_50pct_MJ_per_m3": 99.0},
        source_meta={"source": "synthetic_fixture", "fidelity": "synthetic"}, equipment_result={})
    observation = result["bo_observation"]
    assert observation["metric_name"] == SEA_METRIC
    assert observation["objective_score"] == 0.5
    assert observation["unit"] == "J/g"
    assert observation["fidelity"] == "synthetic"
    assert BOAgent._objective_from_state(state, {})["metric_name"] == SEA_METRIC
    assert DesignAgent()._objective_contract(state, {})["primary_metric"] == SEA_METRIC
    agent = AnalysisAgent()
    metrics = {SEA_METRIC: 0.5, "energy_density_50pct_MJ_per_m3": 99.0}
    assert agent._reported_objective(state, metrics, None) == observation["objective_score"]
    assert agent._reported_objective(state, metrics, {}) == 0.5
    assert agent._reported_objective(state, metrics, {"objective_hash": "bound", "score": 7.0}) == 7.0
    assert agent._reported_objective(state, {}, None) is None
