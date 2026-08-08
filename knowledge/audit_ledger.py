"""Append-only, fsync-backed audit ledger for graph-bound Knowledge events."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LedgerReceipt:
    event_id: str
    path: Path
    sha256: str
    line_number: int
    appended_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "path": str(self.path),
            "sha256": self.sha256,
            "line_number": self.line_number,
            "appended_at": self.appended_at,
        }


class AuditLedger:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def append(self, event: dict[str, Any]) -> LedgerReceipt:
        occurred_at = _parse_utc(str(event.get("occurred_at") or ""))
        path = self.root / "events" / f"{occurred_at.year:04d}" / f"{occurred_at.month:02d}" / f"{occurred_at.day:02d}" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
        encoded = (serialized + "\n").encode("utf-8")
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        with path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            line_number = sum(1 for _ in handle) + 1
            handle.seek(0, os.SEEK_END)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return LedgerReceipt(
            event_id=str(event.get("event_id") or ""),
            path=path,
            sha256=digest,
            line_number=line_number,
            appended_at=datetime.now(timezone.utc).isoformat(),
        )


def _parse_utc(value: str) -> datetime:
    if not value:
        raise ValueError("knowledge event occurred_at is required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("knowledge event occurred_at must include timezone")
    return parsed.astimezone(timezone.utc)
