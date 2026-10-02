from __future__ import annotations

from pathlib import Path

from knowledge.audit_ledger import AuditLedger
from knowledge.durable_outbox import DurableOutbox
from knowledge.event_normalizer import normalize_knowledge_event


def _event() -> dict[str, object]:
    return normalize_knowledge_event(
        {
            "run_id": "run-1",
            "cycle_id": "cycle-1",
            "source_agent": "knowledge_agent",
            "event_type": "run.created",
            "occurred_at": "2026-08-08T00:00:00Z",
        },
        ontology_version="atr-core-1.0.0",
    )


def _enqueue(root: Path, *, max_attempts: int = 2):
    event = _event()
    receipt = AuditLedger(root / "ledger").append(event)
    outbox = DurableOutbox(root / "outbox", max_attempts=max_attempts)
    return outbox, outbox.enqueue(event, receipt)


def test_enqueue_is_atomic_and_idempotent(tmp_path: Path) -> None:
    outbox, first = _enqueue(tmp_path)
    second = outbox.enqueue(_event(), AuditLedger(tmp_path / "ledger").append(_event()))

    assert first.item_id == second.item_id
    assert len(outbox.pending()) == 1
    assert not list((tmp_path / "outbox" / "pending").glob("*.tmp"))


def test_pending_items_survive_service_restart(tmp_path: Path) -> None:
    outbox, item = _enqueue(tmp_path)

    reconstructed = DurableOutbox(outbox.root, max_attempts=2)

    assert [entry.item_id for entry in reconstructed.pending()] == [item.item_id]
    assert reconstructed.stats()["pending"] == 1


def test_acknowledge_moves_item_and_preserves_sync_receipt(tmp_path: Path) -> None:
    outbox, item = _enqueue(tmp_path)

    acknowledged = outbox.acknowledge(item.item_id, {"event_id": item.event["event_id"], "nodes_written": 2})

    assert acknowledged.state == "acknowledged"
    assert outbox.pending() == []
    assert outbox.stats() == {"pending": 0, "acknowledged": 1, "dead_letter": 0}
    assert acknowledged.sync_receipt["nodes_written"] == 2


def test_repeated_failure_moves_item_to_dead_letter_without_losing_event(tmp_path: Path) -> None:
    outbox, item = _enqueue(tmp_path, max_attempts=2)

    retry = outbox.record_failure(item.item_id, RuntimeError("neo4j unavailable"))
    dead = outbox.record_failure(item.item_id, RuntimeError("neo4j unavailable again"))

    assert retry.state == "pending"
    assert retry.attempts == 1
    assert dead.state == "dead_letter"
    assert dead.attempts == 2
    assert dead.event["event_id"] == item.event["event_id"]
    assert "unavailable again" in dead.last_error
    assert outbox.stats() == {"pending": 0, "acknowledged": 0, "dead_letter": 1}


def test_unknown_item_operations_fail_closed(tmp_path: Path) -> None:
    outbox = DurableOutbox(tmp_path / "outbox")

    for operation in (
        lambda: outbox.acknowledge("missing", {}),
        lambda: outbox.record_failure("missing", RuntimeError("x")),
    ):
        try:
            operation()
        except FileNotFoundError as exc:
            assert "missing" in str(exc)
        else:
            raise AssertionError("unknown outbox item must not be silently ignored")
