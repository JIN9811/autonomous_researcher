"""Current continuous domains must not be displayed as a finite cell table."""
from __future__ import annotations

import json
from pathlib import Path

from experiments.bo_visualization import _objective_trace, build_bo_visualization
from experiments.lhs_design_visualization import build_lhs_design_visualization
from tests.unit.test_bo_visualization import _objective, _trace
from tests.unit.test_bo_visualization_js import RENDERER, _node_eval, _payload


def test_continuous_plot_domain_does_not_claim_integer_cell_counts():
    payload = build_bo_visualization(
        run_id="continuous-viz", objective=_objective(),
        parameter_space={"cell_size_mm": [6.2, 9.1], "relative_density": [.2, .48]},
        trace=_trace())
    domain = payload["design_space"]
    assert domain.get("cell_size_kind") == "continuous"
    assert domain["cell_size_bounds_mm"] == [6.2, 9.1]
    assert not domain["feasible_cell_sizes_mm"]
    assert not domain["cell_counts"]
    assert domain.get("specimen_length_mm") is None


def test_continuous_lhs_metadata_preserves_non_table_coordinates():
    point = {"index": 1, "status": "next", "parameters": {
        "cell_size_mm": 7.13789, "relative_density": .32123456}}
    payload = build_lhs_design_visualization(
        run_id="continuous-lhs", parameter_space={"cell_size_mm": [6.2, 9.1],
        "relative_density": [.2, .48]}, trace={"initial_design": {"target": 8, "points": [point]}})
    assert payload["design_space"]["mode"] == "continuous_2d"
    assert payload["design_space"]["x"]["bounds"] == [6.2, 9.1]
    assert payload["initial_design"]["points"][0]["parameters"] == point["parameters"]


def test_lhs_fixed_density_is_not_displayed_as_a_variable_default_range():
    payload = build_lhs_design_visualization(
        run_id="fixed-density-lhs", parameter_space={"cell_size_mm": [6.2, 9.1],
        "relative_density": [.32123456]}, trace={"initial_design": {"target": 8,
        "points": [{"parameters": {"cell_size_mm": 7.13789, "relative_density": .32123456}}]}})
    assert payload["design_space"]["y"]["kind"] == "fixed"
    assert payload["design_space"]["y"]["bounds"] == [.32123456, .32123456]
    assert payload["design_space"]["dimension"] == 1
    renderer = RENDERER.parent / "lhs_design_visualization.js"
    rendered = _node_eval(f"""
const renderer = require({json.dumps(str(renderer))});
const html = renderer.renderPlot({json.dumps(payload)});
console.log(JSON.stringify({{fixed: html.includes('Fixed density'),
  noStrata: !html.includes('Density strata'), finite: !/NaN|Infinity/.test(html)}}));
""")
    assert rendered == {"fixed": True, "noStrata": True, "finite": True}
    from matplotlib import pyplot as plt
    from reporting.lhs_design_visualization_artifacts import _plot
    figure = _plot(payload)
    try:
        assert list(figure.axes[0].get_yticks()) == [.32123456]
        assert any(text.get_text() == "Fixed density" for text in figure.axes[0].texts)
    finally:
        plt.close(figure)


def test_equation_and_next_point_labels_follow_continuous_domain_and_acquisition():
    payload = _payload()
    payload["design_space"] = {"dimension": 2, "variables": ["cell_size_mm", "relative_density"],
        "cell_size_kind": "continuous", "cell_size_bounds_mm": [6.2, 9.1],
        "feasible_cell_sizes_mm": [], "relative_density_bounds": [.2, .48]}
    payload["acquisition"]["name"] = "upper_confidence_bound"
    result = _node_eval(f"""
const renderer = require({json.dumps(str(RENDERER))});
const payload = {json.dumps(payload)};
const equation = renderer.renderEquationCard(payload);
const plot = renderer.renderPlot(payload, {{mode: "parameter_slice"}});
console.log(JSON.stringify({{
  continuous: equation.includes("Continuous cell size") && equation.includes("6.2–9.1"),
  noIntegerRule: !equation.includes("a=L/N"),
  actualAcquisition: equation.includes("UCB") && plot.includes("UCB-selected"),
  noFalseEi: !plot.includes("EI-selected")
}}));
""")
    assert result == {"continuous": True, "noIntegerRule": True,
                      "actualAcquisition": True, "noFalseEi": True}


def test_live_first_lhs_board_uses_handoff_bounds_before_posterior_exists():
    planning = Path(__file__).resolve().parents[2] / "web/static/planning.js"
    result = _node_eval(f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(planning))}, 'utf8');
const extract = (name, next) => source.slice(source.indexOf(`function ${{name}}(`), source.indexOf(`function ${{next}}(`));
const context = {{window: {{LHSDesignVisualization: {{isValid: () => false, renderPlot: p => p}}}}}};
vm.createContext(context);
vm.runInContext(extract('latestBoInitialDesign', 'latestSpecimenFabricationReport') +
  extract('renderBoInitialDesignBoard', 'renderBoParameterChips'), context);
const report = {{state: {{run_metadata: {{orchestrator_design_contract: {{
  parameter_space: {{cell_size_mm: [6.2, 9.1], relative_density: [.23, .42]}},
  initial_design: {{target: 8, index: 1, points: [{{index: 1, status: 'next',
    parameters: {{cell_size_mm: 7.13789, relative_density: .32123456}}}}]}}
}}}}}}}};
const payload = context.renderBoInitialDesignBoard(report);
console.log(JSON.stringify({{x: payload.design_space.x, y: payload.design_space.y,
  point: payload.initial_design.points[0].parameters}}));
""")
    assert result["x"] == {"name": "cell_size_mm", "label": "Cell size", "unit": "mm",
                           "kind": "continuous", "bounds": [6.2, 9.1]}
    assert result["y"]["bounds"] == [.23, .42]
    assert result["point"] == {"cell_size_mm": 7.13789, "relative_density": .32123456}


def _ucb_trace():
    return _objective_trace({}, [], {"candidate_id": "ucb-next", "acquisition": -0.3},
        acquisition_class="UpperConfidenceBound", objective_path={
            "mode": "continuous_2d_gp_path", "search_x": [0, 1],
            "normalized_vectors": [[0, 0], [1, 1]], "mean": [-2, -1],
            "std": [.1, .2], "acquisition": [-1.8, -.3], "next_point_coordinate": 1})


def test_ucb_projection_preserves_signed_acquisition_values():
    trace = _ucb_trace()
    assert [row["acquisition"] for row in trace["rows"]] == [-1.8, -.3]


def test_ucb_browser_and_artifact_use_actual_acquisition_not_ei():
    from matplotlib import pyplot as plt
    from reporting.bo_visualization_artifacts import _plot_posterior

    payload = _payload()
    payload["acquisition"]["name"] = "UpperConfidenceBound"
    payload["objective_trace"] = _ucb_trace()
    # A legacy stored threshold must not be mistaken for a UCB policy threshold.
    payload["objective_trace"]["improvement_threshold"] = 1.5
    result = _node_eval(f"""
const renderer = require({json.dumps(str(RENDERER))});
const html = renderer.renderPlot({json.dumps(payload)}, {{mode: 'two_dimensional_gp'}});
console.log(JSON.stringify({{ucb: html.includes('UCB'),
  noEi: !/Expected Improvement|expected improvement|Improvement threshold/.test(html),
  signed: /-1\\.[0-9]/.test(html)}}));
""")
    assert result == {"ucb": True, "noEi": True, "signed": True}
    figure = _plot_posterior(payload)
    try:
        axis = figure.axes[1]
        assert axis.get_ylabel() == "UCB"
        assert list(axis.lines[0].get_ydata()) == [-1.8, -.3]
        assert not any("threshold" in line.get_label() for line in figure.axes[0].lines)
    finally:
        plt.close(figure)


def test_browser_surface_fallback_renders_negative_interpolated_and_selected_ucb():
    payload = _payload()
    payload["acquisition"]["name"] = "upper_confidence_bound"
    payload["backend"] = {"requested": "botorch", "active": "botorch", "phase": "acquisition"}
    payload["training_observations"] = [
        {"candidate_id": "observed-a", "parameters": {"cell_size_mm": 6.2, "relative_density": .2}, "score": 1.1},
        {"candidate_id": "observed-b", "parameters": {"cell_size_mm": 9.1, "relative_density": .48}, "score": 1.4},
    ]
    payload["next_point"] = {
        "candidate_id": "selected-negative",
        "parameters": {"cell_size_mm": 8.4, "relative_density": .4},
        "mean": 1.3,
        "std": .1,
        "acquisition": -2.0,
    }
    payload["gp_surface"] = {
        "mode": "mixed_2d_gp_surface",
        "x_parameter": "cell_size_mm",
        "y_parameter": "relative_density",
        "x_values": [6.2, 9.1],
        "y_values": [.2, .48],
        "mean": [[1.0, 1.2], [1.3, 1.5]],
        "std": [[.1, .1], [.2, .2]],
        "acquisition": [[.2, .3], [.4, .5]],
    }
    selected_payload = json.dumps(payload)
    payload["next_point"]["acquisition"] = .25
    payload["gp_surface"]["acquisition"] = [[-1.8, -1.4], [-.9, -.3]]
    interpolated_payload = json.dumps(payload)
    result = _node_eval(f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(RENDERER))}, 'utf8')
  .replace('return {{\\n    isValid,', 'return {{\\n    objectiveTraceFromSurface,\\n    isValid,');
const sandbox = {{module: {{exports: {{}}}}, exports: {{}}, globalThis: {{}}}};
vm.runInNewContext(source, sandbox);
const renderer = sandbox.module.exports;
const selected = {selected_payload};
const interpolated = {interpolated_payload};
const selectedTrace = renderer.objectiveTraceFromSurface(selected);
const interpolatedTrace = renderer.objectiveTraceFromSurface(interpolated);
const selectedHtml = renderer.renderPlot(selected, {{mode: 'two_dimensional_gp'}});
console.log(JSON.stringify({{
  selectedValue: selectedTrace.next_point.acquisition,
  interpolatedMinimum: Math.min(...interpolatedTrace.rows.map(row => row.acquisition)),
  fallbackRendered: selectedHtml.includes('continuous 2D GP path') || selectedHtml.includes('Normalized BO search coordinate')
}}));
""")
    assert result == {
        "selectedValue": -2.0,
        "interpolatedMinimum": -1.8,
        "fallbackRendered": True,
    }
