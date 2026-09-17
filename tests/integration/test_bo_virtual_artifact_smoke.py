"""Synthetic SEA only: production BO path without a registered device tool."""
from copy import deepcopy
import csv
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.bo.agent import BOAgent
from experiments.benchmark import run_benchmark
from learning.bo_parameter_space import BOParameterSpace
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage
from reporting.bo_visualization_artifacts import write_bo_visualization_artifacts
from reporting.lhs_design_visualization_artifacts import write_lhs_design_visualization_artifacts
from utils.research_objective import SEA_METRIC


@pytest.mark.asyncio
async def test_synthetic_sea_lhs_to_gp_and_artifact_extraction(tmp_path, monkeypatch):
    import torch
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    monkeypatch.setattr(BOAgent, "_artifact_dir", staticmethod(lambda state: tmp_path / "decisions"))
    registry = ToolRegistry()
    calls, events = [], []
    def benchmark(payload):
        calls.append(deepcopy(payload))
        assert payload["sequential_only"] is True
        assert payload["request"]["execution"] == {"mode": "virtual", "bridge": "virtual", "dry_run": True}
        return run_benchmark(payload, evaluator=lambda request: pytest.fail("BO must propose, never actuate/evaluate"))
    registry.register("experiment.benchmark", benchmark)
    ctx = SimpleNamespace(tools=registry, force_real_llm_in_test=False, emit_execution_event=events.append)
    settings = {"strategy": "bo", "budget": 1, "bo_backend": "botorch", "random_seed": 7,
                "parameter_space": {"cell_size_mm": [5., 10.], "wall_thickness_mm": [.6, 1.2]},
                "acquisition": "expected_improvement", "num_restarts": 2, "raw_samples": 32,
                "objective": {"metric_name": SEA_METRIC, "unit": "J/g", "direction": "maximize"}}
    normalized, _ = BOAgent.normalize_settings(settings)
    points = BOParameterSpace.from_mapping(normalized["parameter_space"]).lhs_points(8, seed=7)
    state = OrchestratorState(run_id="synthetic-sea-artifact-audit", experiment_id="synthetic-only",
                              mode=Mode.TEST, stage=Stage.BO, active_goal="Maximize SEA (synthetic audit only)")
    def add_observation(point, index):
        cell, wall = point["cell_size_mm"], point["wall_thickness_mm"]
        sea = 12.0 - (cell - 7.4) ** 2 * .45 - (wall - .9) ** 2 * 12
        state.experiment_evaluations.append({
            "evaluation_id": f"synthetic-{index}", "candidate_id": f"synthetic-{index}",
            "source": "analysis_agent", "status": "measured_analysis_complete", "ok": True,
            "synthetic": True, "objective_score": sea,
            "metrics": {**point, SEA_METRIC: sea},
            "objective": {"metric_name": SEA_METRIC, "unit": "J/g", "constraints": point}})
    for index, point in enumerate(points[:7]):
        add_observation(point, index)
    try:
        lhs_result = await BOAgent().run_with_settings(state, ctx, settings)
        assert lhs_result.success, lhs_result.summary
        lhs = lhs_result.data["bo_result"]
        assert lhs["optimization_phase"] == "initial_design"
        assert lhs["lhs_visualization"]["initial_design"]["completed"] == 7
        assert lhs["recommendation"]["parameters"] == points[7]
        records = write_lhs_design_visualization_artifacts(lhs["lhs_visualization"], tmp_path / "lhs-before")
        add_observation(points[7], 7)
        gp_result = await BOAgent().run_with_settings(state, ctx, settings)
        assert gp_result.success, gp_result.summary
        bo = gp_result.data["bo_result"]
        trace = bo["benchmark"]["strategies"]["bo"]["surrogate_trace"][-1]
        assert trace["phase"] == "acquisition" and trace["backend_active"] == "botorch"
        assert trace["model"]["class"] == "SingleTaskGP"
        assert trace["model"]["training_count"] == 8
        assert trace["acquisition_class"] == "LogExpectedImprovement"
        candidate = bo["recommendation"]["parameters"]
        assert 5 <= candidate["cell_size_mm"] <= 10
        assert .6 <= candidate["wall_thickness_mm"] <= 1.2
        assert bo["next_design_request"]["constraints"] == candidate
        assert bo["lhs_visualization"]["initial_design"]["completed"] == 8
        assert all(p["status"] == "measured" for p in bo["lhs_visualization"]["initial_design"]["points"])
        viz = bo["visualization"]
        assert bo["objective"]["metric_name"] == SEA_METRIC
        assert viz["objective"]["equation"] == SEA_METRIC
        assert viz["objective"]["unit"] == "J/g"
        assert all(math.isfinite(trace["selected"][key]) for key in ("surrogate_mean", "uncertainty", "acquisition_value"))
        records += write_bo_visualization_artifacts(viz, tmp_path / "posterior")
        records += write_lhs_design_visualization_artifacts(bo["lhs_visualization"], tmp_path / "lhs-complete")
        # A second synthetic feedback cycle must refit, not reuse the old GP/card.
        add_observation(candidate, 8)
        state.current_experiment_spec = deepcopy(candidate)
        state.loop_count += 1
        next_result = await BOAgent().run_with_settings(state, ctx, settings)
        assert next_result.success, next_result.summary
        next_bo = next_result.data["bo_result"]
        next_trace = next_bo["benchmark"]["strategies"]["bo"]["surrogate_trace"][-1]
        assert next_trace["model"]["training_count"] == 9
        assert next_bo["visualization"]["step"] == 9
        assert next_bo["next_design_request"]["status"] == "ready"
        assert next_bo["lhs_visualization"]["initial_design"]["completed"] == 8
        records += write_bo_visualization_artifacts(next_bo["visualization"], tmp_path / "posterior")
        records += write_lhs_design_visualization_artifacts(next_bo["lhs_visualization"], tmp_path / "lhs-complete")
        for plot in (viz, next_bo["visualization"]):
            grid = plot["response_surface"]
            assert grid["mode"] == "continuous_2d_gp_surface"
            assert grid["matrix_order"] == "yx" and grid["shape"] == [33, 33]
            assert (grid["x_values"][0], grid["x_values"][-1]) == (5., 10.)
            assert (grid["y_values"][0], grid["y_values"][-1]) == (.6, 1.2)
            for key in ("mean", "std", "acquisition"):
                assert len(grid[key]) == 33 and all(len(row) == 33 for row in grid[key])
                assert all(math.isfinite(value) for row in grid[key] for value in row)
            assert min(v for row in grid["acquisition"] for v in row) >= 0
            (tmp_path / f"surface-step-{plot['step']}.json").write_text(json.dumps(plot))
            for view in ("2d", "3d"):
                image_path = tmp_path / "posterior" / f"{state.run_id}_bo_step_{plot['step']:03d}_posterior_{view}.png"
                assert image_path.read_bytes().startswith(b"\x89PNG")
            csv_path = tmp_path / "posterior" / f"{state.run_id}_bo_step_{plot['step']:03d}_posterior.csv"
            with csv_path.open() as handle:
                exported = list(csv.DictReader(handle))
            plotted = sorted(plot["objective_trace"]["rows"], key=lambda row: row["search_x"])
            assert len(exported) == len(plotted) == 384
            for actual, expected in zip(exported, plotted, strict=True):
                for key in ("search_x", "mean", "std", "acquisition"):
                    assert float(actual[key]) == pytest.approx(expected[key])
                for key in ("cell_size_mm", "wall_thickness_mm"):
                    assert float(actual[key]) == pytest.approx(expected["parameters"][key])
        paths = [Path(record["path"]) for record in records] + [Path(p) for p in next_bo["artifacts"].values()]
        assert {p.suffix for p in paths} >= {".png", ".svg", ".csv", ".json"}
        for path in paths:
            assert path.is_file() and path.stat().st_size > 0
            if path.suffix == ".png":
                assert path.read_bytes().startswith(b"\x89PNG")
            elif path.suffix == ".json":
                json.loads(path.read_text())
            elif path.suffix == ".csv":
                with path.open() as handle:
                    assert list(csv.DictReader(handle))
        assert len(calls) == 3
        assert events[0]["payload"]["checkpoint"] == "handoff"
        (tmp_path / "audit-summary.json").write_text(json.dumps({
            "synthetic_only": True, "physical_actions": 0, "objective": SEA_METRIC,
            "bounds_mm": settings["parameter_space"], "phases": ["LHS 7/8", "GP 8 observations", "GP 9 observations"],
            "backend": next_trace["backend_active"], "model": next_trace["model"],
            "acquisition_class": next_trace["acquisition_class"],
            "next_candidate": next_bo["next_design_request"], "artifacts": [str(p) for p in paths],
        }, indent=2))
        print(f"Synthetic BO audit artifacts: {tmp_path}")
    finally:
        torch.set_num_threads(previous_threads)
