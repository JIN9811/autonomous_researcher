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
    state.emergency_stop_requested = True
    with pytest.raises(ValueError, match="safety controls"):
        await resume_review(controller)


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
