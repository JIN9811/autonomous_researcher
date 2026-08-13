"""Node-driven tests for the shared BO browser renderer."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RENDERER = PROJECT_ROOT / "web" / "static" / "bo_visualization.js"
STYLES = PROJECT_ROOT / "web" / "static" / "styles.css"


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
        "backend": {"requested": "botorch", "active": "botorch", "model": "SingleTaskGP"},
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
      hasEiSelectedPoint: plot.includes("EI-selected Next point"),
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
        "hasEiSelectedPoint": True,
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


def test_shared_renderer_uses_botorch_paper_plot_semantics() -> None:
    result = _node_eval(
        f"""
const fs = require("fs");
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(_payload())}, {{ mode: "parameter_slice" }});
const css = fs.readFileSync({json.dumps(str(STYLES))}, "utf8");
console.log(JSON.stringify({{
  paperBackground: /\.bo-viz-paper\s*\{{[^}}]*fill:\s*#ffffff/i.test(css),
  svgBackground: /\.bo-viz-svg\s*\{{[^}}]*background:\s*#ffffff/i.test(css),
  blackPosterior: /\.bo-viz-mean-line\s*\{{[^}}]*stroke:\s*#111827/i.test(css),
  grayConfidence: /\.bo-viz-confidence-band\s*\{{[^}}]*fill:\s*#94a3b8/i.test(css),
  blueObservations: /\.bo-viz-observation\s*\{{[^}}]*fill:\s*#2563eb/i.test(css),
  noAcquisitionPanel: !plot.includes('class="bo-viz-acquisition-line"'),
  nextPointCross: plot.includes("bo-viz-next-cross"),
  posteriorPanel: plot.includes("Posterior mean"),
  eiSelectedPoint: plot.includes("EI-selected Next point"),
}}));
"""
    )

    assert result == {
        "paperBackground": True,
        "svgBackground": True,
        "blackPosterior": True,
        "grayConfidence": True,
        "blueObservations": True,
        "noAcquisitionPanel": True,
        "nextPointCross": True,
        "posteriorPanel": True,
        "eiSelectedPoint": True,
    }


def test_expected_improvement_axis_does_not_render_negative_ticks() -> None:
    payload = _payload()
    payload["acquisition"]["value"] = [0.0, 0.00045, 0.00001]
    payload["candidate_index_view"]["acquisition"] = [0.0, 0.00045, 0.00001]
    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(payload)}, {{ mode: "parameter_slice" }});
const tickValues = Array.from(plot.matchAll(/class="bo-viz-tick"[^>]*>([^<]+)<\\/text>/g), (match) => match[1]);
console.log(JSON.stringify({{ negativeTick: tickValues.some((value) => /^-/.test(value)) }}));
"""
    )

    assert result == {"negativeTick": False}


def test_shared_renderer_does_not_replay_stale_png_artifact() -> None:
    payload = _payload()
    payload["artifacts"] = {
        "png_url": "/api/runs/run-1/artifact-file/runtime/bo/posterior.png",
        "csv_url": "/api/runs/run-1/artifact-file/runtime/bo/posterior.csv",
    }
    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(payload)}, {{ mode: "parameter_slice" }});
console.log(JSON.stringify({{
  noMatplotlibImage: !plot.includes('bo-viz-matplotlib-image'),
  noPngUrl: !plot.includes('/api/runs/run-1/artifact-file/runtime/bo/posterior.png'),
  liveSvg: plot.includes('<svg'),
}}));
"""
    )

    assert result == {"noMatplotlibImage": True, "noPngUrl": True, "liveSvg": True}


def test_two_variable_bo_renders_objective_and_ei_on_shared_search_axis() -> None:
    payload = _payload()
    payload["objective"]["equation"] = "objective_score"
    payload["view"]["mode"] = "two_dimensional_gp"
    payload["gp_surface"] = {
        "mode": "mixed_2d_gp_surface",
        "x_parameter": "cell_size_mm",
        "x_values": [5.0, 10.0],
        "y_parameter": "relative_density",
        "y_values": [0.2, 0.48],
        "shape": [2, 2],
        "mean": [[0.4, 0.5], [0.6, 0.7]],
        "std": [[0.1, 0.08], [0.07, 0.05]],
        "acquisition": [[0.01, 0.02], [0.03, 0.04]],
    }
    payload["training_observations"] = [
        {"candidate_id": "lhs-1", "parameters": {"cell_size_mm": 5.0, "relative_density": 0.21}, "score": 0.42},
        {"candidate_id": "lhs-2", "parameters": {"cell_size_mm": 10.0, "relative_density": 0.31}, "score": 0.66},
    ]
    payload["next_point"]["parameters"] = {"cell_size_mm": 10.0, "relative_density": 0.48}
    payload["objective_trace"] = {
        "mode": "normalized_search_path",
        "x_label": "Normalized BO search coordinate",
        "y_label": "Objective score",
        "rows": [
            {"search_x": 0.02, "segment_index": 0, "parameters": {"cell_size_mm": 5.0, "relative_density": 0.2}, "mean": 0.40, "std": 0.10, "acquisition": 0.01},
            {"search_x": 0.48, "segment_index": 0, "parameters": {"cell_size_mm": 5.0, "relative_density": 0.48}, "mean": 0.50, "std": 0.08, "acquisition": 0.02},
            {"search_x": 0.52, "segment_index": 1, "parameters": {"cell_size_mm": 10.0, "relative_density": 0.2}, "mean": 0.60, "std": 0.07, "acquisition": 0.03},
            {"search_x": 0.98, "segment_index": 1, "parameters": {"cell_size_mm": 10.0, "relative_density": 0.48}, "mean": 0.70, "std": 0.05, "acquisition": 0.04},
        ],
        "observations": [
            {"search_x": 0.0364, "candidate_id": "lhs-1", "parameters": {"cell_size_mm": 5.0, "relative_density": 0.21}, "observed": 0.42},
            {"search_x": 0.7007, "candidate_id": "lhs-2", "parameters": {"cell_size_mm": 10.0, "relative_density": 0.31}, "observed": 0.66},
        ],
        "next_point": {"search_x": 0.98, "parameters": {"cell_size_mm": 10.0, "relative_density": 0.48}, "mean": 0.70, "std": 0.05, "acquisition": 0.04},
        "strata": [
            {"start": 0.0, "end": 0.5, "label": "cell_size_mm=5", "parameters": {"cell_size_mm": 5.0}},
            {"start": 0.5, "end": 1.0, "label": "cell_size_mm=10", "parameters": {"cell_size_mm": 10.0}},
        ],
        "current_best": 0.66,
        "improvement_threshold": 0.67,
    }
    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(payload)}, {{ mode: "parameter_slice" }});
console.log(JSON.stringify({{
  oneSvg: (plot.match(/<svg/g) || []).length === 1,
  objectiveFunction: plot.includes("Score"),
  objectiveScale: plot.includes("GP mean"),
  observations: plot.includes("Measured"),
  nextPoint: plot.includes("Maximum EI / next query"),
  noGroupedCellCurves: !plot.includes("Cell size 5 mm") && !plot.includes("Cell size 10 mm"),
  inputVariablesHidden: !plot.includes("cell_size_mm") && !plot.includes("relative_density"),
  responseSurface: plot.includes("BO objective posterior and expected improvement"),
  normalizedAxis: plot.includes("Normalized BO search coordinate"),
  improvementThreshold: plot.includes("Improvement threshold (best + ξ)"),
  noEvaluationSequence: !plot.includes("Evaluation sequence"),
  noSurfaceWaiting: !plot.includes("2D BO surface artifact is being prepared"),
  exactBoTorchPolyline: (plot.match(/bo-viz-gp-mean-grid/g) || []).length === 1,
  noCubicInterpolation: !plot.includes(" C "),
}}));
"""
    )

    assert result == {
        "oneSvg": True,
        "objectiveFunction": True,
        "objectiveScale": True,
        "observations": True,
        "nextPoint": True,
        "noGroupedCellCurves": True,
        "inputVariablesHidden": True,
        "responseSurface": True,
        "normalizedAxis": True,
        "improvementThreshold": True,
        "noEvaluationSequence": True,
        "noSurfaceWaiting": True,
        "exactBoTorchPolyline": True,
        "noCubicInterpolation": True,
    }


def test_renderer_uses_objective_trace_for_existing_run_payload() -> None:
    payload = _payload()
    payload["view"].update({"mode": "conditional_slice", "selected_parameter": "relative_density"})
    payload["gp_surface"] = {
        "mode": "mixed_2d_gp_surface",
        "x_parameter": "cell_size_mm",
        "x_values": [5.0, 10.0],
        "y_parameter": "relative_density",
        "y_values": [0.2, 0.48],
        "shape": [2, 2],
        "mean": [[0.4, 0.5], [0.6, 0.7]],
        "std": [[0.1, 0.08], [0.07, 0.05]],
        "lower_95": [[0.204, 0.3432], [0.4628, 0.602]],
        "upper_95": [[0.596, 0.6568], [0.7372, 0.798]],
        "acquisition": [[0.01, 0.02], [0.03, 0.04]],
    }
    payload["training_observations"] = [
        {"candidate_id": "lhs-1", "parameters": {"cell_size_mm": 5.0, "relative_density": 0.21}, "score": 0.42},
        {"candidate_id": "lhs-2", "parameters": {"cell_size_mm": 10.0, "relative_density": 0.31}, "score": 0.66},
    ]
    payload["next_point"]["parameters"] = {"cell_size_mm": 10.0, "relative_density": 0.48}
    payload["objective_trace"] = {}

    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(payload)}, {{ mode: "parameter_slice" }});
console.log(JSON.stringify({{
  responseSurface: plot.includes("BO objective posterior and expected improvement"),
  inputVariablesHidden: !plot.includes("cell_size_mm") && !plot.includes("relative_density"),
  noGroupedCells: !plot.includes("Cell size 5 mm") && !plot.includes("Cell size 10 mm"),
  normalizedAxis: plot.includes("Normalized BO search coordinate"),
}}));
"""
    )

    assert result == {"responseSurface": True, "inputVariablesHidden": True, "noGroupedCells": True, "normalizedAxis": True}


def test_renderer_reprojects_legacy_segmented_trace_onto_one_continuous_path() -> None:
    payload = _payload()
    payload["gp_surface"] = {
        "mode": "mixed_2d_gp_surface",
        "x_parameter": "cell_size_mm",
        "x_values": [5.0, 10.0],
        "y_parameter": "relative_density",
        "y_values": [0.2, 0.34, 0.48],
        "shape": [2, 3],
        "mean": [[0.4, 0.62, 0.5], [0.58, 0.78, 0.66]],
        "std": [[0.1, 0.07, 0.08], [0.09, 0.05, 0.06]],
        "acquisition": [[0.01, 0.04, 0.02], [0.03, 0.08, 0.05]],
    }
    payload["training_observations"] = [
        {"candidate_id": "lhs-1", "parameters": {"cell_size_mm": 5.0, "relative_density": 0.2}, "score": 0.4},
        {"candidate_id": "lhs-2", "parameters": {"cell_size_mm": 10.0, "relative_density": 0.34}, "score": 0.78},
        {"candidate_id": "lhs-3", "parameters": {"cell_size_mm": 5.0, "relative_density": 0.48}, "score": 0.5},
    ]
    payload["next_point"]["parameters"] = {"cell_size_mm": 10.0, "relative_density": 0.48}
    payload["objective_trace"] = {
        "mode": "normalized_search_path",
        "path_mode": "legacy_segmented_surface",
        "rows": [
            {"search_x": 0.02, "segment_index": 0, "mean": 0.4, "std": 0.1, "acquisition": 0.01},
            {"search_x": 0.48, "segment_index": 0, "mean": 0.5, "std": 0.08, "acquisition": 0.02},
            {"search_x": 0.52, "segment_index": 1, "mean": 0.58, "std": 0.09, "acquisition": 0.03},
            {"search_x": 0.98, "segment_index": 1, "mean": 0.66, "std": 0.06, "acquisition": 0.05},
        ],
    }

    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(payload)}, {{ mode: "parameter_slice" }});
const match = plot.match(/class="bo-viz-gp-mean-grid" points="([^"]+)"/);
console.log(JSON.stringify({{
  pointCount: match ? match[1].trim().split(/\\s+/).length : 0,
  oneMeanLine: (plot.match(/bo-viz-gp-mean-grid/g) || []).length === 1,
}}));
"""
    )

    assert result == {"pointCount": 384, "oneMeanLine": True}


def test_two_variable_bo_keeps_selected_ei_marker_inside_acquisition_panel() -> None:
    payload = _payload()
    payload["view"]["mode"] = "two_dimensional_gp"
    payload["gp_surface"] = {
        "mode": "mixed_2d_gp_surface",
        "x_parameter": "cell_size_mm",
        "x_values": [5.0, 10.0],
        "y_parameter": "relative_density",
        "y_values": [0.2, 0.48],
        "shape": [2, 2],
        "mean": [[0.4, 0.5], [0.6, 0.7]],
        "std": [[0.1, 0.08], [0.07, 0.05]],
        "acquisition": [[0.01, 0.02], [0.03, 0.04]],
    }
    payload["training_observations"] = []
    payload["next_point"].update(
        {
            "parameters": {"cell_size_mm": 10.0, "relative_density": 0.48},
            "acquisition": 0.14,
        }
    )
    payload["objective_trace"] = {}

    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(payload)}, {{ mode: "parameter_slice" }});
const marker = plot.match(/class="bo-viz-next-star" transform="translate\([^ ]+ ([\d.-]+)\)"/);
console.log(JSON.stringify({{
  markerFound: Boolean(marker),
  markerY: marker ? Number(marker[1]) : null,
}}));
"""
    )

    assert result["markerFound"] is True
    assert 455 <= result["markerY"] <= 567


def test_bo_renderer_rejects_lhs_payload_instead_of_mixing_visualizations() -> None:
    payload = _payload()
    payload["backend"] = {"requested": "botorch", "active": "lhs", "model": "LatinHypercube", "phase": "initial_design"}
    payload["design_space"] = {
        "dimension": 2,
        "variables": ["cell_size_mm", "relative_density"],
        "feasible_cell_sizes_mm": [5.0, 6.0, 7.5, 10.0],
        "relative_density_bounds": [0.2, 0.48],
        "input_normalization": "unit_hypercube",
    }
    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(payload)}, {{ mode: "parameter_slice" }});
console.log(JSON.stringify({{
  unavailable: plot.includes("BO posterior unavailable during initial design"),
  noLhs: !plot.includes("Latin Hypercube initial design") && !plot.includes("LHS measured sample"),
}}));
"""
    )

    assert result == {
        "unavailable": True,
        "noLhs": True,
    }


def test_shared_renderer_omits_logei_subplot_and_keeps_projection_context() -> None:
    payload = _payload()
    payload["acquisition"]["name"] = "LogExpectedImprovement"
    payload["view"]["mode"] = "marginal_projection"
    payload["view"]["anchor_count"] = 5
    payload["acquisition"]["value"] = [-4.56, -4.50, -4.44]
    payload["candidate_index_view"]["acquisition"] = [-4.56, -4.50, -4.44]
    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(payload)}, {{ mode: "parameter_slice" }});
const subtitleY = Number((plot.match(/class="bo-viz-subtitle"[^>]*y="([\d.]+)"/) || [])[1]);
const legendY = Number((plot.match(/class="bo-viz-legend"[^>]*translate\([^ ]+ ([\d.]+)\)/) || [])[1]);
console.log(JSON.stringify({{
  legendBelowSubtitle: legendY > subtitleY,
  noLogEiPanel: !plot.includes("Log Expected Improvement"),
  marginalContext: plot.includes("marginal over 5 measured designs"),
}}));
"""
    )

    assert result == {
        "legendBelowSubtitle": True,
        "noLogEiPanel": True,
        "marginalContext": True,
    }


def test_shared_renderer_keeps_narrow_objective_tick_labels_distinct() -> None:
    payload = _payload()
    payload["posterior"].update(
        {
            "mean": [0.2651, 0.2652, 0.2653],
            "std": [0.0002, 0.0002, 0.0002],
            "lower_95": [0.264708, 0.264808, 0.264908],
            "upper_95": [0.265492, 0.265592, 0.265692],
        }
    )
    payload["observations"] = [{"candidate_id": "c1", "x": 0.2, "score": 0.2652}]
    result = _node_eval(
        f"""
const renderer = require({json.dumps(str(RENDERER))});
const plot = renderer.renderPlot({json.dumps(payload)}, {{ mode: "parameter_slice" }});
const ticks = [...plot.matchAll(/class="bo-viz-tick"[^>]*>(-?\d+(?:\.\d+)?)<\/text>/g)]
  .slice(0, 5).map((match) => match[1]);
console.log(JSON.stringify({{ ticks, uniqueCount: new Set(ticks).size }}));
"""
    )

    assert result["uniqueCount"] == 5


def test_live_bo_objective_card_does_not_stretch_to_plot_height() -> None:
    source = (PROJECT_ROOT / "web" / "static" / "planning.js").read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")

    assert 'className: "bo-objective-summary-card"' in source
    assert ".bo-objective-summary-card" in css
    assert "align-self: start" in css


def test_live_bo_transparent_plot_uses_readable_dark_surface_ink() -> None:
    css = STYLES.read_text(encoding="utf-8")

    assert "body.planning-live-body .bo-viz-axis" in css
    assert "body.planning-live-body .bo-viz-title" in css
    assert "body.planning-live-body .bo-viz-tick" in css
    assert "body.planning-live-body .bo-viz-grid" in css
    assert "body.planning-live-body .bo-viz-paper" in css
