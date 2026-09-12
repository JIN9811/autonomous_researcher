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

from datetime import datetime, timedelta, timezone
import re
from secrets import token_hex

_KST = timezone(timedelta(hours=9), "KST")
_TEST_PURPOSES = {
    "virtual_bridge": "test_virtual",
    "installed_printer": "test_real_printer",
    "physical_print": "test_physical_print",
}
_PURPOSES = {"planning", "Experiment", "test", "replay", "fault_injection", *_TEST_PURPOSES.values()}


def run_purpose(mode: str, profile: str = "") -> str:
    """Name only the mode/profile already known at allocation; never infer readiness."""
    if mode == "test":
        return _TEST_PURPOSES.get(profile, "test")
    return {"live": "Experiment", "replay": "replay", "fault-injection": "fault_injection"}.get(mode, "planning")


def _readable_id(purpose: str) -> str:
    if purpose not in _PURPOSES:
        raise ValueError("Unsupported identity purpose")
    timestamp = datetime.now(_KST).strftime("%Y%m%d_%H%M%S_KST")
    return f"{timestamp}_{purpose}_{token_hex(4)}"


def is_run_id(value: str) -> bool:
    """Recognize legacy and readable run prefixes in compatibility artifact references."""
    return value.startswith("run-") or bool(re.fullmatch(
        r"[0-9]{8}_[0-9]{6}_KST_(?:" + "|".join(sorted(_PURPOSES)) + r")_[0-9a-f]{8}", value))


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_run_id(purpose: str = "planning") -> str:
    """Create a readable run identity with a random collision-resistant suffix."""
    return _readable_id(purpose)


def make_experiment_id() -> str:
    """Create a unique experiment identifier."""
    return _readable_id("Experiment")


def make_planning_session_id() -> str:
    """Create a new conversation identity without renaming the parent run."""
    return _readable_id("planning")


def make_event_id() -> str:
    """Create a unique event identifier for stream transport."""
    return f"evt-{_ts()}-{token_hex(2)}"
