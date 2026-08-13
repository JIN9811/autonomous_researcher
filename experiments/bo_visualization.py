"""Build the shared, read-only BO visualization projection.

This module does not select candidates or evaluate experiments. It converts an
already-computed BO trace into a bounded payload shared by browser and artifact
renderers.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from learning.bo_parameter_space import BOParameterSpace


SCHEMA = "bo_visualization.v1"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _number_text(value: Any) -> str:
    number = _finite(value)
    if number is None:
        return str(value)
    return f"{number:.8g}"


def _expression_text(node: Any) -> str:
    if not isinstance(node, dict):
        return "-"
    op = str(node.get("op") or "").strip().lower()
    if op == "metric":
        return str(node.get("metric_id") or node.get("name") or "metric")
    if op == "literal":
        return _number_text(node.get("value"))
    binary = {
        "add": "+",
        "subtract": "-",
        "multiply": "*",
        "divide": "/",
        "ratio": "/",
        "gte": ">=",
        "gt": ">",
        "lte": "<=",
        "lt": "<",
        "eq": "==",
    }
    if op in binary:
        left = node.get("left", node.get("numerator"))
        right = node.get("right", node.get("denominator"))
        return f"{_expression_text(left)} {binary[op]} {_expression_text(right)}"
    if op in {"sum", "mean", "product", "and", "or"}:
        children = node.get("children") or node.get("terms") or []
        rendered = [
            _expression_text(item.get("expression") if isinstance(item, dict) and "expression" in item else item)
            for item in children
        ]
        separator = {"sum": " + ", "mean": ", ", "product": " * ", "and": " and ", "or": " or "}[op]
        body = separator.join(rendered)
        return f"mean({body})" if op == "mean" else body
    if op == "weighted_sum":
        terms = node.get("terms") if isinstance(node.get("terms"), list) else []
        rendered = []
        for term in terms:
            if not isinstance(term, dict):
                continue
            rendered.append(f"{_number_text(term.get('weight', 1))}*{_expression_text(term.get('expression'))}")
        return " + ".join(rendered) or "-"
    if op:
        child = node.get("expression", node.get("child", node.get("value")))
        return f"{op}({_expression_text(child)})"
    return "-"


def numeric_parameter_names(parameter_space: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key, raw in parameter_space.items():
        values = raw if isinstance(raw, list) else [raw]
        finite_values = [_finite(item) for item in values]
        if values and all(item is not None for item in finite_values):
            names.append(str(key))
    return names


def select_slice_parameter(parameter_space: dict[str, Any], trace: dict[str, Any], requested: str = "") -> str:
    del trace  # Reserved for latest-change selection when arbitrary posterior slices are available.
    numeric = numeric_parameter_names(parameter_space)
    if requested and requested in numeric:
        return requested
    if not numeric:
        raise ValueError("BO visualization requires at least one numeric parameter")
    continuous = [
        dimension.name
        for dimension in BOParameterSpace.from_mapping(parameter_space).dimensions
        if dimension.kind == "continuous" and dimension.name in numeric
    ]
    return continuous[0] if continuous else numeric[0]


def objective_display(objective: dict[str, Any]) -> dict[str, Any]:
    expression = objective.get("expression") if isinstance(objective.get("expression"), dict) else {}
    constraints = objective.get("constraints") if isinstance(objective.get("constraints"), list) else []
    return {
        "objective_id": str(objective.get("objective_id") or ""),
        "version": int(objective.get("version") or 0),
        "hash": str(objective.get("objective_hash") or objective.get("hash") or ""),
        "name": str(objective.get("name") or objective.get("objective_id") or "Objective not bound"),
        "direction": str(objective.get("direction") or "maximize"),
        "equation": _expression_text(expression) if expression else str(objective.get("metric_name") or "-"),
        "unit": str(objective.get("unit") or ""),
        "constraints": [_expression_text(item) for item in constraints if isinstance(item, dict)],
        "lifecycle": str(objective.get("lifecycle") or objective.get("status") or ""),
        "run_bound": bool(objective.get("run_bound") or objective.get("binding")),
    }


def _design_space_display(parameter_space: dict[str, Any]) -> dict[str, Any]:
    space = BOParameterSpace.from_mapping(parameter_space)
    active = [dimension.name for dimension in space.active_dimensions]
    cells = parameter_space.get("cell_size_mm") if isinstance(parameter_space.get("cell_size_mm"), list) else []
    feasible_cells = [float(value) for value in cells if _finite(value) is not None]
    density = parameter_space.get("relative_density") if isinstance(parameter_space.get("relative_density"), list) else []
    density_bounds = [float(value) for value in density if _finite(value) is not None]
    specimen_length = 30.0
    return {
        "dimension": len(active),
        "variables": active,
        "specimen_length_mm": specimen_length,
        "cell_size_rule": "a=L/N",
        "cell_counts": [int(round(specimen_length / value)) for value in feasible_cells if value > 0.0],
        "feasible_cell_sizes_mm": feasible_cells,
        "relative_density_bounds": density_bounds[:2],
        "input_normalization": "unit_hypercube",
    }


def _candidate_rows(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in trace.get("candidates", []) if isinstance(item, dict)]


def _initial_design_points(trace: dict[str, Any], parameter_space: dict[str, Any]) -> list[dict[str, Any]]:
    initial_design = trace.get("initial_design") if isinstance(trace.get("initial_design"), dict) else {}
    supplied = initial_design.get("points") if isinstance(initial_design.get("points"), list) else []
    if supplied:
        return [dict(item) for item in supplied if isinstance(item, dict)]
    active_names = [dimension.name for dimension in BOParameterSpace.from_mapping(parameter_space).active_dimensions]
    points: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in trace.get("evaluated_points", []):
        if not isinstance(item, dict):
            continue
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        active_parameters = {name: parameters[name] for name in active_names if name in parameters}
        if len(active_parameters) != len(active_names):
            continue
        candidate_id = str(item.get("candidate_id") or f"lhs-{len(points) + 1:03d}")
        seen.add(candidate_id)
        points.append(
            {
                "index": len(points) + 1,
                "candidate_id": candidate_id,
                "status": "measured",
                "parameters": active_parameters,
            }
        )
    selected = trace.get("selected") if isinstance(trace.get("selected"), dict) else {}
    selected_parameters = selected.get("parameters") if isinstance(selected.get("parameters"), dict) else {}
    active_selected = {name: selected_parameters[name] for name in active_names if name in selected_parameters}
    selected_id = str(selected.get("candidate_id") or "")
    if len(active_selected) == len(active_names) and selected_id not in seen:
        points.append(
            {
                "index": len(points) + 1,
                "candidate_id": selected_id or f"lhs-{len(points) + 1:03d}",
                "status": "next",
                "parameters": active_selected,
            }
        )
    return points


def _observations(
    trace: dict[str, Any],
    selected_parameter: str,
    fixed_parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fixed_parameters = fixed_parameters or {}
    for item in trace.get("evaluated_points", []):
        if not isinstance(item, dict):
            continue
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        if any(parameters.get(name) != value for name, value in fixed_parameters.items()):
            continue
        x = _finite(parameters.get(selected_parameter))
        score = _finite(item.get("score"))
        if x is None or score is None:
            continue
        rows.append({"candidate_id": str(item.get("candidate_id") or ""), "x": x, "score": score})
    return sorted(rows, key=lambda item: (item["x"], item["candidate_id"]))


def _training_observations(
    trace: dict[str, Any],
    parameter_space: dict[str, Any],
) -> list[dict[str, Any]]:
    active_names = [dimension.name for dimension in BOParameterSpace.from_mapping(parameter_space).active_dimensions]
    rows: list[dict[str, Any]] = []
    for item in trace.get("evaluated_points", []):
        if not isinstance(item, dict):
            continue
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        score = _finite(item.get("score"))
        active_parameters = {name: parameters.get(name) for name in active_names}
        if score is None or any(_finite(value) is None for value in active_parameters.values()):
            continue
        rows.append(
            {
                "candidate_id": str(item.get("candidate_id") or ""),
                "parameters": active_parameters,
                "score": score,
            }
        )
    model = trace.get("model") if isinstance(trace.get("model"), dict) else {}
    observation_count = model.get("observation_count")
    if isinstance(observation_count, int) and observation_count >= 0:
        return rows[:observation_count]
    training_count = model.get("training_count")
    if isinstance(training_count, int) and training_count >= 0:
        return rows[:training_count]
    return rows


def _gp_surface(projection: dict[str, Any], acquisition_class: str) -> dict[str, Any]:
    surface = projection.get("surface") if isinstance(projection.get("surface"), dict) else {}
    if surface.get("mode") != "mixed_2d_gp_surface":
        return {}
    normalized = dict(surface)
    acquisition_rows = surface.get("acquisition") if isinstance(surface.get("acquisition"), list) else []
    normalized["acquisition"] = [
        [_display_acquisition(value, acquisition_class) for value in row]
        for row in acquisition_rows
        if isinstance(row, list)
    ]
    return normalized


def _objective_trace(
    surface: dict[str, Any],
    observations: list[dict[str, Any]],
    selected: dict[str, Any],
    *,
    objective_path: dict[str, Any] | None = None,
    acquisition_class: str = "",
    direction: str = "maximize",
    exploration_margin: float = 0.01,
) -> dict[str, Any]:
    """Flatten a mixed 2D search space onto one shared posterior/EI axis.

    This is a visualization coordinate only. Every point retains both original
    design variables, while the GP and acquisition values remain those computed
    by the two-dimensional model.
    """
    path = objective_path if isinstance(objective_path, dict) else {}
    if path.get("mode") == "continuous_2d_gp_path":
        search_x = path.get("search_x") if isinstance(path.get("search_x"), list) else []
        vectors = path.get("normalized_vectors") if isinstance(path.get("normalized_vectors"), list) else []
        means = path.get("mean") if isinstance(path.get("mean"), list) else []
        stds = path.get("std") if isinstance(path.get("std"), list) else []
        acquisitions = path.get("acquisition") if isinstance(path.get("acquisition"), list) else []
        row_count = min(len(search_x), len(vectors), len(means), len(stds), len(acquisitions))
        rows = [
            {
                "search_x": float(search_x[index]),
                "normalized_vector": [float(value) for value in vectors[index]],
                "mean": float(means[index]),
                "std": max(0.0, float(stds[index])),
                "acquisition": max(0.0, _display_acquisition(acquisitions[index], acquisition_class) or 0.0),
            }
            for index in range(row_count)
            if all(_finite(value) is not None for value in (search_x[index], means[index], stds[index], acquisitions[index]))
        ]
        coordinates = path.get("observation_coordinates") if isinstance(path.get("observation_coordinates"), list) else []
        observation_rows = [
            {
                "search_x": float(coordinates[index]),
                "candidate_id": str(item.get("candidate_id") or ""),
                "parameters": dict(item.get("parameters") or {}),
                "observed": _finite(item.get("score")),
            }
            for index, item in enumerate(observations)
            if index < len(coordinates) and _finite(coordinates[index]) is not None
        ]
        next_coordinate = _finite(path.get("next_point_coordinate"))
        next_point = dict(selected) if next_coordinate is not None else {}
        if next_point:
            next_point["search_x"] = next_coordinate
        observed_scores = [item["observed"] for item in observation_rows if _finite(item.get("observed")) is not None]
        current_best = (min(observed_scores) if direction == "minimize" else max(observed_scores)) if observed_scores else None
        margin = max(0.0, float(exploration_margin))
        return {
            "mode": "normalized_search_path",
            "path_mode": "continuous_2d_gp_path",
            "x_label": "Normalized BO search coordinate",
            "y_label": "Score",
            "rows": rows,
            "observations": observation_rows,
            "next_point": next_point,
            "current_best": current_best,
            "exploration_margin": margin,
            "improvement_threshold": None if current_best is None else current_best + (-margin if direction == "minimize" else margin),
        }

    if surface.get("mode") != "mixed_2d_gp_surface":
        return {}
    x_name = str(surface.get("x_parameter") or "")
    y_name = str(surface.get("y_parameter") or "")
    x_values = surface.get("x_values") if isinstance(surface.get("x_values"), list) else []
    y_values = surface.get("y_values") if isinstance(surface.get("y_values"), list) else []
    means = surface.get("mean") if isinstance(surface.get("mean"), list) else []
    stds = surface.get("std") if isinstance(surface.get("std"), list) else []
    acquisitions = surface.get("acquisition") if isinstance(surface.get("acquisition"), list) else []
    if not x_name or not y_name or not x_values or not y_values:
        return {}

    def nearest(values: list[Any], target: Any) -> int:
        target_value = float(target)
        return min(range(len(values)), key=lambda index: abs(float(values[index]) - target_value))

    stratum_count = len(x_values)
    y_min = float(min(y_values))
    y_max = float(max(y_values))
    y_span = max(y_max - y_min, 1e-12)
    inset = 0.04

    def search_coordinate(x_value: Any, y_value: Any) -> float:
        stratum = nearest(x_values, x_value)
        fraction = min(1.0, max(0.0, (float(y_value) - y_min) / y_span))
        return (stratum + inset + fraction * (1.0 - 2.0 * inset)) / stratum_count

    rows: list[dict[str, Any]] = []
    for row_index, x_value in enumerate(x_values):
        if row_index >= len(means) or row_index >= len(stds) or row_index >= len(acquisitions):
            continue
        if not all(len(matrix[row_index]) == len(y_values) for matrix in (means, stds, acquisitions)):
            continue
        for column_index, y_value in enumerate(y_values):
            mean = _finite(means[row_index][column_index])
            std = _finite(stds[row_index][column_index])
            acquisition = _finite(acquisitions[row_index][column_index])
            if None in {mean, std, acquisition}:
                continue
            rows.append({
                "search_x": search_coordinate(x_value, y_value),
                "segment_index": row_index,
                "parameters": {x_name: float(x_value), y_name: float(y_value)},
                "mean": mean,
                "std": max(0.0, std),
                "acquisition": max(0.0, acquisition),
            })

    observation_rows: list[dict[str, Any]] = []
    for item in observations:
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        if _finite(parameters.get(x_name)) is None or _finite(parameters.get(y_name)) is None:
            continue
        observation_rows.append({
            "search_x": search_coordinate(parameters[x_name], parameters[y_name]),
            "segment_index": nearest(x_values, parameters[x_name]),
            "candidate_id": str(item.get("candidate_id") or ""),
            "parameters": dict(parameters),
            "observed": _finite(item.get("score")),
        })

    next_point: dict[str, Any] = {}
    selected_parameters = selected.get("parameters") if isinstance(selected.get("parameters"), dict) else {}
    if _finite(selected_parameters.get(x_name)) is not None and _finite(selected_parameters.get(y_name)) is not None:
        row_index = nearest(x_values, selected_parameters[x_name])
        column_index = nearest(y_values, selected_parameters[y_name])
        next_point = {
            "search_x": search_coordinate(selected_parameters[x_name], selected_parameters[y_name]),
            "candidate_id": str(selected.get("candidate_id") or "next"),
            "parameters": dict(selected_parameters),
            "mean": _finite(selected.get("mean")) if _finite(selected.get("mean")) is not None else _finite(means[row_index][column_index]),
            "std": max(0.0, _finite(selected.get("std")) if _finite(selected.get("std")) is not None else (_finite(stds[row_index][column_index]) or 0.0)),
            "acquisition": max(0.0, _finite(selected.get("acquisition")) if _finite(selected.get("acquisition")) is not None else (_finite(acquisitions[row_index][column_index]) or 0.0)),
        }

    observed_scores = [item["observed"] for item in observation_rows if _finite(item.get("observed")) is not None]
    current_best = (min(observed_scores) if direction == "minimize" else max(observed_scores)) if observed_scores else None
    margin = max(0.0, float(exploration_margin))
    threshold = None if current_best is None else current_best + (-margin if direction == "minimize" else margin)
    return {
        "mode": "normalized_search_path",
        "path_mode": "legacy_segmented_surface",
        "x_label": "Normalized BO search coordinate",
        "y_label": "Score",
        "rows": rows,
        "observations": observation_rows,
        "next_point": next_point,
        "current_best": current_best,
        "exploration_margin": margin,
        "improvement_threshold": threshold,
    }


def _grouped_gp_series(
    surface: dict[str, Any],
    training_observations: list[dict[str, Any]],
    selected: dict[str, Any],
) -> list[dict[str, Any]]:
    """Expose one continuous GP curve per feasible discrete design value."""
    if surface.get("mode") != "mixed_2d_gp_surface":
        return []
    fixed_parameter = str(surface.get("x_parameter") or "")
    varying_parameter = str(surface.get("y_parameter") or "")
    fixed_values = surface.get("x_values") if isinstance(surface.get("x_values"), list) else []
    varying_values = surface.get("y_values") if isinstance(surface.get("y_values"), list) else []
    matrix_keys = ("mean", "std", "lower_95", "upper_95", "acquisition")
    matrices = {
        key: surface.get(key) if isinstance(surface.get(key), list) else []
        for key in matrix_keys
    }
    if not fixed_parameter or not varying_parameter or not fixed_values or not varying_values:
        return []

    selected_parameters = selected.get("parameters") if isinstance(selected.get("parameters"), dict) else {}
    fixed_label = fixed_parameter.removesuffix("_mm").replace("_", " ").capitalize()
    series: list[dict[str, Any]] = []
    for index, fixed_value in enumerate(fixed_values):
        rows = {key: matrices[key][index] if index < len(matrices[key]) else [] for key in matrix_keys}
        if any(not isinstance(values, list) or len(values) != len(varying_values) for values in rows.values()):
            continue
        observations = []
        for item in training_observations:
            parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
            observed_fixed = _finite(parameters.get(fixed_parameter))
            observed_x = _finite(parameters.get(varying_parameter))
            if observed_fixed is None or observed_x is None or not math.isclose(observed_fixed, float(fixed_value), abs_tol=1e-8):
                continue
            observations.append(
                {
                    "candidate_id": str(item.get("candidate_id") or ""),
                    "x": observed_x,
                    "score": item["score"],
                }
            )
        observations.sort(key=lambda item: (item["x"], item["candidate_id"]))
        is_selected = _finite(selected_parameters.get(fixed_parameter))
        is_selected = is_selected is not None and math.isclose(float(is_selected), float(fixed_value), abs_tol=1e-8)
        series.append(
            {
                "series_id": f"{fixed_parameter}={_number_text(fixed_value)}",
                "label": f"{fixed_label} {_number_text(fixed_value)} {_parameter_unit(fixed_parameter)}".strip(),
                "fixed_parameters": {fixed_parameter: fixed_value},
                "x_parameter": varying_parameter,
                "x_label": varying_parameter.replace("_", " ").title(),
                "x_unit": _parameter_unit(varying_parameter),
                "x": list(varying_values),
                **{key: list(values) for key, values in rows.items()},
                "observations": observations,
                "selected_for_next_point": bool(is_selected),
            }
        )
    return series


def _best_observation(observations: list[dict[str, Any]], direction: str) -> dict[str, Any]:
    if not observations:
        return {}
    key = lambda item: item["score"]
    return dict(min(observations, key=key) if direction == "minimize" else max(observations, key=key))


def _parameter_unit(name: str) -> str:
    if name.endswith("_mm"):
        return "mm"
    if name.endswith("_deg"):
        return "deg"
    return "1"


def _display_acquisition(value: Any, acquisition_class: str) -> float | None:
    """Convert numerically stable LogEI scores back to operator-facing EI."""
    number = _finite(value)
    if number is None:
        return None
    if str(acquisition_class or "").strip().lower() == "logexpectedimprovement":
        return math.exp(min(number, 700.0))
    return number


def _parameter_slice(
    *,
    parameter: str,
    candidates: list[dict[str, Any]],
    trace: dict[str, Any],
    direction: str,
    acquisition_class: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in candidates:
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        x = _finite(parameters.get(parameter))
        mean = _finite(item.get("surrogate_mean"))
        std = _finite(item.get("uncertainty"))
        acquisition = _display_acquisition(item.get("acquisition_value"), acquisition_class)
        if None in {x, mean, std, acquisition}:
            continue
        rows.append(
            {
                "candidate_id": str(item.get("candidate_id") or ""),
                "x": x,
                "mean": mean,
                "std": max(0.0, std),
                "acquisition": acquisition,
            }
        )
    rows.sort(key=lambda item: (item["x"], item["candidate_id"]))
    observations = _observations(trace, parameter)
    current_best = _best_observation(observations, direction)
    selected = trace.get("selected") if isinstance(trace.get("selected"), dict) else {}
    selected_parameters = selected.get("parameters") if isinstance(selected.get("parameters"), dict) else {}
    return {
        "x_label": parameter.replace("_", " ").title(),
        "x_unit": _parameter_unit(parameter),
        "posterior": {
            "x": [item["x"] for item in rows],
            "mean": [item["mean"] for item in rows],
            "std": [item["std"] for item in rows],
            "lower_95": [item["mean"] - 1.96 * item["std"] for item in rows],
            "upper_95": [item["mean"] + 1.96 * item["std"] for item in rows],
        },
        "acquisition": {
            "x": [item["x"] for item in rows],
            "value": [item["acquisition"] for item in rows],
        },
        "observations": observations,
        "current_best": current_best,
        "next_point": {
            "candidate_id": str(selected.get("candidate_id") or ""),
            "x": _finite(selected_parameters.get(parameter)),
            "mean": _finite(selected.get("surrogate_mean")),
            "std": _finite(selected.get("uncertainty")),
            "acquisition": _display_acquisition(selected.get("acquisition_value"), acquisition_class),
        },
    }


def build_bo_visualization(
    *,
    run_id: str,
    objective: dict[str, Any],
    parameter_space: dict[str, Any],
    trace: dict[str, Any],
    selected_parameter: str = "",
) -> dict[str, Any]:
    parameter = select_slice_parameter(parameter_space, trace, selected_parameter)
    candidates = _candidate_rows(trace)
    objective_info = objective_display(objective)
    acquisition_class = str(trace.get("acquisition_class") or trace.get("acquisition") or "acquisition")
    parameter_slices = {
        name: _parameter_slice(
            parameter=name,
            candidates=candidates,
            trace=trace,
            direction=objective_info["direction"],
            acquisition_class=acquisition_class,
        )
        for name in numeric_parameter_names(parameter_space)
    }
    selected_slice = parameter_slices[parameter]
    observations = selected_slice["observations"]
    current_best = selected_slice["current_best"]
    best_parameters: dict[str, Any] = {}
    if current_best:
        match = next((item for item in candidates if str(item.get("candidate_id") or "") == current_best["candidate_id"]), None)
        if isinstance(match, dict) and isinstance(match.get("parameters"), dict):
            best_parameters = dict(match["parameters"])
    selected = trace.get("selected") if isinstance(trace.get("selected"), dict) else {}
    selected_parameters = selected.get("parameters") if isinstance(selected.get("parameters"), dict) else {}
    next_point = selected_slice["next_point"]
    next_point["parameters"] = {
        name: selected_parameters[name]
        for name in numeric_parameter_names(parameter_space)
        if name in selected_parameters and _finite(selected_parameters[name]) is not None
    }
    projection = trace.get("projection") if isinstance(trace.get("projection"), dict) else {}
    gp_surface = _gp_surface(projection, acquisition_class)
    training_observations = _training_observations(trace, parameter_space)
    gp_series: list[dict[str, Any]] = []
    if gp_series:
        primary_series = gp_series[0]
        selected_slice["posterior"] = {
            key: list(primary_series[key])
            for key in ("x", "mean", "std", "lower_95", "upper_95")
        }
        selected_slice["acquisition"] = {
            "x": list(primary_series["x"]),
            "value": list(primary_series["acquisition"]),
        }
        observations = [dict(item) for series in gp_series for item in series["observations"]]
        current_best = _best_observation(observations, objective_info["direction"])
        selected_slice["observations"] = observations
        selected_slice["current_best"] = current_best
    model = trace.get("model") if isinstance(trace.get("model"), dict) else {}
    initial_design = trace.get("initial_design") if isinstance(trace.get("initial_design"), dict) else {}
    marginal_projection = projection.get("mode") == "observed_design_marginal"
    conditional_projection = projection.get("mode") == "candidate_conditioned_slice"
    response_surface = bool(gp_surface)
    projection_fixed = (
        dict(projection.get("fixed_parameters") or {})
        if conditional_projection and isinstance(projection.get("fixed_parameters"), dict)
        else {}
    )
    if conditional_projection and not response_surface:
        projection_x = projection.get("x") if isinstance(projection.get("x"), list) else []
        projection_mean = projection.get("mean") if isinstance(projection.get("mean"), list) else []
        projection_std = projection.get("std") if isinstance(projection.get("std"), list) else []
        projection_lower = projection.get("lower_95") if isinstance(projection.get("lower_95"), list) else []
        projection_upper = projection.get("upper_95") if isinstance(projection.get("upper_95"), list) else []
        projection_acquisition = projection.get("acquisition") if isinstance(projection.get("acquisition"), list) else []
        projection_length = len(projection_x)
        if projection_length and all(
            len(values) == projection_length
            for values in (
                projection_mean,
                projection_std,
                projection_lower,
                projection_upper,
                projection_acquisition,
            )
        ):
            selected_slice["posterior"] = {
                "x": [_finite(value) for value in projection_x],
                "mean": [_finite(value) for value in projection_mean],
                "std": [_finite(value) for value in projection_std],
                "lower_95": [_finite(value) for value in projection_lower],
                "upper_95": [_finite(value) for value in projection_upper],
            }
            selected_slice["acquisition"] = {
                "x": [_finite(value) for value in projection_x],
                "value": [_display_acquisition(value, acquisition_class) for value in projection_acquisition],
            }
        observations = _observations(trace, parameter, projection_fixed)
        current_best = _best_observation(observations, objective_info["direction"])
        selected_slice["observations"] = observations
        selected_slice["current_best"] = current_best

    audit_rows = []
    for index, item in enumerate(candidates, start=1):
        x = _finite(item.get("x")) or float(index)
        mean = _finite(item.get("surrogate_mean"))
        std = _finite(item.get("uncertainty"))
        acquisition = _display_acquisition(item.get("acquisition_value"), acquisition_class)
        if None in {mean, std, acquisition}:
            continue
        audit_rows.append((x, mean, max(0.0, std), acquisition, str(item.get("candidate_id") or "")))

    fixed_parameters = {} if response_surface else projection_fixed if conditional_projection else ({} if marginal_projection else {
        key: value
        for key, value in (selected_parameters or best_parameters).items()
        if key != parameter and isinstance(value, (str, int, float, bool))
    })
    warnings: list[str] = []
    if not selected_slice["posterior"]["x"]:
        warnings.append(f"No candidate posterior values contain selected parameter: {parameter}")
    backend_active = str(trace.get("backend_active") or "lightweight_pool")
    if backend_active != "botorch":
        warnings.append("Parameter slice is a candidate-pool projection, not an arbitrary-point GP posterior.")

    payload = {
        "schema": SCHEMA,
        "run_id": str(run_id or ""),
        "step": int(trace.get("step") or 0),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objective": objective_info,
        "design_space": _design_space_display(parameter_space),
        "initial_design": {
            "sampler": str(initial_design.get("sampler") or "latin_hypercube"),
            "target": int(initial_design.get("target") or 8),
            "completed": int(initial_design.get("completed") or 0),
            "points": _initial_design_points(trace, parameter_space),
        },
        "view": {
            "mode": "objective_trace" if gp_surface else ("marginal_projection" if marginal_projection else ("conditional_slice" if conditional_projection else "parameter_slice")),
            "selected_parameter": parameter,
            "available_parameters": numeric_parameter_names(parameter_space),
            "x_label": parameter.replace("_", " ").title(),
            "x_unit": _parameter_unit(parameter),
            "fixed_parameters": fixed_parameters,
            "fixed_parameter_source": "none" if gp_surface else ("observed_design_marginal" if marginal_projection else "selected_candidate"),
            "anchor_count": 0 if response_surface else (int(projection.get("anchor_count") or 0) if (marginal_projection or conditional_projection) else 0),
        },
        "posterior": selected_slice["posterior"],
        "gp_surface": gp_surface,
        "objective_trace": _objective_trace(
            gp_surface,
            training_observations,
            next_point,
            objective_path=projection.get("objective_path"),
            acquisition_class=acquisition_class,
            direction=objective_info["direction"],
            exploration_margin=_finite(trace.get("xi")) or 0.01,
        ),
        "gp_series": gp_series,
        "training_observations": training_observations,
        "acquisition": {
            "name": "Expected Improvement" if acquisition_class.lower() == "logexpectedimprovement" else acquisition_class,
            "raw_name": acquisition_class,
            **selected_slice["acquisition"],
        },
        "observations": observations,
        "current_best": current_best,
        "next_point": next_point,
        "parameter_slices": parameter_slices,
        "candidate_index_view": {
            "x": [item[0] for item in audit_rows],
            "mean": [item[1] for item in audit_rows],
            "std": [item[2] for item in audit_rows],
            "lower_95": [item[1] - 1.96 * item[2] for item in audit_rows],
            "upper_95": [item[1] + 1.96 * item[2] for item in audit_rows],
            "acquisition": [item[3] for item in audit_rows],
            "candidate_ids": [item[4] for item in audit_rows],
        },
        "backend": {
            "requested": str(trace.get("backend_requested") or "botorch"),
            "active": backend_active,
            "model": "SingleTaskGP" if backend_active == "botorch" else ("LatinHypercube" if backend_active == "lhs" else "pool_projection"),
            "phase": str(trace.get("phase") or ""),
            "optimizer": dict(trace.get("optimizer") or {}) if isinstance(trace.get("optimizer"), dict) else {},
            "kernel": str(model.get("kernel") or "ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=2))"),
            "noise_mode": str(model.get("noise_mode") or "inferred_homoskedastic"),
            "input_normalization": str(model.get("input_normalization") or "unit_hypercube"),
            "training_count": int(model.get("training_count") or len(training_observations)),
        },
        "status": "complete",
        "warnings": warnings,
    }
    return validate_bo_visualization(payload)


def rebuild_legacy_continuous_objective_trace(
    visualization: dict[str, Any],
    *,
    parameter_space: dict[str, Any],
    random_seed: int = 7,
    num_restarts: int = 12,
    raw_samples: int = 256,
    optimizer_timeout_s: float | None = None,
    fit_max_iter: int = 50,
) -> dict[str, Any]:
    """Refit a legacy segmented plot without changing the BO run decision."""
    payload = dict(visualization)
    objective_trace = payload.get("objective_trace") if isinstance(payload.get("objective_trace"), dict) else {}
    if objective_trace.get("path_mode") == "continuous_2d_gp_path":
        return payload
    observations = payload.get("training_observations") if isinstance(payload.get("training_observations"), list) else []
    space = BOParameterSpace.from_mapping(parameter_space)
    if space.active_dimension_count != 2 or len(observations) < 2:
        return payload

    from learning.botorch_backend import propose_next

    acquisition = payload.get("acquisition") if isinstance(payload.get("acquisition"), dict) else {}
    raw_acquisition = str(acquisition.get("raw_name") or acquisition.get("name") or "expected_improvement")
    acquisition_name = "expected_improvement" if raw_acquisition.lower() == "logexpectedimprovement" else raw_acquisition
    objective = payload.get("objective") if isinstance(payload.get("objective"), dict) else {}
    selected = dict(payload.get("next_point") or {})
    selected_parameters = selected.get("parameters") if isinstance(selected.get("parameters"), dict) else None
    proposal = propose_next(
        parameter_space=space,
        observations=observations,
        acquisition=acquisition_name,
        objective_direction=str(objective.get("direction") or "maximize"),
        random_seed=int(random_seed),
        num_restarts=int(num_restarts),
        raw_samples=int(raw_samples),
        optimizer_timeout_s=optimizer_timeout_s,
        fit_max_iter=int(fit_max_iter),
        projection_candidate=selected_parameters,
    ).to_dict()
    payload["objective_trace"] = _objective_trace(
        {},
        observations,
        selected,
        objective_path=proposal["projection"].get("objective_path"),
        acquisition_class=str(proposal["acquisition"].get("class") or ""),
        direction=str(objective.get("direction") or "maximize"),
        exploration_margin=_finite(objective_trace.get("exploration_margin")) or 0.01,
    )
    return validate_bo_visualization(payload)


def _validate_numeric_arrays(container: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    arrays = [container.get(key) for key in keys]
    if not all(isinstance(values, list) for values in arrays):
        raise ValueError(f"{label} arrays must be lists")
    lengths = {len(values) for values in arrays}
    if len(lengths) != 1:
        raise ValueError(f"{label} arrays must have equal lengths")
    if any(_finite(value) is None for values in arrays for value in values):
        raise ValueError(f"{label} arrays must contain finite numbers")


def validate_bo_visualization(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError(f"BO visualization schema must be {SCHEMA}")
    posterior = payload.get("posterior") if isinstance(payload.get("posterior"), dict) else {}
    _validate_numeric_arrays(posterior, ("x", "mean", "std", "lower_95", "upper_95"), "posterior")
    acquisition = payload.get("acquisition") if isinstance(payload.get("acquisition"), dict) else {}
    _validate_numeric_arrays(acquisition, ("x", "value"), "acquisition")
    if len(posterior["x"]) != len(acquisition["x"]):
        raise ValueError("posterior and acquisition arrays must have equal lengths")
    audit = payload.get("candidate_index_view") if isinstance(payload.get("candidate_index_view"), dict) else {}
    _validate_numeric_arrays(audit, ("x", "mean", "std", "lower_95", "upper_95", "acquisition"), "candidate index")
    if len(audit["x"]) != len(audit.get("candidate_ids", [])):
        raise ValueError("candidate index arrays must match candidate ids")
    surface = payload.get("gp_surface") if isinstance(payload.get("gp_surface"), dict) else {}
    if surface:
        x_values = surface.get("x_values")
        y_values = surface.get("y_values")
        shape = surface.get("shape")
        if not isinstance(x_values, list) or not isinstance(y_values, list) or shape != [len(x_values), len(y_values)]:
            raise ValueError("GP surface axes and shape must agree")
        if any(_finite(value) is None for value in [*x_values, *y_values]):
            raise ValueError("GP surface axes must contain finite numbers")
        for key in ("mean", "std", "lower_95", "upper_95", "acquisition"):
            matrix = surface.get(key)
            if not isinstance(matrix, list) or len(matrix) != len(x_values):
                raise ValueError(f"GP surface {key} matrix must match x axis")
            if any(not isinstance(row, list) or len(row) != len(y_values) for row in matrix):
                raise ValueError(f"GP surface {key} matrix must match y axis")
            if any(_finite(value) is None for row in matrix for value in row):
                raise ValueError(f"GP surface {key} matrix must contain finite numbers")
    series_rows = payload.get("gp_series") if isinstance(payload.get("gp_series"), list) else []
    for index, series in enumerate(series_rows):
        if not isinstance(series, dict):
            raise ValueError(f"GP series {index} must be an object")
        _validate_numeric_arrays(
            series,
            ("x", "mean", "std", "lower_95", "upper_95", "acquisition"),
            f"GP series {index}",
        )
    parameter_slices = payload.get("parameter_slices", {})
    if not isinstance(parameter_slices, dict):
        raise ValueError("parameter slices must be an object")
    for name, slice_payload in parameter_slices.items():
        if not isinstance(slice_payload, dict):
            raise ValueError(f"parameter slice {name} must be an object")
        slice_posterior = slice_payload.get("posterior") if isinstance(slice_payload.get("posterior"), dict) else {}
        _validate_numeric_arrays(slice_posterior, ("x", "mean", "std", "lower_95", "upper_95"), f"parameter slice {name} posterior")
        slice_acquisition = slice_payload.get("acquisition") if isinstance(slice_payload.get("acquisition"), dict) else {}
        _validate_numeric_arrays(slice_acquisition, ("x", "value"), f"parameter slice {name} acquisition")
        if len(slice_posterior["x"]) != len(slice_acquisition["x"]):
            raise ValueError(f"parameter slice {name} arrays must have equal lengths")
    return payload
