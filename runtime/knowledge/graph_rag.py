"""Source-separated Graph RAG context assembly."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from knowledge.graph_query_planner import GraphQueryPlan


class GraphRAG:
    @staticmethod
    def build_context(
        *,
        plan: GraphQueryPlan,
        graph_result: dict[str, Any],
        typed_memory: list[dict[str, Any]],
        vector_context: dict[str, Any],
        orchestrator_state: dict[str, Any],
        sync_status: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": "graph_rag_context.v1",
            "query_plan": plan.as_dict(),
            "sources": {
                "graph": {
                    "ok": bool(graph_result.get("ok", False)),
                    "backend": str(graph_result.get("backend") or "unknown"),
                    "nodes": deepcopy(list(graph_result.get("nodes") or [])[: plan.limit]),
                    "edges": deepcopy(list(graph_result.get("edges") or [])[: plan.limit]),
                },
                "typed_memory": deepcopy(typed_memory[: plan.limit]),
                "vector": deepcopy(vector_context),
                "current_state": deepcopy(orchestrator_state),
            },
            "sync_status": deepcopy(sync_status),
        }
