"""
Fault-matrix coverage for Guardian improvement 09.

These tests do not replace hardware fault-injection, but they verify that the
core Guardian policy normalizes representative fault payloads into block,
safe-stop, or BO quarantine semantics before a physical or optimization action
can continue.
"""

from __future__ import annotations

import pytest

from orchestrator.state import Mode, OrchestratorState, Stage
from policies.guardian_gate import gate_blocks_execution, guardian_gate


def _state(stage: Stage) -> OrchestratorState:
    return OrchestratorState(run_id="run-guardian-fault", experiment_id="exp-guardian-fault", mode=Mode.LIVE, stage=stage)


@pytest.mark.parametrize(
    ("stage", "payload", "expected_reason"),
    [
        (
            Stage.VISION,
            {"vision_report": {"status": "blocked", "failure_code": "CAMERA_FRAME_MISSING", "message": "camera frame missing"}},
            "MISSING_REQUIRED_INPUT",
        ),
        (
            Stage.MANIPULATION,
            {"manipulation": {"status": "blocked", "failure_code": "ROBOT_ACTION_OUT_OF_BOUNDS"}},
            "ROBOT_ACTION_OUT_OF_BOUNDS",
        ),
        (
            Stage.EQUIPMENT,
            {"equipment_result": {"status": "blocked", "failure_code": "UTM_NO_MOTION_AFTER_START"}},
            "UTM_NO_MOTION",
        ),
        (
            Stage.ANALYSIS,
            {"analysis": {"ok": False, "status": "blocked", "failure_code": "DATA_PARSE_FAILED"}},
            "DATA_PARSE_FAILED",
        ),
        (
            Stage.BO,
            {"bo_result": {"status": "blocked", "failure_code": "BO_CANDIDATE_UNSAFE"}},
            "BO_CANDIDATE_UNSAFE",
        ),
        (
            Stage.GUARDIAN,
            {"self_evolution": {"status": "blocked", "failure_code": "SELF_EVOLUTION_GATE_FAILED"}},
            "SELF_EVOLUTION_GATE_FAILED",
        ),
    ],
)
def test_guardian_fault_matrix_blocks_representative_faults(stage: Stage, payload: dict, expected_reason: str) -> None:
    gate = guardian_gate(state=_state(stage), stage=stage.value, phase="post", agent=f"{stage.value}_agent", payload=payload)

    assert gate["decision"] == "block"
    assert gate_blocks_execution(gate) is True
    assert gate["incident_records"]
    assert gate["corrective_actions"]
    assert any(alarm["reason_code"] == expected_reason for alarm in gate["alarms"])


def test_guardian_fault_matrix_safe_stops_critical_utm_no_motion() -> None:
    gate = guardian_gate(
        state=_state(Stage.EQUIPMENT),
        stage="equipment",
        phase="post",
        agent="equipment_agent",
        payload={
            "equipment_result": {
                "status": "blocked",
                "severity": "critical",
                "failure_code": "UTM_NO_MOTION_AFTER_START",
            }
        },
    )

    assert gate["decision"] == "safe_stop"
    assert gate_blocks_execution(gate) is True
    assert gate["guardian_decision"]["recommended_action"] == "safe_stop_and_verify"


def test_guardian_fault_matrix_blocks_bad_analysis_from_bo_update() -> None:
    gate = guardian_gate(
        state=_state(Stage.ANALYSIS),
        stage="analysis",
        phase="post",
        agent="analysis_agent",
        payload={
            "ok_for_bo": True,
            "analysis": {
                "status": "blocked",
                "failure_code": "DATA_QUALITY_LOW",
                "artifact_refs": [],
            },
        },
    )

    assert gate["decision"] == "block"
    assert gate["ok_for_bo"] is False
    assert gate["guardian_contract"]["ok_for_bo"] is False
