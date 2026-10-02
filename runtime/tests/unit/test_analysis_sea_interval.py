"""SEA is mass-normalized energy to 50% initial height, not the CSV endpoint."""
import json
from pathlib import Path

import pytest

from agents.analysis.agent import AnalysisAgent
from tests.unit.test_analysis_agent import _CtxStub, _state
from utils.research_objective import SEA_METRIC


def curve(end, *, displacement_offset=0.0, force_offset=0.0):
    return [
        {"time_s": i * 3.0, "displacement_mm": i / 10 + displacement_offset,
         "force_N": 1000 * i / 10 + force_offset}
        for i in range(round(end * 10) + 1)
    ]


@pytest.mark.parametrize("end", [15.0, 16.0, 21.0])
@pytest.mark.parametrize("offsets", [(0.0, 0.0), (2.0, 10.0)])
def test_sea_ignores_extra_travel_and_uses_the_same_canonical_energy(end, offsets):
    metrics = AnalysisAgent()._metrics(
        curve(end, displacement_offset=offsets[0], force_offset=offsets[1]),
        {"cross_section_area_mm2": 900, "gauge_length_mm": 30, "mass_g": 10},
    )
    assert metrics["energy_absorption_limit_mm"] == 15
    assert metrics["energy_absorption_limit_reached"] is True
    assert metrics["energy_absorption_50pct_mJ"] == pytest.approx(112500)
    assert metrics[SEA_METRIC] == pytest.approx(11.25)
    assert metrics[SEA_METRIC] == pytest.approx(metrics["energy_absorption_50pct_mJ"] / 1000 / 10)


def test_sea_interpolates_half_height_instead_of_hardcoding_travel():
    metrics = AnalysisAgent()._metrics(
        [{"displacement_mm": d, "force_N": 1000 * d} for d in (0, 4, 8, 12, 16)],
        {"cross_section_area_mm2": 400, "gauge_length_mm": 20, "mass_g": 10},
    )
    assert metrics["energy_absorption_limit_mm"] == 10
    assert metrics[SEA_METRIC] == pytest.approx(5)


@pytest.mark.parametrize("height", [20.0, 30.0, 40.0])
def test_sea_boundary_follows_current_specimen_height(height):
    metrics = AnalysisAgent()._metrics(
        curve(height * 0.6),
        {"cross_section_area_mm2": 900, "gauge_length_mm": height, "mass_g": 10},
    )
    boundary = height * 0.5
    assert metrics["energy_absorption_limit_mm"] == boundary
    assert metrics[SEA_METRIC] == pytest.approx(0.5 * boundary ** 2 / 10)


@pytest.mark.parametrize("end,mass", [(14.9, 10), (16, 0), (16, -1)])
def test_sea_has_no_score_without_full_interval_or_positive_mass(end, mass):
    metrics = AnalysisAgent()._metrics(
        curve(end), {"cross_section_area_mm2": 900, "gauge_length_mm": 30, "mass_g": mass},
    )
    assert metrics[SEA_METRIC] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("end", [14.9, 16.0, 21.0])
async def test_sea_interval_reaches_report_bo_knowledge_and_saved_artifacts(end, tmp_path, monkeypatch):
    monkeypatch.setattr("agents.analysis.agent.resolve_path", lambda value: tmp_path / value)
    state = _state(equipment_result={"ok": True, "tool": "equipment.pyautogui.run", "utm_data": curve(end)})
    state.current_experiment_spec.update(
        specimen_size_mm=[30, 30, 30], expected_mass_g=10,
        objective_type="specific energy absorption",
    )
    state.current_experiment_objective = {"metric_name": SEA_METRIC, "direction": "maximize"}
    state.run_metadata["specimen_result"] = {
        "run_id": state.run_id, "specimen_id": state.current_experiment_spec["specimen_id"],
        "slicer_result": {"ok": True, "estimated_mass_g": 10},
    }
    result = await AnalysisAgent().run(state, _CtxStub())
    assert result.success
    expected = 11.25 if end >= 15 else None
    analysis = result.data["analysis"]
    assert analysis["objective_score"] == expected
    assert result.data["bo_observation"]["objective_score"] == expected
    assert result.data["bo_observation"]["ok_for_bo"] is (end >= 15)
    assert result.data["bo_observation"]["observed_metrics"] == ({SEA_METRIC: expected} if end >= 15 else {})
    assert result.data["bo_handoff"]["objective"]["score"] == expected
    assert result.data["knowledge_payload"]["metrics"][SEA_METRIC] == expected
    evaluation = result.data["experiment_evaluation"]
    assert evaluation["objective_score"] == expected
    assert evaluation["objective"]["name"] == "Specific energy absorption to 50% compressive strain"
    assert result.data["bo_handoff"]["objective"]["name"] == evaluation["objective"]["name"]
    saved = json.loads(Path(analysis["analysis_artifacts"]["experiment_evaluation"]).read_text())
    assert saved["metrics"][SEA_METRIC] == expected


def test_current_utm_reference_separates_method_stop_from_analysis_interval():
    root = Path(__file__).resolve().parents[2]
    reference = root / "references/trapeziumx_v_equipment_agent"
    values = json.loads((reference / "manifest.json").read_text())["current_method_values"]
    assert values["contact_detection_load"]["value"] == 10
    endpoint = values["compression_endpoint"]
    assert endpoint["fixed"] is False
    assert "value" not in endpoint
    assert endpoint["minimum_measured_strain_for_analysis"] == 0.5
    assert endpoint["minimum_measured_travel_expression"] == "0.5 * initial_specimen_height_mm"
    assert "derived_target_stroke" not in values
    assert values["sea_evaluation_strain"] == 0.5
    assert values["pretest_inter_jig_distance"]["value"] == 32
    assert values["robot_entry_clearance"]["value"] == 150
    assert values["test_speed"]["value"] == 2
    assert values["test_speed"]["unit"] == "mm/min"
    assert "21 mm" not in (reference / "README_KR.md").read_text()
    assert "16 mm" not in (reference / "README_KR.md").read_text()
