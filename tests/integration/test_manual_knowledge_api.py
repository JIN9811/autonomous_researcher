from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app


class _ManualKnowledgeService:
    def status(self) -> dict[str, Any]:
        return {"ok": True, "equipment_type": "utm", "source_count": 2, "chunk_count": 24}

    def ingest(self) -> dict[str, Any]:
        return {"ok": True, "source_count": 2, "chunk_count": 24}

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("equipment_type") != "utm":
            raise ValueError("equipment_type must be utm")
        return {
            "schema": "manual_context.v1",
            "equipment_type": "utm",
            "purpose": payload.get("purpose"),
            "chunks": [{"chunk_id": "manual:chunk:1", "text": "시험 시작 절차"}],
            "context_hash": "manual-context-hash",
            "semantic_projection": {
                "schema": "manual_semantic_projection.v1",
                "nodes": [{"id": "procedure:1", "kind": "Procedure"}],
                "edges": [],
            },
        }

    def graph(self, *, limit: int = 100, view: str = "semantic") -> dict[str, Any]:
        kind = "Procedure" if view == "semantic" else "ManualChunk"
        return {"ok": True, "view": view, "nodes": [{"id": "equipment:utm", "kind": kind}][:limit], "edges": []}

    def close(self) -> None:
        return None


def test_manual_knowledge_api_exposes_ingest_status_query_and_graph(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "_manual_knowledge_service", lambda: _ManualKnowledgeService())
    client = TestClient(app)

    assert client.get("/api/knowledge/manuals/status").json()["source_count"] == 2
    assert client.post("/api/knowledge/manuals/ingest").json()["chunk_count"] == 24
    context = client.post(
        "/api/knowledge/manuals/query",
        json={"equipment_type": "utm", "purpose": "procedure", "query": "시험 시작 절차", "top_k": 4},
    ).json()
    graph = client.get("/api/knowledge/manuals/graph?limit=20").json()

    assert context["context_hash"] == "manual-context-hash"
    assert context["semantic_projection"]["nodes"][0]["kind"] == "Procedure"
    assert graph["view"] == "semantic"
    assert graph["nodes"][0]["id"] == "equipment:utm"


def test_manual_knowledge_api_rejects_non_utm_scope(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "_manual_knowledge_service", lambda: _ManualKnowledgeService())
    client = TestClient(app)

    response = client.post(
        "/api/knowledge/manuals/query",
        json={"equipment_type": "printer", "purpose": "procedure", "query": "start"},
    )

    assert response.status_code == 422
    assert "equipment_type must be utm" in response.json()["detail"]


def test_manual_context_failure_degrades_to_insufficient_evidence(monkeypatch) -> None:
    class _UnavailableManualKnowledgeService(_ManualKnowledgeService):
        closed = False

        def query(self, payload: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("manual index unavailable")

        def close(self) -> None:
            self.closed = True

    service = _UnavailableManualKnowledgeService()
    monkeypatch.setattr(app_main, "_manual_knowledge_service", lambda: service)

    context = app_main._manual_knowledge_context("UTM recovery", purpose="recovery")

    assert context["equipment_type"] == "utm"
    assert context["insufficient_evidence"] is True
    assert context["chunks"] == []
    assert "manual index unavailable" in context["error"]
    assert service.closed is True


def test_manual_graph_api_exposes_explicit_evidence_view(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "_manual_knowledge_service", lambda: _ManualKnowledgeService())
    client = TestClient(app)

    response = client.get("/api/knowledge/manuals/graph?view=evidence&limit=20")

    assert response.status_code == 200
    assert response.json()["view"] == "evidence"
    assert response.json()["nodes"][0]["kind"] == "ManualChunk"


def test_manual_graph_api_rejects_unknown_view(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "_manual_knowledge_service", lambda: _ManualKnowledgeService())
    client = TestClient(app)

    response = client.get("/api/knowledge/manuals/graph?view=unknown")

    assert response.status_code == 422
