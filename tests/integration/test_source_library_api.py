"""Real source routes with isolated storage, never the production lifespan."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    from knowledge.source_library import SourceLibrary
    from knowledge.source_runtime import SourceIngestionService
    from knowledge.source_api import install_source_routes
    app = FastAPI()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    service = SourceIngestionService(SourceLibrary(tmp_path / "library", inbox), lambda: None)
    install_source_routes(app, service_factory=lambda: service)
    return TestClient(app)


def test_status_and_settings(client):
    assert client.get("/api/knowledge/sources/status").json()["enabled"] is False
    assert client.post("/api/knowledge/sources/settings", json={"enabled": True}).json()["enabled"]
    assert client.post("/api/knowledge/sources/settings", json={"enabled": "false"}).status_code == 422


def test_query_scope_and_arbitrary_paths_are_rejected(client):
    assert client.post("/api/knowledge/sources/query", json={
        "query": "threshold", "scope": {"unknown_filter": "x"}}).status_code == 422
    assert client.post("/api/knowledge/sources/query", json={"query": "", "root": "/tmp"}).status_code == 422
    assert client.post("/api/knowledge/sources/read", json={"record_id": "missing"}).status_code in {404, 422}


def test_scan_does_not_invoke_model(client):
    assert client.post("/api/knowledge/sources/scan").status_code == 200
    assert client.post("/api/knowledge/sources/query", json={"query": "", "scope": {"tags": []}}).json()["hits"] == []
