"""Graph reconciliation routes retire without constructing workers or proposals."""
from fastapi.testclient import TestClient
import pytest
import app.main as main


@pytest.mark.parametrize("method,path", [
    ("get", "/api/knowledge/relations/status"),
    ("get", "/api/knowledge/relations/proposals"),
    ("get", "/api/knowledge/relations/decisions"),
    ("post", "/api/knowledge/relations/reconcile"),
    ("post", "/api/knowledge/relations/scan"),
    ("post", "/api/knowledge/relations/proposals/proposal-1/decision"),
])
def test_relation_routes_retired_without_worker_or_graph(method, path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Graph reconciliation must not run")
    monkeypatch.setattr(main, "_knowledge_reconciliation_worker", forbidden)
    monkeypatch.setattr(main, "_knowledge_service", forbidden)
    response = getattr(TestClient(main.app), method)(path)
    assert response.status_code == 410
    assert response.json()["component"] == "knowledge_graph"
