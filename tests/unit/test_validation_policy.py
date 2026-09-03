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
            "equipment_result": {"ok": True, "status": "verified_complete"},
            "equipment_handoff": {"status": "ready_for_analysis"},
            "utm_data_ready": {"status": "ready"},
            "equipment_report": {
                "cross_checks": {
                    "screen_started": True,
                    "physical_motion_started": True,
                    "save_completed": True,
                    "data_file_created": True,
                    "data_parse_probe_ok": True,
                }
            },
        },
    )

    assert ok is True
    assert message == "ok"


def test_equipment_stage_blocks_non_ready_handoff() -> None:
    ok, message = validate_agent_output(
        "equipment",
        {
            "protocol_note": "demo only",
            "equipment_result": {"ok": True, "status": "completed"},
            "equipment_handoff": {"status": "blocked", "failure_code": "UTM_PROTOCOL_REQUIRED"},
        },
    )

    assert ok is False
    assert "UTM_PROTOCOL_REQUIRED" in message


def test_equipment_stage_accepts_typed_no_actuation_preflight_for_cae_analysis() -> None:
    ok, message = validate_agent_output(
        "equipment",
        {
            "protocol_note": "agentic UTM flow validated; execution deferred by policy",
            "equipment_result": {
                "ok": True,
                "status": "execution_ready_pending_approval",
                "actuation_performed": False,
            },
            "equipment_preflight": {
                "schema": "equipment_preflight.v1",
                "status": "execution_ready_pending_approval",
                "actuation_performed": False,
                "resolved_program_id": "run_utm_compression_cycle",
            },
            "equipment_handoff": {
                "status": "execution_ready_pending_approval",
                "ready_for_analysis": False,
                "actuation_performed": False,
            },
        },
    )

    assert ok is True
    assert message == "ok"


def test_specimen_stage_accepts_only_consistent_typed_no_actuation_preflight() -> None:
    payload = {
        "printer_preflight": {
            "schema": "printer_preflight.v1",
            "status": "execution_ready_pending_approval",
            "actuation_performed": False,
            "upload_performed": False,
            "start_command_published": False,
        },
        "specimen_fabricated": {
            "schema": "specimen_fabricated.v1",
            "status": "preflight_ready",
            "physical_location": "not_actuated",
        },
    }

    assert validate_agent_output("specimen", payload) == (True, "ok")

    payload["specimen_fabricated"]["status"] = "blocked"
    ok, message = validate_agent_output("specimen", payload)
    assert ok is False
    assert "specimen preflight handoff" in message.lower()


def test_specimen_stage_rejects_preflight_that_claims_actuation() -> None:
    ok, message = validate_agent_output(
        "specimen",
        {
            "printer_preflight": {
                "schema": "printer_preflight.v1",
                "status": "execution_ready_pending_approval",
                "actuation_performed": True,
                "upload_performed": False,
                "start_command_published": False,
            },
            "specimen_fabricated": {
                "schema": "specimen_fabricated.v1",
                "status": "preflight_ready",
                "physical_location": "not_actuated",
            },
        },
    )

    assert ok is False
    assert "printer_preflight" in message


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
