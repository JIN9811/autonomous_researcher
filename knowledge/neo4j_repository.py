"""Event-oriented repository over the existing ATR Neo4j graph backend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from knowledge.graph_backend import KnowledgeGraphBackend


@dataclass(frozen=True)
class GraphSyncReceipt:
    event_id: str
    backend: str
    nodes_written: int
    edges_written: int
    synchronized_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "knowledge_graph_sync_receipt.v1",
            "event_id": self.event_id,
            "backend": self.backend,
            "nodes_written": self.nodes_written,
            "edges_written": self.edges_written,
            "synchronized_at": self.synchronized_at,
        }


class Neo4jRepository:
    """Translate validated Knowledge events into idempotent graph upserts."""

    def __init__(self, backend: KnowledgeGraphBackend) -> None:
        self.backend = backend

    def health(self) -> dict[str, Any]:
        return self.backend.health()

    def apply_event(self, event: dict[str, Any]) -> GraphSyncReceipt:
        health = self.backend.health()
        if not health.get("enabled", True):
            raise ConnectionError("knowledge graph backend is disabled")
        if not health.get("ok", False):
            raise ConnectionError(str(health.get("error") or "neo4j unavailable"))
        nodes, edges = event_to_graph(event)
        node_result = self.backend.upsert_nodes(nodes)
        if not node_result.get("ok", False):
            raise RuntimeError(str(node_result.get("error") or "neo4j node upsert failed"))
        edge_result = self.backend.upsert_edges(edges)
        if not edge_result.get("ok", False):
            raise RuntimeError(str(edge_result.get("error") or "neo4j edge upsert failed"))
        return GraphSyncReceipt(
            event_id=str(event["event_id"]),
            backend=str(node_result.get("backend") or edge_result.get("backend") or health.get("backend") or "neo4j"),
            nodes_written=int(node_result.get("nodes_written") or 0),
            edges_written=int(edge_result.get("edges_written") or 0),
            synchronized_at=datetime.now(timezone.utc).isoformat(),
        )

    def close(self) -> None:
        self.backend.close()


def event_to_graph(event: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    event_id = str(event["event_id"])
    run_id = str(event.get("run_id") or "")
    cycle_id = str(event.get("cycle_id") or "")
    source_agent = str(event.get("source_agent") or "")
    common = {
        "run_id": run_id,
        "cycle_id": cycle_id,
        "ontology_version": str(event.get("ontology_version") or ""),
        "occurred_at": str(event.get("occurred_at") or ""),
    }
    nodes: dict[str, dict[str, Any]] = {
        event_id: {
            "id": event_id,
            "kind": "Event",
            "label": str(event.get("event_type") or event_id),
            "event_id": event_id,
            "event_type": str(event.get("event_type") or ""),
            "idempotency_key": str(event.get("idempotency_key") or ""),
            **common,
            "properties": {
                "payload_summary": dict(event.get("payload_summary") or {}),
                "provenance": dict(event.get("provenance") or {}),
            },
        }
    }
    edges: dict[str, dict[str, Any]] = {}
    if run_id:
        run_node = f"runtime:run:{run_id}"
        nodes.setdefault(run_node, {"id": run_node, "kind": "Run", "label": run_id, "run_id": run_id, "properties": {"run_id": run_id}})
        _add_edge(edges, event_id, run_node, "OBSERVED_IN", common)
    if cycle_id:
        cycle_node = cycle_id if cycle_id.startswith("runtime:cycle:") else f"runtime:cycle:{run_id}:{cycle_id}"
        nodes.setdefault(cycle_node, {"id": cycle_node, "kind": "Cycle", "label": cycle_id, **common, "properties": {"cycle_id": cycle_id}})
        _add_edge(edges, event_id, cycle_node, "OCCURRED_DURING", common)
    if source_agent:
        agent_node = source_agent if source_agent.startswith("project:agent:") else f"project:agent:{source_agent.removesuffix('_agent')}"
        nodes.setdefault(agent_node, {"id": agent_node, "kind": "Agent", "label": source_agent, "agent_id": source_agent, "properties": {"agent_id": source_agent}})
        _add_edge(edges, event_id, agent_node, "PRODUCED_BY", common)
    for ref in event.get("entity_refs", []):
        entity_id = str(ref.get("entity_id") or "")
        if not entity_id:
            continue
        entity_class = str(ref.get("entity_class") or "KnowledgeEntity")
        properties = {str(key): value for key, value in ref.items() if key not in {"entity_id", "entity_class"}}
        nodes[entity_id] = {
            "id": entity_id,
            "kind": entity_class,
            "label": str(ref.get("label") or entity_id),
            **common,
            **properties,
            "properties": properties,
        }
        _add_edge(edges, event_id, entity_id, "REFERENCES", common)
    for intent in event.get("relationship_intents", []):
        source_id = str(intent.get("source_id") or "")
        target_id = str(intent.get("target_id") or "")
        relation_type = str(intent.get("relation_type") or "")
        if not source_id or not target_id or not relation_type:
            continue
        nodes.setdefault(source_id, {"id": source_id, "kind": str(intent.get("source_class") or "KnowledgeEntity"), "label": source_id, **common, "properties": {}})
        nodes.setdefault(target_id, {"id": target_id, "kind": str(intent.get("target_class") or "KnowledgeEntity"), "label": target_id, **common, "properties": {}})
        relation_id = str(intent.get("relation_id") or f"{source_id}__{relation_type}__{target_id}")
        edges[relation_id] = {
            "id": relation_id,
            "source": source_id,
            "target": target_id,
            "type": relation_type,
            **common,
            "properties": dict(intent.get("properties") or {}),
        }
    return list(nodes.values()), list(edges.values())


def _add_edge(edges: dict[str, dict[str, Any]], source: str, target: str, relation_type: str, common: dict[str, Any]) -> None:
    relation_id = f"{source}__{relation_type}__{target}"
    edges[relation_id] = {
        "id": relation_id,
        "source": source,
        "target": target,
        "type": relation_type,
        **common,
        "properties": {},
    }
