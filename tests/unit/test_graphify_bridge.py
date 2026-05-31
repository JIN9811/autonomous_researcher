"""Tests for Graphify-compatible project scan/import bridge."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge.graph_backend import JsonGraphBackend
from knowledge.graphify_bridge import import_project_graph, load_graphify_graph, scan_project_graph


def _fixture_project(root: Path) -> None:
    (root / "agents").mkdir(parents=True)
    (root / "docs" / "runtime").mkdir(parents=True)
    (root / "graphs" / "modules" / "analysis").mkdir(parents=True)
    (root / "agents" / "analysis_agent.py").write_text(
        "from knowledge.stores import JsonlKnowledgeStore\n\n"
        "def run_analysis():\n"
        "    return 'guardian bo gyroid utm'\n",
        encoding="utf-8",
    )
    (root / "docs" / "runtime" / "analysis.md").write_text("Analysis agent documents UTM and BO handoff.\n", encoding="utf-8")
    (root / "graphs" / "modules" / "analysis" / "module.yaml").write_text("module:\n  id: analysis\n", encoding="utf-8")
    (root / "memory").mkdir()
    (root / "memory" / "prusa_connection.json").write_text('{"password":"do-not-scan"}', encoding="utf-8")


def test_scan_project_graph_writes_graph_report_and_excludes_secrets(tmp_path: Path) -> None:
    _fixture_project(tmp_path)

    result = scan_project_graph(tmp_path, source_paths=["agents", "docs/runtime", "graphs"], out_dir=tmp_path / "memory" / "knowledge" / "graphify")

    assert result["ok"] is True
    graph_json = Path(result["outputs"]["graph_json"])
    report = Path(result["outputs"]["graph_report"])
    assert graph_json.exists()
    assert report.exists()
    graph = json.loads(graph_json.read_text(encoding="utf-8"))
    node_ids = {node["id"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}
    assert "file:agents/analysis_agent.py" in node_ids
    assert "agent:analysis" in node_ids
    assert "module:analysis" in node_ids
    assert "memory/prusa_connection.json" not in json.dumps(graph, ensure_ascii=False)
    assert {"IMPLEMENTS", "DOCUMENTS", "DECLARES"} & edge_types


def test_import_project_graph_to_json_backend(tmp_path: Path) -> None:
    _fixture_project(tmp_path)
    scan = scan_project_graph(tmp_path, source_paths=["agents", "docs/runtime", "graphs"], out_dir=tmp_path / "memory" / "knowledge" / "graphify")
    backend = JsonGraphBackend(tmp_path / "memory" / "knowledge" / "graph_backend" / "knowledge_graph.json")

    result = import_project_graph(backend, Path(scan["outputs"]["graph_json"]), include_runtime_memory=False)

    assert result["ok"] is True
    assert result["project_nodes"] > 0
    assert result["nodes_written"] > 0
    context = backend.query({"kind": "project_context", "target_id": "analysis", "limit": 20})
    assert any(node["id"] == "agent:analysis" or node["id"] == "file:agents/analysis_agent.py" for node in context["nodes"])


def test_load_common_graphify_link_schema(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "a", "type": "Concept", "label": "A"}, {"id": "b", "type": "Concept", "label": "B"}],
                "links": [{"source": "a", "target": "b", "relation": "connects"}],
            }
        ),
        encoding="utf-8",
    )

    graph = load_graphify_graph(graph_path)

    assert {node["id"] for node in graph["nodes"]} == {"graphify:a", "graphify:b"}
    assert graph["edges"][0]["type"] == "CONNECTS"
