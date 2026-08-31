"""Contract tests for the Lab Equipment workflow-level Agentic Task."""

from __future__ import annotations

from utils.equipment_agentic_task import (
    UTM_COMPRESSION_TASK_ID,
    build_utm_compression_flow_template,
    evaluate_equipment_entry_gate,
)


def test_utm_template_builds_the_recorded_cycle_without_runtime_bindings() -> None:
    """Catch reordered/missing phases or accidental physical defaults in the template."""
    flow = build_utm_compression_flow_template("utm_windows_v1")

    assert flow["agentic_task_id"] == UTM_COMPRESSION_TASK_ID
    assert [block["id"] for block in flow["blocks"]] == [
        "prepare_next_specimen",
        "start_test",
        "monitor_contact_and_run",
        "await_auto_return",
        "save_raw_data",
        "validate_raw_data",
        "advance_without_save",
        "restore_robot_clearance",
    ]
    assert all(
        block["skill"] == {"skill_id": "", "skill_version": ""}
        for block in flow["blocks"]
    )
    assert all(block["vision"]["enabled"] is False for block in flow["blocks"])
    assert all(block["vision"]["task_id"] == "" for block in flow["blocks"])
    assert all(block["agentic"]["failed"] == "__blocked__" for block in flow["blocks"])
    assert [block["agentic"]["completed"] for block in flow["blocks"]] == [
        "next",
        "next",
        "next",
        "next",
        "next",
        "next",
        "next",
        "__complete__",
    ]
    assert "5 N" not in repr(flow)
    assert "21 mm" not in repr(flow)
    assert "120 mm" not in repr(flow)


def test_live_entry_gate_accepts_only_identity_bound_ready_for_equipment() -> None:
    """Catch a live equipment start that bypasses the upstream verified handoff."""
    gate = evaluate_equipment_entry_gate(
        run_id="run-1",
        specimen_id="specimen-1",
        source_stage_context={
            "manipulation": {
                "handoff_status": "ready_for_equipment",
                "run_id": "run-1",
                "specimen_id": "specimen-1",
            },
            "specimen": {"specimen_id": "specimen-1"},
        },
        test_like=False,
    )

    assert gate == {
        "schema": "atr.equipment_entry_gate.v1",
        "locked": True,
        "ok": True,
        "status": "verified",
        "failure_code": "",
        "blocking_reasons": [],
        "expected_identity": {"run_id": "run-1", "specimen_id": "specimen-1"},
        "observed_identity": {"run_id": "run-1", "specimen_id": "specimen-1"},
        "handoff_status": "ready_for_equipment",
        "source": "manipulation_handoff",
        "simulated": False,
    }
    assert "enabled" not in gate


def test_live_entry_gate_blocks_missing_or_mismatched_handoff() -> None:
    """Catch acceptance of stale evidence from a different run or specimen."""
    gate = evaluate_equipment_entry_gate(
        run_id="run-1",
        specimen_id="specimen-1",
        source_stage_context={
            "manipulation": {
                "handoff_status": "ready_for_equipment",
                "run_id": "run-old",
                "specimen_id": "specimen-2",
            }
        },
        test_like=False,
    )

    assert gate["ok"] is False
    assert gate["status"] == "blocked"
    assert gate["failure_code"] == "EQUIPMENT_HANDOFF_NOT_READY"
    assert gate["blocking_reasons"] == ["run_id_mismatch", "specimen_id_mismatch"]


def test_test_like_entry_gate_is_explicitly_simulated() -> None:
    """Catch test-mode evidence being represented as a physical upstream handoff."""
    gate = evaluate_equipment_entry_gate(
        run_id="run-test",
        specimen_id="specimen-test",
        source_stage_context={},
        test_like=True,
    )

    assert gate["ok"] is True
    assert gate["simulated"] is True
    assert gate["source"] == "test_mode_simulated"
    assert gate["handoff_status"] == "ready_for_equipment"
