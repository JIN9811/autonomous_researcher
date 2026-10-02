"""A recovered topic read must not mask active failures or block valid UTM evidence."""
from copy import deepcopy

import pytest

from orchestrator.state import Mode, OrchestratorState, Stage
from policies.guardian_gate import guardian_gate, gate_blocks_execution


CAPTURE_KEYS = ["raw_capture", "utm_clear_verification"]


def recovered_capture(capture_key="raw_capture"):
    capture = {
        "ok": True, "detected": True, "topic": "/camera/image_rect",
        "frame_capture": {
            "ok": True, "frame_available": True, "topic": "/camera/image_rect",
            "attempts": [
                {"ok": False, "topic": "/camera/image_raw", "failure_code": "ROS_IMAGE_TIMEOUT"},
                {"ok": True, "topic": "/camera/image_rect", "failure_code": ""},
            ],
        },
    }
    if capture_key == "utm_clear_verification":
        capture.update(purpose="utm_clear_verification", status="clear",
                       clear_confirmed=True, detected=False, registered=True)
    return {"observation": {capture_key: capture}}


def evaluate(payload):
    state = OrchestratorState(run_id="run-recovered", experiment_id="exp-recovered", mode=Mode.LIVE, stage=Stage.VISION)
    return guardian_gate(state=state, stage="vision", phase="post", payload=payload)


@pytest.mark.parametrize("capture_key", CAPTURE_KEYS)
def test_recovered_utm_frame_can_pass_guardian_without_rewriting_attempt_history(capture_key):
    payload = recovered_capture(capture_key)
    original = deepcopy(payload)
    result = evaluate(payload)
    assert not gate_blocks_execution(result)
    assert result["ok_for_next_stage"] is True
    assert not any(a["reason_code"] == "ROS_IMAGE_TIMEOUT" for a in result["alarms"])
    assert payload == original  # History remains available for diagnosis.


@pytest.mark.parametrize("invalid", ["capture_failed", "no_frame", "frame_failed", "wrong_topic", "no_success", "new_failure"])
@pytest.mark.parametrize("capture_key", CAPTURE_KEYS)
def test_unrecovered_or_mismatched_frame_attempt_still_blocks(invalid, capture_key):
    payload = recovered_capture(capture_key)
    capture = payload["observation"][capture_key]
    frame = capture["frame_capture"]
    if invalid == "capture_failed":
        capture["ok"] = False
    elif invalid == "no_frame":
        frame["frame_available"] = False
    elif invalid == "frame_failed":
        frame["ok"] = False
    elif invalid == "wrong_topic":
        frame["attempts"][-1]["topic"] = "/unrelated"
    elif invalid == "no_success":
        frame["attempts"].pop()
    else:
        frame["attempts"].append({"ok": False, "failure_code": "ROS_IMAGE_TIMEOUT"})
    assert gate_blocks_execution(evaluate(payload))


@pytest.mark.parametrize("location", ["outside", "current", "attempt"])
@pytest.mark.parametrize("capture_key", CAPTURE_KEYS)
def test_success_does_not_suppress_unrelated_or_current_failure(location, capture_key):
    payload = recovered_capture(capture_key)
    if location == "outside":
        payload["other_camera"] = {"ok": False, "failure_code": "ROS_IMAGE_TIMEOUT"}
    elif location == "current":
        payload["observation"][capture_key]["failure_code"] = "STOP_FAILED"
    else:
        payload["observation"][capture_key]["frame_capture"]["attempts"][0]["failure_code"] = "CAMERA_PORT_RELEASE_FAILED"
    assert gate_blocks_execution(evaluate(payload))


@pytest.mark.parametrize("recovered_key,failed_key", [
    ("raw_capture", "utm_clear_verification"),
    ("utm_clear_verification", "raw_capture"),
])
def test_recovered_capture_does_not_clear_another_capture_timeout(recovered_key, failed_key):
    payload = recovered_capture(recovered_key)
    failed = recovered_capture(failed_key)["observation"][failed_key]
    failed["frame_capture"]["ok"] = False
    failed["frame_capture"]["attempts"].pop()
    payload["observation"][failed_key] = failed
    gate = evaluate(payload)
    assert gate_blocks_execution(gate)
    assert any(a["source_path"] == f"payload.observation.{failed_key}.frame_capture.attempts[0]"
               and a["reason_code"] == "ROS_IMAGE_TIMEOUT" for a in gate["alarms"])


def test_real_clear_result_envelope_recovers_both_observation_and_stored_evidence():
    from utils.utm_clear_cycle import _result

    capture = recovered_capture("utm_clear_verification")["observation"]["utm_clear_verification"]
    execution = {"run_id": "run-recovered", "loop_id": 0, "specimen_id": "specimen-1",
                 "session_id": "clear-1", "state": "done", "success": True}
    payload = _result(execution, capture=capture).data
    original = deepcopy(payload)
    gate = evaluate(payload)
    assert not gate_blocks_execution(gate)
    assert payload == original


def test_failed_stored_capture_is_not_hidden_by_successful_observation():
    payload = recovered_capture("utm_clear_verification")
    stored = deepcopy(payload["observation"]["utm_clear_verification"])
    stored["frame_capture"]["attempts"].pop()
    stored["frame_capture"]["ok"] = False
    payload["utm_verification_2"] = {"record": {"evidence": stored}}
    assert gate_blocks_execution(evaluate(payload))
