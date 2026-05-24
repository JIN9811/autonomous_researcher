"""
Integration tests for API documentation helper endpoints.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_agent_baseline_json_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/docs/agent-baseline")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "agent_program_baseline"
    assert payload["path"].endswith("docs/runtime/agent_program_baseline.md")
    assert "Agent Program Integration Baseline" in payload["content"]


def test_agent_baseline_markdown_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/docs/agent-baseline.md")
    assert response.status_code == 200
    assert "Agent Program Integration Baseline" in response.text
