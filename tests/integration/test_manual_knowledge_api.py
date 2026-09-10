"""Legacy manual endpoints retire explicitly without reading historical files."""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main


@pytest.mark.parametrize("method,path", [
    ("get", "status"), ("post", "ingest"), ("post", "query"), ("get", "graph"),
])
def test_manual_api_is_retired_without_opening_old_service(monkeypatch, method, path):
    def tripwire():
        pytest.fail("Retired endpoint opened the old manual service")
    monkeypatch.setattr(app_main, "_manual_knowledge_service", tripwire)
    client = TestClient(app_main.app)  # Never enter production lifespan.
    response = getattr(client, method)(f"/api/knowledge/manuals/{path}")
    assert response.status_code == 410
    assert response.json()["status"] == "retired"
    assert response.json()["replacement"] == "/api/knowledge/sources/status"


def test_legacy_context_reports_retirement_without_querying_old_corpus(monkeypatch):
    def tripwire():
        pytest.fail("Compatibility context opened the retired corpus")
    monkeypatch.setattr(app_main, "_manual_knowledge_service", tripwire)
    context = app_main._manual_knowledge_context("reference", purpose="recovery")
    assert context["status"] == "retired" and context["chunks"] == []
    assert context["insufficient_evidence"] is True
