"""Map bounded graph plans to existing graph backend operations."""

from __future__ import annotations

from typing import Any

from knowledge.graph_backend import KnowledgeGraphBackend
from knowledge.graph_query_planner import GraphQueryPlan


class GraphRetrievalService:
    def __init__(self, backend: KnowledgeGraphBackend) -> None:
        self.backend = backend

    def query(self, plan: GraphQueryPlan) -> dict[str, Any]:
        query = _backend_query(plan)
        result = self.backend.query(query)
        return {**result, "query_plan": plan.as_dict()}


def _backend_query(plan: GraphQueryPlan) -> dict[str, Any]:
    filters = dict(plan.filters)
    common = {"limit": plan.limit, "include_properties": True}
    if plan.kind == "run_context":
        return {"kind": "target_context", "target_type": "Run", "target_id": filters.get("run_id", ""), **common}
    if plan.kind == "similar_experiments":
        return {"kind": "text", "q": filters.get("q") or filters.get("experiment_id", ""), **common}
    if plan.kind == "failure_path":
        return {"kind": "target_context", "target_type": "Failure", "target_id": filters.get("entity_id") or filters.get("agent_id", ""), **common}
    if plan.kind == "success_path":
        return {"kind": "target_context", "target_type": "SuccessPattern", "target_id": filters.get("agent_id", ""), **common}
    if plan.kind == "specimen_lineage":
        return {"kind": "target_context", "target_type": "Specimen", "target_id": filters.get("specimen_id") or filters.get("entity_id", ""), **common}
    if plan.kind == "device_history":
        return {"kind": "target_context", "target_type": "Device", "target_id": filters.get("device_id", ""), **common}
    if plan.kind == "policy_history":
        return {"kind": "target_context", "target_type": "Policy", "target_id": filters.get("policy_id", ""), **common}
    if plan.kind == "bo_context":
        return {"kind": "target_context", "target_type": "BOIteration", "target_id": filters.get("objective_id", ""), **common}
    if plan.kind == "safety_context":
        return {"kind": "target_context", "target_type": "GuardianGate", "target_id": filters.get("stage") or filters.get("run_id", ""), **common}
    if plan.kind == "project_context":
        return {"kind": "project_context", "target_id": filters.get("module_id") or filters.get("agent_id") or filters.get("q", ""), **common}
    if plan.kind == "impact_analysis":
        return {"kind": "project_context", "target_id": filters.get("module_id") or filters.get("entity_id", ""), **common}
    return {"kind": "neighbors", "node_id": filters.get("entity_id", ""), **common}
