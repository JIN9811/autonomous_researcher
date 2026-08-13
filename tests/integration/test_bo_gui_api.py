"""Integration tests for BO Workspace API."""

from __future__ import annotations

import json

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


def test_bo_workspace_contains_manual_visual_and_json_authoring() -> None:
    html = TestClient(app).get("/bo").text

    for element_id in (
        "objective-author-mode",
        "objective-manual-builder",
        "objective-manual-metadata",
        "objective-expression-builder",
        "objective-constraints-builder",
        "objective-json-editor",
        "objective-json-errors",
        "btn-objective-json-apply",
        "btn-objective-json-restore",
        "btn-objective-json-format",
        "btn-objective-manual-save",
        "objective-preset-select",
        "btn-objective-load-preset",
    ):
        assert f'id="{element_id}"' in html
    assert html.index('<script src="/static/objective_builder.js"') < html.index('<script src="/static/bo.js"')
    assert "objective-function-body" not in html

    script = TestClient(app).get("/static/bo.js").text
    for contract in (
        'getJson("/api/objectives/authoring-contract")',
        "ObjectiveBuilder.createState",
        "ObjectiveBuilder.mountEditor",
        'postJson("/api/objectives/manual"',
        "loadRevision",
        'getJson("/api/objectives/presets")',
        "loadPreset",
    ):
        assert contract in script


def test_bo_workspace_contains_shared_live_visualization_cards() -> None:
    html = TestClient(app).get("/bo").text

    for element_id in (
        "bo-objective-equation-card",
        "lhs-design-card",
        "lhs-design-plot",
        "lhs-design-artifacts",
        "bo-posterior-card",
        "bo-posterior-view",
        "bo-posterior-parameter",
        "bo-posterior-step",
        "bo-posterior-latest",
    ):
        assert f'id="{element_id}"' in html
    assert html.index('/static/lhs_design_visualization.js') < html.index('/static/bo_visualization.js')
    assert html.index('/static/bo_visualization.js') < html.rindex('<script src="/static/bo.js"')
    assert '/static/bo_visualization.js?v=20260813-threshold-label-1' in html
    assert '/static/styles.css?v=20260811-botorch-paper-3' in html

    live_html = TestClient(app).get("/live").text
    assert '/static/lhs_design_visualization.js?v=20260812-lhs-paper-1' in live_html
    assert '/static/bo_visualization.js?v=20260813-threshold-label-1' in live_html
    assert 'bo-paper-3' in live_html
    assert 'planning.js?v=20260813-test-complete-freeze-1' in live_html


def test_bo_workspace_resets_visualization_state_before_each_new_run() -> None:
    script = TestClient(app).get("/static/bo.js").text

    assert "function resetVisualizationRun()" in script
    for function_name in ("runBenchmark", "runBOAgent"):
        function_start = script.index(f"async function {function_name}()")
        function_end = script.index("\n}", function_start)
        function_body = script[function_start:function_end]
        assert function_body.index("resetVisualizationRun();") < function_body.index("await postJson(")


def test_bo_config_endpoint_reports_defaults() -> None:
    client = TestClient(app)

    response = client.get("/api/bo/config")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["defaults"]["strategy"] == "bo"
    assert "expected_improvement" in payload["defaults"]["supported_acquisitions"]


def test_bo_config_exposes_lhs_and_posterior_as_separate_state() -> None:
    payload = TestClient(app).get("/api/bo/config").json()

    assert "recent_lhs_visualization" in payload
    assert "lhs_visualization_steps" in payload
    assert payload["recent_lhs_visualization"] == {} or payload["recent_lhs_visualization"]["schema"] == "lhs_design_visualization.v1"


def test_bo_config_refits_legacy_segmented_trace_once_per_completed_step(monkeypatch) -> None:
    values = [0.2, 0.3]
    legacy = {
        "schema": "bo_visualization.v1",
        "run_id": "run-legacy-bo",
        "step": 20,
        "generated_at": "2026-08-13T00:00:00+00:00",
        "objective": {"direction": "maximize"},
        "posterior": {
            "x": values,
            "mean": [0.5, 0.6],
            "std": [0.1, 0.1],
            "lower_95": [0.304, 0.404],
            "upper_95": [0.696, 0.796],
        },
        "acquisition": {"x": values, "value": [0.01, 0.02], "raw_name": "LogExpectedImprovement"},
        "candidate_index_view": {
            "x": [1.0, 2.0],
            "mean": [0.5, 0.6],
            "std": [0.1, 0.1],
            "lower_95": [0.304, 0.404],
            "upper_95": [0.696, 0.796],
            "acquisition": [0.01, 0.02],
            "candidate_ids": ["lhs-001", "lhs-002"],
        },
        "parameter_slices": {},
        "backend": {"active": "botorch"},
        "training_observations": [
            {"candidate_id": "lhs-001", "parameters": {"cell_size_mm": 5.0, "relative_density": 0.22}, "score": 0.5},
            {"candidate_id": "lhs-002", "parameters": {"cell_size_mm": 10.0, "relative_density": 0.38}, "score": 0.6},
        ],
        "objective_trace": {
            "mode": "normalized_search_path",
            "rows": [
                {"search_x": 0.02, "segment_index": 0, "mean": 0.5, "std": 0.1, "acquisition": 0.01},
                {"search_x": 0.98, "segment_index": 1, "mean": 0.6, "std": 0.1, "acquisition": 0.02},
            ],
        },
    }
    monkeypatch.setattr(
        app_main.controller,
        "snapshot",
        lambda: {
            "state": {
                "run_id": "run-legacy-bo",
                "run_metadata": {
                    "bo_visualization": legacy,
                    "bo_agent": {
                        "parameter_space": {"cell_size_mm": [5.0, 10.0], "relative_density": [0.2, 0.48]},
                        "metadata": {"random_seed": 7},
                    },
                },
            },
            "logs": {},
        },
    )
    calls: list[str] = []

    def rebuild(payload, **_kwargs):
        calls.append(payload["run_id"])
        upgraded = dict(payload)
        upgraded["objective_trace"] = {
            "mode": "normalized_search_path",
            "path_mode": "continuous_2d_gp_path",
            "rows": [{"search_x": 0.0}, {"search_x": 1.0}],
        }
        return upgraded

    monkeypatch.setattr(app_main, "rebuild_legacy_continuous_objective_trace", rebuild, raising=False)
    if hasattr(app_main, "_BO_VISUALIZATION_UPGRADE_CACHE"):
        app_main._BO_VISUALIZATION_UPGRADE_CACHE.clear()

    first = TestClient(app_main.app).get("/api/bo/config").json()
    second = TestClient(app_main.app).get("/api/bo/config").json()

    assert first["recent_visualization"]["objective_trace"]["path_mode"] == "continuous_2d_gp_path"
    assert second["recent_visualization"]["objective_trace"]["path_mode"] == "continuous_2d_gp_path"
    assert calls == ["run-legacy-bo"]


def test_bo_config_restores_full_visualization_when_runtime_state_is_compacted(tmp_path, monkeypatch) -> None:
    values = [float(index) / 100.0 for index in range(96)]
    full_visualization = {
        "schema": "bo_visualization.v1",
        "run_id": "run-large-bo",
        "posterior": {
            "x": values,
            "mean": values,
            "std": [0.1] * 96,
            "lower_95": [value - 0.196 for value in values],
            "upper_95": [value + 0.196 for value in values],
        },
        "acquisition": {"x": values, "value": values},
        "candidate_index_view": {
            "x": values,
            "mean": values,
            "std": [0.1] * 96,
            "lower_95": [value - 0.196 for value in values],
            "upper_95": [value + 0.196 for value in values],
            "acquisition": values,
            "candidate_ids": [f"candidate-{index:03d}" for index in range(96)],
        },
        "parameter_slices": {},
    }
    run_dir = tmp_path / "run-large-bo"
    result_dir = run_dir / "runtime" / "bo"
    result_dir.mkdir(parents=True)
    (result_dir / "20260811T000000000000Z_bo_agent_result.json").write_text(
        json.dumps({"bo_result": {"visualization": full_visualization}}),
        encoding="utf-8",
    )
    compacted = {
        **full_visualization,
        "posterior": {**full_visualization["posterior"], "x": values[:80] + [{"_truncated_items": 16}]},
    }
    monkeypatch.setattr(
        app_main.controller,
        "snapshot",
        lambda: {
            "state": {"run_id": "run-large-bo", "run_metadata": {"bo_visualization": compacted}},
            "logs": {"run_dir": str(run_dir)},
        },
    )

    payload = TestClient(app_main.app).get("/api/bo/config").json()

    assert len(payload["recent_visualization"]["posterior"]["x"]) == 96
    assert payload["recent_visualization"]["posterior"]["x"][-1] == 0.95


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
    assert config["saved"]["bo_backend"] == "botorch"
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
    latest_visualization = payload["benchmark"]["strategies"]["bo"]["surrogate_trace"][-1]["lhs_visualization"]
    assert latest_visualization["schema"] == "lhs_design_visualization.v1"
    assert latest_visualization["step"] == 3
    assert any(
        event.get("type") == "tool.completed"
        and event.get("node_id") == "bo"
        and event.get("payload", {}).get("workspace") == "bo"
        for event in app_main.controller.recent_events()
    )
    assert any(
        event.get("event_type") == "lhs.visualization.updated"
        and event.get("payload", {}).get("step") == 3
        and event.get("payload", {}).get("visualization", {}).get("schema") == "lhs_design_visualization.v1"
        for event in app_main.controller.recent_events()
    )
    config = client.get("/api/bo/config").json()
    assert config["recent_lhs_visualization"]["step"] == 3
    assert config["recent_lhs_visualization"]["artifacts"]["png_url"].endswith("_lhs_design_step_003.png")
    assert config["recent_lhs_visualization"]["artifacts"]["csv_url"].endswith("_lhs_design_step_003.csv")
    assert [item["step"] for item in config["lhs_visualization_steps"]][-3:] == [1, 2, 3]


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
    assert payload["benchmark"]["bo_backend_requested"] == "botorch"
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
    lhs_artifacts = {
        path
        for path in artifact_paths
        if path.startswith("workspace/bo/") and "_lhs_design_step_" in path
    }
    assert {path.rsplit(".", 1)[-1] for path in lhs_artifacts} == {"png", "svg", "csv", "json"}
    assert any(
        event.get("type") == "artifact.created"
        and event.get("payload", {}).get("artifact", {}).get("path") in artifact_paths
        for event in app_main.controller.recent_events()
    )
