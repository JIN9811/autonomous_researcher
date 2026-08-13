"""Tests for publication-style BO completion artifacts."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.image as mpimg
import pytest
from matplotlib import pyplot as plt

from experiments.bo_visualization import _objective_trace, build_bo_visualization
from reporting.bo_visualization_artifacts import _plot_posterior, write_bo_visualization_artifacts


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
            "backend_requested": "botorch",
            "backend_active": "botorch",
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

    svg_path = next(path for path in paths if path.suffix == ".svg")
    svg = svg_path.read_text(encoding="utf-8").lower()
    assert "#111827" in svg
    assert "#94a3b8" in svg
    assert "#2563eb" in svg
    assert "#f97316" in svg
    assert "#ffffff" in svg

    png_path = next(path for path in paths if path.suffix == ".png")
    pixels = mpimg.imread(png_path)
    assert pixels.shape[-1] == 4
    assert tuple(float(value) for value in pixels[0, 0, :3]) == pytest.approx((1.0, 1.0, 1.0))
    assert float(pixels[0, 0, 3]) == 1.0


def test_write_bo_visualization_artifacts_rejects_invalid_payload(tmp_path: Path) -> None:
    payload = _visualization()
    payload["schema"] = "bo_visualization.v0"

    with pytest.raises(ValueError, match="schema"):
        write_bo_visualization_artifacts(payload, tmp_path)


def test_write_bo_visualization_artifacts_rejects_lhs_contract(tmp_path: Path) -> None:
    payload = _visualization()
    payload["schema"] = "lhs_design_visualization.v1"

    with pytest.raises(ValueError, match="schema"):
        write_bo_visualization_artifacts(payload, tmp_path)


def test_two_variable_gp_artifact_renders_objective_response_surface(tmp_path: Path) -> None:
    payload = _visualization()
    payload["view"]["mode"] = "two_dimensional_gp"
    payload["backend"]["training_count"] = 8
    payload["gp_surface"] = {
        "mode": "mixed_2d_gp_surface",
        "x_parameter": "cell_size_mm",
        "x_values": [5.0, 6.0, 7.5, 10.0],
        "y_parameter": "relative_density",
        "y_values": [0.2, 0.3, 0.4, 0.48],
        "shape": [4, 4],
        "mean": [[0.4 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
        "std": [[0.08 - col * 0.01 for col in range(4)] for _row in range(4)],
        "lower_95": [[0.2 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
        "upper_95": [[0.6 + row * 0.1 + col * 0.01 for col in range(4)] for row in range(4)],
        "acquisition": [[0.01 + row * 0.01 + col * 0.005 for col in range(4)] for row in range(4)],
    }
    payload["training_observations"] = [
        {
            "candidate_id": f"lhs-{index:03d}",
            "parameters": {
                "cell_size_mm": (5.0, 6.0, 7.5, 10.0)[(index - 1) % 4],
                "relative_density": 0.20 + index * 0.03,
            },
            "score": 0.4 + index * 0.05,
        }
        for index in range(1, 9)
    ]
    payload["next_point"].update({"parameters": {"cell_size_mm": 7.5, "relative_density": 0.36}})
    payload["gp_series"] = []
    payload["objective_trace"] = _objective_trace(
        payload["gp_surface"],
        payload["training_observations"],
        payload["next_point"],
        direction="maximize",
        exploration_margin=0.01,
    )

    figure = _plot_posterior(payload)
    assert len(figure.axes) == 2
    assert all(axis.name == "rectilinear" for axis in figure.axes)
    assert figure.axes[0].get_title(loc="left").startswith("BO objective posterior and expected improvement")
    assert figure.axes[0].get_ylabel() == "Score"
    assert figure.axes[1].get_ylabel() == "Expected Improvement"
    assert figure.axes[1].get_xlabel() == "Normalized BO search coordinate"
    plt.close(figure)

    records = write_bo_visualization_artifacts(payload, tmp_path)

    svg_path = next(Path(item["path"]) for item in records if item["media_type"] == "image/svg+xml")
    svg = svg_path.read_text(encoding="utf-8")
    assert "BO objective posterior and expected improvement" in svg
    assert "Normalized BO search coordinate" in svg
    assert "Expected Improvement" in svg
    assert "Improvement threshold (best + ξ)" in svg
    assert "Measured observations" in svg
    assert "EI-selected next input" in svg
    assert "Cell Size Mm 5 mm" not in svg
    assert "cell_size_mm" not in svg
    assert "relative_density" not in svg

    csv_path = next(Path(item["path"]) for item in records if item["media_type"] == "text/csv")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == ["search_x", "cell_size_mm", "relative_density", "mean", "std", "lower_95", "upper_95", "acquisition"]
    assert len(rows) == 16
