"""Integration tests for Guardian graph-wide status/report APIs."""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from app.main import app, controller


def test_guardian_status_api_summarizes_risk_incidents_approvals_and_tool_calls() -> None:
    client = TestClient(app)
    old_metadata = copy.deepcopy(controller._state.run_metadata)
    old_device_health = copy.deepcopy(controller._state.device_health)
    old_current_spec = copy.deepcopy(controller._state.current_experiment_spec)
    old_current_objective = copy.deepcopy(controller._state.current_experiment_objective)
    old_loop_count = controller._state.loop_count
    old_safe_stop_requested = controller._state.safe_stop_requested
    try:
        controller._state.run_metadata.update(
            {
                "guardian_gates": [
                    {
                        "schema": "guardian_gate_result.v1",
                        "gate_id": "guardian-gate-api-001",
                        "stage": "equipment",
                        "phase": "post",
                        "decision": "block",
                        "reason_code": "UTM_NO_MOTION",
                        "risk_score": 0.78,
                        "risk_vector": {"equipment": 0.78, "hardware": 0.7, "data": 0.2},
                        "created_at": "2026-05-31T00:00:00+00:00",
                        "guardian_decision": {"schema": "guardian_decision.v1", "decision": "block", "reason_code": "UTM_NO_MOTION"},
                        "guardian_contract": {"schema_version": "guardian_contract.v1", "ok_for_next_stage": False, "ok_for_bo": False},
                    }
                ],
                "guardian_contracts": [{"schema_version": "guardian_contract.v1", "ok_for_next_stage": False, "ok_for_bo": False}],
                "latest_guardian_gate_decision": {"schema": "guardian_decision.v1", "decision": "block", "reason_code": "UTM_NO_MOTION"},
                "incident_records": [
                    {
                        "schema": "incident_record.v1",
                        "incident_id": "incident-api-001",
                        "stage": "equipment",
                        "severity": "major",
                        "risk_class": "equipment",
                        "failure_code": "UTM_NO_MOTION",
                    }
                ],
                "hardware_alerts": [
                    {
                        "schema": "hardware_alert.v1",
                        "alert_id": "alert-api-001",
                        "stage": "equipment",
                        "device_class": "utm",
                        "component": "utm_motion",
                        "severity": "blocking",
                        "status": "blocked",
                        "failure_code": "UTM_NO_MOTION",
                        "blocks_workflow": True,
                    }
                ],
                "tool_call_records": [
                    {
                        "schema": "tool_call_record.v1",
                        "record_id": "tool-record-api-001",
                        "call_id": "tool-call-api-001",
                        "stage": "equipment",
                        "tool": "equipment.pyautogui.run",
                        "status": "blocked",
                        "failure_code": "GUARDIAN_TOOL_SHIELD_BLOCKED",
                        "guardian_decision": "block",
                        "guardian_reason_code": "UTM_NO_MOTION",
                    }
                ],
                "guardian_approval_queue": [
                    {
                        "approval_id": "approval-api-001",
                        "stage": "equipment",
                        "title": "Guardian approval required",
                        "reason": "live equipment action",
                        "status": "pending",
                    }
                ],
                "corrective_actions": [
                    {"schema": "corrective_action.v1", "action_id": "ca-api-001", "recommended_action": "stop_macro_and_recheck_screen"}
                ],
                "handoff_packets": [{"stage": "equipment", "packet": {"schema": "utm_data_ready.v1", "status": "blocked"}}],
                "safety_budget": {
                    "max_loop_count": 5,
                    "max_print_time_min": 120,
                    "max_load_n": 1500,
                    "max_robot_live_rollouts": 2,
                    "max_physical_prints": 1,
                },
            }
        )
        controller._state.current_experiment_spec = {
            "expected_print_time_min": 96,
            "target_load_n": 800,
            "constraints": {"max_print_time_min": 120, "max_load_n": 1500},
        }
        controller._state.current_experiment_objective = {"max_loop_count": 5}
        controller._state.loop_count = 4
        controller._state.safe_stop_requested = True
        controller._state.device_health["utm"] = "blocking:UTM_NO_MOTION"

        response = client.get("/api/guardian/status")
        assert response.status_code == 200
        payload = response.json()

        assert payload["schema"] == "guardian_status_report.v1"
        assert payload["status"] == "blocked"
        assert payload["summary"]["blocked_action_count"] >= 3
        assert payload["summary"]["incident_count"] == 1
        assert payload["summary"]["pending_approval_count"] == 1
        risk_by_class = {item["risk_class"]: item for item in payload["graph_wide_risk_map"]}
        assert risk_by_class["equipment"]["score"] == 0.78
        assert payload["blocked_actions"]["tool_calls"][0]["tool"] == "equipment.pyautogui.run"
        assert payload["incident_ledger"]["severity_counts"]["major"] == 1
        assert payload["safety_budget"]["schema"] == "guardian_safety_budget.v1"
        assert payload["summary"]["safety_budget_status"] in {"within_budget", "near_limit"}
        budget_by_resource = {item["resource"]: item for item in payload["safety_budget"]["items"]}
        assert budget_by_resource["loop_count"]["used"] == 4.0
        assert budget_by_resource["print_time"]["limit"] == 120.0
        assert payload["safe_stop_verification"]["schema"] == "guardian_safe_stop_verification.v1"
        assert payload["safe_stop_verification"]["requested"] is True
        assert payload["evidence_completeness"]["schema"] == "guardian_evidence_completeness.v1"
        assert payload["summary"]["evidence_completeness_status"] in {"missing", "partial", "complete"}
        assert payload["self_evolution_gate"]["schema"] == "guardian_self_evolution_gate.v1"
        assert payload["summary"]["self_evolution_gate_status"] == payload["self_evolution_gate"]["status"]
        assert payload["device_data_integrity"]["device_health"]["utm"] == "blocking:UTM_NO_MOTION"
        heartbeats = payload["device_data_integrity"]["live_device_heartbeat"]
        assert any(item["device_id"] == "utm" and item["heartbeat_status"] == "blocked" for item in heartbeats)
        assert payload["handoff_packet"]["latest_guardian_decision"]["decision"] == "block"

        state_response = client.get("/api/state")
        assert state_response.status_code == 200
        assert state_response.json()["guardian_status"]["schema"] == "guardian_status_report.v1"
    finally:
        controller._state.run_metadata = old_metadata
        controller._state.device_health = old_device_health
        controller._state.current_experiment_spec = old_current_spec
        controller._state.current_experiment_objective = old_current_objective
        controller._state.loop_count = old_loop_count
        controller._state.safe_stop_requested = old_safe_stop_requested


def test_run_guardian_status_unknown_run_returns_404() -> None:
    client = TestClient(app)
    response = client.get("/api/runs/run-does-not-exist-guardian/status")
    assert response.status_code == 404


def test_guardian_incident_note_api_attaches_note_to_incident_record() -> None:
    client = TestClient(app)
    old_metadata = copy.deepcopy(controller._state.run_metadata)
    try:
        controller._state.run_metadata = {
            "incident_records": [
                {
                    "schema": "incident_record.v1",
                    "incident_id": "incident-note-api-001",
                    "stage": "equipment",
                    "severity": "near_miss",
                    "risk_class": "equipment",
                }
            ]
        }

        response = client.post(
            f"/api/runs/{controller._state.run_id}/guardian/incidents/incident-note-api-001/notes",
            json={"note": "Operator confirmed UTM window mismatch root cause.", "operator": "pytest"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["matched_incident"] is True
        assert payload["note"]["schema"] == "guardian_incident_note.v1"
        incident = controller._state.run_metadata["incident_records"][0]
        assert incident["operator_notes"][0]["note"] == "Operator confirmed UTM window mismatch root cause."
        assert controller._state.run_metadata["guardian_incident_notes"][0]["incident_id"] == "incident-note-api-001"
    finally:
        controller._state.run_metadata = old_metadata
