"""Normalized mixed parameter spaces and deterministic initial BO designs."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from numbers import Real
from typing import Any, Iterable, Mapping, Sequence

from scipy.stats import qmc


def _is_numeric(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _canonical(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


@dataclass(frozen=True)
class ParameterDimension:
    """One declared BO dimension."""

    name: str
    kind: str
    values: tuple[Any, ...]

    @property
    def active(self) -> bool:
        return self.kind != "fixed"

    def encode(self, value: Any) -> float:
        if self.kind == "fixed":
            if value != self.values[0]:
                raise ValueError(f"{self.name} must remain fixed at {self.values[0]!r}")
            raise ValueError(f"fixed parameter {self.name} is not encoded")
        if self.kind == "continuous":
            low, high = (float(item) for item in self.values)
            number = float(value)
            if not low <= number <= high:
                raise ValueError(f"{self.name}={number} is outside continuous bounds [{low}, {high}]")
            return (number - low) / (high - low)
        try:
            index = self.values.index(value)
        except ValueError as exc:
            raise ValueError(f"{self.name}={value!r} is not in choices {list(self.values)!r}") from exc
        return float(index) / float(max(1, len(self.values) - 1))

    def decode(self, unit_value: float) -> Any:
        unit = min(1.0, max(0.0, float(unit_value)))
        if self.kind == "fixed":
            return self.values[0]
        if self.kind == "continuous":
            low, high = (float(item) for item in self.values)
            return low + unit * (high - low)
        index = int(math.floor(unit * len(self.values)))
        return self.values[min(index, len(self.values) - 1)]


@dataclass(frozen=True)
class BOParameterSpace:
    """Stable normalized representation of a mixed BO parameter mapping."""

    dimensions: tuple[ParameterDimension, ...]

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "BOParameterSpace":
        if not mapping:
            raise ValueError("parameter space must not be empty")
        dimensions: list[ParameterDimension] = []
        for raw_name, raw_domain in mapping.items():
            name = str(raw_name).strip()
            if not name:
                raise ValueError("parameter names must not be empty")
            if isinstance(raw_domain, Sequence) and not isinstance(raw_domain, (str, bytes, bytearray)):
                values = tuple(raw_domain)
            else:
                values = (raw_domain,)
            if not values:
                raise ValueError(f"parameter {name} must declare at least one value")
            if len(values) == 1 or (len(values) == 2 and values[0] == values[1]):
                dimensions.append(ParameterDimension(name=name, kind="fixed", values=(values[0],)))
                continue
            if len(values) == 2 and all(_is_numeric(item) for item in values):
                low, high = (float(item) for item in values)
                if not math.isfinite(low) or not math.isfinite(high) or low >= high:
                    raise ValueError(f"{name} continuous bounds must be finite and ascending")
                dimensions.append(ParameterDimension(name=name, kind="continuous", values=(low, high)))
                continue
            unique: list[Any] = []
            for item in values:
                if item not in unique:
                    unique.append(item)
            dimensions.append(ParameterDimension(name=name, kind="discrete", values=tuple(unique)))
        return cls(dimensions=tuple(dimensions))

    @property
    def active_dimensions(self) -> tuple[ParameterDimension, ...]:
        return tuple(item for item in self.dimensions if item.active)

    @property
    def active_dimension_count(self) -> int:
        return len(self.active_dimensions)

    @property
    def continuous_dimension_count(self) -> int:
        return sum(item.kind == "continuous" for item in self.active_dimensions)

    @property
    def initial_design_size(self) -> int:
        return max(2 * self.continuous_dimension_count, 8)

    @property
    def fixed_parameters(self) -> dict[str, Any]:
        return {item.name: item.values[0] for item in self.dimensions if item.kind == "fixed"}

    @property
    def schema_hash(self) -> str:
        payload = [
            {"name": item.name, "kind": item.kind, "values": _canonical(item.values)}
            for item in self.dimensions
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def encode(self, parameters: Mapping[str, Any]) -> list[float]:
        for name, expected in self.fixed_parameters.items():
            if name in parameters and parameters[name] != expected:
                raise ValueError(f"{name} must remain fixed at {expected!r}")
        vector: list[float] = []
        for dimension in self.active_dimensions:
            if dimension.name not in parameters:
                raise ValueError(f"missing parameter {dimension.name}")
            vector.append(dimension.encode(parameters[dimension.name]))
        return vector

    def decode(self, vector: Sequence[float], fixed_features: Mapping[int, float] | None = None) -> dict[str, Any]:
        if len(vector) != self.active_dimension_count:
            raise ValueError(f"expected {self.active_dimension_count} encoded values, received {len(vector)}")
        fixed_features = fixed_features or {}
        output = dict(self.fixed_parameters)
        for index, dimension in enumerate(self.active_dimensions):
            output[dimension.name] = dimension.decode(fixed_features.get(index, vector[index]))
        return {item.name: output[item.name] for item in self.dimensions}

    def signature(self, parameters: Mapping[str, Any]) -> str:
        normalized = self.decode(self.encode(parameters))
        payload = json.dumps(_canonical(normalized), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def mixed_fixed_features(self, *, max_combinations: int = 256) -> list[dict[int, float]]:
        discrete = [
            (index, dimension)
            for index, dimension in enumerate(self.active_dimensions)
            if dimension.kind == "discrete"
        ]
        if not discrete:
            return []
        count = math.prod(len(dimension.values) for _, dimension in discrete)
        if count > max_combinations:
            raise ValueError(f"mixed parameter space has {count} discrete combinations; maximum is {max_combinations}")
        combinations: list[dict[int, float]] = []
        value_sets = [range(len(dimension.values)) for _, dimension in discrete]
        for selected in itertools.product(*value_sets):
            combinations.append(
                {
                    index: float(choice) / float(max(1, len(dimension.values) - 1))
                    for (index, dimension), choice in zip(discrete, selected, strict=True)
                }
            )
        return combinations

    def lhs_points(
        self,
        count: int,
        *,
        seed: int,
        excluded_signatures: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        requested = max(0, int(count))
        if requested == 0:
            return []
        excluded = {str(item) for item in excluded_signatures}
        total = requested + len(excluded)
        for _ in range(6):
            unit_rows = self._lhs_unit_rows(total, seed=seed)
            points = [self.decode(row) for row in unit_rows]
            filtered: list[dict[str, Any]] = []
            seen = set(excluded)
            for point in points:
                signature = self.signature(point)
                if signature in seen:
                    continue
                seen.add(signature)
                filtered.append(point)
                if len(filtered) == requested:
                    return filtered
            total *= 2
        raise ValueError("unable to produce enough unique LHS points for the declared parameter space")

    def _lhs_unit_rows(self, count: int, *, seed: int) -> list[list[float]]:
        active = self.active_dimensions
        continuous_indexes = [index for index, item in enumerate(active) if item.kind == "continuous"]
        if continuous_indexes:
            continuous_rows = qmc.LatinHypercube(d=len(continuous_indexes), seed=seed).random(n=count)
        else:
            continuous_rows = [[0.5] * 0 for _ in range(count)]

        rows = [[0.5 for _ in active] for _ in range(count)]
        for row_index, values in enumerate(continuous_rows):
            for column_index, active_index in enumerate(continuous_indexes):
                rows[row_index][active_index] = float(values[column_index])

        for active_index, dimension in enumerate(active):
            if dimension.kind != "discrete":
                continue
            offset = (int(seed) + active_index * 17) % len(dimension.values)
            for row_index in range(count):
                choice = (offset + row_index) % len(dimension.values)
                rows[row_index][active_index] = float(choice) / float(max(1, len(dimension.values) - 1))
        return rows

