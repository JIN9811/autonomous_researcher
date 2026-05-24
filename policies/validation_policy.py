"""
File purpose:
- Validate core stage output schemas and state consistency.

Key classes/functions:
- validate_agent_output

Inputs/outputs:
- Input: stage and output payload
- Output: bool validity and optional message

Dependencies:
- none

Modification guide:
- Safe places to edit: stage-specific required keys
- Risky places to edit: strictness may break stage transitions
- Related files: orchestrator/run_loop.py, tests/integration/test_loop.py
"""

from __future__ import annotations


_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "design": ("experiment_spec",),
    "vision": ("observation",),
    "equipment": ("equipment_result", "protocol_note"),
    "analysis": ("analysis",),
    "guardian": ("guardian",),
}


def validate_agent_output(stage: str, payload: dict[str, object]) -> tuple[bool, str]:
    """Validate required payload keys for selected stages."""
    required = _REQUIRED_KEYS.get(stage, ())
    missing = [key for key in required if key not in payload]
    if missing:
        return False, f"Missing required keys for stage={stage}: {missing}"
    if stage == "equipment":
        result = payload.get("equipment_result")
        if not isinstance(result, dict):
            return False, "Invalid equipment_result payload."
        if result.get("ok") is False:
            failure_code = result.get("failure_code") or result.get("status") or "unknown"
            return False, f"Equipment stage failed: {failure_code}"
    if stage == "analysis":
        result = payload.get("analysis")
        if not isinstance(result, dict):
            return False, "Invalid analysis payload."
        if result.get("ok") is False:
            failure_code = result.get("failure_code") or "unknown"
            return False, f"Analysis stage failed: {failure_code}"
    return True, "ok"
