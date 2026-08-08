"""Allowlisted query plans for Knowledge Graph retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


ALLOWED_QUERY_KINDS = frozenset(
    {
        "run_context",
        "similar_experiments",
        "failure_path",
        "success_path",
        "specimen_lineage",
        "device_history",
        "policy_history",
        "bo_context",
        "safety_context",
        "project_context",
        "impact_analysis",
        "provenance_trace",
    }
)
_ALLOWED_FILTERS = frozenset(
    {
        "run_id",
        "cycle_id",
        "experiment_id",
        "entity_id",
        "specimen_id",
        "device_id",
        "policy_id",
        "objective_id",
        "agent_id",
        "module_id",
        "stage",
        "status",
        "q",
    }
)


@dataclass(frozen=True)
class GraphQueryPlan:
    kind: str
    filters: Mapping[str, str]
    depth: int = 2
    limit: int = 50

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "filters": dict(self.filters), "depth": self.depth, "limit": self.limit}


def validate_query_plan(payload: dict[str, Any]) -> GraphQueryPlan:
    if not isinstance(payload, dict):
        raise TypeError("graph query plan must be an object")
    if "cypher" in payload or str(payload.get("kind") or "").lower() in {"raw", "cypher"}:
        raise ValueError("raw Cypher is forbidden")
    kind = str(payload.get("kind") or "")
    if kind not in ALLOWED_QUERY_KINDS:
        raise ValueError(f"unsupported graph query kind: {kind}")
    try:
        depth = int(payload.get("depth", 2))
        limit = int(payload.get("limit", 50))
    except (TypeError, ValueError) as exc:
        raise ValueError("graph query depth and limit must be integers") from exc
    if depth < 1 or depth > 4:
        raise ValueError("graph query depth must be between 1 and 4")
    if limit < 1 or limit > 100:
        raise ValueError("graph query limit must be between 1 and 100")
    raw_filters = payload.get("filters") or {}
    if not isinstance(raw_filters, dict):
        raise ValueError("graph query filters must be an object")
    unknown = sorted(set(str(key) for key in raw_filters) - _ALLOWED_FILTERS)
    if unknown:
        raise ValueError(f"unsupported graph query filter: {', '.join(unknown)}")
    filters: dict[str, str] = {}
    for key, value in raw_filters.items():
        if isinstance(value, (str, int, float, bool)):
            filters[str(key)] = str(value)[:500]
        elif value is not None:
            raise ValueError(f"graph query filter {key} must be scalar")
    return GraphQueryPlan(kind=kind, filters=MappingProxyType(filters), depth=depth, limit=limit)
