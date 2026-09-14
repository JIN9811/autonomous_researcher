"""Latest same-session execution evidence outranks the launch snapshot."""
import pytest
from agents.vision.agent import VisionAgent
from orchestrator.state import OrchestratorState


@pytest.mark.parametrize("phase", ["ACTION_ACTIVE", "ACTION_STOPPED", "STOPPED", "COMPLETED"])
def test_latest_session_counter_replaces_launch_zero(phase):
    state = OrchestratorState(run_id="r", experiment_id="e", run_metadata={"manipulation_result": {
        "session_id": "current", "workflow": "rollout", "runtime_phase": "PROCESS_STARTED",
        "execution_evidence": {"required": True, "observed": False, "action_count": 0}}})
    status = {"ok": True, "session_id": "current", "runtime": {"phase": phase, "action_count": 42}}
    evidence = VisionAgent._rollout_execution_evidence(state, status)
    assert evidence["observed"] is True
    assert evidence["action_count"] == 42


@pytest.mark.parametrize("session,ok", [("foreign", True), ("current", False)])
def test_foreign_or_failed_status_cannot_prove_execution(session, ok):
    state = OrchestratorState(run_id="r", experiment_id="e", run_metadata={"manipulation_result": {
        "session_id": "current", "workflow": "rollout"}})
    result = VisionAgent._rollout_execution_evidence(state, {
        "ok": ok, "session_id": session, "runtime": {"phase": "ACTION_ACTIVE", "action_count": 42}})
    assert result["observed"] is False
