"""Knowledge graph retirement must not remove ontology or local knowledge APIs."""
from pathlib import Path
import importlib.util

import pytest
from fastapi.testclient import TestClient

import app.main as main


@pytest.mark.parametrize("method,path", [
    ("get", "/api/knowledge/graph/stats"),
    ("get", "/api/knowledge/graph/health"),
    ("post", "/api/knowledge/graph/query"),
    ("post", "/api/knowledge/graph/sync"),
    ("post", "/api/knowledge/graph/import"),
    ("post", "/api/knowledge/graphify/scan"),
    ("get", "/api/knowledge/relations/status"),
    ("post", "/api/knowledge/relations/reconcile"),
    ("get", "/api/knowledge/manuals/graph"),
])
def test_retired_graph_routes_never_construct_graph_services(monkeypatch, method, path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Retired graph factory called")
    monkeypatch.setattr(main, "_knowledge_graph_backend", forbidden)
    monkeypatch.setattr(main, "_knowledge_service", forbidden)
    monkeypatch.setattr(main, "_knowledge_reconciliation_worker", forbidden)
    monkeypatch.setattr(main, "_manual_knowledge_service", forbidden)
    response = getattr(TestClient(main.app), method)(path)
    assert response.status_code == 410
    assert response.json()["status"] == "retired"


def test_ontology_remains_available_without_graph_connection(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Ontology attempted graph connection")
    monkeypatch.setattr(main, "graph_backend_from_env", forbidden)
    response = TestClient(main.app).get("/api/knowledge/ontology")
    assert response.status_code == 200
    assert "Observation" in response.json()["classes"]
    assert "relations" in response.json()


def test_markdown_query_and_read_enforce_same_scope(tmp_path, monkeypatch):
    assert importlib.util.find_spec("knowledge.markdown_memory") is not None
    from knowledge.markdown_runtime import store_for
    store = store_for(project_root=tmp_path)
    note = {"run_id": "run-a", "cycle_id": "loop-000001", "agent_id": "analysis_agent", "event_id": "event-1",
            "ontology_type": "Observation", "title": "Export complete", "body": "The exported CSV was verified.",
            "source_refs": ["runs/run-a/result.json"]}
    receipt = store.write_note(note)
    monkeypatch.setattr(main, "_markdown_store", lambda: store)
    client = TestClient(main.app)
    result = client.post("/api/knowledge/markdown/query", json={"query": "CSV", "scope": {"run_id": "run-a"}})
    assert result.status_code == 200
    assert result.json()["hits"][0]["record_id"] == receipt["record_id"]
    excluded = client.post("/api/knowledge/markdown/query", json={"query": "CSV", "scope": {"run_id": []}})
    assert excluded.json()["hits"] == []
    detail = client.post("/api/knowledge/markdown/read", json={"record_id": receipt["record_id"], "scope": {"run_id": "run-a"}})
    assert detail.status_code == 200
    assert "CSV" in str(detail.json())
    blocked = client.post("/api/knowledge/markdown/read", json={"record_id": receipt["record_id"], "scope": {"run_id": "run-b"}})
    assert blocked.status_code == 404
    assert client.post("/api/knowledge/markdown/query", json={"query": "CSV", "scope": {"typo": "run-a"}}).status_code == 422
    assert client.get("/api/knowledge/status").json()["graph"]["status"] == "retired"


def test_markdown_lifecycle_and_unknown_query_fields_are_explicit(tmp_path, monkeypatch):
    assert importlib.util.find_spec("knowledge.markdown_memory") is not None
    from knowledge.markdown_runtime import store_for
    store = store_for(project_root=tmp_path)
    receipt = store.write_note({"run_id": "run-a", "cycle_id": "loop-000001", "agent_id": "analysis", "event_id": "a",
        "ontology_type": "KnowledgeClaim", "title": "Old procedure", "body": "Old export procedure.", "source_refs": ["log:a"]})
    monkeypatch.setattr(main, "_markdown_store", lambda: store)
    client = TestClient(main.app)
    response = client.post(f"/api/knowledge/markdown/{receipt['record_id']}/status",
                           json={"status": "needs_review", "reason": "Procedure configuration changed"})
    assert response.status_code == 200
    assert client.post("/api/knowledge/markdown/query", json={"query": "procedure"}).json()["hits"] == []
    assert client.post("/api/knowledge/markdown/query", json={"query": "procedure", "arbitrary": True}).status_code == 422


def test_missing_lifecycle_record_is_not_reported_as_http_success(tmp_path, monkeypatch):
    from knowledge.markdown_runtime import store_for
    monkeypatch.setattr(main, "_markdown_store", lambda: store_for(project_root=tmp_path))
    response = TestClient(main.app).post("/api/knowledge/markdown/km-" + "a" * 32 + "/status",
        json={"status": "needs_review", "reason": "Review requested"})
    assert response.status_code == 404


def test_intake_job_runs_off_request_and_exposes_persistent_status(tmp_path, monkeypatch):
    from knowledge.markdown_runtime import store_for
    monkeypatch.setattr(main, "_markdown_store", lambda: store_for(project_root=tmp_path))
    monkeypatch.setattr(main, "KNOWLEDGE_MEMORY_ROOT", tmp_path / "memory" / "knowledge")
    original = main.resolve_path
    monkeypatch.setattr(main, "resolve_path", lambda value: tmp_path / "runs" if value == "runs" else original(value))
    client = TestClient(main.app)
    response = client.post("/api/knowledge/markdown/intake", json={"limit": 1})
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    status = client.get("/api/knowledge/markdown/intake/" + response.json()["job_id"])
    assert status.json()["status"] == "completed"
    assert status.json()["result"]["processed"] == 0
    assert not status.json()["physical_actuation"] and not status.json()["llm_used"]
