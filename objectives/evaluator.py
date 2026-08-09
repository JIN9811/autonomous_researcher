"""Deterministic evaluator for statically compiled objective expressions."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

from objectives.compiler import CompiledObjective
from objectives.schemas import ObjectiveEvaluation


@dataclass
class _Value:
    value: float | bool
    contributions: dict[str, float] = field(default_factory=dict)


def _merge_contributions(values: list[_Value], factors: list[float] | None = None) -> dict[str, float]:
    merged: dict[str, float] = {}
    factors = factors or [1.0] * len(values)
    for item, factor in zip(values, factors, strict=True):
        for key, value in item.contributions.items():
            merged[key] = merged.get(key, 0.0) + factor * value
    return merged


def _number(value: _Value, path: str) -> float:
    if isinstance(value.value, bool):
        raise ValueError(f"{path}: expected numeric value")
    numeric = float(value.value)
    if not math.isfinite(numeric):
        raise ValueError(f"{path}: objective output must be finite")
    return numeric


def _evaluate(node: dict[str, Any], metrics: dict[str, float], path: str = "expression") -> _Value:
    operator = node["op"]
    if operator == "literal":
        return _Value(float(node["value"]))
    if operator == "metric":
        metric_id = str(node["metric_id"])
        if metric_id not in metrics:
            raise ValueError(f"{path}: missing metric {metric_id}")
        value = float(metrics[metric_id])
        if not math.isfinite(value):
            raise ValueError(f"{path}: metric {metric_id} must be finite")
        return _Value(value, {metric_id: value})

    if operator in {"add", "subtract", "multiply", "min", "max", "aggregate"}:
        values = [_evaluate(item, metrics, f"{path}.args[{index}]") for index, item in enumerate(node["args"])]
        numbers = [_number(value, path) for value in values]
        if operator == "add":
            result = sum(numbers)
        elif operator == "subtract":
            result = numbers[0] - sum(numbers[1:])
        elif operator == "multiply":
            result = math.prod(numbers)
        elif operator == "min":
            result = min(numbers)
        elif operator == "max":
            result = max(numbers)
        else:
            method = node.get("method", "mean")
            result = sum(numbers) / len(numbers) if method == "mean" else sum(numbers) if method == "sum" else math.prod(numbers)
        factors = [1.0, *([-1.0] * (len(values) - 1))] if operator == "subtract" else None
        return _Value(result, _merge_contributions(values, factors))

    if operator in {"divide", "ratio"}:
        numerator = _evaluate(node["numerator"], metrics, f"{path}.numerator")
        denominator = _evaluate(node["denominator"], metrics, f"{path}.denominator")
        denominator_value = _number(denominator, path)
        epsilon = float(node["epsilon"])
        if abs(denominator_value) <= epsilon:
            raise ValueError(f"{path}: denominator is within epsilon of zero")
        value = _number(numerator, path) / denominator_value
        return _Value(value, _merge_contributions([numerator, denominator]))

    if operator == "weighted_sum":
        result = 0.0
        contributions: dict[str, float] = {}
        for index, term in enumerate(node["terms"]):
            item = _evaluate(term["expression"], metrics, f"{path}.terms[{index}].expression")
            weighted = float(term["weight"]) * _number(item, path)
            name = str(term.get("name") or f"term_{index}")
            contributions[name] = weighted
            result += weighted
        return _Value(result, contributions)

    if operator in {"abs", "square", "power", "sqrt", "log1p"}:
        item = _evaluate(node["arg"], metrics, f"{path}.arg")
        value = _number(item, path)
        if operator == "abs":
            result = abs(value)
        elif operator == "square":
            result = value * value
        elif operator == "power":
            result = math.pow(value, float(node["exponent"]))
        elif operator == "sqrt":
            if value < 0:
                raise ValueError(f"{path}: sqrt input must be non-negative")
            result = math.sqrt(value)
        else:
            if value <= -1:
                raise ValueError(f"{path}: log1p input must exceed -1")
            result = math.log1p(value)
        return _Value(result, item.contributions)

    if operator in {"clip", "normalize"}:
        value = _number(_evaluate(node["value"], metrics, f"{path}.value"), path)
        lower = _number(_evaluate(node["min"], metrics, f"{path}.min"), path)
        upper = _number(_evaluate(node["max"], metrics, f"{path}.max"), path)
        if upper <= lower:
            raise ValueError(f"{path}: max must be greater than min")
        result = min(max(value, lower), upper)
        if operator == "normalize":
            result = (result - lower) / (upper - lower)
        return _Value(result)

    if operator == "target_deviation":
        value = _number(_evaluate(node["value"], metrics, f"{path}.value"), path)
        target = _number(_evaluate(node["target"], metrics, f"{path}.target"), path)
        scale = _number(_evaluate(node["scale"], metrics, f"{path}.scale"), path)
        if scale <= 0:
            raise ValueError(f"{path}: scale must be positive")
        return _Value(abs(value - target) / scale)

    if operator == "hinge_penalty":
        value = _number(_evaluate(node["value"], metrics, f"{path}.value"), path)
        threshold = _number(_evaluate(node["threshold"], metrics, f"{path}.threshold"), path)
        scale = _number(_evaluate(node["scale"], metrics, f"{path}.scale"), path)
        if scale <= 0:
            raise ValueError(f"{path}: scale must be positive")
        delta = value - threshold if node.get("side", "above") == "above" else threshold - value
        return _Value(max(delta, 0.0) / scale)

    if operator == "piecewise_penalty":
        value = _number(_evaluate(node["value"], metrics, f"{path}.value"), path)
        points = [
            (_number(_evaluate(point["x"], metrics, f"{path}.points[{index}].x"), path), float(point["y"]))
            for index, point in enumerate(node["points"])
        ]
        if value <= points[0][0]:
            return _Value(points[0][1])
        if value >= points[-1][0]:
            return _Value(points[-1][1])
        for (left_x, left_y), (right_x, right_y) in zip(points, points[1:], strict=False):
            if left_x <= value <= right_x:
                ratio = (value - left_x) / (right_x - left_x)
                return _Value(left_y + ratio * (right_y - left_y))

    if operator in {"less_than", "less_equal", "greater_than", "greater_equal", "equal"}:
        left = _number(_evaluate(node["args"][0], metrics, f"{path}.args[0]"), path)
        right = _number(_evaluate(node["args"][1], metrics, f"{path}.args[1]"), path)
        comparisons = {
            "less_than": left < right,
            "less_equal": left <= right,
            "greater_than": left > right,
            "greater_equal": left >= right,
            "equal": math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12),
        }
        return _Value(comparisons[operator])

    if operator in {"and", "or"}:
        values = [bool(_evaluate(item, metrics, f"{path}.args[{index}]").value) for index, item in enumerate(node["args"])]
        return _Value(all(values) if operator == "and" else any(values))
    if operator == "not":
        return _Value(not bool(_evaluate(node["arg"], metrics, f"{path}.arg").value))
    raise ValueError(f"{path}: unsupported compiled operator {operator}")


def _score(compiled: CompiledObjective, metrics: dict[str, float]) -> tuple[float, float, dict[str, float]]:
    result = _evaluate(compiled.spec.expression, metrics)
    raw = _number(result, "expression")
    score = raw if compiled.spec.direction == "maximize" else -raw
    if not math.isfinite(score):
        raise ValueError("objective score must be finite")
    return score, raw, result.contributions


def _uncertainty(
    compiled: CompiledObjective,
    metrics: dict[str, float],
    base_score: float,
    uncertainty: float | dict[str, float] | None,
) -> float | None:
    if uncertainty is None:
        return None
    if isinstance(uncertainty, (int, float)):
        value = float(uncertainty)
        if not math.isfinite(value) or value < 0:
            raise ValueError("uncertainty must be finite and non-negative")
        return value
    deltas: list[float] = []
    for metric_id, spread in sorted(uncertainty.items()):
        if metric_id not in metrics:
            continue
        numeric = float(spread)
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError(f"uncertainty for {metric_id} must be finite and non-negative")
        perturbed = dict(metrics)
        perturbed[metric_id] = perturbed[metric_id] + numeric
        perturbed_score, _, _ = _score(compiled, perturbed)
        deltas.append(perturbed_score - base_score)
    return math.sqrt(sum(delta * delta for delta in deltas)) if deltas else 0.0


def evaluate_objective(
    compiled: CompiledObjective,
    metrics: dict[str, Any],
    observation_id: str,
    uncertainty: float | dict[str, float] | None = None,
    *,
    provenance_refs: list[str] | None = None,
    fidelity: str = "measured",
) -> ObjectiveEvaluation:
    """Evaluate a compiled objective without code execution or LLM involvement."""
    validated: dict[str, float] = {}
    for metric_id in compiled.validation.metric_ids:
        if metric_id not in metrics:
            raise ValueError(f"missing metric {metric_id}")
        validated[metric_id] = compiled.registry.validate_metric_value(metric_id, metrics[metric_id])

    score, raw, contributions = _score(compiled, validated)
    constraint_results: list[dict[str, Any]] = []
    for index, constraint in enumerate(compiled.spec.constraints):
        passed = bool(_evaluate(constraint, validated, f"constraints[{index}]").value)
        constraint_results.append({"index": index, "passed": passed})
    evaluation_id = "objective-eval-" + hashlib.sha256(
        f"{compiled.objective_hash}:{observation_id}".encode()
    ).hexdigest()[:16]
    return ObjectiveEvaluation(
        evaluation_id=evaluation_id,
        objective_id=compiled.spec.objective_id,
        objective_version=compiled.spec.version,
        objective_hash=compiled.objective_hash,
        observation_id=observation_id,
        score=score,
        raw_value=raw,
        feasible=all(item["passed"] for item in constraint_results),
        term_contributions={key: float(value) for key, value in contributions.items()},
        constraint_results=constraint_results,
        uncertainty=_uncertainty(compiled, validated, score, uncertainty),
        metrics=validated,
        provenance_refs=provenance_refs or [observation_id],
        fidelity=fidelity,
        created_at=compiled.spec.created_at,
    )
