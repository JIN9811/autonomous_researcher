"""Convert typed Knowledge memory into graph backend nodes and edges."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from knowledge.graph_backend import KnowledgeGraphBackend
from knowledge.schemas import AgentPerformanceRecord, EvolutionEvidencePack, EvolutionOutcomeRecord, ExperimentKnowledgeRecord, FailurePatternRecord, SuccessPatternRecord
from knowledge.stores import JsonlKnowledgeStore


Record = ExperimentKnowledgeRecord | AgentPerformanceRecord | FailurePatternRecord | SuccessPatternRecord | EvolutionEvidencePack | EvolutionOutcomeRecord


def mirror_knowledge_records(
    backend: KnowledgeGraphBackend,
    *,
    experiment_record: ExperimentKnowledgeRecord | None = None,
    performance_records: list[AgentPerformanceRecord] | None = None,
    failure_patterns: list[FailurePatternRecord] | None = None,
    success_patterns: list[SuccessPatternRecord] | None = None,
    evidence_packs: list[EvolutionEvidencePack] | None = None,
    evolution_outcomes: list[EvolutionOutcomeRecord] | None = None,
) -> dict[str, Any]:
    """Best-effort mirror of typed Knowledge records into a graph backend."""
    records: list[Record] = []
    if experiment_record is not None:
        records.append(experiment_record)
    records.extend(performance_records or [])
    records.extend(failure_patterns or [])
    records.extend(success_patterns or [])
    records.extend(evidence_packs or [])
    records.extend(evolution_outcomes or [])
    nodes, edges = records_to_graph(records)
    try:
        health = backend.health()
        if not health.get("enabled", True):
            return {"ok": True, "enabled": False, "backend": health.get("backend", "disabled"), "nodes_written": 0, "edges_written": 0}
        node_result = backend.upsert_nodes(nodes)
        edge_result = backend.upsert_edges(edges)
        return {
            "ok": bool(node_result.get("ok", True) and edge_result.get("ok", True)),
            "enabled": True,
            "backend": node_result.get("backend") or edge_result.get("backend") or health.get("backend", "unknown"),
            "nodes_written": int(node_result.get("nodes_written") or 0),
            "edges_written": int(edge_result.get("edges_written") or 0),
            "node_count": node_result.get("node_count"),
            "edge_count": edge_result.get("edge_count"),
            "error": node_result.get("error") or edge_result.get("error") or "",
        }
    except Exception as exc:
        return {"ok": False, "enabled": True, "backend": "unknown", "nodes_written": 0, "edges_written": 0, "error": str(exc)}


def import_store_to_graph(store: JsonlKnowledgeStore, backend: KnowledgeGraphBackend, *, limit: int = 500) -> dict[str, Any]:
    """Import recent long-term Knowledge JSONL rows into a graph backend."""
    records: list[Record] = []
    records.extend(store._read_model_list("experiment_records", ExperimentKnowledgeRecord, limit=limit))  # noqa: SLF001 - migration helper
    records.extend(store.list_agent_performance(limit=limit))
    records.extend(store.list_failure_patterns(limit=limit))
    records.extend(store.list_success_patterns(limit=limit))
    records.extend(store.list_evolution_packs(limit=limit))
    records.extend(store.list_evolution_outcomes(limit=limit))
    nodes, edges = records_to_graph(records)
    try:
        health = backend.health()
        if not health.get("enabled", True):
            return {"ok": True, "enabled": False, "backend": health.get("backend", "disabled"), "records": len(records), "nodes_written": 0, "edges_written": 0}
        node_result = backend.upsert_nodes(nodes)
        edge_result = backend.upsert_edges(edges)
        result = {
            "ok": bool(node_result.get("ok", True) and edge_result.get("ok", True)),
            "enabled": True,
            "backend": node_result.get("backend") or edge_result.get("backend") or health.get("backend", "unknown"),
            "records": len(records),
            "nodes_written": int(node_result.get("nodes_written") or 0),
            "edges_written": int(edge_result.get("edges_written") or 0),
            "node_count": node_result.get("node_count"),
            "edge_count": edge_result.get("edge_count"),
        }
        _write_import_state(store.memory_root, result)
        return result
    except Exception as exc:
        result = {"ok": False, "enabled": True, "backend": "unknown", "records": len(records), "nodes_written": 0, "edges_written": 0, "error": str(exc)}
        _write_import_state(store.memory_root, result)
        return result


def records_to_graph(records: list[Record]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    for record in records:
        for node in _record_nodes(record):
            nodes[node["id"]] = {**nodes.get(node["id"], {}), **node}
        for edge in _record_edges(record):
            edges[edge["id"]] = {**edges.get(edge["id"], {}), **edge}
    return list(nodes.values()), list(edges.values())


def _record_nodes(record: Record) -> list[dict[str, Any]]:
    payload = _dump(record)
    record_id = _record_id(record)
    run_id = str(payload.get("run_id") or payload.get("activated_for_run_id") or "")
    nodes = [
        {
            "id": record_id,
            "kind": _record_kind(record),
            "label": _record_label(record),
            "record_type": _record_kind(record),
            "run_id": run_id,
            "agent_id": _agent_id(record),
            "stage": str(payload.get("stage") or ""),
            "target_type": str(payload.get("target_type") or ""),
            "target_id": str(payload.get("target_id") or ""),
            "created_at": str(payload.get("created_at") or ""),
            "properties": payload,
        }
    ]
    if run_id:
        nodes.append({"id": f"run:{run_id}", "kind": "Run", "label": run_id, "run_id": run_id, "properties": {"run_id": run_id}})
    agent_id = _agent_id(record)
    if agent_id:
        nodes.append({"id": f"agent:{agent_id}", "kind": "Agent", "label": agent_id, "agent_id": agent_id, "properties": {"agent_id": agent_id}})
    for agent in _affected_agents(record):
        nodes.append({"id": f"agent:{agent}", "kind": "Agent", "label": agent, "agent_id": agent, "properties": {"agent_id": agent}})
    target_id = str(payload.get("target_id") or "")
    target_type = str(payload.get("target_type") or "")
    if target_id:
        nodes.append({"id": f"target:{target_type}:{target_id}", "kind": "EvolutionTarget", "label": f"{target_type}:{target_id}", "target_type": target_type, "target_id": target_id, "properties": {"target_type": target_type, "target_id": target_id}})
    for artifact in _artifact_refs(record):
        artifact_id = _artifact_id(artifact)
        if artifact_id:
            nodes.append({"id": f"artifact:{artifact_id}", "kind": "Artifact", "label": artifact_id, "properties": artifact})
    return nodes


def _record_edges(record: Record) -> list[dict[str, Any]]:
    payload = _dump(record)
    record_id = _record_id(record)
    run_id = str(payload.get("run_id") or payload.get("activated_for_run_id") or "")
    edges: list[dict[str, Any]] = []
    if run_id:
        edges.append(_edge(record_id, f"run:{run_id}", "OBSERVED_IN", run_id=run_id))
    agent_id = _agent_id(record)
    if agent_id:
        edges.append(_edge(record_id, f"agent:{agent_id}", "ASSOCIATED_WITH", run_id=run_id))
    for agent in _affected_agents(record):
        edges.append(_edge(record_id, f"agent:{agent}", "AFFECTS", run_id=run_id))
    target_id = str(payload.get("target_id") or "")
    target_type = str(payload.get("target_type") or "")
    if target_id:
        rel_type = "RECOMMENDS" if isinstance(record, EvolutionEvidencePack) else "TARGETS"
        edges.append(_edge(record_id, f"target:{target_type}:{target_id}", rel_type, run_id=run_id))
    for artifact in _artifact_refs(record):
        artifact_id = _artifact_id(artifact)
        if artifact_id:
            edges.append(_edge(record_id, f"artifact:{artifact_id}", "USED", run_id=run_id, properties={"artifact": artifact}))
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    for used in provenance.get("used", []) or []:
        target = f"artifact:{used}" if "/" in str(used) or "." in str(used) else f"source:{used}"
        edges.append(_edge(record_id, target, "USED", run_id=run_id, properties={"source_ref": str(used)}))
    for derived in provenance.get("was_derived_from", []) or []:
        target = f"run:{derived}" if str(derived).startswith("run") else f"source:{derived}"
        edges.append(_edge(record_id, target, "DERIVED_FROM", run_id=run_id, properties={"source_ref": str(derived)}))
    for assoc in provenance.get("was_associated_with", []) or []:
        target = f"agent:{assoc}" if str(assoc).endswith("agent") or str(assoc) in _known_agents() else f"source:{assoc}"
        edges.append(_edge(record_id, target, "ASSOCIATED_WITH", run_id=run_id, properties={"source_ref": str(assoc)}))
    if isinstance(record, EvolutionOutcomeRecord):
        variant = str(record.variant_id or "")
        if variant:
            edges.append(_edge(record_id, f"variant:{variant}", "ATTRIBUTES_OUTCOME", run_id=run_id))
    return edges


def _edge(source: str, target: str, edge_type: str, *, run_id: str = "", properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": f"{source}__{edge_type}__{target}",
        "source": source,
        "target": target,
        "type": edge_type,
        "run_id": run_id,
        "properties": properties or {},
    }


def _dump(record: BaseModel) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _record_id(record: Record) -> str:
    if isinstance(record, ExperimentKnowledgeRecord):
        return f"experiment:{record.record_id}"
    if isinstance(record, AgentPerformanceRecord):
        return f"performance:{record.record_id}"
    if isinstance(record, FailurePatternRecord):
        return f"failure:{record.pattern_id}"
    if isinstance(record, SuccessPatternRecord):
        return f"success:{record.skill_id}"
    if isinstance(record, EvolutionEvidencePack):
        return f"evolution_pack:{record.pack_id}"
    if isinstance(record, EvolutionOutcomeRecord):
        return f"evolution_outcome:{record.outcome_id}"
    return f"record:{id(record)}"


def _record_kind(record: Record) -> str:
    if isinstance(record, ExperimentKnowledgeRecord):
        return "ExperimentKnowledge"
    if isinstance(record, AgentPerformanceRecord):
        return "AgentPerformance"
    if isinstance(record, FailurePatternRecord):
        return "FailurePattern"
    if isinstance(record, SuccessPatternRecord):
        return "SuccessPattern"
    if isinstance(record, EvolutionEvidencePack):
        return "EvolutionPack"
    if isinstance(record, EvolutionOutcomeRecord):
        return "EvolutionOutcome"
    return "KnowledgeRecord"


def _record_label(record: Record) -> str:
    if isinstance(record, ExperimentKnowledgeRecord):
        return record.summary[:80] or record.record_id
    if isinstance(record, AgentPerformanceRecord):
        return f"{record.agent_id}:{record.status}:{record.score}"
    if isinstance(record, FailurePatternRecord):
        return record.failure_type
    if isinstance(record, SuccessPatternRecord):
        return record.scope or record.skill_id
    if isinstance(record, EvolutionEvidencePack):
        return record.objective[:80] or record.pack_id
    if isinstance(record, EvolutionOutcomeRecord):
        return f"{record.target_type}:{record.target_id}:{record.verdict}"
    return _record_id(record)


def _agent_id(record: Record) -> str:
    if isinstance(record, AgentPerformanceRecord):
        return record.agent_id
    if isinstance(record, SuccessPatternRecord):
        return record.agent_id
    return ""


def _affected_agents(record: Record) -> list[str]:
    if isinstance(record, FailurePatternRecord):
        return list(record.affected_agents)
    if isinstance(record, EvolutionEvidencePack):
        return [record.target_id] if record.target_type == "prompt" and record.target_id else []
    if isinstance(record, EvolutionOutcomeRecord):
        return [record.target_id] if record.target_id else []
    return []


def _artifact_refs(record: Record) -> list[dict[str, Any]]:
    payload = _dump(record)
    refs: list[dict[str, Any]] = []
    if isinstance(payload.get("artifact_refs"), list):
        refs.extend(item for item in payload["artifact_refs"] if isinstance(item, dict))
    if isinstance(payload.get("artifact_refs"), dict):
        for value in payload["artifact_refs"].values():
            if isinstance(value, list):
                refs.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                refs.append(value)
    if isinstance(payload.get("supporting_records"), dict):
        for item in payload["supporting_records"].get("artifact_refs", []) or []:
            if isinstance(item, dict):
                refs.append(item)
    return refs[:50]


def _artifact_id(artifact: dict[str, Any]) -> str:
    return str(artifact.get("path") or artifact.get("artifact_id") or artifact.get("kind") or "")


def _known_agents() -> set[str]:
    return {"design", "specimen", "vision", "manipulation", "equipment", "analysis", "knowledge", "bo", "guardian", "orchestrator"}


def _write_import_state(memory_root: Path, result: dict[str, Any]) -> None:
    try:
        out_dir = memory_root / "graph_backend"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": datetime.now(timezone.utc).isoformat(), **result}
        (out_dir / "import_state.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    except Exception:
        return
