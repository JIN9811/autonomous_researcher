import pytest

from orchestrator.cycle_progress import record_guardian_completion
from orchestrator.state import OrchestratorState


@pytest.mark.parametrize("before", [5, 6, 7])
def test_guardian_completion_is_same_cycle_even_on_recheck_or_legacy_drift(before):
    state = OrchestratorState(run_id="run", experiment_id="exp", loop_count=before, current_experiment_spec={"specimen_id": "six"},
        run_metadata={"_planning_resume_context": {"kind": "planning_cycle_series",
            "phase": "tail", "cycle_index": 6, "current_spec": {"specimen_id": "six"}}})
    record_guardian_completion(state)
    assert state.loop_count == 6
    record_guardian_completion(state)
    assert state.loop_count == 6


def test_non_planning_loop_and_mismatched_context_keep_existing_counter():
    state = OrchestratorState(run_id="run", experiment_id="exp", loop_count=5, current_experiment_spec={"specimen_id": "six"})
    record_guardian_completion(state)
    assert state.loop_count == 6
    state.run_metadata["_planning_resume_context"] = {"kind": "planning_cycle_series",
        "phase": "tail", "cycle_index": 2, "current_spec": {"specimen_id": "other"}}
    record_guardian_completion(state)
    assert state.loop_count == 7


def test_display_preserves_small_authoritative_cycle_without_private_spec():
    from app.controller import MainController
    projection = MainController._compact_planning_run_metadata({"_planning_resume_context": {
        "kind": "planning_cycle_series", "cycle_index": 7, "total_cycles": 20,
        "phase": "specimen", "current_spec": {"large": "payload"}}})
    assert projection["planning_resume_context"] == {
        "kind": "planning_cycle_series", "cycle_index": 7, "total_cycles": 20, "phase": "specimen"}
