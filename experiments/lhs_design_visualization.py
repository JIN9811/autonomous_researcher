"""Dedicated visualization contract for mixed-space Latin hypercube designs."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from scipy.stats import qmc


SCHEMA = "lhs_design_visualization.v1"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _cell_axis(parameter_space: dict[str, Any]) -> dict[str, Any]:
    raw = parameter_space.get("cell_size_mm")
    values = raw if isinstance(raw, list) else []
    output = sorted({_finite(item) for item in values if _finite(item) is not None})
    numeric = [float(item) for item in output]
    if len(numeric) == 2:
        return {"name": "cell_size_mm", "label": "Cell size", "unit": "mm", "kind": "continuous", "bounds": numeric}
    return {"name": "cell_size_mm", "label": "Cell size", "unit": "mm", "kind": "discrete", "values": numeric}


def _density_bounds(parameter_space: dict[str, Any]) -> list[float]:
    raw = parameter_space.get("relative_density")
    values = raw if isinstance(raw, list) else []
    numeric = [_finite(item) for item in values]
    if len(numeric) >= 2 and numeric[0] is not None and numeric[-1] is not None:
        return [float(numeric[0]), float(numeric[-1])]
    return [0.20, 0.48]


def _normalized_points(points: list[dict[str, Any]], x_axis: dict[str, Any], bounds: list[float]) -> list[list[float]]:
    rows: list[list[float]] = []
    density_span = bounds[1] - bounds[0]
    cells = [float(item) for item in x_axis.get("values", [])]
    cell_bounds = [float(item) for item in x_axis.get("bounds", [])]
    for item in points:
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        cell = _finite(parameters.get("cell_size_mm"))
        density = _finite(parameters.get("relative_density"))
        if cell is None or density is None or density_span <= 0:
            continue
        if x_axis.get("kind") == "continuous" and len(cell_bounds) == 2:
            cell_unit = (cell - cell_bounds[0]) / max(cell_bounds[1] - cell_bounds[0], 1e-12)
        elif cell in cells:
            cell_unit = cells.index(cell) / max(1, len(cells) - 1)
        else:
            continue
        rows.append([cell_unit, (density - bounds[0]) / density_span])
    return rows


def build_lhs_design_visualization(
    *,
    run_id: str,
    parameter_space: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    """Build a standalone LHS design-space payload without BO posterior fields."""
    initial = trace.get("initial_design") if isinstance(trace.get("initial_design"), dict) else {}
    target = max(1, int(initial.get("target") or 8))
    completed = max(0, min(target, int(initial.get("completed") or 0)))
    x_axis = _cell_axis(parameter_space)
    bounds = _density_bounds(parameter_space)
    points: list[dict[str, Any]] = []
    for fallback_index, item in enumerate(initial.get("points", []), start=1):
        if not isinstance(item, dict):
            continue
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        cell = _finite(parameters.get("cell_size_mm"))
        density = _finite(parameters.get("relative_density"))
        if cell is None or density is None:
            continue
        stratum = min(target, max(1, int((density - bounds[0]) / max(bounds[1] - bounds[0], 1e-12) * target) + 1))
        points.append(
            {
                "index": int(item.get("index") or fallback_index),
                "candidate_id": str(item.get("candidate_id") or f"lhs-candidate-{fallback_index:03d}"),
                "status": str(item.get("status") or ("measured" if fallback_index <= completed else "planned")),
                "density_stratum": stratum,
                "parameters": {"cell_size_mm": cell, "relative_density": density},
            }
        )

    signatures = [(item["parameters"]["cell_size_mm"], item["parameters"]["relative_density"]) for item in points]
    normalized = _normalized_points(points, x_axis, bounds)
    discrepancy = float(qmc.discrepancy(normalized, method="CD")) if normalized else 0.0
    payload = {
        "schema": SCHEMA,
        "run_id": str(run_id or ""),
        "step": int(trace.get("step") or min(completed + 1, target)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "design_space": {
            "dimension": 2,
            "mode": "mixed_discrete_continuous",
            "x": x_axis,
            "y": {"name": "relative_density", "label": "Relative density", "unit": "1", "kind": "continuous", "bounds": bounds},
            "normalization": "unit_hypercube",
        },
        "initial_design": {
            "sampler": str(initial.get("sampler") or "latin_hypercube"),
            "target": target,
            "completed": completed,
            "seed": int(initial.get("seed") or 7),
            "points": points,
        },
        "diagnostics": {
            "coverage_fraction": completed / target,
            "centered_discrepancy": discrepancy,
            "duplicate_count": len(signatures) - len(set(signatures)),
            "occupied_density_strata": sorted({item["density_stratum"] for item in points}),
        },
        "status": "complete" if completed >= target else "active",
    }
    return validate_lhs_design_visualization(payload)


def validate_lhs_design_visualization(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError(f"LHS visualization schema must be {SCHEMA}")
    design_space = payload.get("design_space") if isinstance(payload.get("design_space"), dict) else {}
    x_axis = design_space.get("x") if isinstance(design_space.get("x"), dict) else {}
    y_axis = design_space.get("y") if isinstance(design_space.get("y"), dict) else {}
    cells = [float(item) for item in x_axis.get("values", []) if _finite(item) is not None]
    cell_bounds = [float(item) for item in x_axis.get("bounds", []) if _finite(item) is not None]
    bounds = [float(item) for item in y_axis.get("bounds", []) if _finite(item) is not None]
    if x_axis.get("kind") == "continuous":
        if len(cell_bounds) != 2 or cell_bounds[0] >= cell_bounds[1]:
            raise ValueError("continuous cell_size_mm bounds must be finite and ascending")
    elif not cells:
        raise ValueError("discrete cell_size_mm values are required")
    if len(bounds) != 2 or bounds[0] >= bounds[1]:
        raise ValueError("relative_density bounds must be finite and ascending")
    initial = payload.get("initial_design") if isinstance(payload.get("initial_design"), dict) else {}
    target = int(initial.get("target") or 0)
    completed = int(initial.get("completed") or 0)
    if target < 1 or completed < 0 or completed > target:
        raise ValueError("initial design progress is invalid")
    for item in initial.get("points", []):
        if not isinstance(item, dict):
            raise ValueError("LHS points must be objects")
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        cell = _finite(parameters.get("cell_size_mm"))
        density = _finite(parameters.get("relative_density"))
        cell_valid = cell is not None and (
            (x_axis.get("kind") == "continuous" and cell_bounds[0] <= cell <= cell_bounds[1])
            or (x_axis.get("kind") != "continuous" and cell in cells)
        )
        if not cell_valid:
            raise ValueError(f"cell_size_mm={cell} is outside the feasible set")
        if density is None or not bounds[0] <= density <= bounds[1]:
            raise ValueError(f"relative_density={density} is outside bounds")
        if str(item.get("status") or "") not in {"measured", "next", "planned"}:
            raise ValueError("LHS point status must be measured, next, or planned")
    return payload
