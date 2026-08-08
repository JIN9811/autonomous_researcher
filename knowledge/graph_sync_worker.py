"""Bounded replay worker from durable outbox to the operational graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowledge.durable_outbox import DurableOutbox
from knowledge.neo4j_repository import Neo4jRepository


@dataclass(frozen=True)
class SyncReport:
    ok: bool
    processed: int
    acknowledged: int
    failed: int
    pending: int
    dead_letter: int
    safety_lag: int
    errors: tuple[dict[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "processed": self.processed,
            "acknowledged": self.acknowledged,
            "failed": self.failed,
            "pending": self.pending,
            "dead_letter": self.dead_letter,
            "safety_lag": self.safety_lag,
            "errors": list(self.errors),
        }


class GraphSyncWorker:
    def __init__(self, outbox: DurableOutbox, repository: Neo4jRepository) -> None:
        self.outbox = outbox
        self.repository = repository

    def sync_pending(self, *, limit: int = 100) -> SyncReport:
        bounded_limit = max(1, min(int(limit), 1000))
        items = self.outbox.pending()[:bounded_limit]
        acknowledged = 0
        failed = 0
        errors: list[dict[str, str]] = []
        for item in items:
            try:
                receipt = self.repository.apply_event(item.event)
                if receipt.event_id != str(item.event.get("event_id") or ""):
                    raise RuntimeError("graph receipt event_id mismatch")
                self.outbox.acknowledge(item.item_id, receipt.as_dict())
                acknowledged += 1
            except Exception as exc:
                self.outbox.record_failure(item.item_id, exc)
                failed += 1
                errors.append({"item_id": item.item_id, "error": str(exc)[:500]})
        stats = self.outbox.stats()
        safety_lag = sum(
            1
            for item in self.outbox.pending()
            if str(item.event.get("event_type") or "").startswith("guardian.")
        )
        return SyncReport(
            ok=failed == 0,
            processed=len(items),
            acknowledged=acknowledged,
            failed=failed,
            pending=stats["pending"],
            dead_letter=stats["dead_letter"],
            safety_lag=safety_lag,
            errors=tuple(errors),
        )
