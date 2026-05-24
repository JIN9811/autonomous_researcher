"""Integration tests for BO Workspace API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app


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
