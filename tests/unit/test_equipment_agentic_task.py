"""Contract tests for the Lab Equipment workflow-level Agentic Task."""

from __future__ import annotations

from copy import deepcopy

from utils.equipment_agentic_task import (
    UTM_COMPRESSION_TASK_ID,
    build_utm_compression_flow_template,
    evaluate_equipment_entry_gate,
    project_equipment_cycle_evidence,
    validate_equipment_agentic_flow,
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
    passive_vision = {
        block["id"]: (
            block["vision"]["task_id"],
            block["vision"]["result_label"],
        )
        for block in flow["blocks"]
        if block["vision"]["enabled"]
    }
    assert passive_vision == {
        "prepare_next_specimen": ("utm_state_working", "WORKING"),
        "start_test": ("utm_motion_down", "DOWN"),
        "restore_robot_clearance": ("utm_state_not_working", "NOT WORKING"),
    }
    assert all(block["vision"]["blocking"] is False for block in flow["blocks"])
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


def test_live_entry_gate_does_not_fill_missing_handoff_identity_from_specimen_context() -> None:
    """Catch unrelated specimen context making an incomplete handoff look identity-bound."""
    gate = evaluate_equipment_entry_gate(
        run_id="run-1",
        specimen_id="specimen-1",
        source_stage_context={
            "manipulation": {
                "handoff_status": "ready_for_equipment",
                "run_id": "run-1",
            },
            "specimen": {"specimen_id": "specimen-1"},
        },
        test_like=False,
    )

    assert gate["ok"] is False
    assert gate["blocking_reasons"] == ["specimen_id_missing"]


def test_live_entry_gate_rejects_missing_expected_specimen_identity() -> None:
    gate = evaluate_equipment_entry_gate(
        run_id="run-1",
        specimen_id="",
        source_stage_context={
            "manipulation": {
                "handoff_status": "ready_for_equipment",
                "run_id": "run-1",
                "specimen_id": "stale-specimen",
            }
        },
        test_like=False,
    )

    assert gate["ok"] is False
    assert "expected_specimen_id_missing" in gate["blocking_reasons"]


def test_agentic_flow_contract_rejects_unknown_or_noncanonical_revision() -> None:
    canonical = build_utm_compression_flow_template("utm_windows_v1")

    assert validate_equipment_agentic_flow("", canonical["blocks"])["ok"] is True
    assert validate_equipment_agentic_flow(UTM_COMPRESSION_TASK_ID, canonical["blocks"])["ok"] is True
    assert validate_equipment_agentic_flow("unknown_task", canonical["blocks"])["failure_code"] == (
        "EQUIPMENT_AGENTIC_TASK_UNSUPPORTED"
    )
    shortened = canonical["blocks"][:-1]
    invalid = validate_equipment_agentic_flow(UTM_COMPRESSION_TASK_ID, shortened)
    assert invalid["ok"] is False
    assert invalid["failure_code"] == "EQUIPMENT_FLOW_REVISION_INVALID"


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


def test_cycle_projection_uses_observed_values_and_validates_csv_before_readiness() -> None:
    """Catch fabricated method values or readiness before data and clearance proof."""
    projection = project_equipment_cycle_evidence(
        transitions=[
            {
                "block_id": "save_raw_data",
                "phase": "skill",
                "outcome": "completed",
                "evidence": {
                    "linux_path": "/tmp/raw.csv",
                    "artifact_kind": "utm_csv",
                    "artifact_id": "raw-1",
                    "run_id": "run-1",
                    "specimen_id": "specimen-1",
                },
            },
            {
                "block_id": "validate_raw_data",
                "phase": "skill",
                "outcome": "completed",
                "evidence": {
                    "linux_path": "/tmp/raw.csv",
                    "artifact_kind": "utm_csv",
                    "artifact_id": "raw-1",
                    "data_parse_probe_ok": True,
                    "row_count_probe": 50,
                    "columns_probe": ["time_s", "displacement_mm", "force_N"],
                    "write_complete": True,
                    "run_id": "run-1",
                    "specimen_id": "specimen-1",
                },
            },
            {
                "block_id": "advance_without_save",
                "phase": "skill",
                "outcome": "completed",
            },
            {
                "block_id": "restore_robot_clearance",
                "phase": "skill",
                "outcome": "completed",
                "evidence": {"height": {"observed": 118.4, "target": 118.4}},
            },
        ],
        result_data={
            "workflow_agentic_task": {"run_id": "run-1", "specimen_id": "specimen-1"},
            "equipment_result": {"force": 6.2, "stroke": 19.8, "height": 118.4},
            "equipment_report": {"method_values": {"height_target": 118.4}},
        },
    )

    assert projection["method_values"] == {
        "Force": {"observed": 6.2, "target": None},
        "Stroke": {"observed": 19.8, "target": None},
        "Height": {"observed": 118.4, "target": 118.4},
    }
    assert projection["raw_data_export"]["path"] == "/tmp/raw.csv"
    assert projection["raw_data_export"]["validated"] is True
    assert projection["next_specimen_readiness"] == {
        "ready": True,
        "next_test_completed": True,
        "save_current_test": False,
        "clearance_restored": True,
        "clearance_height": {"observed": 118.4, "target": 118.4},
        "failure_code": "",
    }
    assert projection["handoff_eligibility"]["eligible"] is True
    assert "LAN" not in repr(projection)


def test_cycle_projection_blocks_next_specimen_without_valid_raw_csv() -> None:
    """Catch Next Test and clearance being treated as sufficient without Raw CSV."""
    projection = project_equipment_cycle_evidence(
        transitions=[
            {"block_id": "advance_without_save", "phase": "skill", "outcome": "completed"},
            {"block_id": "restore_robot_clearance", "phase": "skill", "outcome": "completed"},
        ],
        result_data={},
    )

    assert projection["raw_data_export"]["validated"] is False
    assert projection["next_specimen_readiness"]["ready"] is False
    assert projection["handoff_eligibility"] == {
        "eligible": False,
        "missing_requirements": ["raw_csv_validated", "robot_clearance_restored"],
        "failure_code": "RAW_CSV_VALIDATION_FAILED",
    }


def test_cycle_projection_requires_clearance_height_to_match_configured_target() -> None:
    projection = project_equipment_cycle_evidence(
        transitions=[
            {
                "block_id": "save_raw_data",
                "phase": "skill",
                "outcome": "completed",
                "evidence": {
                    "linux_path": "/tmp/raw.csv",
                    "artifact_kind": "utm_csv",
                    "artifact_id": "raw-1",
                    "run_id": "run-1",
                    "specimen_id": "specimen-1",
                },
            },
            {
                "block_id": "validate_raw_data",
                "phase": "skill",
                "outcome": "completed",
                "evidence": {
                    "linux_path": "/tmp/raw.csv",
                    "artifact_kind": "utm_csv",
                    "artifact_id": "raw-1",
                    "data_parse_probe_ok": True,
                    "row_count_probe": 2,
                    "columns_probe": ["time_s", "displacement_mm", "force_N"],
                    "write_complete": True,
                    "run_id": "run-1",
                    "specimen_id": "specimen-1",
                },
            },
            {"block_id": "advance_without_save", "phase": "skill", "outcome": "completed"},
            {
                "block_id": "restore_robot_clearance",
                "phase": "skill",
                "outcome": "completed",
                "evidence": {"height": {"observed": 118.0, "target": 120.0}},
            },
        ],
        result_data={"workflow_agentic_task": {"run_id": "run-1", "specimen_id": "specimen-1"}},
    )

    assert projection["raw_data_export"]["validated"] is True
    assert projection["next_specimen_readiness"]["clearance_restored"] is False
    assert projection["handoff_eligibility"]["failure_code"] == "ROBOT_CLEARANCE_NOT_RESTORED"


def test_cycle_projection_rejects_cross_artifact_unstable_or_mismatched_csv_evidence() -> None:
    transitions = [
        {
            "block_id": "save_raw_data",
            "phase": "skill",
            "outcome": "completed",
            "evidence": {
                "linux_path": "/tmp/raw.csv",
                "artifact_kind": "utm_csv",
                "artifact_id": "raw-1",
                "run_id": "run-1",
                "specimen_id": "specimen-1",
            },
        },
        {
            "block_id": "validate_raw_data",
            "phase": "skill",
            "outcome": "completed",
            "evidence": {
                "linux_path": "/tmp/raw.csv",
                "artifact_kind": "utm_csv",
                "artifact_id": "raw-1",
                "data_parse_probe_ok": True,
                "row_count_probe": 2,
                "columns_probe": ["time_s", "displacement_mm", "force_N"],
                "write_complete": True,
                "run_id": "run-1",
                "specimen_id": "specimen-1",
            },
        },
    ]
    result = {"workflow_agentic_task": {"run_id": "run-1", "specimen_id": "specimen-1"}}
    cases = []
    different_path = deepcopy(transitions)
    different_path[1]["evidence"]["linux_path"] = "/tmp/other.csv"
    cases.append(different_path)
    unstable = deepcopy(transitions)
    unstable[1]["evidence"].pop("write_complete")
    cases.append(unstable)
    wrong_identity = deepcopy(transitions)
    wrong_identity[1]["evidence"]["specimen_id"] = "other-specimen"
    cases.append(wrong_identity)
    missing_column = deepcopy(transitions)
    missing_column[1]["evidence"]["columns_probe"] = ["time_s", "force_N"]
    cases.append(missing_column)

    assert all(
        project_equipment_cycle_evidence(transitions=case, result_data=result)["raw_data_export"]["validated"] is False
        for case in cases
    )


def test_cycle_projection_retains_bounded_screen_transition_evidence() -> None:
    """Catch postcondition evidence being dropped from workflow reports."""
    projection = project_equipment_cycle_evidence(
        transitions=[
            {
                "block_id": "start_test",
                "phase": "skill",
                "outcome": "completed",
                "evidence": {
                    "before_frame": "frame-before",
                    "after_frame": "frame-after",
                    "locator_id": "start-test-button",
                    "postcondition": {"button": "disabled", "icon": "running"},
                },
            }
        ],
        result_data={},
    )

    assert projection["screen_transition_evidence"] == [
        {
            "block_id": "start_test",
            "before_frame": "frame-before",
            "after_frame": "frame-after",
            "locator_id": "start-test-button",
            "locator_version": "",
            "postcondition": {"button": "disabled", "icon": "running"},
        }
    ]


def test_cycle_projection_unwraps_structured_observed_and_target_values() -> None:
    """Catch structured sensor evidence leaking into scalar GUI value fields."""
    projection = project_equipment_cycle_evidence(
        transitions=[],
        result_data={
            "equipment_result": {
                "force": {"observed": 6.2, "target": 7.0},
                "stroke": {"value": 19.8, "configured": 20.0},
                "height": {"observed": 118.4},
            }
        },
    )

    assert projection["method_values"] == {
        "Force": {"observed": 6.2, "target": 7.0},
        "Stroke": {"observed": 19.8, "target": 20.0},
        "Height": {"observed": 118.4, "target": None},
    }
