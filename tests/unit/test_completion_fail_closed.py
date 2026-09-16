"""Offline regressions: availability and acceptance are not task completion."""
import pytest

from app.controller import MainController as AppController
from agents.specimen.agent import SpecimenMakingAgent
from agents.bo.agent import BOAgent
from orchestrator.state import OrchestratorState
from utils.specimen_execution import current_printer_execution_verified


@pytest.mark.parametrize("state", ["IDLE", "READY", "COMMUNICATION_READY", "RUNNING"])
def test_non_terminal_printer_states_never_complete_even_at_100_percent(state):
    result = AppController._classify_specimen_printer_completion_status(
        {"ok": True, "device_screen": {"progress_panel": {
            "state": state, "job_name": "current", "progress_percent": 100,
        }}}, started_seen=True, expected_job_names=("current",))
    assert result["status"] != "complete"


@pytest.mark.parametrize("started,job", [(False, "current"), (True, ""), (True, "current-old")])
def test_finish_requires_observed_start_and_exact_job(started, job):
    result = AppController._classify_specimen_printer_completion_status(
        {"ok": True, "device_screen": {"progress_panel": {
            "state": "FINISH", "job_name": job, "progress_percent": 100,
        }}}, started_seen=started, expected_job_names=("current",))
    assert result["status"] != "complete"


def test_specimen_does_not_rewrite_agreed_wall_or_cell():
    spec = {"geometry_type": "gyroid", "wall_thickness_mm": 0.87321, "cell_size_mm": 7.12345}
    result = SpecimenMakingAgent._enforce_fdm_gyroid_hard_rules(spec)
    assert all(result[key] == value for key, value in spec.items())
    assert 0 < result["relative_density"] < 1
    assert "relative_density" not in spec


@pytest.mark.parametrize("wall", [0, -1, float("nan"), float("inf"), "invalid"])
def test_invalid_wall_is_rejected_not_substituted(wall):
    with pytest.raises(ValueError):
        SpecimenMakingAgent._enforce_fdm_gyroid_hard_rules({
            "geometry_type": "gyroid", "wall_thickness_mm": wall, "cell_size_mm": 5})


def test_missing_analysis_approval_never_becomes_bo_training_score():
    state = OrchestratorState(run_id="r", experiment_id="e", active_goal="test")
    state.latest_analysis = {"bo_handoff": {
        "parameters": {"cell_size_mm": 7.5, "relative_density": 0.3},
        "metrics": {"energy_density_50pct_MJ_per_m3": 0.1},
        "objective": {"metric_name": "energy_density_50pct_MJ_per_m3"},
    }}
    records = BOAgent._analysis_handoff_records(state)
    assert records and records[0]["ok_for_bo"] is False
    assert "score" not in records[0]


@pytest.mark.parametrize("changed", [None, "run_id", "loop_id", "specimen_id", "status", "completion_scope"])
def test_physical_vision_requires_current_printer_receipt(changed):
    state = OrchestratorState(run_id="r", experiment_id="e", active_goal="test",
                              current_experiment_spec={"specimen_id": "s"})
    receipt = {"run_id": "r", "loop_id": state.loop_count, "specimen_id": "s",
               "status": "complete", "completion_scope": "printer_job_only"}
    if changed:
        receipt[changed] = "wrong"
    assert current_printer_execution_verified(state, {
        "printer_path": "installed_printer", "printer_completion_wait": receipt}) is (changed is None)


def test_physical_vision_does_not_accept_unscoped_done_flag():
    state = OrchestratorState(run_id="r", experiment_id="e", active_goal="test")
    assert not current_printer_execution_verified(state, {
        "printer_path": "installed_printer", "printer_completion_verified": True})
