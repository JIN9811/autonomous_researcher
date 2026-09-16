from copy import deepcopy
import pytest
from orchestrator.state import OrchestratorState, Stage
from app.equipment_selection_recovery import validate_selection_boundary


def fixture():
    state = OrchestratorState(run_id="r",experiment_id="e",stage=Stage.GUARDIAN,is_paused=True,
        current_experiment_spec={"specimen_id":"s"})
    scope = {"run_id":"r","loop_id":0,"specimen_id":"s"}
    state.run_metadata.update(manipulation_execution={**scope,"session_id":"robot","state":"done","success":True},
        utm_verifications={**scope,"verification_1":{"confirmed":True,"evidence":{
            "session_id":"robot","rollout_stopped":True,"rollout_stop_status":"STOPPED"}}})
    record={"identity":{"run_id":"r","experiment_id":"e","specimen_id":"s","sequence_id":"stacked-loop-0"},
        "lifecycle":"ESCALATED","events":[{"lifecycle":"RESOLVING"},{"lifecycle":"ESCALATED"}],
        "workflow_result":{"data":{"failure_code":"EQUIPMENT_WORKFLOW_SELECTION_REJECTED",
            "equipment_decisions":[{"phase":"select","request":{"tool":"request_operator"}}]}}}
    return state, record


def test_only_never_executed_selection_is_recoverable():
    state,record=fixture()
    validate_selection_boundary(state,record)


@pytest.mark.parametrize("fault",["executed","not_paused","wrong_run","not_stopped","unverified","estop"])
def test_rejects_unsafe_boundaries(fault):
    state,record=fixture()
    if fault=="executed": record["events"].append({"lifecycle":"EXECUTING"})
    if fault=="not_paused": state.is_paused=False
    if fault=="wrong_run": record["identity"]["run_id"]="old"
    if fault=="not_stopped": state.run_metadata["utm_verifications"]["verification_1"]["evidence"]["rollout_stopped"]=False
    if fault=="unverified": state.run_metadata["manipulation_execution"]["success"]=None
    if fault=="estop": state.emergency_stop_requested=True
    with pytest.raises(ValueError): validate_selection_boundary(state,record)


def test_display_preview_cannot_change_equipment_authority():
    from agents.equipment.workflow import _incoming_evidence
    state,_=fixture()
    state.run_metadata["utm_verifications"]["previews"]={"verification_1":{"confirmed":False,"status":"pending"}}
    evidence=_incoming_evidence(state)["records"]["utm_verifications"]["evidence"]
    assert "previews" not in evidence
    assert evidence["verification_1"]["confirmed"] is True
