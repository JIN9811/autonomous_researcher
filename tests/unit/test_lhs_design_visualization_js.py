"""Node-driven tests for the dedicated LHS browser renderer."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RENDERER = PROJECT_ROOT / "web" / "static" / "lhs_design_visualization.js"


def test_lhs_renderer_uses_publication_design_space_semantics() -> None:
    node = shutil.which("node")
    assert node
    payload = {
        "schema": "lhs_design_visualization.v1",
        "run_id": "run-js-lhs",
        "step": 3,
        "design_space": {
            "x": {"name": "cell_size_mm", "label": "Cell size", "unit": "mm", "kind": "discrete", "values": [5, 6, 7.5, 10]},
            "y": {"name": "relative_density", "label": "Relative density", "unit": "1", "kind": "continuous", "bounds": [0.2, 0.48]},
        },
        "initial_design": {
            "sampler": "latin_hypercube",
            "target": 8,
            "completed": 2,
            "points": [
                {"index": 1, "status": "measured", "density_stratum": 4, "parameters": {"cell_size_mm": 10, "relative_density": 0.31}},
                {"index": 2, "status": "next", "density_stratum": 6, "parameters": {"cell_size_mm": 6, "relative_density": 0.39}},
                {"index": 3, "status": "planned", "density_stratum": 3, "parameters": {"cell_size_mm": 7.5, "relative_density": 0.29}},
            ],
        },
        "diagnostics": {"coverage_fraction": 0.25, "centered_discrepancy": 0.07, "duplicate_count": 0},
        "status": "active",
    }
    script = f"""
const renderer = require({json.dumps(str(RENDERER))});
const payload = {json.dumps(payload)};
const plot = renderer.renderPlot(payload);
console.log(JSON.stringify({{
  valid: renderer.isValid(payload),
  mixedTitle: plot.includes("Mixed-space Latin hypercube initial design"),
  axes: plot.includes("Cell size (mm)") && plot.includes("Relative density"),
  strata: plot.includes("lhs-viz-stratum"),
  measured: plot.includes("Measured design"),
  nextPoint: plot.includes("Next design"),
  planned: plot.includes("Planned design"),
  noPosterior: !plot.includes("Posterior mean") && !plot.includes("Expected Improvement"),
}}));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == {
        "valid": True,
        "mixedTitle": True,
        "axes": True,
        "strata": True,
        "measured": True,
        "nextPoint": True,
        "planned": True,
        "noPosterior": True,
    }


def test_lhs_renderer_accepts_continuous_cell_size_bounds() -> None:
    node = shutil.which("node")
    assert node
    payload = {
        "schema": "lhs_design_visualization.v1",
        "run_id": "run-js-lhs-continuous",
        "step": 1,
        "design_space": {
            "x": {"name": "cell_size_mm", "label": "Cell size", "unit": "mm", "kind": "continuous", "bounds": [5.0, 8.0]},
            "y": {"name": "relative_density", "label": "Relative density", "unit": "1", "kind": "continuous", "bounds": [0.2, 0.4]},
        },
        "initial_design": {
            "sampler": "latin_hypercube",
            "target": 8,
            "completed": 1,
            "points": [{"index": 1, "status": "measured", "parameters": {"cell_size_mm": 7.2, "relative_density": 0.31}}],
        },
    }
    script = f"""
const renderer = require({json.dumps(str(RENDERER))});
const payload = {json.dumps(payload)};
console.log(JSON.stringify({{ valid: renderer.isValid(payload), axes: renderer.renderPlot(payload).includes("Cell size (mm)") }}));
"""
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert json.loads(result.stdout) == {"valid": True, "axes": True}
