from copy import deepcopy
from types import SimpleNamespace
import pytest
from orchestrator.state import Stage
from utils.vision_polling import placement_poll_pending, vision_poll_pending, quiet_vision_poll_event


def fixture():
    scope = dict(run_id="r", loop_id=0, specimen_id="s")
    return SimpleNamespace(stage=Stage.VISION, run_id="r", loop_count=0,
        current_experiment_spec={"specimen_id":"s"}, run_metadata={
            "manipulation_execution": {**scope,"session_id":"robot","state":"running"},
            "utm_verifications": {**scope,"verification_1":{"evidence":{
                **scope,"session_id":"robot","status":"waiting","detected":False}}}})


def test_repeated_placement_wait_does_not_become_ordinary_work():
    state=fixture()
    assert all(placement_poll_pending(state) for _ in range(100))


@pytest.mark.parametrize("key,value", [("run_id","old"),("loop_id",1),("specimen_id","old"),
    ("session_id","old"),("status","failed"),("detected",True)])
def test_other_scope_or_terminal_evidence_is_not_exempt(key,value):
    state=fixture()
    state.run_metadata["utm_verifications"]["verification_1"]["evidence"][key]=value
    assert not placement_poll_pending(state)


def test_completed_or_missing_execution_is_not_exempt():
    state=fixture()
    state.run_metadata["manipulation_execution"]["state"]="done"
    assert not placement_poll_pending(state)


@pytest.mark.parametrize("kind", ["node.started", "node.completed", "orchestrator.followup"])
def test_poll_chat_is_quiet_but_success_and_errors_visible(kind):
    state=fixture()
    event={"type":kind,"payload":{"node_id":"vision"}}
    assert quiet_vision_poll_event(state,event)
    event["payload"]["requires_response"]=True
    assert not quiet_vision_poll_event(state,event)
    event["payload"].pop("requires_response")
    event["level"]="ERROR"
    assert not quiet_vision_poll_event(state,event)
    event.pop("level")
    state.run_metadata["manipulation_execution"]["state"]="done"
    assert not quiet_vision_poll_event(state,event)


def test_replay_followup_poll_is_exempt_without_legacy_deadline_field():
    state=fixture()
    state.run_metadata={"utm_clear_execution":dict(run_id="r",loop_id=0,
        specimen_id="s",session_id="replay",state="waiting",replay_execution_verified=True)}
    assert all(vision_poll_pending(state) for _ in range(100))
    assert quiet_vision_poll_event(state,{"type":"node.completed","payload":{"node_id":"vision"}})
    state.run_metadata["utm_clear_execution"]["state"]="done"
    assert not vision_poll_pending(state)
    state.run_metadata["utm_clear_execution"].update(state="waiting",run_id="old")
    assert not vision_poll_pending(state)
    state.run_metadata.clear()
    assert not placement_poll_pending(state)
