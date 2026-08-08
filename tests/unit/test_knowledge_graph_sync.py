from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge.audit_ledger import AuditLedger
from knowledge.durable_outbox import DurableOutbox
from knowledge.event_normalizer import normalize_knowledge_event
from knowledge.graph_sync_worker import GraphSyncWorker
from knowledge.neo4j_repository import Neo4jRepository


class MemoryGraphBackend:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}

    def health(self) -> dict[str, Any]:
        return {"ok": self.available, "enabled": True, "backend": "neo4j-test"}

    def upsert_nodes(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.available:
            raise ConnectionError("neo4j unavailable")
        self.nodes.update({node["id"]: node for node in nodes})
        return {"ok": True, "backend": "neo4j-test", "nodes_written": len(nodes)}

    def upsert_edges(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.available:
            raise ConnectionError("neo4j unavailable")
        self.edges.update({edge["id"]: edge for edge in edges})
        return {"ok": True, "backend": "neo4j-test", "edges_written": len(edges)}

    def query(self, query: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "nodes": list(self.nodes.values()), "edges": list(self.edges.values())}

    def close(self) -> None:
        return None


def _event() -> dict[str, Any]:
    return normalize_knowledge_event(
        {
            "run_id": "run-sync-1",
            "cycle_id": "cycle-2",
            "source_agent": "analysis_agent",
            "event_type": "specimen.analyzed",
            "occurred_at": "2026-08-08T01:00:00Z",
            "entity_refs": [
                {"entity_id": "runtime:run:run-sync-1", "entity_class": "Run", "status": "running"},
                {"entity_id": "runtime:specimen:s-1", "entity_class": "Specimen", "status": "analyzed"},
            ],
            "relationship_intents": [
                {
                    "relation_id": "relation:run-specimen-1",
                    "relation_type": "GENERATES",
                    "source_id": "runtime:candidate:c-1",
                    "source_class": "Candidate",
                    "target_id": "runtime:specimen:s-1",
                    "target_class": "Specimen",
                }
            ],
        },
        ontology_version="atr-core-1.0.0",
    )


def _queued(tmp_path: Path, *, max_attempts: int = 3):
    event = _event()
    receipt = AuditLedger(tmp_path / "ledger").append(event)
    outbox = DurableOutbox(tmp_path / "outbox", max_attempts=max_attempts)
    item = outbox.enqueue(event, receipt)
    return outbox, item


def test_repository_replays_event_without_duplicate_logical_nodes(tmp_path: Path) -> None:
    backend = MemoryGraphBackend()
    repository = Neo4jRepository(backend)
    event = _event()

    first = repository.apply_event(event)
    second = repository.apply_event(event)

    assert first.event_id == event["event_id"]
    assert second.event_id == event["event_id"]
    assert list(backend.nodes).count(event["event_id"]) == 1
    assert "runtime:specimen:s-1" in backend.nodes
    assert "relation:run-specimen-1" in backend.edges


def test_sync_worker_acknowledges_only_matching_event_receipt(tmp_path: Path) -> None:
    outbox, item = _queued(tmp_path)
    backend = MemoryGraphBackend()
    worker = GraphSyncWorker(outbox, Neo4jRepository(backend))

    report = worker.sync_pending()

    assert report.ok
    assert report.acknowledged == 1
    assert report.failed == 0
    assert outbox.pending() == []
    assert outbox.stats()["acknowledged"] == 1
    assert item.event["event_id"] in backend.nodes


def test_sync_worker_preserves_pending_event_during_outage_then_recovers(tmp_path: Path) -> None:
    outbox, item = _queued(tmp_path)
    backend = MemoryGraphBackend(available=False)
    worker = GraphSyncWorker(outbox, Neo4jRepository(backend))

    degraded = worker.sync_pending()
    backend.available = True
    recovered = worker.sync_pending()

    assert not degraded.ok
    assert degraded.failed == 1
    assert degraded.pending == 1
    assert recovered.ok
    assert recovered.acknowledged == 1
    assert outbox.stats()["pending"] == 0
    assert item.event["event_id"] in backend.nodes
