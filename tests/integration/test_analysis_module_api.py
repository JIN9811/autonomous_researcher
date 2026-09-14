"""Installed Analysis frontend and report ownership under the no-effects guard."""
from copy import deepcopy

from tests.integration.test_agent_execution_graph_api import actual_controller, module_api


def test_retired_computation_routes_are_absent(module_api):
    client, _, _, guard, _ = module_api
    paths = client.get('/openapi.json').json()['paths']
    assert not any(path.startswith(('/api/cae', '/api/analysis/fem', '/api/self-evolution')) for path in paths)
    assert client.get('/cae').status_code == 404
    assert not guard.denied


def test_analysis_frontend_asset_catalog_and_report_use_installed_owner(module_api):
    client, _, controller, guard, _ = module_api
    module = client.get("/api/modules/analysis").json()
    assert module["implementation"] == controller._deps.agent_registry.get_module("analysis").describe()
    assert module["execution_catalog"]["implementation_structure"]["operations"]["analysis.task"]

    manifest = next(item for item in client.get("/api/runtime/agent-manifests").json()["agents"] if item["id"] == "analysis")
    assert manifest["implementation"]["frontend"] == {
        "host": "/live",
        "descriptor": "graphs/modules/analysis/ui.yaml",
        "asset_url": "/module-assets/analysis/live_report.js",
        "namespace": "AX4LABAnalysisUI",
        "factory": "createFrontend",
        "report_api": "/api/agents/analysis/report",
    }
    assert {key: manifest["renderer"][key] for key in ("dashboard", "report", "fallback")} == {
        "dashboard": "module", "report": "module", "fallback": "descriptor",
    }
    assert "analysis_measured_response" in {card["id"] for card in manifest["cards"]}
    assert not any(card["id"].startswith("analysis_fem_") for card in manifest["cards"])
    asset = client.get(manifest["implementation"]["frontend"]["asset_url"])
    assert asset.status_code == 200
    assert "AX4LABAnalysisUI" in asset.text

    analysis = {
        "ok": True,
        "source": {
            "path": "runs/current/utm.csv",
            "fingerprint": {"sha256": "analysis-full-report"},
            "column_mapping": {"force": "Force", "displacement": "Stroke"},
        },
        "utm_curve": {"preview": [{"displacement_mm": 1.0, "force_N": 20.0}]},
        "utm_metrics": {"peak_force_N": 512.0},
        "quality_gate": {"ok_for_bo": True},
        "cae_result": {"solver": "CalculiX", "status": "completed"},
        "fem_result": {"status": "completed", "peak_force_N": 498.0},
        "fem_agentic_loop": {"status": "queued", "execution": "background", "attempts": [{"attempt_id": "a1"}]},
        "multifidelity_comparison": {"rmse": 0.04},
        "failure_tags": ["none"],
        "closed_loop_sources": ["measurement", "cae"],
        "analysis_artifacts": {"canonical_curve": "/runs/current/curve.json"},
    }
    state = controller._state
    state.latest_analysis = analysis
    state.run_metadata.update(
        analysis_bo_observation={"ok_for_bo": True},
        analysis_bo_handoff={"schema_version": "analysis_bo_handoff_v2", "next_agent": "bo"},
        analysis_metrics={"peak_force_N": 512.0},
    )
    before = deepcopy(state.run_metadata)
    sections = client.get("/api/agents/analysis/report").json()["report"]["sections"]
    assert sections["analysis_report"] == analysis
    assert sections["analysis_report"]["source"]["fingerprint"]["sha256"] == "analysis-full-report"
    assert sections["analysis_report"]["cae_result"]["solver"] == "CalculiX"
    assert sections["analysis_report"]["fem_agentic_loop"]["attempts"][0]["attempt_id"] == "a1"
    assert sections["analysis_report"]["closed_loop_sources"] == ["measurement", "cae"]
    assert "fem" not in sections["role_specific"]
    assert sections["bo_handoff"]["next_agent"] == "bo"
    assert sections["metrics"] == {"peak_force_N": 512.0}
    assert {key: state.run_metadata[key] for key in before} == before
    assert "_projection_state" not in state.run_metadata
    assert guard.physical_call_count == 0
    assert guard.denied == []


def test_inactive_analysis_owner_cannot_serve_its_module_asset(module_api):
    client, _, controller, guard, _ = module_api
    registry = controller._deps.agent_registry
    active = set(registry.active_names()) - {"analysis_agent"}
    registry.bind_activation(lambda: active)
    assert client.get("/module-assets/analysis/live_report.js").status_code == 404
    assert guard.physical_call_count == 0
    assert guard.denied == []


def test_live_host_publishes_current_analysis_frontend_asset_versions(module_api):
    client, _, _, guard, _ = module_api
    live_html = client.get("/live").text
    assert "/static/planning.js?v=" in live_html
    assert "/static/analysis_fem_live." not in live_html
    assert guard.physical_call_count == 0
    assert guard.denied == []
