"""Unit tests for stage output validation policy."""

from __future__ import annotations

from policies.validation_policy import validate_agent_output


def test_equipment_stage_requires_result_contract() -> None:
    ok, message = validate_agent_output("equipment", {"protocol_note": "ready"})

    assert ok is False
    assert "equipment_result" in message


def test_equipment_stage_blocks_failed_pyautogui_result() -> None:
    ok, message = validate_agent_output(
        "equipment",
        {
            "protocol_note": "bridge failed",
            "equipment_result": {
                "ok": False,
                "failure_code": "PYAUTOGUI_BRIDGE_UNREACHABLE",
            },
        },
    )

    assert ok is False
    assert "PYAUTOGUI_BRIDGE_UNREACHABLE" in message


def test_equipment_stage_accepts_successful_pyautogui_result() -> None:
    ok, message = validate_agent_output(
        "equipment",
        {
            "protocol_note": "bridge complete",
            "equipment_result": {"ok": True, "status": "completed"},
        },
    )

    assert ok is True
    assert message == "ok"


def test_analysis_stage_blocks_failed_utm_analysis() -> None:
    ok, message = validate_agent_output(
        "analysis",
        {
            "analysis": {
                "ok": False,
                "failure_code": "UTM_DATA_REQUIRED",
            }
        },
    )

    assert ok is False
    assert "UTM_DATA_REQUIRED" in message
