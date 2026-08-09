"""Integration tests for BO Workspace API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app


def test_bo_workspace_contains_objective_compiler_surfaces() -> None:
    client = TestClient(app)

    response = client.get("/bo")

    assert response.status_code == 200
    html = response.text
    for element_id in (
        "objective-compiler-workspace",
        "objective-intent-input",
        "objective-metric-browser",
        "objective-equation-tree",
        "objective-validation-panel",
        "objective-preview-panel",
        "objective-version-diff",
        "btn-objective-compose",
        "btn-objective-validate",
        "btn-objective-preview",
        "btn-objective-approve",
        "btn-objective-activate",
    ):
        assert f'id="{element_id}"' in html
    assert "objective-template" not in html


def test_bo_config_endpoint_reports_defaults() -> None:
    client = TestClient(app)

    response = client.get("/api/bo/config")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["defaults"]["strategy"] == "bo"
    assert "expected_improvement" in payload["defaults"]["supported_acquisitions"]


def test_bo_config_endpoint_saves_workspace_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_main, "BO_WORKSPACE_SETTINGS_PATH", tmp_path / "bo_workspace_settings.json")
    client = TestClient(app_main.app)

    response = client.post(
        "/api/bo/config",
        json={
            "strategy": "bo",
            "acquisition": "upper_confidence_bound",
            "budget": 6,
            "random_seed": 17,
            "bo_backend": "botorch_optional",
            "parameter_space": {"geometry_type": ["gyroid"], "relative_density": [0.22, 0.42]},
            "objective": {"objective_id": "saved-bo", "metric_name": "objective_score", "direction": "maximize"},
        },
    )
    payload = response.json()
    config = client.get("/api/bo/config").json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert config["saved"]["acquisition"] == "upper_confidence_bound"
    assert config["saved"]["budget"] == 6
    assert config["saved"]["bo_backend"] == "botorch_optional"
    assert config["saved"]["objective"]["objective_id"] == "saved-bo"


def test_bo_benchmark_endpoint_runs_virtual_bo() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/bo/benchmark",
        json={
            "strategy": "bo",
            "acquisition": "expected_improvement",
            "budget": 3,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "relative_density": [0.2, 0.4],
                "wall_thickness_mm": [1.2, 2.0],
                "cell_size_mm": [5.0, 8.0],
            },
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert "bo" in payload["benchmark"]["strategies"]
    assert len(payload["benchmark"]["strategies"]["bo"]["curve"]) == 3
    assert len(payload["benchmark"]["strategies"]["bo"]["surrogate_trace"]) == 3
    assert payload["benchmark"]["strategies"]["bo"]["surrogate_trace"][0]["selected"]["parameters"]
    assert any(
        event.get("type") == "tool.completed"
        and event.get("node_id") == "bo"
        and event.get("payload", {}).get("workspace") == "bo"
        for event in app_main.controller.recent_events()
    )


def test_bo_benchmark_endpoint_maps_reasoning_strategy_to_bo_backend() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/bo/benchmark",
        json={
            "strategy": "llm_preference_bo",
            "acquisition": "upper_confidence_bound",
            "budget": 2,
            "bo_backend": "botorch_optional",
            "llm_preference_enabled": True,
            "llm_candidate_weight": "auto",
            "top_k": 4,
            "parameter_space": {
                "geometry_type": ["gyroid"],
                "relative_density": [0.2, 0.42],
                "wall_thickness_mm": [1.2, 1.8],
                "cell_size_mm": [10.0],
            },
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert set(payload["benchmark"]["strategies"]) == {"bo"}
    assert payload["benchmark"]["bo_backend_requested"] == "botorch_optional"
    assert payload["benchmark"]["strategies"]["bo"]["surrogate_trace"][0]["acquisition"] == "upper_confidence_bound"


def test_bo_run_endpoint_returns_recommendation() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/bo/run",
        json={
            "strategy": "mbo",
            "acquisition": "uncertainty_sampling",
            "budget": 2,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["data"]["bo_result"]["recommendation"]["candidate_id"]
    assert payload["data"]["bo_result"]["recommendation"]["parameters"]
    assert any(
        event.get("type") == "node.completed"
        and event.get("node_id") == "bo"
        and event.get("payload", {}).get("module_runtime", {}).get("direct_workspace_api") is True
        for event in app_main.controller.recent_events()
    )
    run_id = payload["snapshot"]["state"]["run_id"]
    artifacts = client.get(f"/api/runs/{run_id}/artifacts").json()["artifacts"]
    artifact_paths = {item["path"] for item in artifacts}
    assert any(path.startswith("workspace/bo/") and path.endswith("_result.json") for path in artifact_paths)
    assert any(path.startswith("workspace/bo/") and path.endswith("_bo_progress.svg") for path in artifact_paths)
    assert any(
        event.get("type") == "artifact.created"
        and event.get("payload", {}).get("artifact", {}).get("path") in artifact_paths
        for event in app_main.controller.recent_events()
    )
