"""
File purpose:
- Manage bounded retry counts per stage.

Key classes/functions:
- should_retry
- bump_retry

Inputs/outputs:
- Input: state retry counters, stage, max retry
- Output: retry decision and updated counter

Dependencies:
- orchestrator.state.OrchestratorState

Modification guide:
- Safe places to edit: max retry defaults
- Risky places to edit: key naming for retry counters
- Related files: orchestrator/run_loop.py, policies/recovery_policy.py
"""

from __future__ import annotations

from orchestrator.state import OrchestratorState


def should_retry(state: OrchestratorState, stage_name: str, max_retry: int) -> bool:
    """Return True when stage retry budget is not exhausted."""
    return state.retry_counters.get(stage_name, 0) < max_retry


def bump_retry(state: OrchestratorState, stage_name: str) -> int:
    """Increment retry counter and return new value."""
    current = state.retry_counters.get(stage_name, 0) + 1
    state.retry_counters[stage_name] = current
    return current
