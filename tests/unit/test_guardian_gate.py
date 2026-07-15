"""
Unit tests for graph-wide Guardian gate alarm normalization.
"""

from __future__ import annotations

from orchestrator.state import Mode, OrchestratorState, Stage
from policies.guardian_gate import gate_blocks_execution, guardian_gate


def _state(stage: Stage = Stage.MANIPULATION) -> OrchestratorState:
    return OrchestratorState(run_id="run-gate-test", experiment_id="exp-gate-test", mode=Mode.LIVE, stage=stage)


def test_guardian_gate_blocks_boolean_workflow_alarm() -> None:
    gate = guardian_gate(
        state=_state(Stage.SPECIMEN),
        stage="specimen",
        phase="post",
        agent="specimen_agent",
        payload={
            "ok": False,
            "requires_connection_info": True,
            "message": "PrusaLink connection info is required.",
        },
    )

    assert gate["schema"] == "guardian_gate_result.v1"
    assert gate["decision"] == "block"
    assert gate_blocks_execution(gate) is True
    assert gate["guardian_contract"]["schema_version"] == "guardian_contract.v1"
    assert gate["incident_records"]
    assert gate["corrective_actions"]
    assert any(alarm["reason_code"] == "MISSING_REQUIRED_INPUT" for alarm in gate["alarms"])


def test_guardian_gate_routes_human_approval_without_execution_block() -> None:
    gate = guardian_gate(
        state=_state(Stage.MANIPULATION),
        stage="manipulation",
        phase="action",
        agent="manipulation_agent",
        payload={
            "requires_human_approval": True,
            "message": "Policy rollout requires operator approval.",
        },
    )

    assert gate["decision"] == "require_human_approval"
    assert gate_blocks_execution(gate) is False
    assert gate["guardian_contract"]["requires_human_approval"] is True
    assert any(alarm["reason_code"] == "HUMAN_APPROVAL_REQUIRED" for alarm in gate["alarms"])


def test_guardian_gate_reads_nested_agent_warning_and_low_confidence() -> None:
    gate = guardian_gate(
        state=_state(Stage.VISION),
        stage="vision",
        phase="post",
        agent="vision_agent",
        payload={
            "vision_report": {
                "signal_board": [
                    {"signal": "pickup_ready", "status": "warning", "confidence": 0.42, "message": "low pose confidence"}
                ]
            }
        },
    )

    assert gate["decision"] == "allow_with_warning"
    assert gate_blocks_execution(gate) is False
    assert gate["risk_vector"]["vision"] > 0
    assert any(alarm["reason_code"] == "VISION_CONFIDENCE_LOW" for alarm in gate["alarms"])


def test_guardian_gate_safe_stops_physical_active_cam_failure() -> None:
    gate = guardian_gate(
        state=_state(Stage.VISION),
        stage="vision",
        phase="post",
        agent="vision_agent",
        payload={
            "ok": False,
            "failure_code": "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED",
            "safe_stop_recommended": True,
            "observation": {
                "source": "lerobot_active_robot_cam",
                "camera_key": "wrist",
            },
        },
    )

    assert gate["decision"] == "safe_stop"
    assert gate_blocks_execution(gate) is True


def test_guardian_gate_does_not_treat_signal_ack_as_operator_approval() -> None:
    gate = guardian_gate(
        state=_state(Stage.VISION),
        stage="vision",
        phase="post",
        agent="vision_agent",
        payload={
            "agent_signals": [
                {
                    "schema": "vision_signal_item.v1",
                    "signal": "pickup_ready",
                    "status": "ready",
                    "confidence": 0.91,
                    "requires_ack": True,
                    "target_agent": "manipulation_agent",
                    "blocking_reason": None,
                },
                {
                    "schema": "vision_signal_item.v1",
                    "signal": "basket_empty_after_pick",
                    "status": "not_checked",
                    "confidence": 0.0,
                    "requires_ack": True,
                    "target_agent": "manipulation_agent",
                    "blocking_reason": "not_observed_in_current_stage",
                }
            ]
        },
    )

    assert gate_blocks_execution(gate) is False
    assert gate["decision"] in {"allow", "allow_with_warning"}
    assert not any(alarm["reason_code"] == "HUMAN_APPROVAL_REQUIRED" for alarm in gate["alarms"])
    assert not any(alarm["message"] == "not_observed_in_current_stage" for alarm in gate["alarms"])


def test_guardian_gate_collects_agent_specific_alarm_keys() -> None:
    gate = guardian_gate(
        state=_state(Stage.DESIGN),
        stage="design",
        phase="post",
        agent="design_agent",
        payload={
            "design_report": {
                "validation_warnings": ["manufacturability score is low"],
                "handoff_to_specimen": {"missing_required_fields": ["layer_height_mm"]},
            }
        },
    )

    assert gate["decision"] == "block"
    reason_codes = {alarm["reason_code"] for alarm in gate["alarms"]}
    assert "MISSING_REQUIRED_INPUT" in reason_codes
    assert "MANUFACTURABILITY SCORE IS LOW" in reason_codes


def test_guardian_gate_treats_knowledge_performance_record_gaps_as_warning() -> None:
    gate = guardian_gate(
        state=_state(Stage.KNOWLEDGE),
        stage="knowledge",
        phase="post",
        agent="knowledge_agent",
        payload={
            "knowledge_report": {
                "agent_performance_records": [
                    {"signals": {"missing_required_fields": ["specimen_fabricated", "fabrication_report"]}}
                ]
            }
        },
    )

    assert gate_blocks_execution(gate) is False
    assert gate["decision"] == "allow_with_warning"
    assert any(alarm["reason_code"] == "MISSING_REQUIRED_INPUT" for alarm in gate["alarms"])


def test_guardian_gate_reports_bo_block_update_taxonomy() -> None:
    gate = guardian_gate(
        state=_state(Stage.BO),
        stage="bo",
        phase="post",
        agent="bo_agent",
        payload={"bo_result": {"status": "blocked", "failure_code": "BO_CANDIDATE_UNSAFE"}},
    )

    assert gate["decision"] == "block"
    assert gate["ok_for_bo"] is False
    assert gate["guardian_decision"]["taxonomy_action"] == "block_bo_update"
    assert gate["guardian_decision"]["recommended_action"] == "block_bo_update_and_request_new_candidate"

def test_guardian_gate_allows_expected_test_dry_run_print_disabled_marker() -> None:
    state = OrchestratorState(run_id="run-gate-test", experiment_id="exp-gate-test", mode=Mode.TEST, stage=Stage.SPECIMEN)
    gate = guardian_gate(
        state=state,
        stage="specimen",
        phase="post",
        agent="specimen_agent",
        payload={
            "ok": True,
            "mode": "test",
            "status": "simulated_printed",
            "bridge_result": {
                "ok": True,
                "status": "simulated_printed",
                "print_result": {
                    "status": "not_enabled",
                    "failure_code": "START_PRINT_DISABLED",
                    "message": "START_PRINT_DISABLED; not_enabled",
                },
            },
        },
    )

    assert gate["decision"] == "allow"
    assert gate_blocks_execution(gate) is False
    assert not any(alarm["reason_code"] == "START_PRINT_DISABLED" for alarm in gate["alarms"])
