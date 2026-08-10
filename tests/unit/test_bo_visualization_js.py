"""Node-driven tests for the shared BO browser renderer."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RENDERER = PROJECT_ROOT / "web" / "static" / "bo_visualization.js"


def _node_eval(script: str) -> dict[str, object]:
    node = shutil.which("node")
    assert node, "node is required for BO visualization renderer tests"
    result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _payload() -> dict[str, object]:
    return {
        "schema": "bo_visualization.v1",
        "run_id": "run-js",
        "step": 2,
        "objective": {
            "objective_id": "sea",
            "version": 2,
            "hash": "abcdef1234567890",
            "name": "Specific energy absorption",
            "direction": "maximize",
            "equation": "specific_energy_absorption / mass_g",
            "unit": "J/g",
            "constraints": ["relative_density >= 0.2"],
        },
        "view": {
            "mode": "parameter_slice",
            "selected_parameter": "relative_density",
            "available_parameters": ["relative_density", "wall_thickness_mm"],
            "x_label": "Relative Density",
            "x_unit": "1",
            "fixed_parameters": {"wall_thickness_mm": 1.2},
            "fixed_parameter_source": "current_best",
        },
        "posterior": {
            "x": [0.2, 0.3, 0.4],
            "mean": [0.62, 0.78, 0.71],
            "std": [0.08, 0.05, 0.06],
            "lower_95": [0.4632, 0.682, 0.5924],
            "upper_95": [0.7768, 0.878, 0.8276],
        },
        "acquisition": {"name": "expected_improvement", "x": [0.2, 0.3, 0.4], "value": [0.02, 0.09, 0.04]},
        "observations": [{"candidate_id": "c1", "x": 0.2, "score": 0.6}],
        "current_best": {"candidate_id": "c1", "x": 0.2, "score": 0.6},
        "next_point": {"candidate_id": "c2", "x": 0.3, "mean": 0.78, "std": 0.05, "acquisition": 0.09},
        "candidate_index_view": {
            "x": [1, 2, 3],
            "mean": [0.62, 0.78, 0.71],
            "std": [0.08, 0.05, 0.06],
            "lower_95": [0.4632, 0.682, 0.5924],
            "upper_95": [0.7768, 0.878, 0.8276],
            "acquisition": [0.02, 0.09, 0.04],
            "candidate_ids": ["c1", "c2", "c3"],
        },
        "backend": {"requested": "botorch_optional", "active": "botorch_optional", "model": "pool_projection"},
        "status": "complete",
        "warnings": ["pool projection"],
    }


def test_shared_renderer_outputs_equation_confidence_and_point_semantics() -> None:
    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const payload = {json.dumps(_payload())};
const equation = renderer.renderEquationCard(payload);
const plot = renderer.renderPlot(payload, {{ mode: "parameter_slice" }});
console.log(JSON.stringify({{
  hasEquation: equation.includes("specific_energy_absorption / mass_g"),
  hasVersion: equation.includes("v2"),
  hasConfidenceBand: plot.includes("bo-viz-confidence-band"),
  hasMeasuredLegend: plot.includes("Measured observations"),
  hasNextPoint: plot.includes("Next point"),
  hasAcquisition: plot.includes("Expected Improvement"),
  svgCount: (plot.match(/<svg/g) || []).length,
}}));
"""
    )

    assert result == {
        "hasEquation": True,
        "hasVersion": True,
        "hasConfidenceBand": True,
        "hasMeasuredLegend": True,
        "hasNextPoint": True,
        "hasAcquisition": True,
        "svgCount": 1,
    }


def test_shared_renderer_switches_to_candidate_audit_without_uncertainty_rescaling() -> None:
    result = _node_eval(
        f"""
const fs = require("fs");
const renderer = require({json.dumps(str(RENDERER))});
const payload = {json.dumps(_payload())};
const plot = renderer.renderPlot(payload, {{ mode: "candidate_index" }});
const source = fs.readFileSync({json.dumps(str(RENDERER))}, "utf8");
console.log(JSON.stringify({{
  candidateModeLabel: plot.includes("Candidate pool index") ? "Candidate pool index" : "missing",
  hasCandidateId: plot.includes("c2"),
  forbiddenScale: /uncertainty\s*\*\s*0\.12/.test(source),
  parameters: renderer.availableParameters(payload),
}}));
"""
    )

    assert result == {
        "candidateModeLabel": "Candidate pool index",
        "hasCandidateId": True,
        "forbiddenScale": False,
        "parameters": ["relative_density", "wall_thickness_mm"],
    }


def test_shared_renderer_uses_backend_supplied_parameter_slice() -> None:
    payload = _payload()
    payload["parameter_slices"] = {
        "cell_size_mm": {
            "x_label": "Cell Size Mm",
            "x_unit": "mm",
            "posterior": {
                "x": [5.0, 7.5, 10.0],
                "mean": [0.3, 0.6, 0.5],
                "std": [0.1, 0.1, 0.1],
                "lower_95": [0.104, 0.404, 0.304],
                "upper_95": [0.496, 0.796, 0.696],
            },
            "acquisition": {"x": [5.0, 7.5, 10.0], "value": [0.1, 0.4, 0.2]},
            "observations": [{"candidate_id": "c1", "x": 5.0, "score": 0.28}],
            "current_best": {"candidate_id": "c2", "x": 7.5, "score": 0.58},
            "next_point": {"candidate_id": "c2", "x": 7.5, "mean": 0.6},
        }
    }
    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const html = renderer.renderPlot({json.dumps(payload)}, {{ parameter: "cell_size_mm" }});
console.log(JSON.stringify({{ selectedSlice: html.includes("Cell Size Mm (mm)") }}));
"""
    )

    assert result == {"selectedSlice": True}


def test_shared_renderer_rejects_invalid_payload_without_throwing() -> None:
    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const html = renderer.renderPlot({{"schema": "wrong"}}, {{}});
console.log(JSON.stringify({{ stale: html.includes("BO visualization unavailable") }}));
"""
    )

    assert result == {"stale": True}
