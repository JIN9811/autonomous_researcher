"""Static compiler for the bounded, unit-safe objective expression DSL."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from objectives.metric_registry import MetricRegistry
from objectives.schemas import ObjectiveSpec, ObjectiveValidation


MAX_AST_DEPTH = 16
MAX_AST_NODES = 256
MAX_ABS_POWER = 4.0

Dimension = tuple[tuple[str, Fraction], ...]
ValueKind = Literal["number", "boolean"]


def _dimension(**powers: int) -> Dimension:
    return tuple(sorted((name, Fraction(power)) for name, power in powers.items() if power))


DIMENSIONLESS: Dimension = ()
DIMENSIONS: dict[str, Dimension] = {
    "dimensionless": DIMENSIONLESS,
    "force": _dimension(force=1),
    "length": _dimension(length=1),
    "stiffness": _dimension(force=1, length=-1),
    "stress": _dimension(force=1, length=-2),
    "energy": _dimension(force=1, length=1),
    "energy_density": _dimension(force=1, length=-2),
    "specific_energy": _dimension(length=2, time=-2),
    "time": _dimension(time=1),
}
UNIT_DIMENSIONS: dict[str, Dimension] = {
    "1": DIMENSIONLESS,
    "": DIMENSIONLESS,
    "N": DIMENSIONS["force"],
    "mm": DIMENSIONS["length"],
    "N/mm": DIMENSIONS["stiffness"],
    "MPa": DIMENSIONS["stress"],
    "mJ": DIMENSIONS["energy"],
    "mJ/mm3": DIMENSIONS["energy_density"],
    "J/g": DIMENSIONS["specific_energy"],
    "s": DIMENSIONS["time"],
    "min": DIMENSIONS["time"],
}

OPERATOR_KEYS: dict[str, frozenset[str]] = {
    "literal": frozenset({"op", "value", "unit"}),
    "metric": frozenset({"op", "metric_id"}),
    "reference": frozenset({"op", "name"}),
    "add": frozenset({"op", "args"}),
    "subtract": frozenset({"op", "args"}),
    "multiply": frozenset({"op", "args"}),
    "divide": frozenset({"op", "numerator", "denominator", "epsilon"}),
    "ratio": frozenset({"op", "numerator", "denominator", "epsilon"}),
    "weighted_sum": frozenset({"op", "terms"}),
    "abs": frozenset({"op", "arg"}),
    "square": frozenset({"op", "arg"}),
    "power": frozenset({"op", "arg", "exponent"}),
    "sqrt": frozenset({"op", "arg"}),
    "log1p": frozenset({"op", "arg"}),
    "min": frozenset({"op", "args"}),
    "max": frozenset({"op", "args"}),
    "clip": frozenset({"op", "value", "min", "max"}),
    "target_deviation": frozenset({"op", "value", "target", "scale"}),
    "hinge_penalty": frozenset({"op", "value", "threshold", "scale", "side"}),
    "piecewise_penalty": frozenset({"op", "value", "points"}),
    "normalize": frozenset({"op", "value", "min", "max"}),
    "aggregate": frozenset({"op", "args", "method"}),
    "less_than": frozenset({"op", "args"}),
    "less_equal": frozenset({"op", "args"}),
    "greater_than": frozenset({"op", "args"}),
    "greater_equal": frozenset({"op", "args"}),
    "equal": frozenset({"op", "args"}),
    "and": frozenset({"op", "args"}),
    "or": frozenset({"op", "args"}),
    "not": frozenset({"op", "arg"}),
}


def _combine(left: Dimension, right: Dimension, sign: int = 1) -> Dimension:
    values = dict(left)
    for key, power in right:
        values[key] = values.get(key, Fraction(0)) + sign * power
    return tuple(sorted((key, power) for key, power in values.items() if power))


def _power(dimension: Dimension, exponent: Fraction) -> Dimension:
    return tuple((key, power * exponent) for key, power in dimension if power * exponent)


def _dimension_name(dimension: Dimension) -> str:
    if dimension == DIMENSIONLESS:
        return "dimensionless"
    preferred = ("force", "length", "stiffness", "stress", "energy", "specific_energy", "time")
    for name in preferred:
        if DIMENSIONS[name] == dimension:
            return name
    return "*".join(
        name if exponent == 1 else f"{name}^{float(exponent):g}"
        for name, exponent in dimension
    )


@dataclass(frozen=True)
class NodeType:
    kind: ValueKind
    dimension: Dimension = DIMENSIONLESS


@dataclass(frozen=True)
class CompiledObjective:
    spec: ObjectiveSpec
    objective_hash: str
    validation: ObjectiveValidation
    registry: MetricRegistry


class ObjectiveCompileError(ValueError):
    def __init__(self, validation: ObjectiveValidation) -> None:
        self.validation = validation
        super().__init__(validation.errors[0] if validation.errors else "objective compilation failed")


class _Compiler:
    def __init__(self, registry: MetricRegistry) -> None:
        self.registry = registry
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.metric_ids: list[str] = []
        self._metric_seen: set[str] = set()
        self.node_count = 0
        self.max_depth = 0

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def compile_node(self, node: object, path: str, depth: int) -> NodeType:
        self.node_count += 1
        self.max_depth = max(self.max_depth, depth)
        if self.node_count > MAX_AST_NODES:
            self.error(path, f"AST node count exceeds {MAX_AST_NODES}")
            return NodeType("number")
        if depth > MAX_AST_DEPTH:
            self.error(path, f"AST depth exceeds {MAX_AST_DEPTH}")
            return NodeType("number")
        if not isinstance(node, dict):
            self.error(path, "expression node must be an object")
            return NodeType("number")
        operator = node.get("op")
        if not isinstance(operator, str):
            self.error(f"{path}.op", "operator is required")
            return NodeType("number")

        allowed_keys = OPERATOR_KEYS.get(operator)
        if allowed_keys is not None:
            unexpected = sorted(set(node) - allowed_keys)
            if unexpected:
                self.error(path, f"unexpected fields for {operator}: {', '.join(unexpected)}")

        method = getattr(self, f"compile_{operator}", None)
        if method is None:
            self.error(f"{path}.op", f"unsupported objective operator {operator!r}")
            return NodeType("number")
        return method(node, path, depth)

    def child(self, node: dict[str, Any], key: str, path: str, depth: int) -> NodeType:
        if key not in node:
            self.error(f"{path}.{key}", "field is required")
            return NodeType("number")
        return self.compile_node(node[key], f"{path}.{key}", depth + 1)

    def args(self, node: dict[str, Any], path: str, depth: int, minimum: int = 2) -> list[NodeType]:
        raw = node.get("args")
        if not isinstance(raw, list) or len(raw) < minimum:
            self.error(f"{path}.args", f"requires at least {minimum} expression nodes")
            return []
        return [self.compile_node(item, f"{path}.args[{index}]", depth + 1) for index, item in enumerate(raw)]

    def require_numbers(self, nodes: list[NodeType], path: str) -> None:
        if any(node.kind != "number" for node in nodes):
            self.error(path, "numeric operands are required")

    def require_compatible(self, nodes: list[NodeType], path: str) -> Dimension:
        self.require_numbers(nodes, path)
        dimensions = {node.dimension for node in nodes}
        if len(dimensions) > 1:
            names = sorted(_dimension_name(value) for value in dimensions)
            self.error(path, f"incompatible units: {', '.join(names)}")
        return nodes[0].dimension if nodes else DIMENSIONLESS

    def compile_literal(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        value = node.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            self.error(f"{path}.value", "literal must be a finite number")
        unit = node.get("unit", "1")
        if unit not in UNIT_DIMENSIONS:
            self.error(f"{path}.unit", f"unsupported unit {unit!r}")
        return NodeType("number", UNIT_DIMENSIONS.get(str(unit), DIMENSIONLESS))

    def compile_metric(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        metric_id = node.get("metric_id")
        if not isinstance(metric_id, str):
            self.error(f"{path}.metric_id", "metric_id is required")
            return NodeType("number")
        try:
            definition = self.registry.get(metric_id)
        except KeyError:
            self.error(f"{path}.metric_id", f"unknown metric: {metric_id}")
            return NodeType("number")
        if metric_id not in self._metric_seen:
            self.metric_ids.append(metric_id)
            self._metric_seen.add(metric_id)
        return NodeType("number", DIMENSIONS[definition.dimension])

    def compile_reference(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        self.error(path, "references require a future named-expression contract and are not enabled")
        return NodeType("number")

    def compile_add(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        values = self.args(node, path, depth)
        return NodeType("number", self.require_compatible(values, f"{path}.args"))

    compile_subtract = compile_add
    compile_min = compile_add
    compile_max = compile_add

    def compile_multiply(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        values = self.args(node, path, depth)
        self.require_numbers(values, f"{path}.args")
        dimension = DIMENSIONLESS
        for value in values:
            dimension = _combine(dimension, value.dimension)
        return NodeType("number", dimension)

    def _compile_division(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        numerator = self.child(node, "numerator", path, depth)
        denominator = self.child(node, "denominator", path, depth)
        self.require_numbers([numerator, denominator], path)
        epsilon = node.get("epsilon")
        if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)) or not math.isfinite(float(epsilon)) or epsilon <= 0:
            self.error(f"{path}.epsilon", "positive finite epsilon is required for division")
        return NodeType("number", _combine(numerator.dimension, denominator.dimension, -1))

    compile_divide = _compile_division
    compile_ratio = _compile_division

    def compile_weighted_sum(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        terms = node.get("terms")
        if not isinstance(terms, list) or not terms:
            self.error(f"{path}.terms", "at least one weighted term is required")
            return NodeType("number")
        values: list[NodeType] = []
        names: set[str] = set()
        for index, term in enumerate(terms):
            term_path = f"{path}.terms[{index}]"
            if not isinstance(term, dict):
                self.error(term_path, "weighted term must be an object")
                continue
            unexpected = sorted(set(term) - {"name", "weight", "expression"})
            if unexpected:
                self.error(term_path, f"unexpected weighted-term fields: {', '.join(unexpected)}")
            weight = term.get("weight")
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(float(weight)):
                self.error(f"{term_path}.weight", "weight must be finite")
            name = str(term.get("name") or f"term_{index}")
            if name in names:
                self.error(f"{term_path}.name", "term names must be unique")
            names.add(name)
            values.append(self.child(term, "expression", term_path, depth))
        return NodeType("number", self.require_compatible(values, f"{path}.terms"))

    def compile_abs(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        value = self.child(node, "arg", path, depth)
        self.require_numbers([value], path)
        return value

    def compile_square(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        value = self.compile_abs(node, path, depth)
        return NodeType("number", _power(value.dimension, Fraction(2)))

    def compile_power(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        value = self.child(node, "arg", path, depth)
        exponent = node.get("exponent")
        if isinstance(exponent, bool) or not isinstance(exponent, (int, float)) or not math.isfinite(float(exponent)):
            self.error(f"{path}.exponent", "finite exponent is required")
            return NodeType("number")
        if abs(float(exponent)) > MAX_ABS_POWER:
            self.error(f"{path}.exponent", f"absolute exponent must not exceed {MAX_ABS_POWER:g}")
        return NodeType("number", _power(value.dimension, Fraction(str(exponent))))

    def compile_sqrt(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        value = self.compile_abs(node, path, depth)
        return NodeType("number", _power(value.dimension, Fraction(1, 2)))

    def compile_log1p(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        value = self.compile_abs(node, path, depth)
        if value.dimension != DIMENSIONLESS:
            self.error(f"{path}.arg", "log1p input must be dimensionless")
        return NodeType("number")

    def compile_clip(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        values = [self.child(node, key, path, depth) for key in ("value", "min", "max")]
        return NodeType("number", self.require_compatible(values, path))

    def compile_normalize(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        values = [self.child(node, key, path, depth) for key in ("value", "min", "max")]
        self.require_compatible(values, path)
        return NodeType("number")

    def compile_target_deviation(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        values = [self.child(node, key, path, depth) for key in ("value", "target", "scale")]
        self.require_compatible(values, path)
        return NodeType("number")

    def compile_hinge_penalty(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        values = [self.child(node, key, path, depth) for key in ("value", "threshold", "scale")]
        self.require_compatible(values, path)
        if node.get("side", "above") not in {"above", "below"}:
            self.error(f"{path}.side", "side must be 'above' or 'below'")
        return NodeType("number")

    def compile_piecewise_penalty(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        value = self.child(node, "value", path, depth)
        points = node.get("points")
        if not isinstance(points, list) or len(points) < 2:
            self.error(f"{path}.points", "at least two piecewise points are required")
            return NodeType("number")
        x_nodes: list[NodeType] = []
        previous: float | None = None
        for index, point in enumerate(points):
            point_path = f"{path}.points[{index}]"
            if not isinstance(point, dict):
                self.error(point_path, "point must be an object")
                continue
            unexpected = sorted(set(point) - {"x", "y"})
            if unexpected:
                self.error(point_path, f"unexpected piecewise-point fields: {', '.join(unexpected)}")
            x_nodes.append(self.child(point, "x", point_path, depth))
            y = point.get("y")
            if isinstance(y, bool) or not isinstance(y, (int, float)) or not math.isfinite(float(y)):
                self.error(f"{point_path}.y", "penalty value must be finite")
            x_value = point.get("x", {}).get("value") if isinstance(point.get("x"), dict) else None
            if isinstance(x_value, (int, float)) and previous is not None and float(x_value) <= previous:
                self.error(f"{point_path}.x", "piecewise x values must increase")
            if isinstance(x_value, (int, float)):
                previous = float(x_value)
        self.require_compatible([value, *x_nodes], path)
        return NodeType("number")

    def compile_aggregate(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        values = self.args(node, path, depth, minimum=1)
        dimension = self.require_compatible(values, f"{path}.args")
        if node.get("method", "mean") not in {"mean", "sum", "product"}:
            self.error(f"{path}.method", "aggregate method must be mean, sum, or product")
        if dimension != DIMENSIONLESS:
            self.error(path, "aggregate inputs must be dimensionless")
        return NodeType("number")

    def _compile_comparison(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        values = self.args(node, path, depth, minimum=2)
        if len(values) != 2:
            self.error(f"{path}.args", "comparison requires exactly two operands")
        self.require_compatible(values, f"{path}.args")
        return NodeType("boolean")

    compile_less_than = _compile_comparison
    compile_less_equal = _compile_comparison
    compile_greater_than = _compile_comparison
    compile_greater_equal = _compile_comparison
    compile_equal = _compile_comparison

    def _compile_boolean_group(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        values = self.args(node, path, depth)
        if any(value.kind != "boolean" for value in values):
            self.error(f"{path}.args", "boolean operands are required")
        return NodeType("boolean")

    compile_and = _compile_boolean_group
    compile_or = _compile_boolean_group

    def compile_not(self, node: dict[str, Any], path: str, depth: int) -> NodeType:
        value = self.child(node, "arg", path, depth)
        if value.kind != "boolean":
            self.error(f"{path}.arg", "boolean operand is required")
        return NodeType("boolean")


def _canonical_hash(spec: ObjectiveSpec, registry_version: str) -> str:
    payload = spec.model_dump(mode="json")
    payload["metric_registry_version"] = registry_version
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_objective(spec: ObjectiveSpec, registry: MetricRegistry) -> ObjectiveValidation:
    compiler = _Compiler(registry)
    result = compiler.compile_node(spec.expression, "expression", 1)
    if result.kind != "number":
        compiler.error("expression", "objective root must produce a number")
    for index, constraint in enumerate(spec.constraints):
        constraint_type = compiler.compile_node(constraint, f"constraints[{index}]", 1)
        if constraint_type.kind != "boolean":
            compiler.error(f"constraints[{index}]", "hard constraint must produce a boolean")
    return ObjectiveValidation(
        valid=not compiler.errors,
        objective_id=spec.objective_id,
        version=spec.version,
        objective_hash=_canonical_hash(spec, registry.version_id),
        registry_version=registry.version_id,
        result_dimension=_dimension_name(result.dimension),
        errors=compiler.errors,
        warnings=compiler.warnings,
        metric_ids=compiler.metric_ids,
        node_count=compiler.node_count,
        max_depth=compiler.max_depth,
    )


def compile_objective(spec: ObjectiveSpec, registry: MetricRegistry) -> CompiledObjective:
    validation = validate_objective(spec, registry)
    if not validation.valid:
        raise ObjectiveCompileError(validation)
    normalized = spec.model_copy(update={"metric_registry_version": registry.version_id})
    return CompiledObjective(
        spec=normalized,
        objective_hash=validation.objective_hash,
        validation=validation,
        registry=registry,
    )
