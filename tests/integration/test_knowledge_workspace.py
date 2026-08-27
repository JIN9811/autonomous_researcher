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
        'data-knowledge-tab="relations"',
        'data-knowledge-tab="manuals"',
        'id="knowledge-graph"',
        'id="knowledge-node-inspector"',
        'id="knowledge-edit-mode"',
        'id="knowledge-edit-toolbar"',
        'id="knowledge-edit-validate"',
        'id="knowledge-edit-apply"',
        'id="knowledge-edit-discard"',
        'id="knowledge-memory-grid"',
        'id="knowledge-ontology-classes"',
        'id="knowledge-sync-result"',
        'id="knowledge-project-graph"',
        'id="knowledge-relation-summary"',
        'id="knowledge-relation-queue"',
        'id="knowledge-relation-context"',
        'id="knowledge-relation-decision"',
        'id="knowledge-relation-history"',
        'id="knowledge-manual-status"',
        'id="knowledge-manual-query"',
        'id="knowledge-manual-results"',
        'id="knowledge-manual-graph"',
        'id="knowledge-manual-inspector"',
        'id="knowledge-manual-show-evidence"',
        "/static/vendor/echarts.min.js",
        "/static/knowledge.js",
        "/static/knowledge.css",
    ]:
        assert required in html


def test_manual_workspace_exposes_semantic_graph_and_inspector() -> None:
    client = TestClient(app)

    response = client.get("/knowledge#manuals")

    assert response.status_code == 200
    html = response.text
    assert 'id="knowledge-manual-graph"' in html
    assert 'id="knowledge-manual-results"' in html
    assert 'id="knowledge-manual-inspector"' in html
    assert 'id="knowledge-manual-show-evidence"' in html


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
        "/api/knowledge/relations/status",
        "/api/knowledge/relations/proposals",
        "/api/knowledge/relations/decisions",
        "/api/knowledge/manuals/status",
        "/api/knowledge/manuals/ingest",
        "/api/knowledge/manuals/query",
        "/api/knowledge/manuals/graph",
        "/api/knowledge/graph/edit/validate",
        "/api/knowledge/graph/edit/apply",
    ]:
        assert endpoint in script
    assert "queryPlan" in script
    assert "provenance_trace" in script
    assert "cypher" not in script.lower()
    assert "grid-template-columns: minmax(0, 7fr) minmax(280px, 3fr);" in styles
    assert ".knowledge-graph-canvas" in styles
    assert ".knowledge-relation-layout" in styles
    assert ".knowledge-edit-toolbar" in styles
    assert "background: #ffffff" in styles
    assert "sessionStorage" in script
    assert "knowledgeGraphEditDraft" in script
