"""Installed BO frontend, package and report ownership under the no-effects guard."""
from copy import deepcopy

from tests.integration.test_agent_execution_graph_api import actual_controller, module_api


def test_bo_frontend_asset_package_catalog_and_report_use_installed_owner(module_api):
    client, _, controller, guard, _ = module_api
    module = client.get("/api/modules/bo").json()
    assert module["implementation"] == controller._deps.agent_registry.get_module("bo").describe()
    assert {item["handler"] for item in module["execution_catalog"]["operations"]} == {
        "bo.task", "bo.deliver",
    }
    assert module["execution_catalog"]["implementation_structure"]["operations"]["bo.task"]

    manifest = next(
        item for item in client.get("/api/runtime/agent-manifests").json()["agents"]
        if item["id"] == "bo"
    )
    assert manifest["implementation"]["frontend"] == {
        "host": "/live",
        "descriptor": "graphs/modules/bo/ui.yaml",
        "asset_url": "/module-assets/bo/live_report.js",
        "namespace": "AX4LABBOUI",
        "factory": "createFrontend",
        "report_api": "/api/agents/bo/report",
    }
    assert {key: manifest["renderer"][key] for key in ("dashboard", "report", "fallback")} == {
        "dashboard": "module", "report": "module", "fallback": "descriptor",
    }
    assert [card["id"] for card in manifest["cards"]][:3] == [
        "bo_objective_equation", "bo_live_posterior", "bo_initial_design",
    ]
    asset = client.get(manifest["implementation"]["frontend"]["asset_url"])
    assert asset.status_code == 200
    assert "AX4LABBOUI" in asset.text

    package = next(
        item for item in client.get("/api/packages").json()["agent_packages"]
        if item["id"] == "bo"
    )
    assert package["handler"] == "agent.bo_agent"
    assert package["bridge_modules"] == []

    bo_result = {
        "ok": True,
        "run_id": controller._state.run_id,
        "strategy": "bo",
        "acquisition": "expected_improvement",
        "optimization_phase": "acquisition",
        "decision": {"schema": "bo_decision.v1", "status": "accepted"},
        "prior_summary": {"prior_count": 4, "measured_count": 3, "failed_count": 1},
        "candidate_ranking": [{"candidate_id": "candidate-current", "combined_score": 0.82}],
        "recommendation": {"candidate_id": "candidate-current", "parameters": {"cell_size_mm": 7.2}},
        "next_design_request": {
            "schema": "next_design_request.v1", "run_id": controller._state.run_id,
            "status": "ready", "consumer_agent": "design_agent",
        },
        "lhs_visualization": {"schema": "lhs_design_visualization.v1", "step": 4},
        "visualization": {"schema": "bo_visualization.v1", "step": 9},
        "artifacts": {"bo_decision": "/runs/current/bo/bo_decision.json"},
    }
    state = controller._state
    state.run_metadata.update(
        bo_agent=bo_result,
        next_design_request=bo_result["next_design_request"],
        bo_agent_payload={"bo_result": {"run_id": "stale-payload"}},
    )
    before = deepcopy(state.run_metadata)
    report = client.get(f"/api/agents/bo/report?run_id={state.run_id}")
    assert report.status_code == 200
    sections = report.json()["report"]["sections"]
    assert sections["bo_result"] == bo_result
    assert sections["bo_result"]["candidate_ranking"][0]["candidate_id"] == "candidate-current"
    assert sections["role_specific"]["lhs_visualization"]["step"] == 4
    assert sections["role_specific"]["visualization"]["step"] == 9
    assert sections["next_design_request"]["consumer_agent"] == "design_agent"
    assert sections["metrics"]["candidate_count"] == 1
    assert {key: state.run_metadata[key] for key in before} == before
    assert "_projection_state" not in state.run_metadata
    assert guard.physical_call_count == 0
    assert guard.denied == []


def test_inactive_bo_owner_cannot_serve_its_module_asset(module_api):
    client, _, controller, guard, _ = module_api
    registry = controller._deps.agent_registry
    active = set(registry.active_names()) - {"bo_agent"}
    registry.bind_activation(lambda: active)
    assert client.get("/module-assets/bo/live_report.js").status_code == 404
    assert guard.physical_call_count == 0
    assert guard.denied == []


def test_bo_report_uses_owner_payload_when_compact_metadata_is_absent(module_api):
    client, _, controller, guard, _ = module_api
    state = controller._state
    bo_result = {
        "run_id": state.run_id,
        "candidate_ranking": [{"candidate_id": "payload-candidate"}],
        "recommendation": {"candidate_id": "payload-candidate"},
    }
    state.run_metadata.pop("bo_agent", None)
    state.run_metadata["bo_agent_payload"] = {"bo_result": bo_result}

    report = client.get(f"/api/agents/bo/report?run_id={state.run_id}")

    assert report.status_code == 200
    sections = report.json()["report"]["sections"]
    assert sections["bo_result"] == bo_result
    assert sections["role_specific"]["candidate_ranking"] == bo_result["candidate_ranking"]
    assert guard.physical_call_count == 0
    assert guard.denied == []


def test_live_host_publishes_current_bo_frontend_asset_version(module_api):
    client, _, _, guard, _ = module_api
    assert "/static/planning.js?v=20260914-bo-owner-1" in client.get("/live").text
    assert guard.physical_call_count == 0
    assert guard.denied == []
