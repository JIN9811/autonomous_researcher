"""A validated same-work retry retires software failures, never safety evidence."""

from copy import deepcopy

import pytest

from agents.core.guardian.agent import GuardianAgent
from orchestrator.state import OrchestratorState, Stage
from policies import guardian_gate_lifecycle as lifecycle


def records(stage="bo"):
    attempt = {"schema": "guardian_agent_attempt.v1", "work_id": "work-a", "attempt_id": "attempt-1", "specimen_id": "s1"}
    failed = {
        "gate_id": "failed", "run_id": "run", "experiment_id": "exp", "loop_id": 12,
        "stage": stage, "phase": "post", "agent": f"{stage}_agent", "tool": "", "action": "",
        "decision": "block", "reason_code": "AGENT_RESULT_FAILED", "created_at": "2026-09-26T01:00:00+00:00",
        "audit_log": {"agent_attempt": attempt},
        "alarms": [{"reason_code": "AGENT_RESULT_FAILED", "source_path": "payload"}],
        "corrective_actions": [{"action_id": "failed-ca-1", "status": "open"}],
        "incident_records": [{"incident_id": "failed", "status": "open"}],
    }
    exception = {**deepcopy(failed), "gate_id": "exception", "phase": "exception", "reason_code": "VALUEERROR",
                 "alarms": [{"reason_code": "VALUEERROR", "source_path": "payload"}],
                 "created_at": "2026-09-26T01:00:01+00:00", "corrective_actions": [], "incident_records": []}
    new = {**attempt, "attempt_id": "attempt-2"}
    passed = {**deepcopy(failed), "gate_id": "passed", "decision": "allow", "reason_code": "OK", "alarms": [],
              "created_at": "2026-09-26T01:01:00+00:00", "ok_for_next_stage": True,
              "audit_log": {"agent_attempt": new, "agent_completion": {**new, "validated": True, "success": True, "status": "completed"}},
              "corrective_actions": [], "incident_records": []}
    return [failed, exception, passed]


@pytest.mark.parametrize("stage", ["design", "specimen", "vision", "manipulation", "equipment", "analysis", "bo", "knowledge", "guardian", "extension"])
def test_validated_retry_resolves_same_work_failures_and_linked_records(stage):
    gates = records(stage)
    incidents = [{"incident_id": "failed", "status": "open"}, {"incident_id": "exception", "status": "open"}, {"incident_id": "unrelated", "status": "open"}]
    actions = [{"action_id": "failed-ca-1", "status": "open"}, {"action_id": "unrelated-ca-1", "status": "open"}]
    lifecycle.resolve_completed_retries(gates, incidents, actions)
    assert len(gates) == 3 and gates[0]["decision"] == "block"
    assert [gate["audit_log"].get("resolved_by") for gate in gates] == ["passed", "passed", None]
    assert [incident["status"] for incident in incidents] == ["resolved", "resolved", "open"]
    assert [action["status"] for action in actions] == ["resolved", "open"]
    assert gates[0]["incident_records"][0]["status"] == "resolved"
    assert gates[0]["corrective_actions"][0]["status"] == "resolved"
    assert gates[0]["audit_log"]["resolution_evidence"]["attempt_id"] == "attempt-2"


@pytest.mark.parametrize("field,value", [("run_id", "other"), ("experiment_id", "other"), ("loop_id", 13), ("stage", "analysis"), ("agent", "other_agent"), ("tool", "tool"), ("phase", "pre"), ("decision", "modify"), ("ok_for_next_stage", False), ("created_at", "2026-09-26T00:00:00+00:00")])
def test_wrong_scope_or_nonpassing_completion_cannot_resolve(field, value):
    gates = records(); gates[-1][field] = value
    lifecycle.resolve_completed_retries(gates, [], [])
    assert "resolved_by" not in gates[0]["audit_log"]


@pytest.mark.parametrize("field,value", [("work_id", "other"), ("specimen_id", "s2"), ("attempt_id", "attempt-1"), ("validated", False), ("success", False), ("status", "running"), ("status", "waiting"), ("status", "progress")])
def test_incomplete_or_mismatched_proof_never_releases(field, value):
    gates = records(); gates[-1]["audit_log"]["agent_completion"][field] = value
    lifecycle.resolve_completed_retries(gates, [], [])
    assert "resolved_by" not in gates[0]["audit_log"]


@pytest.mark.parametrize("hazard", ["EMERGENCY_STOP", "SYSTEM_SAFE_STOP_RECOMMENDED", "HUMAN_APPROVAL_REQUIRED", "COLLISION_RISK", "BAMBU_MQTT_UNAVAILABLE", "UTM_CLEARANCE_REQUIRED"])
def test_completed_software_retry_does_not_clear_hazard(hazard):
    gates = records(); gates[0]["alarms"].append({"reason_code": hazard, "source_path": "payload"})
    lifecycle.resolve_completed_retries(gates, [], [])
    assert "resolved_by" not in gates[0]["audit_log"]


@pytest.mark.parametrize("decision", ["safe_stop", "require_human_approval"])
def test_stop_and_approval_decisions_never_auto_resolve(decision):
    gates = records(); gates[0]["decision"] = decision
    lifecycle.resolve_completed_retries(gates, [], [])
    assert "resolved_by" not in gates[0]["audit_log"]


def test_allow_without_runtime_completion_is_not_evidence():
    gates = records(); gates[-1]["audit_log"].pop("agent_completion")
    lifecycle.resolve_completed_retries(gates, [], [])
    assert "resolved_by" not in gates[0]["audit_log"]


def test_pressure_projects_verified_completion_without_mutating_saved_history():
    state = OrchestratorState(run_id="run", experiment_id="exp", loop_count=12,
                              run_metadata={"guardian_gates": records()})
    before = deepcopy(state.run_metadata)
    assert GuardianAgent._resolve_graph_gate_pressure(state)["active_gate_count"] == 0
    assert state.run_metadata == before


def test_bo_invalid_decision_wrapper_is_software_only_with_exact_candidate_evidence():
    gates = records()
    for gate in gates:
        gate["audit_log"]["agent_attempt"]["candidate_id"] = "candidate-13"
    gates[-1]["audit_log"]["agent_completion"]["candidate_id"] = "candidate-13"
    gates[0]["alarms"].extend([
        {"reason_code": "BO_CANDIDATE_UNSAFE", "message": "BO_DECISION_INVALID", "source_path": "payload.bo_result"},
        {"reason_code": "CONTRACT_SCHEMA_INVALID", "message": "blocked", "source_path": "payload.bo_result.next_design_request"},
        {"reason_code": "CONTRACT_SCHEMA_INVALID", "message": "failed", "source_path": "payload.artifact_execution"},
    ])
    lifecycle.resolve_completed_retries(gates, [], [])
    assert gates[0]["audit_log"]["resolved_by"] == "passed"


@pytest.mark.parametrize("candidate,message", [("", "BO_DECISION_INVALID"), ("other", "BO_DECISION_INVALID"), ("candidate-13", "Unsafe cell geometry")])
def test_real_bo_candidate_hazard_or_missing_candidate_binding_remains_active(candidate, message):
    gates = records()
    gates[0]["audit_log"]["agent_attempt"]["candidate_id"] = "candidate-13"
    gates[-1]["audit_log"]["agent_attempt"]["candidate_id"] = candidate
    gates[-1]["audit_log"]["agent_completion"]["candidate_id"] = candidate
    gates[0]["alarms"].append({"reason_code": "BO_CANDIDATE_UNSAFE", "message": message, "source_path": "payload.bo_result"})
    lifecycle.resolve_completed_retries(gates, [], [])
    assert "resolved_by" not in gates[0]["audit_log"]


@pytest.mark.parametrize("payload", [{"status": "running"}, {"pending_operator_input": True}, {"artifact_execution": {"status": "waiting"}}, {"bo_result": {"status": "progress"}}, {"requires_human_approval": True}, {"status": "failed"}, {"guardian": {"action": "recover"}}, {"observation": {"status": "waiting"}}, {"analysis": {"status": "running"}}])
def test_completion_attestation_rejects_weak_success_payload(payload):
    passed = records()[-1]; passed["audit_log"].pop("agent_completion")
    lifecycle.complete_agent_attempt(passed, payload)
    assert "agent_completion" not in passed["audit_log"]


def test_linked_record_with_conflicting_explicit_scope_is_not_resolved():
    gates = records()
    incidents = [{"incident_id": "failed", "run_id": "other", "status": "open"}]
    actions = [{"action_id": "failed-ca-1", "loop_id": 13, "status": "open"}]
    lifecycle.resolve_completed_retries(gates, incidents, actions)
    assert incidents[0]["status"] == "open" and actions[0]["status"] == "open"


def test_attempt_identity_is_frozen_and_ignores_volatile_session():
    state = OrchestratorState(run_id="run", experiment_id="exp", active_goal="same work", current_experiment_spec={"specimen_id": "s1", "candidate_id": "c1"})
    first = lifecycle.new_agent_attempt(state, "attempt-1")
    state.active_session_id = "new-rollout-session"
    second = lifecycle.new_agent_attempt(state, "attempt-2")
    assert first["work_id"] == second["work_id"] and first["attempt_id"] != second["attempt_id"]
    state.current_experiment_spec["specimen_id"] = "s2"
    third = lifecycle.new_agent_attempt(state, "attempt-3")
    assert first["specimen_id"] == "s1" and first["work_id"] != third["work_id"]


def test_manipulation_transfer_and_disposal_are_different_work():
    state = OrchestratorState(run_id="run", experiment_id="exp", stage=Stage.MANIPULATION,
                              current_experiment_spec={"specimen_id": "s1"})
    transfer = lifecycle.new_agent_attempt(state, "attempt-1")
    state.run_metadata["equipment_result"] = {"status": "completed"}
    disposal = lifecycle.new_agent_attempt(state, "attempt-2")
    assert transfer["work_id"] != disposal["work_id"]


def test_vision_pickup_placement_and_clearance_are_different_work():
    state = OrchestratorState(run_id="run", experiment_id="exp", stage=Stage.VISION,
                              current_experiment_spec={"specimen_id": "s1"})
    pickup = lifecycle.new_agent_attempt(state, "attempt-1")
    state.run_metadata["robot_task_result"] = {"run_id": "run", "specimen_id": "s1", "handoff_status": "needs_post_place_vision"}
    placement = lifecycle.new_agent_attempt(state, "attempt-2")
    state.run_metadata["utm_clear_execution"] = {"run_id": "run", "loop_id": 0, "specimen_id": "s1"}
    clearance = lifecycle.new_agent_attempt(state, "attempt-3")
    assert len({pickup["work_id"], placement["work_id"], clearance["work_id"]}) == 3


def test_bo_work_uses_actual_objective_not_legacy_candidate_constraint_cache():
    state = OrchestratorState(run_id="run", experiment_id="exp", stage=Stage.BO,
        current_experiment_spec={"specimen_id": "s1", "candidate_id": "c1", "constraints": {"max_mass_g": 50}},
        current_experiment_objective={"objective_id": "sea", "direction": "maximize", "constraints": {"cell_size_mm": 5, "wall_thickness_mm": 1, "relative_density": .2}},
        run_metadata={"bo_settings": {"parameter_space": {"cell_size_mm": [4, 5], "wall_thickness_mm": [1, 2]}}})
    before = lifecycle.new_agent_attempt(state, "attempt-1")
    state.current_experiment_objective["constraints"].update(cell_size_mm=6, wall_thickness_mm=2, relative_density=.3)
    retry = lifecycle.new_agent_attempt(state, "attempt-2")
    assert before["work_id"] == retry["work_id"]
    state.run_metadata["bo_settings"]["parameter_space"].update(orientation_deg=[0], anisotropy_ratio=[1])
    normalized_retry = lifecycle.new_agent_attempt(state, "attempt-2-normalized")
    assert retry["work_id"] == normalized_retry["work_id"]
    state.run_metadata["bo_settings"]["parameter_space"]["cell_size_mm"] = [6, 7]
    changed_request = lifecycle.new_agent_attempt(state, "attempt-3")
    assert retry["work_id"] != changed_request["work_id"]


@pytest.mark.parametrize("payload", [
    {"manipulation": {"status": "execution_ready_pending_approval"}},
    {"robot_task_result": {"status": "warning", "handoff_status": "execution_ready_pending_approval", "completion_status": "preflight_complete"}},
    {"robot_task_result": {"status": "warning", "handoff_status": "needs_post_place_vision", "completion_status": "reported_complete"}},
    {"handoff_packet": {"execution": {"status": "waiting"}}},
])
def test_physical_preflight_or_unverified_handoff_is_not_completed_work(payload):
    passed = records("manipulation")[-1]; passed["audit_log"].pop("agent_completion")
    lifecycle.complete_agent_attempt(passed, payload)
    assert "agent_completion" not in passed["audit_log"]


def test_bo_accepted_decision_and_ready_handoff_are_completed_not_benchmark_history():
    passed = records()[-1]; passed["audit_log"].pop("agent_completion")
    payload = {"bo_result": {"ok": True, "decision": {"schema": "bo_decision.v1", "status": "accepted",
        "trace": [{"result": {"status": "accepted"}}]}, "next_design_request": {"status": "ready"},
        "benchmark": {"strategies": {"bo": {"results": [{"status": "failed", "ok": False}]}}}}}
    lifecycle.complete_agent_attempt(passed, payload)
    assert passed["audit_log"]["agent_completion"]["status"] == "completed"
    passed["audit_log"].pop("agent_completion")
    lifecycle.complete_agent_attempt(passed, {"artifact_execution": {"status": "accepted"}})
    assert "agent_completion" not in passed["audit_log"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("handoff_no_external")
async def test_common_runtime_completion_hook_retires_prior_failed_attempt(tmp_path):
    from agents.base_agent import AgentResult
    from tests.unit.test_langgraph_runtime import _retry_test_loop
    from tests.unit.test_guardian_agent import _valid_spec
    loop, state, design, events = _retry_test_loop(tmp_path, module_retry={"max_attempts": 1, "backoff_s": 0}, global_max_retry=1)
    state.current_experiment_spec = _valid_spec()
    await loop.step()
    assert GuardianAgent._resolve_graph_gate_pressure(state)["active_gate_count"] == 1

    async def successful_retry(state, ctx):
        return AgentResult(success=True, summary="validated design", data={"experiment_spec": _valid_spec()})

    design.run = successful_retry
    await loop.step()
    assert GuardianAgent._resolve_graph_gate_pressure(state)["active_gate_count"] == 0
    failed = next(gate for gate in state.run_metadata["guardian_gates"] if gate["phase"] == "exception")
    assert failed["audit_log"]["lifecycle"] == "resolved"
    assert failed["audit_log"]["resolution_evidence"]["status"] == "completed"
    assert any(incident["status"] == "resolved" for incident in state.run_metadata["incident_records"])
