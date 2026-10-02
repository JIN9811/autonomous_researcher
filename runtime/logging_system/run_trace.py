"""
File purpose:
- Keep a compact in-memory trace of the most recent runtime events.

Key classes/functions:
- RunTrace

Inputs/outputs:
- Input: event dictionaries
- Output: bounded list for GUI replay and diagnostics

Dependencies:
- collections.deque

Modification guide:
- Safe places to edit: buffer sizing and event projection
- Risky places to edit: event structure assumptions in GUI
- Related files: app/controller.py, web/static/app.js
"""

from __future__ import annotations

from collections import deque
from typing import Any


class RunTrace:
    """Bounded in-memory trace used for fast GUI event replay."""

    def __init__(self, max_events: int = 500) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)

    def add(self, event: dict[str, Any]) -> None:
        """Append event into the trace buffer."""
        self._events.append(event)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return buffered events in insertion order."""
        return list(self._events)
