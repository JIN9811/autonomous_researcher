"""Integration tests for the bounded Objective Compiler API."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import main as app_main
from backends.llm_backend import LLMResponse
from objectives.metric_registry import MetricRegistry
from objectives.service import ObjectiveService
from objectives.store import ObjectiveStore


class _ComposerContext:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def complete(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(text=json.dumps(self.payload), model="fake-composer")


def spec(*, unsafe: bool = False, incompatible: bool = False) -> dict:
    if incompatible:
        expression = {
            "op": "add",
            "args": [
                {"op": "metric", "metric_id": "compressive_strength_mpa"},
                {"op": "metric", "metric_id": "displacement_at_peak_mm"},
            ],
        }
    else:
        expression = {
            "op": "metric",
            "metric_id": "compressive_strength_mpa",
        }
    if unsafe:
        expression["code"] = "open('/etc/passwd').read()"
    return {
        "objective_id": "api-objective",
        "version": 1,
        "name": "API objective",
        "direction": "maximize",
        "expression": expression,
    }


def client_for(tmp_path, monkeypatch, payload: dict | None = None) -> tuple[TestClient, ObjectiveService]:
    service = ObjectiveService(
        store=ObjectiveStore(tmp_path / "memory" / "objectives", run_root=tmp_path / "runs"),
        registry=MetricRegistry.default(),
        context=_ComposerContext(payload or spec()),
    )
    monkeypatch.setattr(app_main, "_objective_service", lambda: service)
    return TestClient(app_main.app), service


def test_objective_api_exposes_metrics_and_full_lifecycle(tmp_path, monkeypatch) -> None:
    client, _ = client_for(tmp_path, monkeypatch)

    metrics = client.get("/api/objectives/metrics")
    composed = client.post("/api/objectives/compose", json={"intent": "maximize strength"})
    validated = client.post("/api/objectives/validate", json={"objective_id": "api-objective", "version": 1})
    previewed = client.post(
        "/api/objectives/preview",
        json={
            "objective_id": "api-objective",
            "version": 1,
            "observations": [
                {
                    "observation_id": "obs-api",
                    "metrics": {"compressive_strength_mpa": 5.0},
                    "quality_ok": True,
                }
            ],
        },
    )
    approved = client.post(
        "/api/objectives/approve",
        json={"objective_id": "api-objective", "version": 1, "operator": "jin"},
    )
    activated = client.post(
        "/api/objectives/activate",
        json={"objective_id": "api-objective", "version": 1, "run_id": "run-api", "operator": "jin"},
    )
    evaluated = client.post(
        "/api/objectives/evaluate",
        json={
            "run_id": "run-api",
            "observation_id": "obs-live",
            "metrics": {"compressive_strength_mpa": 6.0},
        },
    )

    assert metrics.status_code == 200 and len(metrics.json()["metrics"]) >= 1
    assert composed.status_code == 200
    assert validated.status_code == 200 and validated.json()["validation"]["valid"] is True
    assert previewed.status_code == 200 and previewed.json()["preview"]["usable_rows"] == 1
    assert approved.status_code == 200
    assert activated.status_code == 200
    assert evaluated.status_code == 200 and evaluated.json()["evaluation"]["objective_hash"] == activated.json()["binding"]["objective_hash"]
    assert str(tmp_path) not in evaluated.text

    status = client.get("/api/objectives/status", params={"run_id": "run-api"}).json()
    lifecycle = status["objective_states"][0]
    assert lifecycle["objective_id"] == "api-objective"
    assert lifecycle["validation"]["valid"] is True
    assert lifecycle["preview"]["usable_rows"] == 1
    assert lifecycle["approved"] is True
    assert lifecycle["active"] is True


def test_objective_api_maps_lifecycle_and_validation_errors(tmp_path, monkeypatch) -> None:
    client, service = client_for(tmp_path, monkeypatch, payload=spec(incompatible=True))

    missing = client.get("/api/objectives/metrics/not_registered")
    client.post("/api/objectives/compose", json={"intent": "invalid units"})
    invalid = client.post("/api/objectives/validate", json={"objective_id": "api-objective", "version": 1})
    conflict = client.post(
        "/api/objectives/activate",
        json={"objective_id": "api-objective", "version": 1, "run_id": "run-api", "operator": "jin"},
    )

    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert conflict.status_code == 409
    assert str(service.store.root) not in conflict.text


def test_objective_api_rejects_composer_code_payload(tmp_path, monkeypatch) -> None:
    client, _ = client_for(tmp_path, monkeypatch, payload=spec(unsafe=True))

    response = client.post("/api/objectives/compose", json={"intent": "run code"})

    assert response.status_code == 422
    assert "code" in response.text
