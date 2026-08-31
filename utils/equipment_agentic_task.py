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
    specimen = context.get("specimen") if isinstance(context.get("specimen"), dict) else {}
    observed = {
        "run_id": str(handoff.get("run_id") or "").strip(),
        "specimen_id": str(handoff.get("specimen_id") or specimen.get("specimen_id") or "").strip(),
    }
    handoff_status = str(
        handoff.get("handoff_status")
        or handoff.get("status")
        or handoff.get("completion_status")
        or ""
    ).strip()
    blocking: list[str] = []
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
