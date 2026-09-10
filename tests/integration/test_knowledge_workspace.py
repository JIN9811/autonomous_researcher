"""Rendered workspace contracts, without production application startup."""

from html.parser import HTMLParser
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

from app.main import app


class WorkspaceControls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.controls = {}
        self.tabs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.controls[attrs["id"]] = (tag, attrs)
        if "data-knowledge-tab" in attrs:
            self.tabs.append(attrs["data-knowledge-tab"])


def test_workspace_has_scoped_markdown_search_and_preserved_evidence_tabs():
    response = TestClient(app).get("/knowledge")  # Deliberately no lifespan context.
    assert response.status_code == 200
    page = WorkspaceControls(response.text)
    assert page.tabs == ["markdown", "memory", "ontology", "manuals"]
    for field in ("query", "run", "cycle", "agent", "type", "fidelity", "status", "tags", "applicability"):
        assert f"knowledge-markdown-{field}" in page.controls
    for control in ("knowledge-markdown-results", "knowledge-markdown-detail", "knowledge-record-count",
                    "knowledge-memory-grid", "knowledge-ontology-classes", "knowledge-activity-chart",
                    "knowledge-manual-results", "knowledge-intake-run", "knowledge-intake-limit"):
        assert control in page.controls


def test_main_dashboard_knowledge_status_uses_markdown_counts():
    client = TestClient(app)
    page = WorkspaceControls(client.get("/").text)
    assert "knowledge-workspace-dot" in page.controls
    script = client.get("/static/app.js").text
    start = script.index("async function refreshKnowledgeWorkspaceStatus()")
    end = script.index("\nasync function ", start + 1)
    function = script[start:end]
    # Execute the real status formatter in isolation: no dashboard/model/device bootstrap.
    runner = """
      const assert = require('node:assert/strict');
      const knowledgeWorkspaceDetailEl = {textContent: ''};
      const knowledgeWorkspaceDotEl = {};
      const urls = [];
      const setDotState = (el, value) => {el.state = value;};
      const fetch = async url => {
        urls.push(url);
        return {ok: true, json: async () => ({ok: true, storage: 'markdown',
          markdown: {ok: true, records: 7, revisions: 9, status_counts: {valid: 5, needs_review: 2}, index: {errors: []}},
          graph: {enabled: false, status: 'retired'}})};
      };
    """ + function + """
      refreshKnowledgeWorkspaceStatus().then(() => {
        assert.deepEqual(urls, ['/api/knowledge/status']);
        assert.equal(knowledgeWorkspaceDotEl.state, 'active');
        assert.match(knowledgeWorkspaceDetailEl.textContent, /7 records/);
        assert.match(knowledgeWorkspaceDetailEl.textContent, /2 needs review/);
        assert.doesNotMatch(knowledgeWorkspaceDetailEl.textContent, /graph|nodes|edges|neo4j/i);
      });
    """
    result = subprocess.run(["node", "-e", runner], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_workspace_browser_scopes_details_and_retains_manual_citations(tmp_path):
    # Only templates, assets and temporary fixture APIs, never app.main lifespan.
    import runpy
    audit = runpy.run_path(str(Path(__file__).parents[1] / "ui" / "knowledge_workspace_browser_audit.py"))
    with audit["fixture_server"](tmp_path / "fixture") as base_url:
        result = audit["audit"](base_url, tmp_path / "screenshots")
    assert result["ok"]
    assert result["retired_requests"] == []
    assert result["console_errors"] == []
    assert result["viewports"] == [1440, 390]
