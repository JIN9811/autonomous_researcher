"""Live refresh compaction must retain measured candidate evidence, not raw curves."""
from app.bootstrap import load_runtime


def test_compact_display_retains_all_cycle_scores_and_their_units():
    evaluations = [
        {"run_id": "run-current", "candidate_id": f"specimen-{index}", "source": "analysis_agent",
         "ok": True, "objective_score": index, "fidelity": "utm_high",
         "objective": {"metric_name": "specific_energy_absorption_J_per_g", "unit": "J/g",
                       "constraints": {"large": [0] * 10000}},
         "metrics": {"cell_size_mm": 5 + index / 10, "wall_thickness_mm": 0.8},
         "raw_curve": [0] * 10000}
        for index in range(8)
    ]
    compact = load_runtime()._compact_planning_state_for_display({
        "run_id": "run-current", "experiment_evaluations": evaluations,
    })
    assert len(compact["experiment_evaluations"]) == 8
    first = compact["experiment_evaluations"][0]
    assert first["objective_score"] == 0
    assert first["source"] == "analysis_agent"
    assert first["run_id"] == "run-current"
    assert first["objective"] == {"metric_name": "specific_energy_absorption_J_per_g", "unit": "J/g"}
    assert first["parameters"] == {"cell_size_mm": 5, "wall_thickness_mm": 0.8}
    assert "raw_curve" not in first
    assert "constraints" not in first["objective"]
