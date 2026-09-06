"""Display lifecycle only: no printer, camera, or downstream agent execution."""
import pytest

from orchestrator.state import AgentRuntimeStatus, Stage
from tests.unit.test_runtime_recovery_and_manipulation_status import ResultAgent, runtime_fixture


def specimen_data():
    return {"specimen_result": {
        "ok": True, "specimen_id": "specimen-1", "printer_path": "installed_printer",
        "print_result": {"status": "started"},
        "fabrication_report": {"fabrication_outcome": {
            "status": "ready_for_vision", "requires_after_print_confirmation": True,
        }},
    }}


def vision_data(confirmed=True):
    return {
        "observation": {"spc_autoejection_confirmation": {
            "confirmed": confirmed, "status": "confirmed" if confirmed else "not_confirmed",
        }},
        "vision_signal": {"run_id": "run-lifecycle", "loop_id": "loop-0", "specimen_id": "specimen-1"},
        "transition_decision": "vision_manipulation_handoff" if confirmed else "vision_active_cam_monitoring",
    }


@pytest.fixture(params=["runtime", "controller"])
def lifecycle(tmp_path, request):
    runtime, state, _ = runtime_fixture(tmp_path, stage=Stage.SPECIMEN)
    state.agent_status["specimen_agent"] = AgentRuntimeStatus(state="idle", success=True, mode="test")
    if request.param == "runtime":
        merge = runtime._merge_agent_data
    else:
        from app.controller import MainController
        controller = MainController.__new__(MainController)
        controller._state = state
        merge = controller._merge_planning_agent_data
    return state, merge


def test_submit_is_running_until_matching_active_cam_verification(lifecycle):
    state, merge = lifecycle
    state.latest_observations = vision_data()["observation"]
    merge(Stage.SPECIMEN, specimen_data())
    assert state.agent_status["specimen_agent"].state == "running"
    assert state.agent_status["specimen_agent"].success is None
    merge(Stage.VISION, vision_data())
    assert state.agent_status["specimen_agent"].state == "done"
    assert state.agent_status["specimen_agent"].success is True
    assert state.run_metadata["specimen_execution"]["loop_id"] == 0


@pytest.mark.parametrize("key,value", [("run_id", "other"), ("loop_id", "loop-1"), ("loop_id", None), ("specimen_id", "other")])
def test_other_or_unscoped_vision_cannot_finish_current_specimen(lifecycle, key, value):
    state, merge = lifecycle
    merge(Stage.SPECIMEN, specimen_data())
    data = vision_data()
    data["vision_signal"][key] = value
    merge(Stage.VISION, data)
    assert state.agent_status["specimen_agent"].state == "running"
    assert state.agent_status["specimen_agent"].success is None


def test_new_active_cam_failure_revokes_done_but_utm_pass_does_not(lifecycle):
    state, merge = lifecycle
    merge(Stage.SPECIMEN, specimen_data())
    merge(Stage.VISION, vision_data())
    utm = vision_data(False)
    utm["transition_decision"] = "vision_equipment_handoff"
    merge(Stage.VISION, utm)
    assert state.agent_status["specimen_agent"].state == "done"
    merge(Stage.VISION, vision_data(False))
    assert state.agent_status["specimen_agent"].state == "running"
    assert state.agent_status["specimen_agent"].success is None


def test_new_specimen_call_does_not_reuse_earlier_confirmation(lifecycle):
    state, merge = lifecycle
    merge(Stage.SPECIMEN, specimen_data())
    merge(Stage.VISION, vision_data())
    merge(Stage.SPECIMEN, specimen_data())
    assert state.agent_status["specimen_agent"].state == "running"
    assert state.run_metadata["specimen_execution"]["success"] is None


@pytest.mark.parametrize("outcome", ["virtual_finished", "preflight_complete"])
def test_virtual_and_preflight_keep_original_completion_semantics(lifecycle, outcome):
    state, merge = lifecycle
    state.run_metadata["specimen_execution"] = {"state": "running", "loop_id": 0}
    data = specimen_data()
    data["specimen_result"]["fabrication_report"]["fabrication_outcome"].update(
        status=outcome, requires_after_print_confirmation=False,
    )
    merge(Stage.SPECIMEN, data)
    assert "specimen_execution" not in state.run_metadata
    assert state.agent_status["specimen_agent"].success is True


def test_live_snapshot_preserves_scoped_specimen_lifecycle():
    from app.controller import MainController
    execution = {"run_id": "run-lifecycle", "loop_id": 0, "specimen_id": "specimen-1", "state": "running", "success": None}
    assert MainController._compact_planning_run_metadata({"specimen_execution": execution}).get("specimen_execution") == execution


@pytest.mark.asyncio
async def test_actual_runtime_step_keeps_existing_vision_route_and_reports_running(tmp_path):
    runtime, state, events = runtime_fixture(tmp_path, stage=Stage.SPECIMEN,
        agent=ResultAgent("specimen_agent", specimen_data()))
    await runtime.step()
    assert state.stage == Stage.VISION
    assert state.agent_status["specimen_agent"].state == "running"
    result = next(e for e in events if e["event_type"] == "agent_result")
    assert result["payload"]["status"] == "running"


@pytest.mark.asyncio
async def test_failed_specimen_call_emits_error_not_running_or_done(tmp_path):
    runtime, state, events = runtime_fixture(tmp_path, stage=Stage.SPECIMEN,
        agent=ResultAgent("specimen_agent", specimen_data(), success=False))
    state.current_experiment_spec["printer_test_path"] = "installed_printer"
    await runtime.step()
    assert state.agent_status["specimen_agent"].state == "error"
    assert state.agent_status["specimen_agent"].success is False
    assert state.run_metadata["specimen_execution"]["state"] == "error"
    result = next(e for e in events if e["event_type"] == "agent_result")
    assert result["payload"]["status"] == "error"
    runtime._merge_agent_data(Stage.VISION, vision_data())
    assert state.agent_status["specimen_agent"].state == "error"


def test_conflicting_active_cam_details_do_not_complete_spc(lifecycle):
    state, merge = lifecycle
    merge(Stage.SPECIMEN, specimen_data())
    data = vision_data()
    data["observation"]["active_cam_ejection_check"] = {"status": "blocked", "spc_autoejection_confirmed": False}
    merge(Stage.VISION, data)
    assert state.agent_status["specimen_agent"].state == "running"


def test_numeric_loop_identity_and_expired_historical_completion_remain_valid(lifecycle):
    state, merge = lifecycle
    merge(Stage.SPECIMEN, specimen_data())
    data = vision_data()
    data["vision_signal"].update(loop_id=0, expires_at="2000-01-01T00:00:00Z")
    merge(Stage.VISION, data)
    # Historical completion display must not reapply freshness gates for motion.
    assert state.agent_status["specimen_agent"].state == "done"
