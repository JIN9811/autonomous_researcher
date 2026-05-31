"""Integration tests for Graphify-compatible Knowledge graph API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app


def test_graphify_scan_and_import_api_uses_json_backend(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "agents").mkdir(parents=True)
    (tmp_path / "docs" / "runtime").mkdir(parents=True)
    (tmp_path / "agents" / "analysis_agent.py").write_text("def run():\n    return 'analysis bo guardian'\n", encoding="utf-8")
    (tmp_path / "docs" / "runtime" / "analysis.md").write_text("Analysis agent runtime docs.\n", encoding="utf-8")
    monkeypatch.setattr(app_main, "KNOWLEDGE_MEMORY_ROOT", tmp_path / "memory" / "knowledge")

    def _resolve(value: str) -> Path:
        if value == ".":
            return tmp_path
        if value == "runs":
            return tmp_path / "runs"
        return (tmp_path / value).resolve() if not Path(value).is_absolute() else Path(value)

    monkeypatch.setattr(app_main, "resolve_path", _resolve)
    monkeypatch.setenv("ATR_KNOWLEDGE_GRAPH_ENABLED", "1")
    monkeypatch.setenv("ATR_KNOWLEDGE_GRAPH_BACKEND", "json")
    client = TestClient(app)

    scan = client.post("/api/knowledge/graphify/scan", json={"sources": ["agents", "docs/runtime"], "max_file_bytes": 10000}).json()
    assert scan["ok"] is True
    assert scan["node_count"] > 0
    assert Path(scan["outputs"]["graph_json"]).exists()

    imported = client.post("/api/knowledge/graphify/import", json={"include_runtime_memory": False}).json()
    assert imported["ok"] is True
    assert imported["project_nodes"] > 0
    assert imported["nodes_written"] > 0

    query = client.get("/api/knowledge/graph/query?kind=project_context&target_id=analysis&limit=20").json()
    assert any(node["id"] == "agent:analysis" or node["id"] == "file:agents/analysis_agent.py" for node in query["nodes"])
