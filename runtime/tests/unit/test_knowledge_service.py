from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge.ontology.registry import OntologyRegistry
from knowledge.service import KnowledgeService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ServiceBackend:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}

    def health(self) -> dict[str, Any]:
        return {"ok": self.available, "enabled": True, "backend": "neo4j-test"}

    def upsert_nodes(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.available:
            raise ConnectionError("offline")
        self.nodes.update({node["id"]: node for node in nodes})
        return {"ok": True, "backend": "neo4j-test", "nodes_written": len(nodes)}

    def upsert_edges(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.available:
            raise ConnectionError("offline")
        self.edges.update({edge["id"]: edge for edge in edges})
        return {"ok": True, "backend": "neo4j-test", "edges_written": len(edges)}

    def query(self, query: dict[str, Any]) -> dict[str, Any]:
        return {"ok": self.available, "backend": "neo4j-test", "nodes": list(self.nodes.values()), "edges": list(self.edges.values())}

    def close(self) -> None:
        return None


def _payload() -> dict[str, Any]:
    return {
        "run_id": "run-service-1",
        "cycle_id": "cycle-1",
        "source_agent": "knowledge_agent",
        "event_type": "specimen.analyzed",
        "occurred_at": "2026-08-08T02:00:00Z",
        "entity_refs": [{"entity_id": "runtime:specimen:s-1", "entity_class": "Specimen"}],
    }


def test_service_ingest_runs_durable_protocol_and_reports_sync(tmp_path: Path) -> None:
    backend = ServiceBackend()
    service = KnowledgeService(tmp_path, backend=backend, registry=OntologyRegistry.load_default(PROJECT_ROOT))

    result = service.ingest(_payload())

    assert result["ok"]
    assert result["validation"]["ok"]
    assert result["sync"]["acknowledged"] == 1
    assert result["outbox"]["pending"] == 0
    assert Path(result["ledger_receipt"]["path"]).exists()


def test_service_retains_pending_event_when_neo4j_is_unavailable(tmp_path: Path) -> None:
    backend = ServiceBackend(available=False)
    service = KnowledgeService(tmp_path, backend=backend, registry=OntologyRegistry.load_default(PROJECT_ROOT))

    degraded = service.ingest(_payload())
    backend.available = True
    recovered = service.sync()

    assert degraded["ok"]
    assert degraded["status"] == "degraded"
    assert degraded["outbox"]["pending"] == 1
    assert recovered["acknowledged"] == 1
    assert service.status()["outbox"]["pending"] == 0


def test_service_rejects_invalid_event_before_graph_write_but_keeps_audit(tmp_path: Path) -> None:
    backend = ServiceBackend()
    service = KnowledgeService(tmp_path, backend=backend, registry=OntologyRegistry.load_default(PROJECT_ROOT))
    invalid = {**_payload(), "event_type": "not.allowed"}

    result = service.ingest(invalid)

    assert not result["ok"]
    assert result["status"] == "validation_failed"
    assert Path(result["ledger_receipt"]["path"]).exists()
    assert backend.nodes == {}


def test_service_query_uses_allowlisted_plan(tmp_path: Path) -> None:
    service = KnowledgeService(tmp_path, backend=ServiceBackend(), registry=OntologyRegistry.load_default(PROJECT_ROOT))

    result = service.query({"kind": "run_context", "filters": {"run_id": "run-service-1"}, "limit": 10})

    assert result["query_plan"]["kind"] == "run_context"
    try:
        service.query({"kind": "raw", "cypher": "MATCH (n) RETURN n"})
    except ValueError as exc:
        assert "raw Cypher" in str(exc)
    else:
        raise AssertionError("raw Cypher must be rejected")
