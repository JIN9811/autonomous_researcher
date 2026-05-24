"""
File purpose:
- Generate stable, traceable identifiers for runs, experiments, and events.

Key classes/functions:
- make_run_id
- make_experiment_id
- make_event_id

Inputs/outputs:
- Input: optional prefixes and current timestamp
- Output: unique string identifiers

Dependencies:
- datetime
- secrets

Modification guide:
- Safe places to edit: prefix naming conventions
- Risky places to edit: id format relied upon by log filters
- Related files: logging_system/structured_logger.py, orchestrator/state.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from secrets import token_hex


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_run_id() -> str:
    """Create a globally unique run identifier."""
    return f"run-{_ts()}-{token_hex(3)}"


def make_experiment_id() -> str:
    """Create a unique experiment identifier."""
    return f"exp-{_ts()}-{token_hex(2)}"


def make_event_id() -> str:
    """Create a unique event identifier for stream transport."""
    return f"evt-{_ts()}-{token_hex(2)}"
