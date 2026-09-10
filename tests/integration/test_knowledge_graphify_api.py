"""Retired graph imports cannot scan or write historical project data."""
from fastapi.testclient import TestClient
import pytest
import app.main as main


@pytest.mark.parametrize("path", ["/api/knowledge/graphify/scan", "/api/knowledge/graphify/import"])
def test_graphify_routes_retired_even_with_legacy_flags(tmp_path, monkeypatch, path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Retired graph factory invoked")
    monkeypatch.setattr(main, "_knowledge_graph_backend", forbidden)
    monkeypatch.setenv("ATR_KNOWLEDGE_GRAPH_ENABLED", "1")
    monkeypatch.setenv("ATR_KNOWLEDGE_GRAPH_BACKEND", "neo4j")
    response = TestClient(main.app).post(path, json={"sources": ["agents"]})
    assert response.status_code == 410
    assert response.json()["status"] == "retired"
    assert not list(tmp_path.iterdir())
