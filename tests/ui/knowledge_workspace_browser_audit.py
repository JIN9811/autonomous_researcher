"""Safe Markdown workspace audit: real temporary store/API, no production lifespan."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import tempfile
import threading
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import expect, sync_playwright
import uvicorn

from knowledge.http_api import install_markdown_routes, retire_graph_routes
from knowledge.markdown_runtime import store_for


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def fixture_server(root: Path):
    """Only safe local HTTP contracts; raw archive directory is empty and temporary."""
    store = store_for(project_root=root)
    common = dict(cycle_id="loop-000001", agent_id="analysis", ontology_type="Observation",
                  source_refs=["runs/run-a/analysis/result.json"], evidence_kind="observed", fidelity="virtual",
                  tags=["export"], applicability={"equipment": "utm"})
    store.write_note(dict(common, run_id="run-a", event_id="a", title="Scoped export evidence",
                          body="Verified CSV export. " + "Observed evidence. " * 40 + "DETAIL ONLY MARKER"))
    store.write_note(dict(common, run_id="run-b", event_id="b", title="Other run export",
                          body="CSV export from another run."))
    store.write_note(dict(common, run_id="run-a", event_id="review", title="Review export evidence",
                          body="CSV export requires review.", status="needs_review"))
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=ROOT / "web" / "static"), name="static")
    template = Environment(loader=FileSystemLoader(ROOT / "web" / "templates"), autoescape=True)

    @app.get("/knowledge", response_class=HTMLResponse)
    def workspace():
        return template.get_template("knowledge.html").render(title="Knowledge Workspace")

    @app.get("/api/knowledge/ontology")
    def ontology():
        return {"version_id": "audit-ontology", "classes": ["Observation", "KnowledgeClaim"],
                "relations": {"DERIVED_FROM": {"domain": ["KnowledgeClaim"], "range": ["Observation"]}}}

    @app.get("/api/knowledge/agent-performance")
    @app.get("/api/knowledge/failure-patterns")
    @app.get("/api/knowledge/success-patterns")
    def records():
        return {"ok": True, "records": [{"summary": "Preserved typed memory evidence"}]}

    @app.get("/api/knowledge/evolution-packs")
    def evolution():
        return {"ok": True, "packs": [{"summary": "Preserved Evolution evidence"}]}

    @app.get("/api/knowledge/activity")
    def activity():
        return {"ok": True, "cycles": [{"cycle_id": "loop-000001", "collected": 3, "updated": 1,
                                        "retrieved": 2, "used": 1}]}

    @app.get("/api/knowledge/manuals/status")
    @app.post("/api/knowledge/manuals/ingest")
    def manual_status():
        return {"ok": True, "status": "ready", "source_count": 1, "chunk_count": 2, "equipment_type": "utm"}

    @app.post("/api/knowledge/manuals/query")
    def manual_query():
        return {"ok": True, "schema": "manual_context.v1", "coverage": 0.8, "insufficient_evidence": False,
                "chunks": [{"chunk_id": "manual-utm-p42", "page": 42, "text": "Check the communication cable before retrying.",
                            "score": 0.8, "citation": {"source_id": "utm-manual", "title": "UTM Operator Manual",
                                                       "page": 42, "section_path": ["Recovery", "Communication"]}}]}

    install_markdown_routes(app, store_factory=lambda: store, run_root_factory=lambda: root / "runs",
                            memory_root_factory=lambda: root / "memory" / "knowledge")
    retire_graph_routes(app)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            if not server.started:
                raise AssertionError("Lightweight fixture failed to start")
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def audit(base_url: str, screenshot_path: Path) -> dict[str, object]:
    screenshot_path.mkdir(parents=True, exist_ok=True)
    errors, retired_requests, requests, screenshots = [], [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in (1440, 390):
                page = browser.new_page(viewport={"width": width, "height": 1000 if width == 1440 else 844})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(message.text) if message.type in {"error", "warning"} else None)

                def record_request(request):
                    if "/api/knowledge/" in request.url:
                        requests.append({"url": request.url, "body": request.post_data_json if request.post_data else None})
                    if any(part in request.url for part in ("/knowledge/graph", "/knowledge/relations", "/manuals/graph")):
                        retired_requests.append(request.url)

                page.on("request", record_request)
                page.goto(f"{base_url}/knowledge")
                expect(page).to_have_title("Knowledge Workspace")
                expect(page.locator("h1")).to_have_text("Knowledge Workspace")
                expect(page.locator("#knowledge-backend-status")).to_have_text("Markdown")
                expect(page.locator("#knowledge-record-count")).to_have_text("3")
                expect(page.locator("#knowledge-markdown-results button")).to_have_count(2)
                assert page.locator("[data-knowledge-tab]").all_text_contents() == ["Markdown Knowledge", "Memory", "Ontology", "Manual RAG Knowledge"]
                assert not page.locator("vite-error-overlay, nextjs-portal, #webpack-dev-server-client-overlay").count()
                assert "neo4j" not in page.locator(".knowledge-status-strip").inner_text().lower()
                for control, value in (("run", "run-a"), ("cycle", "loop-000001"), ("agent", "analysis"),
                                       ("tags", "export"), ("applicability", '{"equipment":"utm"}')):
                    page.locator(f"#knowledge-markdown-{control}").fill(value)
                page.locator("#knowledge-markdown-type").select_option("Observation")
                page.locator("#knowledge-markdown-fidelity").select_option("virtual")
                page.locator("#knowledge-markdown-query").fill("CSV")
                page.locator("#knowledge-run-query").click()
                expect(page.locator("#knowledge-markdown-results button")).to_have_count(1)
                expect(page.locator("#knowledge-markdown-results")).not_to_contain_text("DETAIL ONLY MARKER")
                query_request = [request for request in requests if request["url"].endswith("/markdown/query")][-1]
                assert query_request["body"]["scope"] == {"run_id": "run-a", "cycle_id": "loop-000001", "agent_id": "analysis",
                    "ontology_type": "Observation", "fidelity": "virtual", "status": "valid", "tags": ["export"],
                    "applicability": {"equipment": "utm"}}
                page.locator("#knowledge-markdown-results button").click()
                expect(page.locator("#knowledge-markdown-detail")).to_contain_text("DETAIL ONLY MARKER")
                expect(page.locator("#knowledge-markdown-detail")).to_contain_text("runs/run-a/analysis/result.json")
                read_request = [request for request in requests if request["url"].endswith("/markdown/read")][-1]
                assert read_request["body"]["scope"]["run_id"] in ("run-a", ["run-a"])
                assert read_request["body"]["scope"]["status"] in ("valid", ["valid"])
                shot = screenshot_path / f"knowledge-markdown-{width}.png"
                page.screenshot(path=str(shot), full_page=width == 390)
                screenshots.append(str(shot))
                # Invalid filter JSON must not silently expand to an unfiltered request.
                page.locator("#knowledge-markdown-applicability").fill("invalid JSON")
                before = len([request for request in requests if request["url"].endswith("/markdown/query")])
                page.locator("#knowledge-run-query").click()
                expect(page.locator("#knowledge-runtime-message")).to_contain_text("Applicability")
                assert len([request for request in requests if request["url"].endswith("/markdown/query")]) == before
                page.locator("#knowledge-markdown-applicability").fill('{"equipment":"utm"}')
                page.locator("#knowledge-markdown-status").select_option("needs_review")
                page.locator("#knowledge-run-query").click()
                expect(page.locator("#knowledge-markdown-results")).to_contain_text("Review export evidence")
                expect(page.locator("#knowledge-markdown-detail")).not_to_contain_text("DETAIL ONLY MARKER")
                page.locator("#knowledge-markdown-results button").click()
                expect(page.locator("#knowledge-markdown-detail")).to_contain_text("CSV export requires review")
                page.locator("#knowledge-markdown-run").fill("missing-run")
                page.locator("#knowledge-run-query").click()
                expect(page.locator("#knowledge-markdown-results")).to_contain_text("No knowledge records")
                page.locator("#knowledge-intake-controls summary").click()
                page.locator("#knowledge-intake-run").fill("run-a")
                page.locator("#knowledge-intake-limit").fill("1")
                page.locator("#knowledge-intake-start").click()
                expect(page.locator("#knowledge-intake-result")).to_contain_text("completed", timeout=10000)
                intake = [request for request in requests if request["url"].endswith("/markdown/intake")][-1]
                assert intake["body"] == {"run_id": "run-a", "limit": 1, "cursor": ""}
                job_id = page.locator("#knowledge-intake-job").input_value()
                assert len(job_id) == 32
                page.reload()
                expect(page.locator("#knowledge-intake-job")).to_have_value(job_id)
                page.locator("#knowledge-intake-controls summary").click()
                page.locator("#knowledge-intake-refresh").click()
                expect(page.locator("#knowledge-intake-result")).to_contain_text("completed")
                for tab in ("memory", "ontology", "manuals"):
                    page.locator(f'[data-knowledge-tab="{tab}"]').click()
                    expect(page.locator(f'[data-knowledge-panel="{tab}"]')).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), f"Overflow in {tab} at {width}px"
                    if tab == "memory":
                        expect(page.locator("#knowledge-memory-grid")).to_contain_text("Evolution packs")
                        expect(page.locator("#knowledge-memory-grid")).to_contain_text("Preserved typed memory evidence")
                    if tab == "ontology":
                        expect(page.locator("#knowledge-ontology-classes")).to_contain_text("Observation")
                page.locator("#knowledge-manual-purpose").select_option("recovery")
                page.locator("#knowledge-manual-ingest").click()
                expect(page.locator("#knowledge-runtime-message")).to_contain_text("Manual ingestion complete")
                page.locator("#knowledge-manual-query").fill("Communication recovery")
                page.locator("#knowledge-manual-run-query").click()
                expect(page.locator("#knowledge-manual-results")).to_contain_text("p.42")
                expect(page.locator("#knowledge-manual-results")).to_contain_text("UTM Operator Manual")
                expect(page.locator("#knowledge-manual-results")).to_contain_text("Recovery > Communication")
                shot = screenshot_path / f"knowledge-manual-{width}.png"
                page.screenshot(path=str(shot), full_page=width == 390)
                screenshots.append(str(shot))
                page.locator('[data-knowledge-tab="markdown"]').click()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), f"Overflow at {width}px"
                assert page.url.endswith("/knowledge#markdown")
                page.close()
            assert not errors, errors
            assert not retired_requests, retired_requests
            return {"ok": True, "url": f"{base_url}/knowledge", "viewports": [1440, 390], "console_errors": errors,
                    "retired_requests": retired_requests, "screenshots": screenshots,
                    "browser": "Browser plugin not available; installed Python Playwright Chromium"}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", help="Use an existing safe fixture; omitted starts the isolated fixture")
    parser.add_argument("--screenshot-dir", type=Path, default=Path(tempfile.gettempdir()) / "knowledge-workspace-audit")
    args = parser.parse_args()
    if args.base_url:
        result = audit(args.base_url.rstrip("/"), args.screenshot_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="knowledge-ui-") as root:
            with fixture_server(Path(root)) as base_url:
                result = audit(base_url, args.screenshot_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
