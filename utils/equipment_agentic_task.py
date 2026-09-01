"""Workflow-level Agentic Task contracts for Lab Equipment execution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


TASK_SCHEMA = "atr.equipment_agentic_task.v1"
ENTRY_GATE_SCHEMA = "atr.equipment_entry_gate.v1"
UTM_COMPRESSION_TASK_ID = "run_utm_compression_cycle"

UTM_COMPRESSION_BLOCKS: tuple[tuple[str, str], ...] = (
    ("prepare_next_specimen", "Move Jigs for Next Specimen"),
    ("start_test", "Start Test"),
    ("monitor_contact_and_run", "Monitor contact and method-driven compression"),
    ("await_auto_return", "Wait for automatic Height return"),
    ("save_raw_data", "Save Raw Data CSV"),
    ("validate_raw_data", "Validate Raw Data CSV"),
    ("advance_without_save", "Next Test without saving current test"),
    ("restore_robot_clearance", "Restore configured robot-entry clearance"),
)

_TASK_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "schema": TASK_SCHEMA,
        "task_id": UTM_COMPRESSION_TASK_ID,
        "label": "UTM Compression Cycle",
        "description": (
            "Run the saved UTM preparation, test, Raw Data validation, Next Test, "
            "and robot-clearance sequence for one verified specimen."
        ),
        "entry_gate": {
            "id": "verified_specimen_utm_handoff",
            "label": "Verified specimen / UTM handoff",
            "locked": True,
        },
        "block_order": [block_id for block_id, _ in UTM_COMPRESSION_BLOCKS],
    },
)


def list_equipment_agentic_tasks() -> list[dict[str, Any]]:
    """Return the code-owned workflow-level task catalog."""
    return deepcopy(list(_TASK_CATALOG))


def build_utm_compression_flow_template(profile_id: str) -> dict[str, Any]:
    """Build an unbound eight-block draft for one existing Equipment Profile."""
    clean_profile = str(profile_id or "").strip()
    if not clean_profile:
        raise ValueError("profile_id is required")
    blocks: list[dict[str, Any]] = []
    for index, (block_id, task) in enumerate(UTM_COMPRESSION_BLOCKS):
        success = "__complete__" if index == len(UTM_COMPRESSION_BLOCKS) - 1 else "next"
        blocks.append(
            {
                "id": block_id,
                "label": task,
                "skill": {"skill_id": "", "skill_version": ""},
                "agentic": {
                    "task": task,
                    "completed": success,
                    "failed": "__blocked__",
                },
                "vision": {
                    "enabled": False,
                    "task_id": "",
                    "detected": success,
                    "not_detected": "__blocked__",
                    "timeout": "__blocked__",
                    "error": "__blocked__",
                },
            }
        )
    return {
        "schema": "atr.equipment_skill_flow.v1",
        "flow_id": clean_profile,
        "profile_id": clean_profile,
        "version": 1,
        "enabled": True,
        "agentic_task_id": UTM_COMPRESSION_TASK_ID,
        "blocks": blocks,
    }


def validate_equipment_agentic_flow(
    agentic_task_id: str,
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate code-owned workflow identity and revision before device input."""
    task_id = str(agentic_task_id or "").strip()
    if not task_id:
        return {"ok": True, "task_id": "", "failure_code": "", "blocking_reasons": []}
    if task_id != UTM_COMPRESSION_TASK_ID:
        return {
            "ok": False,
            "task_id": task_id,
            "failure_code": "EQUIPMENT_AGENTIC_TASK_UNSUPPORTED",
            "blocking_reasons": ["unsupported_agentic_task_id"],
        }
    expected = [block_id for block_id, _ in UTM_COMPRESSION_BLOCKS]
    observed = [str(block.get("id") or "") for block in blocks if isinstance(block, dict)]
    if observed != expected:
        return {
            "ok": False,
            "task_id": task_id,
            "failure_code": "EQUIPMENT_FLOW_REVISION_INVALID",
            "blocking_reasons": ["canonical_block_order_mismatch"],
            "expected_block_order": expected,
            "observed_block_order": observed,
        }
    return {
        "ok": True,
        "task_id": task_id,
        "failure_code": "",
        "blocking_reasons": [],
        "expected_block_order": expected,
        "observed_block_order": observed,
    }


def _handoff_candidate(source_stage_context: dict[str, Any]) -> tuple[dict[str, Any], str]:
    for key, source in (("manipulation", "manipulation_handoff"), ("robot_task", "robot_task_result")):
        candidate = source_stage_context.get(key)
        if not isinstance(candidate, dict):
            continue
        nested = candidate.get("handoff")
        if isinstance(nested, dict):
            merged = {**candidate, **nested}
        else:
            merged = candidate
        if merged:
            return merged, source
    return {}, "unavailable"


def evaluate_equipment_entry_gate(
    *,
    run_id: str,
    specimen_id: str,
    source_stage_context: dict[str, Any],
    test_like: bool,
) -> dict[str, Any]:
    """Validate the locked upstream handoff before any equipment input."""
    expected = {
        "run_id": str(run_id or "").strip(),
        "specimen_id": str(specimen_id or "").strip(),
    }
    if test_like:
        return {
            "schema": ENTRY_GATE_SCHEMA,
            "locked": True,
            "ok": True,
            "status": "verified",
            "failure_code": "",
            "blocking_reasons": [],
            "expected_identity": expected,
            "observed_identity": dict(expected),
            "handoff_status": "ready_for_equipment",
            "source": "test_mode_simulated",
            "simulated": True,
        }

    context = source_stage_context if isinstance(source_stage_context, dict) else {}
    handoff, source = _handoff_candidate(context)
    observed = {
        "run_id": str(handoff.get("run_id") or "").strip(),
        "specimen_id": str(handoff.get("specimen_id") or "").strip(),
    }
    handoff_status = str(
        handoff.get("handoff_status")
        or handoff.get("status")
        or handoff.get("completion_status")
        or ""
    ).strip()
    blocking: list[str] = []
    if not expected["run_id"]:
        blocking.append("expected_run_id_missing")
    if not expected["specimen_id"]:
        blocking.append("expected_specimen_id_missing")
    if handoff_status != "ready_for_equipment":
        blocking.append("handoff_status_not_ready")
    for key in ("run_id", "specimen_id"):
        if expected[key] and not observed[key]:
            blocking.append(f"{key}_missing")
        elif expected[key] and observed[key] != expected[key]:
            blocking.append(f"{key}_mismatch")
    ok = not blocking
    return {
        "schema": ENTRY_GATE_SCHEMA,
        "locked": True,
        "ok": ok,
        "status": "verified" if ok else "blocked",
        "failure_code": "" if ok else "EQUIPMENT_HANDOFF_NOT_READY",
        "blocking_reasons": blocking,
        "expected_identity": expected,
        "observed_identity": observed,
        "handoff_status": handoff_status or "unknown",
        "source": source,
        "simulated": False,
    }


def _dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _dicts(nested)


def _first_value(value: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for mapping in _dicts(value):
        for key in keys:
            candidate = mapping.get(key)
            if candidate is not None and candidate != "":
                return candidate
    return None


def _method_value(
    result_data: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    name: str,
) -> dict[str, Any]:
    lower = name.lower()
    combined = {"result": result_data, "evidence": evidence}
    observed = _first_value(
        combined,
        (lower, f"{lower}_value", f"current_{lower}", f"observed_{lower}"),
    )
    target = _first_value(
        combined,
        (f"{lower}_target", f"target_{lower}", f"configured_{lower}"),
    )
    if isinstance(observed, dict):
        structured_observed = observed
        observed = structured_observed.get("observed", structured_observed.get("value"))
        if target is None:
            target = structured_observed.get("target", structured_observed.get("configured"))
    for mapping in _dicts(combined):
        structured = mapping.get(lower)
        if not isinstance(structured, dict):
            structured = mapping.get(name)
        if isinstance(structured, dict):
            if observed is None:
                observed = structured.get("observed", structured.get("value"))
            if target is None:
                target = structured.get("target", structured.get("configured"))
    return {"observed": observed, "target": target}


def project_equipment_cycle_evidence(
    *,
    transitions: list[dict[str, Any]],
    result_data: dict[str, Any],
) -> dict[str, Any]:
    """Project bounded cycle evidence without inventing method or sensor values."""
    safe_transitions = [dict(item) for item in transitions if isinstance(item, dict)]
    evidence = [
        dict(item.get("evidence"))
        for item in safe_transitions
        if isinstance(item.get("evidence"), dict)
    ]
    completed_blocks = {
        str(item.get("block_id") or "")
        for item in safe_transitions
        if item.get("phase") == "skill" and item.get("outcome") == "completed"
    }

    method_values = {
        name: _method_value(result_data, evidence, name=name)
        for name in ("Force", "Stroke", "Height")
    }

    screen_transitions: list[dict[str, Any]] = []
    for item in safe_transitions:
        item_evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        if not any(
            key in item_evidence
            for key in ("before_frame", "after_frame", "locator_id", "locator_version", "postcondition")
        ):
            continue
        screen_transitions.append(
            {
                "block_id": str(item.get("block_id") or ""),
                "before_frame": str(item_evidence.get("before_frame") or ""),
                "after_frame": str(item_evidence.get("after_frame") or ""),
                "locator_id": str(item_evidence.get("locator_id") or ""),
                "locator_version": str(item_evidence.get("locator_version") or ""),
                "postcondition": (
                    dict(item_evidence.get("postcondition"))
                    if isinstance(item_evidence.get("postcondition"), dict)
                    else item_evidence.get("postcondition") or {}
                ),
            }
        )

    def completed_evidence(block_id: str) -> dict[str, Any]:
        match = next(
            (
                item
                for item in safe_transitions
                if item.get("block_id") == block_id
                and item.get("phase") == "skill"
                and item.get("outcome") == "completed"
                and isinstance(item.get("evidence"), dict)
            ),
            {},
        )
        return dict(match.get("evidence")) if isinstance(match.get("evidence"), dict) else {}

    save_evidence = completed_evidence("save_raw_data")
    validation_evidence = completed_evidence("validate_raw_data")
    csv_path = str(save_evidence.get("linux_path") or "").strip()
    validation_path = str(validation_evidence.get("linux_path") or "").strip()
    parse_ok = validation_evidence.get("data_parse_probe_ok")
    row_count = validation_evidence.get("row_count_probe")
    columns = validation_evidence.get("columns_probe") if isinstance(validation_evidence.get("columns_probe"), list) else []
    stable = validation_evidence.get("write_complete")
    try:
        rows_ok = int(row_count or 0) > 0
    except (TypeError, ValueError):
        rows_ok = False
    required_columns = {"time_s", "displacement_mm", "force_N"}
    columns_ok = required_columns.issubset({str(item) for item in columns})
    artifact_id = str(save_evidence.get("artifact_id") or "").strip()
    validation_artifact_id = str(validation_evidence.get("artifact_id") or "").strip()
    same_artifact = bool(
        csv_path
        and validation_path == csv_path
        and artifact_id
        and validation_artifact_id == artifact_id
        and save_evidence.get("artifact_kind") == "utm_csv"
        and validation_evidence.get("artifact_kind") == "utm_csv"
    )
    overlay = result_data.get("workflow_agentic_task") if isinstance(result_data.get("workflow_agentic_task"), dict) else {}
    if not overlay:
        execution = result_data.get("equipment_skill_flow_execution") if isinstance(result_data.get("equipment_skill_flow_execution"), dict) else {}
        overlay = execution.get("workflow_agentic_task") if isinstance(execution.get("workflow_agentic_task"), dict) else {}
    expected_run_id = str(overlay.get("run_id") or "").strip()
    expected_specimen_id = str(overlay.get("specimen_id") or "").strip()
    identity_ok = bool(
        expected_run_id
        and expected_specimen_id
        and str(save_evidence.get("run_id") or "") == expected_run_id
        and str(validation_evidence.get("run_id") or "") == expected_run_id
        and str(save_evidence.get("specimen_id") or "") == expected_specimen_id
        and str(validation_evidence.get("specimen_id") or "") == expected_specimen_id
    )
    csv_validated = bool(
        same_artifact
        and csv_path.lower().endswith(".csv")
        and parse_ok is True
        and rows_ok
        and columns_ok
        and stable is True
        and identity_ok
    )
    raw_data_export = {
        "path": csv_path,
        "artifact_id": artifact_id,
        "artifact_kind": str(save_evidence.get("artifact_kind") or ""),
        "parse_ok": parse_ok is True,
        "row_count": int(row_count or 0) if rows_ok else 0,
        "columns": [str(item) for item in columns],
        "stable": stable is True,
        "same_artifact": same_artifact,
        "identity_ok": identity_ok,
        "validated": csv_validated,
    }

    next_test_completed = "advance_without_save" in completed_blocks
    clearance_evidence = completed_evidence("restore_robot_clearance")
    clearance_height = _method_value({}, [clearance_evidence], name="Height")
    clearance_observed = clearance_height.get("observed")
    clearance_target = clearance_height.get("target")
    try:
        clearance_matches = abs(float(clearance_observed) - float(clearance_target)) <= 1e-6
    except (TypeError, ValueError):
        clearance_matches = bool(
            clearance_observed is not None
            and clearance_target is not None
            and clearance_observed == clearance_target
        )
    clearance_restored = (
        "restore_robot_clearance" in completed_blocks and clearance_matches
    )
    missing: list[str] = []
    if not csv_validated:
        missing.append("raw_csv_validated")
    if not next_test_completed:
        missing.append("next_test_completed")
    if not clearance_restored:
        missing.append("robot_clearance_restored")
    failure_code = (
        "RAW_CSV_VALIDATION_FAILED"
        if "raw_csv_validated" in missing
        else "NEXT_TEST_TRANSITION_FAILED"
        if "next_test_completed" in missing
        else "ROBOT_CLEARANCE_NOT_RESTORED"
        if missing
        else ""
    )
    ready = not missing
    return {
        "method_values": method_values,
        "screen_transition_evidence": screen_transitions,
        "raw_data_export": raw_data_export,
        "next_specimen_readiness": {
            "ready": ready,
            "next_test_completed": next_test_completed,
            "save_current_test": False,
            "clearance_restored": clearance_restored,
            "clearance_height": clearance_height,
            "failure_code": failure_code,
        },
        "handoff_eligibility": {
            "eligible": ready,
            "missing_requirements": missing,
            "failure_code": failure_code,
        },
    }
