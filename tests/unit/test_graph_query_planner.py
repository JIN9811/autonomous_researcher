from __future__ import annotations

import pytest

from knowledge.graph_query_planner import ALLOWED_QUERY_KINDS, GraphQueryPlan, validate_query_plan


def test_query_plan_accepts_bounded_run_context() -> None:
    plan = validate_query_plan({"kind": "run_context", "filters": {"run_id": "run-1"}, "depth": 2, "limit": 25})

    assert isinstance(plan, GraphQueryPlan)
    assert plan.kind == "run_context"
    assert plan.filters == {"run_id": "run-1"}
    assert plan.depth == 2
    assert plan.limit == 25


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"kind": "raw", "cypher": "MATCH (n) RETURN n"}, "raw Cypher"),
        ({"kind": "drop_database"}, "query kind"),
        ({"kind": "run_context", "depth": 5}, "depth"),
        ({"kind": "run_context", "limit": 101}, "limit"),
        ({"kind": "run_context", "filters": {"password": "x"}}, "filter"),
    ],
)
def test_query_plan_rejects_unbounded_or_unsafe_input(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_query_plan(payload)


def test_query_kind_registry_contains_operational_contexts() -> None:
    assert {
        "run_context",
        "similar_experiments",
        "failure_path",
        "success_path",
        "device_history",
        "policy_history",
        "bo_context",
        "safety_context",
        "project_context",
        "provenance_trace",
    } <= ALLOWED_QUERY_KINDS
