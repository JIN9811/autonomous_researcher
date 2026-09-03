"""Canonical Equipment-compatible Vision task definitions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_TASKS: tuple[dict[str, Any], ...] = (
    {
        "task_id": "utm_state_working",
        "check_id": "utm_state_working",
        "label": "UTM Working State",
        "result_label": "WORKING",
        "description": "Observe that the UTM marker geometry is in the working state.",
        "timeout_s": 3,
        "runtime_modes": ["test", "live"],
        "expected": {"utm_state": "WORKING"},
    },
    {
        "task_id": "utm_motion_down",
        "check_id": "utm_motion_down",
        "label": "UTM Downward Motion",
        "result_label": "DOWN",
        "description": "Observe decreasing marker span while the UTM crosshead moves down.",
        "timeout_s": 10,
        "runtime_modes": ["test", "live"],
        "expected": {"utm_motion_direction": "DOWN"},
    },
    {
        "task_id": "utm_state_not_working",
        "check_id": "utm_state_not_working",
        "label": "UTM Not Working State",
        "result_label": "NOT WORKING",
        "description": "Observe that the UTM marker geometry is in the non-working state.",
        "timeout_s": 3,
        "runtime_modes": ["test", "live"],
        "expected": {"utm_state": "NOT_WORKING"},
    },
    {
        "task_id": "utm_pre_start",
        "check_id": "utm_pre_start",
        "label": "Pre-UTM Fixture Check",
        "description": "Verify the fixture and workspace before UTM motion.",
        "timeout_s": 5,
        "runtime_modes": ["test", "live"],
        "expected": {
            "specimen_on_utm_fixture": True,
            "robot_clear_of_utm": True,
            "compression_flatten_occupied": True,
            "human_intrusion": False,
        },
    },
    {
        "task_id": "utm_motion_confirm",
        "check_id": "utm_motion_confirm",
        "label": "UTM Motion Confirmation",
        "description": "Verify UTM motion and specimen alignment during the test.",
        "timeout_s": 10,
        "runtime_modes": ["test", "live"],
        "expected": {
            "utm_crosshead_motion": "started_or_force_curve_active",
            "specimen_remains_aligned": True,
            "fixture_slip_detected": False,
        },
    },
    {
        "task_id": "utm_test_complete",
        "check_id": "utm_test_complete",
        "label": "Post-UTM Completion Check",
        "description": "Verify stopped motion, safe access, and completion evidence.",
        "timeout_s": 10,
        "runtime_modes": ["test", "live"],
        "expected": {
            "utm_crosshead_stopped": True,
            "fixture_safe_to_access": True,
            "specimen_tested_or_crushed": True,
        },
    },
)

EQUIPMENT_VISION_TASK_IDS = frozenset(item["task_id"] for item in _TASKS)


def list_equipment_vision_tasks() -> list[dict[str, Any]]:
    """Return the ordered public task catalog without exposing mutable state."""
    return deepcopy(list(_TASKS))


def get_equipment_vision_task(task_id: str) -> dict[str, Any]:
    """Resolve one exact task or reject an unknown identifier."""
    clean = str(task_id or "").strip()
    for task in _TASKS:
        if task["task_id"] == clean:
            return deepcopy(task)
    raise ValueError(f"unknown Equipment Vision task: {clean or '<empty>'}")


def build_equipment_vision_check(
    task_id: str,
    *,
    run_id: str,
    loop_id: int,
    specimen_id: str,
) -> dict[str, Any]:
    """Build one existing equipment-vision request from a catalog task."""
    task = get_equipment_vision_task(task_id)
    return {
        "agent_signal_type": "equipment_vision_check_request",
        "task_id": task["task_id"],
        "check_id": task["check_id"],
        "run_id": str(run_id or ""),
        "loop_id": int(loop_id or 0),
        "specimen_id": str(specimen_id or ""),
        "producer_agent": "equipment_agent",
        "consumer_agent": "vision_agent",
        "expected": deepcopy(task["expected"]),
        "result_label": str(task.get("result_label") or task["label"]),
        "timeout_s": int(task["timeout_s"]),
    }
