"""Optional graph backend for Knowledge memory.

The graph backend is a mirror/index. JSONL Knowledge memory remains the source of
truth. Neo4j is optional and imported lazily so normal ATR startup does not need
Neo4j installed or running.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


GRAPH_SCHEMA_VERSION = "atr_knowledge_graph_v1"


class KnowledgeGraphBackend(Protocol):
    """Minimal graph backend contract used by Knowledge Agent and APIs."""

    def health(self) -> dict[str, Any]: ...
    def upsert_nodes(self, nodes: list[dict[str, Any]]) -> dict[str, Any]: ...
    def upsert_edges(self, edges: list[dict[str, Any]]) -> dict[str, Any]: ...
    def query(self, query: dict[str, Any]) -> dict[str, Any]: ...
    def close(self) -> None: ...


class NullGraphBackend:
    """Disabled graph backend that preserves fail-open runtime behavior."""

    def __init__(self, *, enabled: bool = False, status: str = "disabled", error: str = "") -> None:
        self.enabled = enabled
        self.status = status
        self.error = error

    def health(self) -> dict[str, Any]:
        return {"ok": not self.enabled, "enabled": self.enabled, "backend": "disabled", "status": self.status, "error": self.error}

    def upsert_nodes(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        return {"ok": not self.enabled, "enabled": self.enabled, "backend": "disabled", "nodes_written": 0, "skipped": len(nodes), "error": self.error}

    def upsert_edges(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        return {"ok": not self.enabled, "enabled": self.enabled, "backend": "disabled", "edges_written": 0, "skipped": len(edges), "error": self.error}

    def query(self, query: dict[str, Any]) -> dict[str, Any]:
        return {"ok": not self.enabled, "enabled": self.enabled, "backend": "disabled", "query": query, "nodes": [], "edges": [], "error": self.error}

    def close(self) -> None:
        return None


class JsonGraphBackend:
    """Inspectable local graph JSON fallback backend."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def health(self) -> dict[str, Any]:
        graph = self._read_graph()
        return {
            "ok": True,
            "enabled": True,
            "backend": "json",
            "path": self.path.as_posix(),
            "node_count": len(graph.get("nodes", [])),
            "edge_count": len(graph.get("edges", [])),
            "updated_at": graph.get("updated_at", ""),
        }

    def upsert_nodes(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        graph = self._read_graph()
        existing = {str(item.get("id")): item for item in graph.get("nodes", []) if item.get("id")}
        written = 0
        for node in nodes:
            normalized = normalize_node(node)
            if not normalized:
                continue
            node_id = normalized["id"]
            previous = existing.get(node_id, {})
            existing[node_id] = _deep_merge(previous, normalized)
            written += 1
        graph["nodes"] = sorted(existing.values(), key=lambda item: str(item.get("id", "")))
        graph["updated_at"] = _now()
        self._write_graph(graph)
        return {"ok": True, "backend": "json", "nodes_written": written, "node_count": len(graph["nodes"])}

    def upsert_edges(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        graph = self._read_graph()
        existing = {str(item.get("id")): item for item in graph.get("edges", []) if item.get("id")}
        written = 0
        for edge in edges:
            normalized = normalize_edge(edge)
            if not normalized:
                continue
            edge_id = normalized["id"]
            previous = existing.get(edge_id, {})
            existing[edge_id] = _deep_merge(previous, normalized)
            written += 1
        graph["edges"] = sorted(existing.values(), key=lambda item: str(item.get("id", "")))
        graph["updated_at"] = _now()
        self._write_graph(graph)
        return {"ok": True, "backend": "json", "edges_written": written, "edge_count": len(graph["edges"])}

    def query(self, query: dict[str, Any]) -> dict[str, Any]:
        graph = self._read_graph()
        kind = str(query.get("kind") or "summary")
        limit = max(1, min(int(query.get("limit") or 50), 500))
        include_properties = bool(query.get("include_properties", False))
        nodes = list(graph.get("nodes", []))
        edges = list(graph.get("edges", []))
        if kind == "neighbors":
            node_id = str(query.get("node_id") or "")
            related_edges = [edge for edge in edges if edge.get("source") == node_id or edge.get("target") == node_id][:limit]
            related_ids = {node_id}
            for edge in related_edges:
                related_ids.add(str(edge.get("source")))
                related_ids.add(str(edge.get("target")))
            related_nodes = [node for node in nodes if node.get("id") in related_ids][:limit]
            return {"ok": True, "backend": "json", "kind": kind, "nodes": _compact_nodes(related_nodes, include_properties=include_properties), "edges": _compact_edges(related_edges, include_properties=include_properties)}
        if kind == "target_context":
            target_id = str(query.get("target_id") or "")
            target_type = str(query.get("target_type") or "")
            matched_nodes = [node for node in nodes if _node_matches_target(node, target_id=target_id, target_type=target_type)][:limit]
            matched_ids = {str(node.get("id")) for node in matched_nodes}
            matched_edges = [edge for edge in edges if edge.get("source") in matched_ids or edge.get("target") in matched_ids][:limit]
            for edge in matched_edges:
                matched_ids.add(str(edge.get("source")))
                matched_ids.add(str(edge.get("target")))
            matched_nodes = [node for node in nodes if node.get("id") in matched_ids][:limit]
            return {"ok": True, "backend": "json", "kind": kind, "nodes": _compact_nodes(matched_nodes, include_properties=include_properties), "edges": _compact_edges(matched_edges, include_properties=include_properties)}
        if kind == "project_context":
            target_id = str(query.get("target_id") or query.get("q") or "")
            project_nodes = [node for node in nodes if _is_project_graph_node(node)]
            project_edges = [edge for edge in edges if _is_project_graph_edge(edge)]
            if target_id:
                matched_nodes = [node for node in project_nodes if _node_contains(node, target_id)][:limit]
            else:
                matched_nodes = project_nodes[:limit]
            matched_ids = {str(node.get("id")) for node in matched_nodes}
            matched_edges = [edge for edge in project_edges if edge.get("source") in matched_ids or edge.get("target") in matched_ids][:limit]
            for edge in matched_edges:
                matched_ids.add(str(edge.get("source")))
                matched_ids.add(str(edge.get("target")))
            matched_nodes = [node for node in project_nodes if node.get("id") in matched_ids][:limit]
            return {"ok": True, "backend": "json", "kind": kind, "nodes": _compact_nodes(matched_nodes, include_properties=include_properties), "edges": _compact_edges(matched_edges, include_properties=include_properties)}
        if kind == "text":
            term = str(query.get("q") or "").lower()
            matched_nodes = [node for node in nodes if term and term in json.dumps(node, ensure_ascii=False, default=str).lower()][:limit]
            matched_ids = {str(node.get("id")) for node in matched_nodes}
            matched_edges = [edge for edge in edges if edge.get("source") in matched_ids or edge.get("target") in matched_ids][:limit]
            return {"ok": True, "backend": "json", "kind": kind, "nodes": _compact_nodes(matched_nodes, include_properties=include_properties), "edges": _compact_edges(matched_edges, include_properties=include_properties)}
        return {"ok": True, "backend": "json", "kind": kind, "nodes": _compact_nodes(nodes[:limit], include_properties=include_properties), "edges": _compact_edges(edges[:limit], include_properties=include_properties)}

    def close(self) -> None:
        return None

    def _read_graph(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": GRAPH_SCHEMA_VERSION, "created_at": _now(), "updated_at": "", "nodes": [], "edges": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"schema_version": GRAPH_SCHEMA_VERSION, "created_at": _now(), "updated_at": "", "nodes": [], "edges": []}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("schema_version", GRAPH_SCHEMA_VERSION)
        payload.setdefault("created_at", _now())
        payload.setdefault("updated_at", "")
        payload.setdefault("nodes", [])
        payload.setdefault("edges", [])
        return payload

    def _write_graph(self, graph: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(graph, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


class Neo4jGraphBackend:
    """Optional Neo4j graph backend using a generic node/relationship model."""

    def __init__(self, *, uri: str, username: str, password: str, database: str | None = None) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except Exception as exc:  # pragma: no cover - exercised when neo4j is absent
            raise RuntimeError("neo4j package is not installed; install optional dependency 'neo4j'") from exc
        self.uri = uri
        self.username = username
        self.database = database or None
        self._driver = GraphDatabase.driver(uri, auth=(username, password))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        try:
            with self._driver.session(database=self.database) as session:
                session.run(
                    "CREATE CONSTRAINT atr_knowledge_node_id IF NOT EXISTS "
                    "FOR (n:ATRKnowledgeNode) REQUIRE n.id IS UNIQUE"
                ).consume()
                session.run(
                    "CREATE CONSTRAINT atr_knowledge_rel_id IF NOT EXISTS "
                    "FOR ()-[r:ATR_KNOWLEDGE_REL]-() REQUIRE r.id IS UNIQUE"
                ).consume()
        except Exception:
            # Health/upsert will surface the actual connectivity/schema issue.
            return

    def health(self) -> dict[str, Any]:
        try:
            self._driver.verify_connectivity()
            with self._driver.session(database=self.database) as session:
                counts = session.run(
                    "MATCH (n:ATRKnowledgeNode) WITH count(n) AS nodes "
                    "MATCH ()-[r:ATR_KNOWLEDGE_REL]->() RETURN nodes, count(r) AS edges"
                ).single()
            return {
                "ok": True,
                "enabled": True,
                "backend": "neo4j",
                "uri": self.uri,
                "database": self.database or "default",
                "node_count": int(counts["nodes"] if counts else 0),
                "edge_count": int(counts["edges"] if counts else 0),
            }
        except Exception as exc:
            return {"ok": False, "enabled": True, "backend": "neo4j", "uri": self.uri, "error": str(exc)}

    def upsert_nodes(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        normalized = [node for node in (normalize_node(item) for item in nodes) if node]
        if not normalized:
            return {"ok": True, "backend": "neo4j", "nodes_written": 0}
        with self._driver.session(database=self.database) as session:
            session.run(
                "UNWIND $nodes AS node "
                "MERGE (n:ATRKnowledgeNode {id: node.id}) "
                "SET n += node.props, n.kind = node.kind, n.label = node.label, n.updated_at = $updated_at",
                nodes=[_neo4j_node_payload(node) for node in normalized],
                updated_at=_now(),
            )
        return {"ok": True, "backend": "neo4j", "nodes_written": len(normalized)}

    def upsert_edges(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        normalized = [edge for edge in (normalize_edge(item) for item in edges) if edge]
        if not normalized:
            return {"ok": True, "backend": "neo4j", "edges_written": 0}
        with self._driver.session(database=self.database) as session:
            session.run(
                "UNWIND $edges AS edge "
                "MERGE (s:ATRKnowledgeNode {id: edge.source}) "
                "MERGE (t:ATRKnowledgeNode {id: edge.target}) "
                "MERGE (s)-[r:ATR_KNOWLEDGE_REL {id: edge.id}]->(t) "
                "SET r += edge.props, r.type = edge.type, r.updated_at = $updated_at",
                edges=[_neo4j_edge_payload(edge) for edge in normalized],
                updated_at=_now(),
            )
        return {"ok": True, "backend": "neo4j", "edges_written": len(normalized)}

    def query(self, query: dict[str, Any]) -> dict[str, Any]:
        kind = str(query.get("kind") or "summary")
        limit = max(1, min(int(query.get("limit") or 50), 500))
        include_properties = bool(query.get("include_properties", False))
        with self._driver.session(database=self.database) as session:
            if kind == "neighbors":
                node_id = str(query.get("node_id") or "")
                records = session.run(
                    "MATCH (n:ATRKnowledgeNode {id: $node_id}) "
                    "OPTIONAL MATCH (n)-[r:ATR_KNOWLEDGE_REL]-(m:ATRKnowledgeNode) "
                    "RETURN collect(DISTINCT n)[0] AS root, collect(DISTINCT m)[0..$limit] AS nodes, collect(DISTINCT r)[0..$limit] AS edges",
                    node_id=node_id,
                    limit=limit,
                ).single()
                return _neo4j_records_to_result(records, kind=kind, include_properties=include_properties)
            if kind == "target_context":
                target_id = str(query.get("target_id") or "")
                target_type = str(query.get("target_type") or "")
                records = session.run(
                    "MATCH (n:ATRKnowledgeNode) "
                    "WHERE ($target_id = '' OR n.target_id = $target_id OR n.agent_id = $target_id OR n.id CONTAINS $target_id) "
                    "AND ($target_type = '' OR n.target_type = $target_type OR n.kind = $target_type) "
                    "OPTIONAL MATCH (n)-[r:ATR_KNOWLEDGE_REL]-(m:ATRKnowledgeNode) "
                    "RETURN collect(DISTINCT n)[0..$limit] AS roots, collect(DISTINCT m)[0..$limit] AS nodes, collect(DISTINCT r)[0..$limit] AS edges",
                    target_id=target_id,
                    target_type=target_type,
                    limit=limit,
                ).single()
                return _neo4j_records_to_result(records, kind=kind, include_properties=include_properties)
            if kind == "project_context":
                target_id = str(query.get("target_id") or query.get("q") or "")
                records = session.run(
                    "MATCH (n:ATRKnowledgeNode) "
                    "WHERE (n.record_type = 'ProjectGraph' OR n.graph_source = 'project_graph' OR n.id STARTS WITH 'file:' OR n.id STARTS WITH 'module:' OR n.id STARTS WITH 'api:' OR n.id STARTS WITH 'tool:' OR n.id STARTS WITH 'concept:') "
                    "AND ($target_id = '' OR n.id CONTAINS $target_id OR n.label CONTAINS $target_id OR n.agent_id = $target_id OR n.target_id = $target_id) "
                    "OPTIONAL MATCH (n)-[r:ATR_KNOWLEDGE_REL]-(m:ATRKnowledgeNode) "
                    "WHERE (r.graph_source = 'project_graph' OR m.record_type = 'ProjectGraph' OR m.graph_source = 'project_graph' OR m.id STARTS WITH 'file:' OR m.id STARTS WITH 'module:' OR m.id STARTS WITH 'api:' OR m.id STARTS WITH 'tool:' OR m.id STARTS WITH 'concept:' OR m.id STARTS WITH 'agent:') "
                    "RETURN collect(DISTINCT n)[0..$limit] AS roots, collect(DISTINCT m)[0..$limit] AS nodes, collect(DISTINCT r)[0..$limit] AS edges",
                    target_id=target_id,
                    limit=limit,
                ).single()
                return _neo4j_records_to_result(records, kind=kind, include_properties=include_properties)
            records = session.run(
                "MATCH (n:ATRKnowledgeNode) OPTIONAL MATCH ()-[r:ATR_KNOWLEDGE_REL]->() "
                "RETURN collect(DISTINCT n)[0..$limit] AS nodes, collect(DISTINCT r)[0..$limit] AS edges",
                limit=limit,
            ).single()
        return _neo4j_records_to_result(records, kind=kind, include_properties=include_properties)

    def close(self) -> None:
        self._driver.close()


def graph_backend_from_env(project_root: Path) -> KnowledgeGraphBackend:
    """Build graph backend from environment with fail-open defaults."""
    enabled = _env_bool("ATR_KNOWLEDGE_GRAPH_ENABLED", default=False)
    if not enabled:
        return NullGraphBackend()
    backend_type = os.environ.get("ATR_KNOWLEDGE_GRAPH_BACKEND", "json").strip().lower() or "json"
    if backend_type == "neo4j":
        uri = os.environ.get("ATR_NEO4J_URI", "bolt://127.0.0.1:7687")
        username = os.environ.get("ATR_NEO4J_USERNAME", "neo4j")
        password = os.environ.get("ATR_NEO4J_PASSWORD", "")
        database = os.environ.get("ATR_NEO4J_DATABASE", "") or None
        if not password:
            if _env_bool("ATR_KNOWLEDGE_GRAPH_FAIL_OPEN", default=True):
                return NullGraphBackend(enabled=True, status="degraded", error="ATR_NEO4J_PASSWORD is not configured")
            raise RuntimeError("ATR_NEO4J_PASSWORD is required for Neo4j backend")
        try:
            return Neo4jGraphBackend(uri=uri, username=username, password=password, database=database)
        except Exception:
            if _env_bool("ATR_KNOWLEDGE_GRAPH_FAIL_OPEN", default=True):
                return NullGraphBackend(enabled=True, status="degraded", error="Neo4j backend initialization failed")
            raise
    return JsonGraphBackend(project_root / "memory" / "knowledge" / "graph_backend" / "knowledge_graph.json")


def normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    node_id = _safe_id(node.get("id") or node.get("record_id") or node.get("path") or "")
    if not node_id:
        return {}
    kind = _safe_label(node.get("kind") or node.get("label") or "KnowledgeNode")
    label = str(node.get("label") or node_id)
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    normalized = {"id": node_id, "kind": kind, "label": label, "properties": _jsonable(props)}
    for key in ("run_id", "agent_id", "stage", "target_type", "target_id", "record_type", "created_at"):
        if node.get(key) not in (None, ""):
            normalized[key] = str(node.get(key))
    return normalized


def normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    source = _safe_id(edge.get("source") or "")
    target = _safe_id(edge.get("target") or "")
    edge_type = _safe_label(edge.get("type") or "RELATED_TO")
    if not source or not target:
        return {}
    edge_id = _safe_id(edge.get("id") or f"{source}__{edge_type}__{target}")
    props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
    normalized = {"id": edge_id, "source": source, "target": target, "type": edge_type, "properties": _jsonable(props)}
    for key in ("run_id", "created_at"):
        if edge.get(key) not in (None, ""):
            normalized[key] = str(edge.get(key))
    return normalized


def _node_matches_target(node: dict[str, Any], *, target_id: str, target_type: str) -> bool:
    if not target_id and not target_type:
        return True
    if target_id and target_id in {str(node.get("target_id", "")), str(node.get("agent_id", "")), str(node.get("id", ""))}:
        return True
    if target_id and target_id in json.dumps(node, ensure_ascii=False, default=str):
        return True
    if target_type and target_type == str(node.get("target_type", "")):
        return True
    return False


def _is_project_graph_node(node: dict[str, Any]) -> bool:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    node_id = str(node.get("id") or "")
    return (
        node.get("record_type") == "ProjectGraph"
        or props.get("graph_source") == "project_graph"
        or node_id.startswith(("file:", "module:", "api:", "tool:", "concept:", "project:"))
    )


def _is_project_graph_edge(edge: dict[str, Any]) -> bool:
    props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
    return props.get("graph_source") == "project_graph" or str(edge.get("source") or "").startswith(("file:", "module:", "api:", "tool:", "concept:", "project:"))


def _node_contains(node: dict[str, Any], term: str) -> bool:
    needle = term.lower()
    return needle in json.dumps(node, ensure_ascii=False, default=str).lower()


def _neo4j_node_payload(node: dict[str, Any]) -> dict[str, Any]:
    props = dict(node.get("properties") or {})
    for key, value in node.items():
        if key not in {"properties"}:
            props[key] = value
    return {"id": node["id"], "kind": node.get("kind", "KnowledgeNode"), "label": node.get("label", node["id"]), "props": _flatten_props(props)}


def _neo4j_edge_payload(edge: dict[str, Any]) -> dict[str, Any]:
    props = dict(edge.get("properties") or {})
    for key, value in edge.items():
        if key not in {"properties"}:
            props[key] = value
    return {"id": edge["id"], "source": edge["source"], "target": edge["target"], "type": edge.get("type", "RELATED_TO"), "props": _flatten_props(props)}


def _neo4j_records_to_result(records: Any, *, kind: str, include_properties: bool = False) -> dict[str, Any]:
    if not records:
        return {"ok": True, "backend": "neo4j", "kind": kind, "nodes": [], "edges": []}
    raw_nodes: list[Any] = []
    raw_edges: list[Any] = []
    for key in ("root", "roots", "nodes"):
        value = records.get(key) if hasattr(records, "get") else None
        if isinstance(value, list):
            raw_nodes.extend(value)
        elif value is not None:
            raw_nodes.append(value)
    value = records.get("edges") if hasattr(records, "get") else None
    if isinstance(value, list):
        raw_edges.extend(value)
    nodes = _dedupe_by_id([_neo4j_entity_to_dict(item, include_properties=include_properties) for item in raw_nodes if item])
    edges = _dedupe_by_id([_neo4j_entity_to_dict(item, include_properties=include_properties) for item in raw_edges if item])
    return {"ok": True, "backend": "neo4j", "kind": kind, "nodes": nodes, "edges": edges}


def _neo4j_entity_to_dict(entity: Any, *, include_properties: bool = False) -> dict[str, Any]:
    try:
        payload = dict(entity)
    except Exception:
        return {"repr": repr(entity)}
    if include_properties:
        return _truncate_large_values(payload)
    # Neo4j returns both node and relationship properties as flat dictionaries.
    if "source" in payload and "target" in payload:
        return _compact_edge(payload, include_properties=False)
    return _compact_node(payload, include_properties=False)


def _dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "")
        if item_id:
            deduped[item_id] = item
        else:
            anonymous.append(item)
    return list(deduped.values()) + anonymous


def _flatten_props(props: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in props.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            flattened[str(key)] = value
        else:
            flattened[str(key)] = json.dumps(value, ensure_ascii=False, default=str)
    return flattened


def _deep_merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except Exception:
        return str(value)


def _safe_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return "".join(ch if ch.isalnum() or ch in {"-", "_", ".", ":", "/"} else "_" for ch in text)[:512]


def _safe_label(value: Any) -> str:
    text = str(value or "KnowledgeNode").strip()
    clean = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text)
    if not clean or clean[0].isdigit():
        clean = f"K_{clean}"
    return clean[:80]


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_nodes(nodes: list[dict[str, Any]], *, include_properties: bool) -> list[dict[str, Any]]:
    return [_compact_node(node, include_properties=include_properties) for node in nodes]


def _compact_edges(edges: list[dict[str, Any]], *, include_properties: bool) -> list[dict[str, Any]]:
    return [_compact_edge(edge, include_properties=include_properties) for edge in edges]


def _compact_node(node: dict[str, Any], *, include_properties: bool) -> dict[str, Any]:
    if include_properties:
        return _truncate_large_values(node)
    compact = {key: node.get(key) for key in ("id", "kind", "label", "run_id", "agent_id", "stage", "target_type", "target_id", "record_type", "created_at", "updated_at") if node.get(key) not in (None, "")}
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    for key in ("schema_version", "status", "score", "priority", "objective", "failure_type", "verdict", "rollback_recommended"):
        if key in props and key not in compact:
            compact[key] = props[key]
    return compact


def _compact_edge(edge: dict[str, Any], *, include_properties: bool) -> dict[str, Any]:
    if include_properties:
        return _truncate_large_values(edge)
    return {key: edge.get(key) for key in ("id", "source", "target", "type", "run_id", "created_at", "updated_at") if edge.get(key) not in (None, "")}


def _truncate_large_values(payload: dict[str, Any], *, limit: int = 1200) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > limit:
            out[key] = value[:limit] + "...<truncated>"
        elif isinstance(value, dict):
            out[key] = _truncate_large_values(value, limit=limit)
        else:
            out[key] = value
    return out
