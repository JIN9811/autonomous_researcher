from fastapi.testclient import TestClient

from app.main import app


def test_knowledge_workspace_exposes_graph_ontology_memory_and_sync_surfaces() -> None:
    client = TestClient(app)

    response = client.get("/knowledge")

    assert response.status_code == 200
    html = response.text
    for required in [
        "Knowledge Workspace",
        'id="knowledge-backend-status"',
        'id="knowledge-node-count"',
        'data-knowledge-tab="graph"',
        'data-knowledge-tab="memory"',
        'data-knowledge-tab="ontology"',
        'data-knowledge-tab="sync"',
        'data-knowledge-tab="project"',
        'id="knowledge-graph"',
        'id="knowledge-node-inspector"',
        'id="knowledge-memory-grid"',
        'id="knowledge-ontology-classes"',
        'id="knowledge-sync-result"',
        'id="knowledge-project-graph"',
        "/static/vendor/echarts.min.js",
        "/static/knowledge.js",
        "/static/knowledge.css",
    ]:
        assert required in html


def test_main_dashboard_links_knowledge_workspace_and_reads_real_status() -> None:
    client = TestClient(app)

    html = client.get("/").text
    script = client.get("/static/app.js").text

    assert 'id="knowledge-workspace-dot"' in html
    assert 'id="knowledge-workspace-detail"' in html
    assert 'href="/knowledge"' in html
    assert "refreshKnowledgeWorkspaceStatus" in script
    assert 'fetch("/api/knowledge/graph/stats")' in script


def test_knowledge_workspace_uses_only_bounded_knowledge_apis() -> None:
    client = TestClient(app)

    script = client.get("/static/knowledge.js").text
    styles = client.get("/static/knowledge.css").text

    for endpoint in [
        "/api/knowledge/graph/stats",
        "/api/knowledge/graph/query",
        "/api/knowledge/ontology",
        "/api/knowledge/graph/sync",
        "/api/knowledge/activity",
        "/api/knowledge/agent-performance",
        "/api/knowledge/failure-patterns",
        "/api/knowledge/success-patterns",
        "/api/knowledge/evolution-packs",
    ]:
        assert endpoint in script
    assert "queryPlan" in script
    assert "provenance_trace" in script
    assert "cypher" not in script.lower()
    assert "grid-template-columns: minmax(0, 7fr) minmax(280px, 3fr);" in styles
    assert ".knowledge-graph-canvas" in styles
    assert "background: #ffffff" in styles
