"""
File purpose:
- Store structured failure events for recovery-aware planning.

Key classes/functions:
- FailureRecord
- FailureMemory

Inputs/outputs:
- Input: stage, failure type, context
- Output: recent failure list for guardian/orchestrator

Dependencies:
- dataclasses

Modification guide:
- Safe places to edit: additional metadata fields
- Risky places to edit: consumer expectations in guardian policies
- Related files: agents/guardian_agent.py, policies/recovery_policy.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class FailureRecord:
    """Structured failure memory entry."""

    stage: str
    failure_type: str
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FailureMemory:
    """Keeps an append-only failure history."""

    def __init__(self) -> None:
        self._items: list[FailureRecord] = []

    def add(self, record: FailureRecord) -> None:
        """Store one failure record."""
        self._items.append(record)

    def recent(self, limit: int = 10) -> list[FailureRecord]:
        """Return most recent failure records."""
        return self._items[-limit:]
