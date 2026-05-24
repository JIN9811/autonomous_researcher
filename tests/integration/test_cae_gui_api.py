"""Integration tests for CAE Workspace API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app


def test_cae_config_endpoint_reports_defaults() -> None:
    client = TestClient(app)

    response = client.get("/api/cae/config")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["defaults"]["boundary_condition"] == "bottom_fixed_support"
    assert payload["defaults"]["loading_mode"] == "top_cyclic_loading"


def test_cae_config_endpoint_saves_workspace_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_main, "CAE_WORKSPACE_SETTINGS_PATH", tmp_path / "cae_workspace_settings.json")
    client = TestClient(app_main.app)

    response = client.post(
        "/api/cae/config",
        json={
            "mode": "test",
            "solver": "calculix",
            "mesher": "gmsh",
            "specimen_id": "saved-cae",
            "specimen_size_mm": [25, 24, 23],
            "mesh_size_mm": 1.5,
            "load_max_n": 650,
            "cycles": 22,
            "require_solver": False,
        },
    )
    payload = response.json()
    config = client.get("/api/cae/config").json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert config["saved"]["specimen_id"] == "saved-cae"
    assert config["saved"]["specimen_size_mm"] == [25.0, 24.0, 23.0]
    assert config["saved"]["load_max_n"] == 650.0
    assert config["saved"]["cycles"] == 22


def test_cae_run_endpoint_returns_closed_loop_metrics() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/cae/run",
        json={
            "mode": "test",
            "specimen_id": "api-cae-test",
            "specimen_size_mm": [20, 20, 20],
            "load_max_n": 400,
            "cycles": 12,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    result = payload["result"]
    assert result["boundary_condition"] == "bottom_fixed_support"
    assert result["loading_mode"] == "top_cyclic_loading"
    assert result["cae_metrics"]["max_von_mises_MPa"] > 0
    assert result["closed_loop_source"] is True
