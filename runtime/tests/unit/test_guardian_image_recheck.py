from copy import deepcopy

import pytest

from agents.core.guardian.agent import GuardianAgent
from orchestrator.state import OrchestratorState
from policies.guardian_gate_lifecycle import resolve_image_rechecks


def records():
    failed = dict(gate_id="failed", run_id="run", experiment_id="exp", loop_id=5,
                  stage="vision", phase="post", tool="", action="", audit_log={"check_scope": "utm_clearance"},
                  decision="safe_stop", reason_code="SYSTEM_SAFE_STOP_RECOMMENDED",
                  created_at="2026-09-19T03:11:40+00:00",
                  alarms=[{"reason_code": "ROS_IMAGE_TIMEOUT"}, {"reason_code": "SYSTEM_SAFE_STOP_RECOMMENDED"}])
    passed = {**failed, "gate_id": "passed", "decision": "allow", "reason_code": "OK",
              "alarms": [], "ok_for_next_stage": True, "created_at": "2026-09-19T03:30:40+00:00"}
    return [failed, deepcopy(passed)]


def test_successful_same_check_resolves_image_hold_without_erasing_audit():
    gates = records()
    incidents = [{"incident_id": "failed", "severity": "critical", "status": "open"}]
    state = OrchestratorState(run_id="run", experiment_id="exp", run_metadata={"guardian_gates": gates, "incident_records": incidents})
    result = GuardianAgent._resolve_graph_gate_pressure(state)
    assert result["status"] == "pass"
    assert state.run_metadata["guardian_gates"][0]["decision"] == "safe_stop"
    assert state.run_metadata["guardian_gates"][0]["audit_log"]["resolved_by"] == "passed"
    assert state.run_metadata["incident_records"][0]["status"] == "resolved"


@pytest.mark.parametrize("message,path", [
    ("UTM Vision runtime is not running; ROS frame capture was skipped.", "payload.observation.utm_clear_verification"),
    ("UTM_CLEAR_PENDING_TIMEOUT", "payload"),
])
def test_legacy_clearance_camera_holds_require_completed_same_work_proof(message, path):
    gates = records()
    gates[0]["alarms"] = [{"reason_code": "UTM_MACRO_MISMATCH", "message": message, "source_path": path}]
    attempt = {"work_id": "work", "specimen_id": "specimen", "task_id": "utm_clearance"}
    for gate in gates:
        gate["audit_log"]["agent_attempt"] = deepcopy(attempt)
    resolve_image_rechecks(gates, [])
    assert "resolved_by" not in gates[0]["audit_log"]
    gates[1]["audit_log"]["clearance_completion"] = {
        "run_id": "run", "loop_id": 5, "specimen_id": "specimen", "session_id": "clear",
        "verified": True}
    for changed in ("other_work", "other_specimen", "real_hazard"):
        negative = deepcopy(gates)
        if changed == "other_work": negative[1]["audit_log"]["agent_attempt"]["work_id"] = "other"
        elif changed == "other_specimen": negative[1]["audit_log"]["clearance_completion"]["specimen_id"] = "other"
        else: negative[0]["alarms"].append({"reason_code": "UTM_MACRO_MISMATCH", "message": "unsafe motion", "source_path": "payload"})
        resolve_image_rechecks(negative, [])
        assert "resolved_by" not in negative[0]["audit_log"]
    resolve_image_rechecks(gates, [])
    assert gates[0]["audit_log"]["resolved_by"] == "passed"


def test_clearance_completion_audit_requires_fresh_image_and_both_owner_reviews():
    from policies.guardian_gate import _clearance_completion_evidence
    state = OrchestratorState(run_id="run", experiment_id="exp", current_experiment_spec={"specimen_id": "s"})
    scope = {"run_id": "run", "loop_id": 0, "specimen_id": "s", "session_id": "clear"}
    accepted = {"status": "accepted", "scope_valid": True}
    payload = {"utm_clear_execution": {**scope, "state": "done", "success": True,
        "replay_execution_verified": True, "replay_completed_at": 100,
        "replay_evidence": {"ok": True, "follower_closed": True, "frames_sent": 10, "session_id": "clear"},
        "manipulation_result_decision": accepted},
        "utm_verification_2": {**scope, "record": {"confirmed": True, "status": "clear",
        "evidence": {"clear_confirmed": True, "detected": False, "frame_timestamp": 101,
                     "vision_decision": accepted}}}}
    assert _clearance_completion_evidence(payload, state, "vision", "post")["verified"] is True
    for mutation in ("old_frame", "unfinished", "rejected", "other_scope"):
        changed = deepcopy(payload)
        if mutation == "old_frame": changed["utm_verification_2"]["record"]["evidence"]["frame_timestamp"] = 99
        elif mutation == "unfinished": changed["utm_clear_execution"]["success"] = None
        elif mutation == "rejected": changed["utm_clear_execution"]["manipulation_result_decision"]["status"] = "rejected"
        else: changed["utm_verification_2"]["specimen_id"] = "other"
        assert not _clearance_completion_evidence(changed, state, "vision", "post")


@pytest.mark.parametrize("premature_cap", [False, True])
def test_completed_clearance_routes_to_guardian_reconciliation_not_recapture(monkeypatch, premature_cap):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app import run_recovery, safe_hot_reload, guardian_review_recovery
    from orchestrator.state import Stage
    import subprocess
    state = OrchestratorState(run_id="run", experiment_id="exp", stage=Stage.COMPLETE,
        run_metadata={"clearance_review_recovery": {"session_id": "clear"},
            "utm_clear_execution": {"success": True}, "guardian": {
                "reason": "Guardian graph-wide gate requested safe stop: SYSTEM_SAFE_STOP_RECOMMENDED"}})
    controller = SimpleNamespace(_state=state)
    if premature_cap:
        state.run_metadata.pop("utm_clear_execution")
        state.run_metadata["guardian_review_retry"] = {"status": "finished"}
        state.run_metadata["guardian"]["reason"] = "Test run reached planned 15-cycle loop cap."
    idle = Mock()
    monkeypatch.setattr(safe_hot_reload, "assert_idle", idle)
    monkeypatch.setattr(safe_hot_reload, "reload_sources", Mock())
    monkeypatch.setattr(subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    prepare = Mock(return_value={"status": "guardian_recheck_ready"})
    monkeypatch.setattr(guardian_review_recovery, "prepare", prepare)
    assert run_recovery.restore_checkpoint(controller, "run")["status"] == "guardian_recheck_ready"
    prepare.assert_called_once_with(controller)
    idle.assert_called_once_with(controller)


@pytest.mark.parametrize("patch", [
    {"run_id": "other"}, {"experiment_id": "other"}, {"loop_id": 6},
    {"audit_log": {"check_scope": "utm_placement"}}, {"phase": "pre"}, {"tool": "different"},
    {"decision": "allow_with_warning"}, {"ok_for_next_stage": False},
    {"created_at": "2026-09-19T03:00:00+00:00"},
])
def test_unrelated_or_nonpassing_gate_does_not_release_hold(patch):
    gates = records()
    gates[1].update(patch)
    resolve_image_rechecks(gates, [])
    assert "resolved_by" not in gates[0]["audit_log"]


def test_other_hazards_and_incomplete_projections_fail_closed():
    for mutate in (
        lambda gate: gate["alarms"].append({"reason_code": "COLLISION_RISK"}),
        lambda gate: gate["audit_log"].pop("check_scope"),
        lambda gate: gate.pop("gate_id"),
    ):
        gates = deepcopy(records())
        mutate(gates[0])
        resolve_image_rechecks(gates, [])
        assert "resolved_by" not in gates[0]["audit_log"]


def test_compact_projection_keeps_recheck_identity():
    from app.controller import MainController

    projected = MainController._compact_planning_run_metadata({"guardian_gates": records()})
    resolve_image_rechecks(projected["guardian_gates"], [])
    assert projected["guardian_gates"][0]["audit_log"]["resolved_by"] == "passed"


def test_archive_failure_summary_is_not_a_new_hazard_but_contract_failure_is():
    for path, resolved in (("payload.artifact_execution", True), ("payload.measurement_contract", False)):
        gates = records()
        gates[0]["alarms"].append({"reason_code": "CONTRACT_SCHEMA_INVALID", "source_path": path})
        resolve_image_rechecks(gates, [])
        assert (gates[0]["audit_log"].get("lifecycle") == "resolved") is resolved


@pytest.mark.asyncio
async def test_recovery_resumes_guardian_not_completed_physical_stages():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.guardian_review_recovery import resume_review
    from orchestrator.state import Stage

    state = OrchestratorState(run_id="run", experiment_id="exp", stage=Stage.COMPLETE, loop_count=6)
    state.run_metadata.update(guardian={"reason": "Guardian graph-wide gate requested safe stop: SYSTEM_SAFE_STOP_RECOMMENDED"},
        _planning_resume_context={"cycle_index": 6, "total_cycles": 20, "design_constraints": {"cell_size_bounds_mm": [5, 10]}},
        guardian_review_retry={"run_id": "run", "experiment_id": "exp", "cycle": 6, "status": "ready"})
    tasks = []
    controller = SimpleNamespace(_state=state, snapshot=lambda: {"is_running": False},
        _planning_handoff_active=lambda: False, _active_safety_sources=lambda: [],
        _error_resume_lock=asyncio.Lock(), _plc_service_start_rejection=AsyncMock(return_value=None),
        _run_planning_cycle_series=AsyncMock(), _set_planning_handoff_task=tasks.append,
        _emit_control_event=AsyncMock())
    result = await resume_review(controller)
    await tasks[0]
    assert result["resume_stage"] == "guardian"
    kwargs = controller._run_planning_cycle_series.call_args.kwargs
    assert kwargs["start_cycle"] == 6
    assert kwargs["resume_tail_stage"] == Stage.GUARDIAN
    assert state.loop_count == 5  # Guardian sees the same zero-based cycle, not the next one.
    state.emergency_stop_requested = True
    with pytest.raises(ValueError, match="safety controls"):
        await resume_review(controller)


def test_guardian_recheck_premature_cap_requires_matching_finished_recovery():
    from types import SimpleNamespace
    from app.guardian_review_recovery import validate_boundary
    from orchestrator.state import Stage
    state = OrchestratorState(run_id="run", experiment_id="exp", stage=Stage.COMPLETE, loop_count=14,
        current_experiment_spec={"specimen_id": "s14"}, run_metadata={
            "guardian": {"reason": "Test run reached planned 15-cycle loop cap."},
            "_planning_resume_context": {"cycle_index": 14, "total_cycles": 15, "current_spec": {"specimen_id": "s14"}},
            "guardian_review_retry": {"run_id": "run", "experiment_id": "exp", "cycle": 14, "status": "finished"}})
    controller = SimpleNamespace(_state=state, snapshot=lambda: {"is_running": False},
        _planning_handoff_active=lambda: False, _active_safety_sources=lambda: [])
    assert validate_boundary(controller) == ("run", "exp", 14)
    state.run_metadata["guardian_review_retry"]["cycle"] = 13
    with pytest.raises(ValueError): validate_boundary(controller)


def test_legacy_projection_reconciliation_requires_unique_matching_audit(tmp_path):
    import json
    from app.guardian_review_recovery import reconciled_gates
    from app.controller import MainController

    gates = records()
    projected = [{key: gate[key] for key in ("stage", "phase", "decision", "reason_code", "created_at")}
                 for gate in gates]
    state = OrchestratorState(run_id="run", experiment_id="exp", run_metadata={"guardian_gates": projected})
    path = tmp_path / "structured.jsonl"
    path.write_text("\n".join(json.dumps({"payload": {"guardian_gate": gate, "utm_verification_2": {"ok": True}}}) for gate in gates))
    repaired, _ = reconciled_gates(state, path)
    assert repaired[0]["audit_log"]["resolved_by"] == "passed"
    # The original live state is not changed by proof preparation.
    assert "gate_id" not in state.run_metadata["guardian_gates"][0]
    path.write_text("")
    with pytest.raises(ValueError, match="lacks a proven"):
        reconciled_gates(state, path)


def test_log_reconstruction_does_not_undo_already_audited_resolution(tmp_path):
    import json
    from app.guardian_review_recovery import reconciled_gates
    gates = records()
    historical = deepcopy(gates[0])
    historical.update(gate_id="equipment-old", stage="equipment")
    persisted = deepcopy(historical)
    persisted["audit_log"].update(lifecycle="resolved", resolved_by="equipment-revalidated", resolution="archived_completion_verified")
    state = OrchestratorState(run_id="run", experiment_id="exp",
        run_metadata={"guardian_gates": [persisted, *gates]})
    path = tmp_path / "structured.jsonl"
    path.write_text("\n".join(json.dumps({"payload": {"guardian_gate": gate}}) for gate in [historical, *gates]))
    repaired, _ = reconciled_gates(state, path)
    assert repaired[0]["audit_log"]["resolved_by"] == "equipment-revalidated"
