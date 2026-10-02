"""Project manual corpus records into the manual ontology graph."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml


def load_manual_ontology(path: Path | None = None) -> dict[str, Any]:
    ontology_path = path or Path(__file__).resolve().parents[1] / "ontology" / "manual_equipment.v1.yaml"
    payload = yaml.safe_load(ontology_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "atr_manual_ontology.v1":
        raise ValueError("invalid manual ontology")
    return payload


def project_manual_graph(corpus: dict[str, Any], *, ontology: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ontology = ontology or load_manual_ontology()
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    source_by_id = {str(item.get("source_id")): item for item in corpus.get("sources", []) if isinstance(item, dict)}
    equipment_id = "manual-equipment:utm"
    _node(nodes, equipment_id, "EquipmentType", "UTM", {"equipment_type": "utm", "graph_source": "manual_rag"})
    section_ids: dict[tuple[str, str], str] = {}
    for source_id, source in source_by_id.items():
        document_id = f"manual-document:{_slug(source_id)}"
        _node(nodes, document_id, "ManualDocument", str(source.get("title") or source_id), {**source, "graph_source": "manual_rag"})
        _edge(edges, document_id, equipment_id, "APPLIES_TO")
    for chunk in corpus.get("chunks", []):
        if not isinstance(chunk, dict) or str(chunk.get("equipment_type") or "") != "utm":
            continue
        source_id = str(chunk.get("source_id") or "")
        document_id = f"manual-document:{_slug(source_id)}"
        section_label = " / ".join(str(item) for item in chunk.get("section_path", []) if str(item)) or "Document"
        section_key = (source_id, section_label)
        section_id = section_ids.setdefault(section_key, f"manual-section:{_digest(source_id + chr(0) + section_label)}")
        _node(nodes, section_id, "ManualSection", section_label, _provenance(chunk))
        _edge(edges, document_id, section_id, "HAS_SECTION")
        chunk_id = str(chunk.get("chunk_id") or "")
        _node(nodes, chunk_id, "ManualChunk", f"{section_label} p.{chunk.get('page')}", {**_provenance(chunk), "text": str(chunk.get("text") or "")})
        _edge(edges, section_id, chunk_id, "HAS_CHUNK")
        _edge(edges, chunk_id, document_id, "SOURCED_FROM")
        _project_chunk_semantics(chunk, document_id=document_id, nodes=nodes, edges=edges)
    report = validate_manual_graph(list(nodes.values()), list(edges.values()), ontology=ontology)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    return sorted(nodes.values(), key=lambda item: item["id"]), sorted(edges.values(), key=lambda item: item["id"])


def validate_manual_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, ontology: dict[str, Any] | None = None) -> dict[str, Any]:
    ontology = ontology or load_manual_ontology()
    classes = {str(item) for item in ontology.get("classes", [])}
    rules = ontology.get("relations") if isinstance(ontology.get("relations"), dict) else {}
    by_id = {str(node.get("id") or ""): str(node.get("kind") or "") for node in nodes}
    errors: list[str] = []
    for node_id, kind in by_id.items():
        if not node_id or kind not in classes:
            errors.append(f"invalid manual node {node_id}: {kind}")
    for edge in edges:
        relation = str(edge.get("type") or "")
        rule = rules.get(relation)
        source_kind = by_id.get(str(edge.get("source") or ""), "")
        target_kind = by_id.get(str(edge.get("target") or ""), "")
        if not isinstance(rule, dict):
            errors.append(f"unknown manual relation: {relation}")
            continue
        if source_kind not in rule.get("domain", []) or target_kind not in rule.get("range", []):
            errors.append(f"manual relation {relation} excludes {source_kind}->{target_kind}")
    return {"ok": not errors, "errors": errors}


def _project_chunk_semantics(chunk: dict[str, Any], *, document_id: str, nodes: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]]) -> None:
    text = str(chunk.get("text") or "")
    chunk_id = str(chunk.get("chunk_id") or "")
    provenance = _provenance(chunk)
    if re.search(r"(?:WARNING|주의|금지|위험)", text, re.IGNORECASE):
        warning_id = f"manual-warning:{_digest(chunk_id)}"
        _node(nodes, warning_id, "Warning", _summary(text), provenance)
        _edge(edges, chunk_id, warning_id, "HAS_WARNING")
        _edge(edges, warning_id, chunk_id, "SOURCED_FROM")
    marker = r"(?:[:：]\s*|-\s+)"
    cause_match = re.search(
        rf"(?:^|\n|\s)원인\s*{marker}(.+?)(?=(?:\n|\s)조치\s*{marker}|$)",
        text,
        re.DOTALL,
    )
    remedy_match = re.search(rf"(?:^|\n|\s)조치\s*{marker}(.+)$", text, re.DOTALL)
    if cause_match or remedy_match:
        fault_id = f"manual-fault:{_digest(chunk_id)}"
        _node(nodes, fault_id, "Fault", _summary(text), provenance)
        _edge(edges, fault_id, chunk_id, "SOURCED_FROM")
        if cause_match:
            cause_id = f"manual-cause:{_digest(chunk_id + cause_match.group(1))}"
            _node(nodes, cause_id, "Cause", _summary(cause_match.group(1)), provenance)
            _edge(edges, fault_id, cause_id, "HAS_CAUSE")
            _edge(edges, cause_id, chunk_id, "SOURCED_FROM")
        if remedy_match:
            remedy_id = f"manual-remedy:{_digest(chunk_id + remedy_match.group(1))}"
            _node(nodes, remedy_id, "Remedy", _summary(remedy_match.group(1)), provenance)
            _edge(edges, fault_id, remedy_id, "RESOLVED_BY")
            _edge(edges, remedy_id, chunk_id, "SOURCED_FROM")
    step_lines = [line.strip() for line in text.splitlines() if re.match(r"^\d{1,2}[.)]\s*", line.strip())]
    if step_lines:
        procedure_id = f"manual-procedure:{_digest(chunk_id)}"
        _node(nodes, procedure_id, "Procedure", str(chunk.get("section_path", ["Procedure"])[-1]), provenance)
        _edge(edges, procedure_id, chunk_id, "SOURCED_FROM")
        previous = ""
        for index, line in enumerate(step_lines, start=1):
            step_id = f"manual-step:{_digest(chunk_id + str(index))}"
            _node(nodes, step_id, "ProcedureStep", line, {**provenance, "step_index": index})
            _edge(edges, procedure_id, step_id, "HAS_STEP")
            _edge(edges, step_id, chunk_id, "SOURCED_FROM")
            if previous:
                _edge(edges, previous, step_id, "PRECEDES")
            previous = step_id


def _node(target: dict[str, dict[str, Any]], node_id: str, kind: str, label: str, properties: dict[str, Any]) -> None:
    target[node_id] = {"id": node_id, "kind": kind, "label": label[:240], "properties": properties}


def _edge(target: dict[str, dict[str, Any]], source: str, destination: str, relation: str) -> None:
    edge_id = f"manual-edge:{_digest(source + chr(0) + relation + chr(0) + destination)}"
    target[edge_id] = {"id": edge_id, "source": source, "target": destination, "type": relation, "properties": {"graph_source": "manual_rag"}}


def _provenance(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_source": "manual_rag",
        "source_id": str(chunk.get("source_id") or ""),
        "source_sha256": str(chunk.get("source_sha256") or ""),
        "page": int(chunk.get("page") or 0),
        "section_path": list(chunk.get("section_path") or []),
    }


def _summary(text: str, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "-", value.strip()).strip("-").lower() or _digest(value)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
