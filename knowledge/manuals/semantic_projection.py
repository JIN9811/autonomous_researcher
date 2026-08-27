"""Build and query provenance-backed semantic projections of UTM manuals."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict, deque
from typing import Any

from knowledge.manuals.models import SemanticEdge, SemanticNode


_MARKER_RE = re.compile(r"^(?:원인|조치)\s*[:：-]", re.IGNORECASE)
_CAUSE_RE = re.compile(r"(?:^|\n)\s*원인\s*[:：-]\s*([^\n]+)", re.IGNORECASE)
_REMEDY_RE = re.compile(r"(?:^|\n)\s*조치\s*[:：-]\s*([^\n]+)", re.IGNORECASE)
_STEP_RE = re.compile(r"^\s*(\d{1,3})[.)]\s*(.+?)\s*$")
_WARNING_RE = re.compile(r"(?:WARNING|주의|금지|위험)", re.IGNORECASE)


def normalize_semantic_label(value: str) -> str:
    compact = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().lower()
    return re.sub(r"[^0-9a-z가-힣 ]+", "", compact)


def extract_semantic_candidates(chunk: dict[str, Any]) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    """Extract semantic candidates and key-based relations from one cited chunk."""
    chunk_id = str(chunk.get("chunk_id") or "")
    source_id = str(chunk.get("source_id") or "")
    page = int(chunk.get("page") or 0)
    if not chunk_id or not source_id or page <= 0:
        return [], []
    text = str(chunk.get("text") or "")
    section_path = [str(item) for item in chunk.get("section_path", []) if str(item)]
    citation = {
        "source_id": source_id,
        "page": page,
        "section_path": section_path,
        "source_sha256": str(chunk.get("source_sha256") or ""),
    }
    common = {
        "equipment_type": "utm",
        "source_chunk_id": chunk_id,
        "citation": citation,
        "confidence": 0.9,
        "extraction_method": "deterministic",
    }
    candidates: list[dict[str, Any]] = []
    relations: list[tuple[str, str, str]] = []

    causes = [match.group(1).strip() for match in _CAUSE_RE.finditer(text) if match.group(1).strip()]
    remedies = [match.group(1).strip() for match in _REMEDY_RE.finditer(text) if match.group(1).strip()]
    if causes or remedies:
        fault_label = _fault_label(text, section_path)
        fault_key = _candidate_key("Fault", fault_label)
        candidates.append({**common, "key": fault_key, "kind": "Fault", "label": fault_label})
        for cause in causes:
            cause_key = _candidate_key("Cause", cause)
            candidates.append({**common, "key": cause_key, "kind": "Cause", "label": cause})
            relations.append((fault_key, cause_key, "HAS_CAUSE"))
        for remedy in remedies:
            remedy_key = _candidate_key("Remedy", remedy)
            candidates.append({**common, "key": remedy_key, "kind": "Remedy", "label": remedy})
            relations.append((fault_key, remedy_key, "RESOLVED_BY"))

    step_matches = [match for line in text.splitlines() if (match := _STEP_RE.match(line))]
    if step_matches:
        procedure_label = section_path[-1] if section_path else _first_content_line(text, "Procedure")
        procedure_key = _candidate_key("Procedure", procedure_label)
        candidates.append({**common, "key": procedure_key, "kind": "Procedure", "label": procedure_label})
        previous_key = ""
        for index, match in enumerate(step_matches, start=1):
            label = match.group(2).strip()
            step_key = _candidate_key("ProcedureStep", label, context=procedure_label)
            candidates.append(
                {
                    **common,
                    "key": step_key,
                    "kind": "ProcedureStep",
                    "label": label,
                    "metadata": {"step_index": index, "source_step_number": int(match.group(1))},
                }
            )
            relations.append((procedure_key, step_key, "HAS_STEP"))
            if previous_key:
                relations.append((previous_key, step_key, "PRECEDES"))
            previous_key = step_key

    if _WARNING_RE.search(text):
        warning_label = _first_content_line(text, section_path[-1] if section_path else "Warning")
        warning_key = _candidate_key("Warning", warning_label)
        candidates.append({**common, "key": warning_key, "kind": "Warning", "label": warning_label, "confidence": 0.82})

    return candidates, relations


def resolve_semantic_entities(candidates: list[dict[str, Any]]) -> tuple[list[SemanticNode], dict[str, str]]:
    """Merge exact normalized aliases only within one semantic kind and UTM scope."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[str(candidate["key"])].append(candidate)
    nodes: list[SemanticNode] = []
    key_to_id: dict[str, str] = {}
    for key in sorted(grouped):
        items = grouped[key]
        first = items[0]
        chunk_ids = tuple(sorted({str(item["source_chunk_id"]) for item in items}))
        citations = tuple(
            sorted(
                {_citation_key(item["citation"]): dict(item["citation"]) for item in items}.values(),
                key=lambda item: (str(item.get("source_id") or ""), int(item.get("page") or 0)),
            )
        )
        source_ids = sorted({str(item["citation"].get("source_id") or "") for item in items})
        node_id = f"manual-semantic:{str(first['kind']).lower()}:{_digest(key + chr(0) + '|'.join(source_ids))}"
        aliases = tuple(sorted({str(item["label"]) for item in items}))
        metadata: dict[str, Any] = {}
        if str(first["kind"]) == "ProcedureStep":
            metadata["step_index"] = min(int(item.get("metadata", {}).get("step_index") or 0) for item in items)
            metadata["source_step_number"] = min(int(item.get("metadata", {}).get("source_step_number") or 0) for item in items)
        nodes.append(
            SemanticNode(
                node_id=node_id,
                kind=str(first["kind"]),
                label=str(first["label"]),
                equipment_type="utm",
                confidence=max(float(item.get("confidence") or 0.0) for item in items),
                supporting_chunk_ids=chunk_ids,
                citations=citations,
                extraction_method="deterministic",
                aliases=aliases,
                metadata=metadata,
            )
        )
        key_to_id[key] = node_id
    return nodes, key_to_id


def build_semantic_graph(corpus: dict[str, Any], evidence_graph: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic semantic graph whose assertions cite evidence chunks."""
    evidence_ids = {
        str(node.get("id") or "")
        for node in evidence_graph.get("nodes", [])
        if isinstance(node, dict) and str(node.get("kind") or "") == "ManualChunk"
    }
    candidates: list[dict[str, Any]] = []
    raw_relations: list[tuple[str, str, str, str, dict[str, Any]]] = []
    for chunk in corpus.get("chunks", []):
        if not isinstance(chunk, dict) or str(chunk.get("equipment_type") or "") != "utm":
            continue
        chunk_id = str(chunk.get("chunk_id") or "")
        if chunk_id not in evidence_ids:
            continue
        extracted, relations = extract_semantic_candidates(chunk)
        candidates.extend(extracted)
        citation = _citation(chunk)
        raw_relations.extend((source, target, relation, chunk_id, citation) for source, target, relation in relations)

    semantic_nodes, key_to_id = resolve_semantic_entities(candidates)
    node_by_id = {node.node_id: node for node in semantic_nodes}
    relation_support: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source_key, target_key, relation, chunk_id, citation in raw_relations:
        source = key_to_id.get(source_key)
        target = key_to_id.get(target_key)
        if not source or not target:
            continue
        support = relation_support.setdefault((source, target, relation), {"chunks": set(), "citations": {}})
        support["chunks"].add(chunk_id)
        support["citations"][_citation_key(citation)] = citation

    semantic_edges: list[SemanticEdge] = []
    for (source, target, relation), support in sorted(relation_support.items()):
        semantic_edges.append(
            _semantic_edge(source, target, relation, support["chunks"], support["citations"].values())
        )
    for node in semantic_nodes:
        for chunk_id in node.supporting_chunk_ids:
            citations = [citation for citation in node.citations if _citation_matches_chunk(citation, chunk_id, corpus)]
            semantic_edges.append(_semantic_edge(node.node_id, chunk_id, "SUPPORTED_BY", {chunk_id}, citations or node.citations))

    payload = {
        "schema": "manual_semantic_graph.v1",
        "version": _semantic_version(semantic_nodes, semantic_edges),
        "equipment_type": "utm",
        "nodes": [node.as_dict() for node in sorted(semantic_nodes, key=lambda item: item.node_id)],
        "edges": [edge.as_dict() for edge in sorted(semantic_edges, key=lambda item: item.edge_id)],
        "evidence_node_ids": sorted(evidence_ids),
    }
    report = validate_semantic_provenance(payload)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    return payload


def validate_semantic_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    semantic_ids = {str(node.get("id") or "") for node in payload.get("nodes", []) if isinstance(node, dict)}
    evidence_ids = {str(item) for item in payload.get("evidence_node_ids", [])}
    for node in payload.get("nodes", []):
        properties = node.get("properties") if isinstance(node, dict) and isinstance(node.get("properties"), dict) else {}
        if not properties.get("supporting_chunk_ids") or not _valid_citations(properties.get("citations")):
            errors.append(f"semantic node lacks provenance: {node.get('id')}")
    for edge in payload.get("edges", []):
        properties = edge.get("properties") if isinstance(edge, dict) and isinstance(edge.get("properties"), dict) else {}
        if str(edge.get("source") or "") not in semantic_ids:
            errors.append(f"semantic edge source is missing: {edge.get('id')}")
        target = str(edge.get("target") or "")
        if target not in semantic_ids and target not in evidence_ids:
            errors.append(f"semantic edge target is missing: {edge.get('id')}")
        if not properties.get("supporting_chunk_ids") or not _valid_citations(properties.get("citations")):
            errors.append(f"semantic edge lacks provenance: {edge.get('id')}")
    return {"ok": not errors, "errors": errors}


def project_semantic_subgraph(
    graph: dict[str, Any],
    seed_chunk_ids: set[str],
    purpose: str,
    *,
    node_limit: int = 40,
    edge_limit: int = 60,
    depth: int = 2,
) -> dict[str, Any]:
    """Build a bounded semantic-only neighborhood around cited chunk seeds."""
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
    semantic_edges = [
        item
        for item in graph.get("edges", [])
        if isinstance(item, dict) and str(item.get("type") or "") != "SUPPORTED_BY"
    ]
    seed_ids = {
        str(node.get("id") or "")
        for node in nodes
        if seed_chunk_ids & set(node.get("properties", {}).get("supporting_chunk_ids", []))
    }
    priority = _purpose_priority(purpose)
    node_by_id = {str(node.get("id") or ""): node for node in nodes}
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in semantic_edges:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        adjacency[source].add(target)
        adjacency[target].add(source)
    queue = deque((node_id, 0) for node_id in sorted(seed_ids, key=lambda item: _node_rank(node_by_id[item], priority)))
    selected: list[str] = []
    seen: set[str] = set()
    truncated = False
    while queue:
        node_id, level = queue.popleft()
        if node_id in seen:
            continue
        if len(selected) >= max(1, node_limit):
            truncated = True
            break
        seen.add(node_id)
        selected.append(node_id)
        if level < max(0, depth):
            neighbors = sorted(adjacency.get(node_id, ()), key=lambda item: _node_rank(node_by_id[item], priority))
            queue.extend((neighbor, level + 1) for neighbor in neighbors if neighbor not in seen)
    selected_set = set(selected)
    selected_edges = [
        edge
        for edge in sorted(semantic_edges, key=lambda item: str(item.get("id") or ""))
        if str(edge.get("source") or "") in selected_set and str(edge.get("target") or "") in selected_set
    ]
    if len(selected_edges) > edge_limit:
        selected_edges = selected_edges[:edge_limit]
        truncated = True
    return {
        "schema": "manual_semantic_projection.v1",
        "purpose": purpose,
        "seed_ids": sorted(seed_ids),
        "nodes": [node_by_id[node_id] for node_id in selected],
        "edges": selected_edges,
        "depth": depth,
        "node_limit": node_limit,
        "edge_limit": edge_limit,
        "truncated": truncated,
    }


def _fault_label(text: str, section_path: list[str]) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned and not _MARKER_RE.match(cleaned) and not _STEP_RE.match(cleaned):
            return cleaned[:240]
    return (section_path[-1] if section_path else "Fault")[:240]


def _first_content_line(text: str, fallback: str) -> str:
    return next((line.strip()[:240] for line in text.splitlines() if line.strip()), fallback)


def _candidate_key(kind: str, label: str, *, context: str = "") -> str:
    context_key = normalize_semantic_label(context)
    return f"utm\0{kind}\0{context_key}\0{normalize_semantic_label(label)}"


def _citation(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": str(chunk.get("source_id") or ""),
        "page": int(chunk.get("page") or 0),
        "section_path": [str(item) for item in chunk.get("section_path", []) if str(item)],
        "source_sha256": str(chunk.get("source_sha256") or ""),
    }


def _citation_key(citation: dict[str, Any]) -> str:
    return f"{citation.get('source_id')}\0{citation.get('page')}\0{'/'.join(citation.get('section_path') or [])}"


def _valid_citations(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, dict) and int(item.get("page") or 0) > 0 for item in value)
    )


def _semantic_edge(source: str, target: str, relation: str, chunk_ids: Any, citations: Any) -> SemanticEdge:
    chunks = tuple(sorted(str(item) for item in chunk_ids))
    cited = tuple(sorted((dict(item) for item in citations), key=lambda item: (str(item.get("source_id") or ""), int(item.get("page") or 0))))
    edge_id = f"manual-semantic-edge:{_digest(source + chr(0) + relation + chr(0) + target)}"
    return SemanticEdge(edge_id, source, target, relation, 0.9, chunks, cited, "deterministic")


def _citation_matches_chunk(citation: dict[str, Any], chunk_id: str, corpus: dict[str, Any]) -> bool:
    return any(
        str(chunk.get("chunk_id") or "") == chunk_id
        and str(chunk.get("source_id") or "") == str(citation.get("source_id") or "")
        and int(chunk.get("page") or 0) == int(citation.get("page") or 0)
        for chunk in corpus.get("chunks", [])
        if isinstance(chunk, dict)
    )


def _semantic_version(nodes: list[SemanticNode], edges: list[SemanticEdge]) -> str:
    value = "|".join([*(node.node_id for node in nodes), *(edge.edge_id for edge in edges)])
    return _digest(value)


def _purpose_priority(purpose: str) -> dict[str, int]:
    orders = {
        "recovery": ("Fault", "Cause", "Remedy", "Warning", "Procedure", "ProcedureStep"),
        "safety": ("Warning", "Interlock", "Procedure", "ProcedureStep", "Fault", "Remedy"),
        "procedure": ("Procedure", "ProcedureStep", "Warning", "Interlock", "Fault", "Remedy"),
        "skill_authoring": ("Procedure", "ProcedureStep", "Parameter", "Warning", "Fault", "Remedy"),
        "decision": ("Procedure", "Fault", "Warning", "Remedy", "Cause", "ProcedureStep"),
    }
    return {kind: index for index, kind in enumerate(orders.get(purpose, orders["procedure"]))}


def _node_rank(node: dict[str, Any], priority: dict[str, int]) -> tuple[Any, ...]:
    properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    return (
        priority.get(str(node.get("kind") or ""), 99),
        -float(properties.get("confidence") or 0.0),
        str(node.get("label") or ""),
        str(node.get("id") or ""),
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
