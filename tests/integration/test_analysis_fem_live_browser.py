"""Offline browser contract: background cards never execute Analysis or hardware."""
import base64
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest


def test_background_cards_update_in_place_and_navigate_without_solver_calls():
    playwright = pytest.importorskip("playwright.sync_api")
    root = Path(__file__).resolve().parents[2]
    pointer = {"job_id": "j1", "run_id": "r1", "loop_key": "r1:loop-0", "specimen_id": "s1", "status": "queued"}
    curve = [{"displacement_mm": 0, "force_N": 0}, {"displacement_mm": 2, "force_N": 40}]
    analysis = {"fem_job": pointer, "utm_curve": {"preview": curve}, "specimen_geometry": {"gauge_length_mm": 10, "cross_section_area_mm2": 20}}
    attempt = {"attempt_id": "a1", "curve": curve, "field_asset_path": "runs/fixture/a.fields.json", "endpoint_reached": False,
               "mesh_size_mm": 1.2, "mesh_quality": {"valid": True}, "solver_status": "partial", "comparison": {"end_mm": 2, "rmse_N": 0}}
    payload = {"jobs": [{**pointer, "experiment_curve": curve, "specimen_geometry": analysis["specimen_geometry"], "attempts": [], "events": [], "progress": {}}]}
    requests, errors = [], []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1400, "height": 1200})
        page.on("pageerror", lambda err: errors.append(str(err)))

        def serve(route):
            requests.append((route.request.method, route.request.url))
            path = urlparse(route.request.url).path
            if path == "/":
                route.fulfill(content_type="text/html", body='<meta charset="UTF-8"><link rel="stylesheet" href="/static/analysis_fem_live.css"><main id="cards"></main><script src="/static/analysis_fem_live.js"></script>')
            elif path.startswith("/static/"):
                route.fulfill(path=str(root / "web" / path.lstrip("/")))
            elif path == "/api/analysis/fem/jobs":
                route.fulfill(content_type="application/json", body=json.dumps(payload))
            elif path == "/api/cae/fields/metadata":
                route.fulfill(content_type="application/json", body=json.dumps({"frames": [
                    {"frame_index": 0, "time": .1, "step": 1, "fields": {"S_MISES": {"units": "MPa"}, "U": {"units": "mm"}}},
                    {"frame_index": 1, "time": .2, "step": 1, "fields": {"S_MISES": {"units": "MPa"}, "U": {"units": "mm"}}}]}))
            elif path == "/api/cae/fields/render":
                # Transport fixture only, not a synthetic claim of engineering evidence.
                route.fulfill(content_type="image/png", body=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="))
            else:
                route.fulfill(status=404, body="not found")

        page.route("http://fem.local/**", serve)
        page.goto("http://fem.local/")
        page.evaluate("""analysis => {
          window.fem = AnalysisFemLive.createController(); fem.setContext(analysis);
          document.querySelector('#cards').innerHTML = fem.html();
          fem.mount(document.querySelector('.analysis-fem-live'));
        }""", analysis)
        assert page.locator("[data-fem-card]").count() == 4
        assert page.locator('[data-fem-body="overlay"] [data-series="experiment"]').count() == 1
        page.evaluate("fem.poll()")
        payload["jobs"][0].update(status="running", attempts=[attempt, {**attempt, "attempt_id": "a2", "field_asset_path": "runs/fixture/b.fields.json"}])
        page.evaluate("fem.poll()")
        page.wait_for_selector(".fem-contour-image")
        page.evaluate("window.firstImage = document.querySelector('.fem-contour-image')")
        renders_before = len([url for _, url in requests if "/fields/render?" in url])
        payload["jobs"][0]["progress"] = {"phase": "convergence", "elapsed_s": 42}
        page.evaluate("fem.poll()")
        assert page.evaluate("firstImage === document.querySelector('.fem-contour-image')")
        assert len([url for _, url in requests if "/fields/render?" in url]) == renders_before
        assert "convergence" in page.locator('[data-fem-card="agentic"]').inner_text()
        page.locator('[data-fem-card="response"] [data-fem-nav="attempt"][data-step="1"]').click()
        assert "a2" in page.locator('[data-fem-body="response"]').inner_text()
        page.locator('[data-fem-nav="contour"][data-step="1"]').click()
        assert "frame=1" in page.locator(".fem-contour-image").get_attribute("src")
        page.locator('[data-fem-field="U"]').click()
        assert "field=U" in page.locator(".fem-contour-image").get_attribute("src")
        assert page.locator("[data-fem-card]").count() == 4
        page.screenshot(path="/tmp/atr-analysis-fem-live-fixture.png", full_page=True)
        page.evaluate("""analysis => {
          fem.setContext({...analysis, fem_job: {...analysis.fem_job, job_id: 'j2', loop_key: 'r1:loop-1'}});
          document.querySelector('#cards').innerHTML = fem.html(); fem.mount(document.querySelector('.analysis-fem-live'));
        }""", analysis)
        page.evaluate("fem.poll()")  # API still returns loop-0; the new loop must reject it.
        assert page.locator(".fem-contour-image").count() == 0
        assert page.locator('[data-series="fem"]').count() == 0
        assert errors == []
        assert all(method == "GET" for method, _ in requests)
        assert not any("/api/cae/fields?" in url or "/cancel" in url or "/equipment" in url for _, url in requests)
        browser.close()
