"""
File purpose:
- Lightweight in-memory experiment database for test mode and local development.

Key classes/functions:
- ExperimentDB

Inputs/outputs:
- Input: memory records
- Output: queryable list of records by run and best score

Dependencies:
- knowledge.schemas.MemoryRecord

Modification guide:
- Safe places to edit: retrieval filters
- Risky places to edit: storage interface expected by agents
- Related files: agents/knowledge_agent.py, app/controller.py
"""

from __future__ import annotations

from typing import Iterable

from knowledge.schemas import MemoryRecord


class ExperimentDB:
    """In-memory storage for experiment outcomes and summaries."""

    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []

    def add(self, record: MemoryRecord) -> None:
        """Insert one memory record."""
        self._records.append(record)

    def extend(self, records: Iterable[MemoryRecord]) -> None:
        """Insert multiple memory records."""
        self._records.extend(records)

    def list_recent(self, limit: int = 20) -> list[MemoryRecord]:
        """Return recent records in insertion order."""
        return self._records[-limit:]

    def best(self) -> MemoryRecord | None:
        """Return best score record or None when empty."""
        if not self._records:
            return None
        return max(self._records, key=lambda item: item.score)
