"""
File purpose:
- Define standardized recovery actions after agent/tool failures.

Key classes/functions:
- recovery_action

Inputs/outputs:
- Input: stage and error message
- Output: structured recovery decision dictionary

Dependencies:
- none

Modification guide:
- Safe places to edit: action descriptions
- Risky places to edit: keys consumed by orchestrator logging
- Related files: policies/retry_policy.py, logging_system/error_logger.py
"""

from __future__ import annotations


def recovery_action(stage: str, error_text: str) -> dict[str, str]:
    """Return default recovery action guidance for a failed stage."""
    return {
        "stage": stage,
        "action": "retry_with_simulator",
        "reason": error_text[:220],
        "operator_hint": "Switch to test-mode bridge and re-run stage.",
    }
