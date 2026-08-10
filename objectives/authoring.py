"""Server-owned authoring contract for bounded objective editors."""

from __future__ import annotations

from typing import Any

from objectives.compiler import MAX_AST_DEPTH, MAX_AST_NODES, OPERATOR_KEYS, UNIT_DIMENSIONS


_LABELS = {
    "literal": "Literal",
    "metric": "Metric",
    "reference": "Reference",
    "add": "Add",
    "subtract": "Subtract",
    "multiply": "Multiply",
    "divide": "Divide",
    "weighted_sum": "Weighted Sum",
    "ratio": "Ratio",
    "abs": "Absolute Value",
    "square": "Square",
    "power": "Power",
    "sqrt": "Square Root",
    "log1p": "Log One Plus",
    "min": "Minimum",
    "max": "Maximum",
    "clip": "Clip",
    "target_deviation": "Target Deviation",
    "hinge_penalty": "Hinge Penalty",
    "piecewise_penalty": "Piecewise Penalty",
    "normalize": "Normalize",
    "aggregate": "Aggregate",
    "less_than": "Less Than",
    "less_equal": "Less or Equal",
    "greater_than": "Greater Than",
    "greater_equal": "Greater or Equal",
    "equal": "Equal",
    "and": "And",
    "or": "Or",
    "not": "Not",
}

_BOOLEAN_OPERATORS = frozenset(
    {"less_than", "less_equal", "greater_than", "greater_equal", "equal", "and", "or", "not"}
)
_VARIADIC_OPERATORS = frozenset(
    {"add", "subtract", "multiply", "min", "max", "less_than", "less_equal", "greater_than", "greater_equal", "equal", "and", "or"}
)
_UNARY_OPERATORS = frozenset({"abs", "square", "sqrt", "log1p", "not", "power"})
_SLOT_OPERATORS = {
    "divide": ["numerator", "denominator"],
    "ratio": ["numerator", "denominator"],
    "clip": ["value", "min", "max"],
    "target_deviation": ["value", "target", "scale"],
    "hinge_penalty": ["value", "threshold", "scale"],
    "normalize": ["value", "min", "max"],
}
_FIELD_DESCRIPTORS: dict[str, list[dict[str, Any]]] = {
    "literal": [
        {"name": "value", "type": "number", "required": True, "default": 0.0},
        {"name": "unit", "type": "unit", "required": True, "default": "1"},
    ],
    "metric": [{"name": "metric_id", "type": "metric", "required": True}],
    "reference": [{"name": "name", "type": "text", "required": True}],
    "divide": [{"name": "epsilon", "type": "positive_number", "required": True, "default": 1e-9}],
    "ratio": [{"name": "epsilon", "type": "positive_number", "required": True, "default": 1e-9}],
    "power": [{"name": "exponent", "type": "number", "required": True, "default": 2.0, "min": -4.0, "max": 4.0}],
    "hinge_penalty": [{"name": "side", "type": "choice", "required": True, "default": "above", "choices": ["above", "below"]}],
    "aggregate": [{"name": "method", "type": "choice", "required": True, "default": "mean", "choices": ["mean", "median", "min", "max"]}],
}


def _children_for(operator: str) -> dict[str, Any]:
    if operator in {"literal", "metric", "reference"}:
        return {"mode": "none"}
    if operator in _VARIADIC_OPERATORS:
        minimum = 1 if operator in {"and", "or"} else 2
        return {"mode": "args", "minimum": minimum}
    if operator in _UNARY_OPERATORS:
        return {"mode": "arg", "slots": ["arg"]}
    if operator in _SLOT_OPERATORS:
        return {"mode": "slots", "slots": list(_SLOT_OPERATORS[operator])}
    if operator == "weighted_sum":
        return {"mode": "terms", "minimum": 1}
    if operator == "piecewise_penalty":
        return {"mode": "piecewise", "slots": ["value"], "minimum_points": 2}
    if operator == "aggregate":
        return {"mode": "args", "minimum": 1}
    raise AssertionError(f"missing objective authoring child descriptor: {operator}")


def _category_for(operator: str) -> str:
    if operator in {"literal", "metric", "reference"}:
        return "source"
    if operator in _BOOLEAN_OPERATORS:
        return "boolean"
    if "penalty" in operator or operator == "target_deviation":
        return "penalty"
    if operator in {"normalize", "aggregate", "clip"}:
        return "transform"
    return "numeric"


def objective_authoring_manifest() -> dict[str, object]:
    """Return the JSON-safe UI contract derived from the active compiler."""
    if set(_LABELS) != set(OPERATOR_KEYS):
        missing = sorted(set(OPERATOR_KEYS) - set(_LABELS))
        stale = sorted(set(_LABELS) - set(OPERATOR_KEYS))
        raise RuntimeError(f"objective authoring manifest drift: missing={missing}; stale={stale}")
    operators = []
    for operator in sorted(OPERATOR_KEYS):
        operators.append(
            {
                "op": operator,
                "label": _LABELS[operator],
                "category": _category_for(operator),
                "kind": "leaf" if operator in {"literal", "metric", "reference"} else "expression",
                "result_kind": "boolean" if operator in _BOOLEAN_OPERATORS else "number",
                "enabled": operator != "reference",
                "children": _children_for(operator),
                "fields": _FIELD_DESCRIPTORS.get(operator, []),
                "allowed_fields": sorted(OPERATOR_KEYS[operator]),
            }
        )
    return {
        "schema_version": "objective_authoring_manifest.v1",
        "operators": operators,
        "units": sorted(UNIT_DIMENSIONS),
        "limits": {"max_depth": MAX_AST_DEPTH, "max_nodes": MAX_AST_NODES},
    }
