"""Build the shared, read-only BO visualization projection.

This module does not select candidates or evaluate experiments. It converts an
already-computed BO trace into a bounded payload shared by browser and artifact
renderers.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


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

    def normalized_range(name: str) -> float:
        raw = parameter_space.get(name)
        values = raw if isinstance(raw, list) else [raw]
        numbers = [float(item) for item in values if _finite(item) is not None]
        if not numbers:
            return -1.0
        return max(numbers) - min(numbers)

    return max(numeric, key=normalized_range)


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


def _candidate_rows(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in trace.get("candidates", []) if isinstance(item, dict)]


def _observations(trace: dict[str, Any], selected_parameter: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in trace.get("evaluated_points", []):
        if not isinstance(item, dict):
            continue
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        x = _finite(parameters.get(selected_parameter))
        score = _finite(item.get("score"))
        if x is None or score is None:
            continue
        rows.append({"candidate_id": str(item.get("candidate_id") or ""), "x": x, "score": score})
    return sorted(rows, key=lambda item: (item["x"], item["candidate_id"]))


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


def _parameter_slice(
    *,
    parameter: str,
    candidates: list[dict[str, Any]],
    trace: dict[str, Any],
    direction: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in candidates:
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        x = _finite(parameters.get(parameter))
        mean = _finite(item.get("surrogate_mean"))
        std = _finite(item.get("uncertainty"))
        acquisition = _finite(item.get("acquisition_value"))
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
            "acquisition": _finite(selected.get("acquisition_value")),
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
    parameter_slices = {
        name: _parameter_slice(
            parameter=name,
            candidates=candidates,
            trace=trace,
            direction=objective_info["direction"],
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

    audit_rows = []
    for index, item in enumerate(candidates, start=1):
        x = _finite(item.get("x")) or float(index)
        mean = _finite(item.get("surrogate_mean"))
        std = _finite(item.get("uncertainty"))
        acquisition = _finite(item.get("acquisition_value"))
        if None in {mean, std, acquisition}:
            continue
        audit_rows.append((x, mean, max(0.0, std), acquisition, str(item.get("candidate_id") or "")))

    fixed_parameters = {
        key: value
        for key, value in (best_parameters or selected_parameters).items()
        if key != parameter and isinstance(value, (str, int, float, bool))
    }
    warnings: list[str] = []
    if not selected_slice["posterior"]["x"]:
        warnings.append(f"No candidate posterior values contain selected parameter: {parameter}")
    warnings.append("Parameter slice is a candidate-pool projection, not an arbitrary-point GP posterior.")

    payload = {
        "schema": SCHEMA,
        "run_id": str(run_id or ""),
        "step": int(trace.get("step") or 0),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objective": objective_info,
        "view": {
            "mode": "parameter_slice",
            "selected_parameter": parameter,
            "available_parameters": numeric_parameter_names(parameter_space),
            "x_label": parameter.replace("_", " ").title(),
            "x_unit": _parameter_unit(parameter),
            "fixed_parameters": fixed_parameters,
            "fixed_parameter_source": "current_best" if best_parameters else "selected_candidate",
        },
        "posterior": selected_slice["posterior"],
        "acquisition": {"name": str(trace.get("acquisition") or "acquisition"), **selected_slice["acquisition"]},
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
            "requested": str(trace.get("backend_requested") or "lightweight_pool"),
            "active": str(trace.get("backend_active") or "lightweight_pool"),
            "model": "pool_projection",
        },
        "status": "complete",
        "warnings": warnings,
    }
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
