"""
Unit tests for graph-wide Guardian gate alarm normalization.
"""

from __future__ import annotations

import pytest

from orchestrator.state import Mode, OrchestratorState, Stage
from policies.guardian_gate import equipment_skill_recovery_gate, gate_blocks_execution, guardian_gate, tool_requires_action_shield


def _state(stage: Stage = Stage.MANIPULATION) -> OrchestratorState:
    return OrchestratorState(run_id="run-gate-test", experiment_id="exp-gate-test", mode=Mode.LIVE, stage=stage)


@pytest.mark.parametrize("blocking,kind,expected_block", [
    (False, "vision_observation", False),
    (True, "vision_gate", True),
    (None, "vision_observation", True),
    (False, "vision_gate", True),
])
def test_equipment_passive_link_unavailable_respects_gate_contract(blocking, kind, expected_block):
    transition = {
        "phase": "vision", "kind": kind, "blocking": blocking,
        "failure_code": "EQUIPMENT_VISION_LINK_UNAVAILABLE", "outcome": "error",
        "vision_result": {"failure_code": "EQUIPMENT_VISION_LINK_UNAVAILABLE"},
    }
    gate = guardian_gate(
        state=_state(Stage.EQUIPMENT), stage="equipment", phase="post",
        payload={"equipment_skill_flow_execution": {"transitions": [transition]}},
    )
    assert gate_blocks_execution(gate) is expected_block
    if not expected_block:
        assert gate["decision"] == "allow_with_warning"
        assert any(a["reason_code"] == "EQUIPMENT_VISION_LINK_UNAVAILABLE"
                   and a["severity"] == "warning" for a in gate["alarms"])


def test_passive_vision_link_warning_does_not_hide_independent_safety_failure():
    gate = guardian_gate(
        state=_state(Stage.EQUIPMENT), stage="equipment", phase="post",
        payload={"equipment_report": {"block_executions": [{
            "phase": "vision", "kind": "vision_observation", "blocking": False,
            "failure_code": "EQUIPMENT_VISION_LINK_UNAVAILABLE",
            "vision_result": {"safe_stop_recommended": True},
        }]}, "equipment_result": {"failure_code": "UTM_MOTION_FAILED"}},
    )
    assert gate_blocks_execution(gate) is True
    assert any(a["reason_code"] == "UTM_MACRO_MISMATCH" and a["severity"] == "blocking"
               for a in gate["alarms"])
    assert any(a["reason_code"] == "OPERATOR_STOP_REQUESTED" and a["severity"] == "critical"
               for a in gate["alarms"])


def test_passive_observer_does_not_downgrade_explicit_blocking_severity():
    gate = guardian_gate(
        state=_state(Stage.EQUIPMENT), stage="equipment", phase="post",
        payload={"equipment_report": {"block_executions": [{
            "phase": "vision", "kind": "vision_observation", "blocking": False,
            "failure_code": "EQUIPMENT_VISION_LINK_UNAVAILABLE", "severity": "blocking",
        }]}},
    )
    assert gate_blocks_execution(gate) is True


def test_nested_required_vision_gate_is_not_downgraded_by_passive_parent():
    gate = guardian_gate(
        state=_state(Stage.EQUIPMENT), stage="equipment", phase="post",
        payload={"equipment_report": {"block_executions": [{
            "phase": "vision", "kind": "vision_observation", "blocking": False,
            "vision_result": {
                "phase": "vision", "kind": "vision_gate", "blocking": True,
                "failure_code": "EQUIPMENT_VISION_LINK_UNAVAILABLE",
            },
        }]}},
    )
    assert gate_blocks_execution(gate) is True


def test_rollout_stop_and_status_are_not_action_shielded() -> None:
    assert tool_requires_action_shield("lerobot.rollout.start") is True
    assert tool_requires_action_shield("lerobot.rollout.stop") is False
    assert tool_requires_action_shield("lerobot.rollout.status") is False


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


def test_equipment_skill_recovery_gate_blocks_unbounded_or_disallowed_recovery() -> None:
    allowed = equipment_skill_recovery_gate(
        state=_state(Stage.EQUIPMENT),
        recovery={"operation": "focus_window", "attempt": 1, "confidence": 0.91},
        allowed_operations=["focus_window", "screenshot"],
        max_attempts=1,
    )
    blocked = equipment_skill_recovery_gate(
        state=_state(Stage.EQUIPMENT),
        recovery={"operation": "click", "attempt": 2, "confidence": 0.99},
        allowed_operations=["focus_window", "screenshot"],
        max_attempts=1,
    )

    assert gate_blocks_execution(allowed) is False
    assert blocked["decision"] == "block"
    assert blocked["reason_code"] == "EQUIPMENT_SKILL_RECOVERY_REJECTED"
    assert gate_blocks_execution(blocked) is True


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


def test_guardian_gate_allows_valid_frame_specimen_non_detection_wait() -> None:
    state = _state(Stage.VISION)

    gate = guardian_gate(
        state=state,
        stage="vision",
        phase="post",
        agent="vision_agent",
        payload={
            "pending_operator_input": True,
            "requires_response": True,
            "vision_operator_intervention": {
                "schema": "vision_operator_intervention.v1",
                "run_id": state.run_id,
                "checkpoint": "active_cam_ejection",
                "status": "waiting_for_specimen",
                "reason": "specimen_not_detected",
                "capture_path": "/tmp/fresh-empty-workspace.png",
            },
        },
    )

    assert gate["decision"] == "allow_with_warning"
    assert gate["reason_code"] == "SPECIMEN_NOT_DETECTED"
    assert gate_blocks_execution(gate) is False


def test_guardian_gate_allows_utm_retry_after_a_fallback_topic_returns_a_valid_frame() -> None:
    state = _state(Stage.VISION)

    gate = guardian_gate(
        state=state,
        stage="vision",
        phase="post",
        agent="vision_agent",
        payload={
            "observation": {
                "raw_capture": {
                    "ok": True,
                    "status": "not_detected",
                    "detected": False,
                    "failure_code": "SPECIMEN_NOT_DETECTED",
                    "frame_capture": {
                        "ok": True,
                        "frame_available": True,
                        "topic": "/camera/image_raw",
                        "attempts": [
                            {
                                "ok": False,
                                "failure_code": "ROS_IMAGE_TIMEOUT",
                                "message": "No image received on /image_utm within 1.25s",
                            },
                            {"ok": True, "failure_code": "", "topic": "/camera/image_raw"},
                        ],
                    },
                    "utm_completion_run_artifact": {
                        "status": "not_detected",
                        "failure_code": "SPECIMEN_NOT_DETECTED",
                    },
                }
            },
            "vision_operator_intervention": {
                "schema": "vision_operator_intervention.v1",
                "run_id": state.run_id,
                "checkpoint": "utm_post_place",
                "status": "retrying",
                "reason": "specimen_not_detected",
                "rollout_stopped": False,
            },
        },
    )

    assert gate["decision"] == "allow_with_warning"
    assert gate["reason_code"] == "SPECIMEN_NOT_DETECTED"
    assert gate_blocks_execution(gate) is False
    assert not [alarm for alarm in gate["alarms"] if alarm["severity"] == "blocking"]


def test_guardian_gate_still_blocks_active_cam_port_release_failure() -> None:
    gate = guardian_gate(
        state=_state(Stage.VISION),
        stage="vision",
        phase="post",
        agent="vision_agent",
        payload={
            "status": "blocked",
            "failure_code": "CAMERA_PORT_RELEASE_FAILED",
            "camera_returned_to_vla": False,
        },
    )

    assert gate_blocks_execution(gate) is True


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


def test_guardian_gate_allows_specimen_http_start_after_ftps_probe_failure() -> None:
    state = OrchestratorState(
        run_id="run-gate-http",
        experiment_id="exp-gate-http",
        mode=Mode.TEST,
        stage=Stage.SPECIMEN,
    )
    gate = guardian_gate(
        state=state,
        stage="specimen",
        phase="post",
        agent="specimen_agent",
        payload={
            "specimen_result": {
                "ok": True,
                "status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
                "experiment_evaluation": {
                    "bridge_result": {
                        "ok": True,
                        "status": "TEST_PRINTER_EJECTION_PROJECT_STARTED",
                        "ftps_probe": {
                            "ok": False,
                            "status": "blocked",
                            "failure_code": "BAMBU_FTPS_PROBE_FAILED",
                            "message": "TLS handshake timed out",
                        },
                        "print_result": {
                            "ok": True,
                            "status": "started",
                            "upload": {
                                "ok": True,
                                "status": "http_artifact_ready",
                                "route": "http_artifact",
                                "url": "http://printer-artifacts/job.gcode.3mf",
                            },
                            "start": {
                                "ok": True,
                                "status": "published",
                                "published": True,
                                "command": "project_file",
                            },
                        },
                    }
                },
            }
        },
    )

    assert gate_blocks_execution(gate) is False
    assert gate["decision"] in {"allow", "allow_with_warning"}
    assert not any(alarm["reason_code"] == "BAMBU_FTPS_PROBE_FAILED" for alarm in gate["alarms"])
