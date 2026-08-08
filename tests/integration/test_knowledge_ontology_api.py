from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from knowledge.ontology.registry import OntologyRegistry
from knowledge.ontology.validator import OntologyValidator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ApiKnowledgeService:
    def __init__(self) -> None:
        self.registry = OntologyRegistry.load_default(PROJECT_ROOT)
        self.validator = OntologyValidator(self.registry)

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "ready",
            "ontology_version": self.registry.version_id,
            "graph": {"ok": True, "backend": "neo4j-test", "node_count": 12, "edge_count": 9},
            "outbox": {"pending": 0, "acknowledged": 3, "dead_letter": 0},
        }

    def sync(self, *, limit: int = 100) -> dict[str, Any]:
        return {"ok": True, "processed": 0, "acknowledged": 0, "pending": 0, "dead_letter": 0, "safety_lag": 0, "limit": limit}

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "cypher" in payload:
            raise ValueError("raw Cypher is forbidden")
        return {"ok": True, "query_plan": payload, "nodes": [], "edges": []}

    def activity(self, *, run_id: str = "", limit: int = 20) -> dict[str, Any]:
        return {
            "schema": "knowledge_activity_series.v1",
            "run_id": run_id,
            "limit": limit,
            "cycles": [{"cycle_id": "cycle-1", "collected": 4, "updated": 2, "retrieved": 1, "used": 1}],
            "totals": {"collected": 4, "updated": 2, "retrieved": 1, "used": 1},
        }

    def close(self) -> None:
        return None


def test_ontology_and_graph_service_api_contracts(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "_knowledge_service", lambda: ApiKnowledgeService())
    client = TestClient(app)

    ontology = client.get("/api/knowledge/ontology").json()
    validation = client.post(
        "/api/knowledge/ontology/validate",
        json={
            "schema": "knowledge_event.v1",
            "event_id": "event:1",
            "idempotency_key": "sha256:1",
            "run_id": "run-1",
            "cycle_id": "cycle-1",
            "source_agent": "knowledge_agent",
            "event_type": "run.created",
            "occurred_at": "2026-08-08T00:00:00Z",
            "entity_refs": [],
            "relationship_intents": [],
            "artifact_refs": [],
            "payload_summary": {},
            "ontology_version": "atr-core-1.0.0",
            "provenance": {},
        },
    ).json()
    stats = client.get("/api/knowledge/graph/stats").json()
    sync = client.post("/api/knowledge/graph/sync", json={"limit": 25}).json()
    query = client.post("/api/knowledge/graph/query", json={"kind": "run_context", "filters": {"run_id": "run-1"}}).json()
    activity = client.get("/api/knowledge/activity?run_id=run-1&limit=12").json()

    assert ontology["version_id"] == "atr-core-1.0.0"
    assert "Specimen" in ontology["classes"]
    assert validation["ok"]
    assert stats["graph"]["node_count"] == 12
    assert sync["limit"] == 25
    assert query["query_plan"]["kind"] == "run_context"
    assert activity["run_id"] == "run-1"
    assert activity["limit"] == 12
    assert activity["cycles"][0]["used"] == 1


def test_graph_query_api_rejects_raw_cypher(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "_knowledge_service", lambda: ApiKnowledgeService())
    client = TestClient(app)

    response = client.post("/api/knowledge/graph/query", json={"kind": "raw", "cypher": "MATCH (n) RETURN n"})

    assert response.status_code == 422
    assert "raw Cypher" in response.json()["detail"]
