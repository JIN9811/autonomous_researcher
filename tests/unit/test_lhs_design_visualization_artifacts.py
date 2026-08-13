"""Artifact tests for the dedicated LHS figure and data exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.image as mpimg
import pytest

from experiments.lhs_design_visualization import build_lhs_design_visualization
from reporting.lhs_design_visualization_artifacts import write_lhs_design_visualization_artifacts


def _payload() -> dict[str, object]:
    points = [
        {"index": 1, "status": "measured", "parameters": {"cell_size_mm": 10.0, "relative_density": 0.31}},
        {"index": 2, "status": "measured", "parameters": {"cell_size_mm": 5.0, "relative_density": 0.35}},
        {"index": 3, "status": "next", "parameters": {"cell_size_mm": 6.0, "relative_density": 0.39}},
        {"index": 4, "status": "planned", "parameters": {"cell_size_mm": 7.5, "relative_density": 0.29}},
    ]
    return build_lhs_design_visualization(
        run_id="run-lhs-artifact",
        parameter_space={"cell_size_mm": [5.0, 6.0, 7.5, 10.0], "relative_density": [0.2, 0.48]},
        trace={"step": 3, "initial_design": {"target": 8, "completed": 2, "seed": 7, "points": points}},
    )


def test_write_lhs_artifacts_creates_separate_publication_bundle(tmp_path: Path) -> None:
    records = write_lhs_design_visualization_artifacts(_payload(), tmp_path)

    paths = {Path(item["path"]) for item in records}
    assert {path.suffix for path in paths} == {".png", ".svg", ".csv", ".json"}
    assert all("_lhs_design_step_003" in path.stem for path in paths)
    assert all(path.is_file() and path.stat().st_size > 0 for path in paths)

    with next(path for path in paths if path.suffix == ".csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == [
        "index", "status", "candidate_id", "cell_size_mm", "relative_density", "density_stratum"
    ]

    json_payload = json.loads(next(path for path in paths if path.suffix == ".json").read_text(encoding="utf-8"))
    assert json_payload["schema"] == "lhs_design_visualization.v1"

    svg = next(path for path in paths if path.suffix == ".svg").read_text(encoding="utf-8")
    assert "Mixed-space Latin hypercube initial design" in svg
    assert "Cell size (mm)" in svg
    assert "Relative density" in svg
    assert "Density strata" in svg

    pixels = mpimg.imread(next(path for path in paths if path.suffix == ".png"))
    assert tuple(float(value) for value in pixels[0, 0, :3]) == pytest.approx((1.0, 1.0, 1.0))

