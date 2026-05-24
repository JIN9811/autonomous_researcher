"""
File purpose:
- Define safe-stop behavior applied by guardian/orchestrator.

Key classes/functions:
- safe_stop_reason

Inputs/outputs:
- Input: explicit stop flags and guardian signals
- Output: safe-stop reason text

Dependencies:
- none

Modification guide:
- Safe places to edit: reason templates
- Risky places to edit: semantics used in UI
- Related files: agents/guardian_agent.py, orchestrator/run_loop.py
"""

from __future__ import annotations


def safe_stop_reason(trigger: str) -> str:
    """Return human-readable reason for a safe-stop event."""
    return f"Safe-stop engaged: {trigger}"
