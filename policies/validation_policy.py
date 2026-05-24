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
    "analysis": ("analysis",),
    "guardian": ("guardian",),
}


def validate_agent_output(stage: str, payload: dict[str, object]) -> tuple[bool, str]:
    """Validate required payload keys for selected stages."""
    required = _REQUIRED_KEYS.get(stage, ())
    missing = [key for key in required if key not in payload]
    if missing:
        return False, f"Missing required keys for stage={stage}: {missing}"
    return True, "ok"
