"""Tests for publication-style BO completion artifacts."""

from __future__ import annotations

import csv
from pathlib import Path

from experiments.bo_visualization import build_bo_visualization
from reporting.bo_visualization_artifacts import write_bo_visualization_artifacts


def _visualization() -> dict[str, object]:
    return build_bo_visualization(
        run_id="run-bo-artifact",
        objective={
            "objective_id": "sea",
            "name": "Specific energy absorption",
            "direction": "maximize",
            "unit": "J/g",
            "expression": {"op": "metric", "metric_id": "specific_energy_absorption"},
        },
        parameter_space={"relative_density": [0.2, 0.3, 0.4]},
        trace={
            "step": 3,
            "acquisition": "expected_improvement",
            "backend_requested": "botorch_optional",
            "backend_active": "botorch_optional",
            "candidates": [
                {
                    "candidate_id": f"candidate-{index}",
                    "x": index,
                    "surrogate_mean": mean,
                    "uncertainty": std,
                    "acquisition_value": acquisition,
                    "parameters": {"relative_density": density},
                }
                for index, (density, mean, std, acquisition) in enumerate(
                    [(0.2, 0.62, 0.08, 0.02), (0.3, 0.78, 0.05, 0.09), (0.4, 0.71, 0.06, 0.04)],
                    start=1,
                )
            ],
            "evaluated_points": [
                {
                    "candidate_id": "candidate-1",
                    "score": 0.60,
                    "parameters": {"relative_density": 0.2},
                }
            ],
            "selected": {
                "candidate_id": "candidate-2",
                "surrogate_mean": 0.78,
                "uncertainty": 0.05,
                "acquisition_value": 0.09,
                "parameters": {"relative_density": 0.3},
            },
        },
        selected_parameter="relative_density",
    )


def test_write_bo_visualization_artifacts_creates_png_svg_and_csv(tmp_path: Path) -> None:
    records = write_bo_visualization_artifacts(_visualization(), tmp_path)

    paths = {Path(item["path"]) for item in records}
    assert {path.suffix for path in paths} == {".png", ".svg", ".csv"}
    assert all(path.is_file() and path.stat().st_size > 0 for path in paths)

    csv_path = next(path for path in paths if path.suffix == ".csv")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == ["x", "mean", "std", "lower_95", "upper_95", "acquisition"]
    assert float(rows[0]["lower_95"]) == 0.62 - 1.96 * 0.08
    assert float(rows[0]["upper_95"]) == 0.62 + 1.96 * 0.08


def test_write_bo_visualization_artifacts_rejects_invalid_payload(tmp_path: Path) -> None:
    payload = _visualization()
    payload["schema"] = "bo_visualization.v0"

    try:
        write_bo_visualization_artifacts(payload, tmp_path)
    except ValueError as exc:
        assert "schema" in str(exc)
    else:
        raise AssertionError("invalid visualization schema was accepted")
