"""Durable filesystem outbox for replayable Knowledge Graph writes."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from knowledge.audit_ledger import LedgerReceipt


@dataclass(frozen=True)
class OutboxItem:
    item_id: str
    state: str
    event: dict[str, Any]
    ledger_receipt: dict[str, Any]
    attempts: int = 0
    last_error: str = ""
    created_at: str = ""
    updated_at: str = ""
    sync_receipt: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "knowledge_outbox_item.v1",
            "item_id": self.item_id,
            "state": self.state,
            "event": self.event,
            "ledger_receipt": self.ledger_receipt,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "sync_receipt": self.sync_receipt,
        }


class DurableOutbox:
    _STATES = ("pending", "acknowledged", "dead_letter")

    def __init__(self, root: Path, *, max_attempts: int = 5) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.root = Path(root)
        self.max_attempts = max_attempts
        for state in self._STATES:
            (self.root / state).mkdir(parents=True, exist_ok=True)

    def enqueue(self, event: dict[str, Any], ledger_receipt: LedgerReceipt) -> OutboxItem:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            raise ValueError("outbox event_id is required")
        item_id = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:32]
        existing = self._find(item_id)
        if existing is not None:
            return existing
        now = _now()
        item = OutboxItem(
            item_id=item_id,
            state="pending",
            event=dict(event),
            ledger_receipt=ledger_receipt.as_dict(),
            created_at=now,
            updated_at=now,
        )
        self._write_atomic(self._path("pending", item_id), item)
        return item

    def pending(self) -> list[OutboxItem]:
        return self._list_state("pending")

    def acknowledge(self, item_id: str, sync_receipt: dict[str, Any]) -> OutboxItem:
        item = self._load_required("pending", item_id)
        event_id = str(item.event.get("event_id") or "")
        receipt_event_id = str(sync_receipt.get("event_id") or "")
        if receipt_event_id and receipt_event_id != event_id:
            raise ValueError(f"sync receipt event mismatch: {receipt_event_id} != {event_id}")
        updated = replace(
            item,
            state="acknowledged",
            updated_at=_now(),
            sync_receipt=dict(sync_receipt),
        )
        self._move(item_id, "pending", "acknowledged", updated)
        return updated

    def record_failure(self, item_id: str, error: BaseException | str) -> OutboxItem:
        item = self._load_required("pending", item_id)
        attempts = item.attempts + 1
        state = "dead_letter" if attempts >= self.max_attempts else "pending"
        updated = replace(
            item,
            state=state,
            attempts=attempts,
            last_error=str(error)[:2000],
            updated_at=_now(),
        )
        if state == "dead_letter":
            self._move(item_id, "pending", "dead_letter", updated)
        else:
            self._write_atomic(self._path("pending", item_id), updated)
        return updated

    def stats(self) -> dict[str, int]:
        return {state: len(list((self.root / state).glob("*.json"))) for state in self._STATES}

    def _list_state(self, state: str) -> list[OutboxItem]:
        return [self._read(path) for path in sorted((self.root / state).glob("*.json"))]

    def _find(self, item_id: str) -> OutboxItem | None:
        for state in self._STATES:
            path = self._path(state, item_id)
            if path.exists():
                return self._read(path)
        return None

    def _load_required(self, state: str, item_id: str) -> OutboxItem:
        path = self._path(state, item_id)
        if not path.exists():
            raise FileNotFoundError(f"outbox item not found: {item_id}")
        return self._read(path)

    def _move(self, item_id: str, source: str, target: str, item: OutboxItem) -> None:
        source_path = self._path(source, item_id)
        self._write_atomic(source_path, item)
        target_path = self._path(target, item_id)
        os.replace(source_path, target_path)
        _fsync_directory(source_path.parent)
        _fsync_directory(target_path.parent)

    def _write_atomic(self, path: Path, item: OutboxItem) -> None:
        temp_path = path.with_suffix(f".{os.getpid()}.tmp")
        payload = item.as_dict()
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)

    def _path(self, state: str, item_id: str) -> Path:
        if state not in self._STATES:
            raise ValueError(f"unknown outbox state: {state}")
        return self.root / state / f"{item_id}.json"

    @staticmethod
    def _read(path: Path) -> OutboxItem:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"outbox item must be an object: {path}")
        raw.pop("schema", None)
        return OutboxItem(**raw)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
