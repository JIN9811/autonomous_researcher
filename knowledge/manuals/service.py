"""Bounded UTM manual GraphRAG service."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from knowledge.graph_backend import KnowledgeGraphBackend, graph_backend_from_env
from knowledge.manuals.graph_projection import load_manual_ontology, project_manual_graph, validate_manual_graph
from knowledge.manuals.ingest import ManualIngestor
from knowledge.manuals.semantic_projection import build_semantic_graph, project_semantic_subgraph, validate_semantic_provenance


ALLOWED_PURPOSES = frozenset({"skill_authoring", "procedure", "decision", "safety", "recovery"})
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_]+")
_HANGUL_RE = re.compile(r"[가-힣]{2,}")
_EMBED_DIM = 128
_PURPOSE_TERMS = {
    "skill_authoring": ("화면", "버튼", "메뉴", "설정", "입력", "선택", "저장"),
    "procedure": ("절차", "순서", "방법", "설정", "시작", "시험", "확인"),
    "decision": ("조건", "상태", "확인", "판단", "설정", "선택"),
    "safety": ("안전", "경고", "주의", "위험", "과부하", "긴급", "금지"),
    "recovery": ("장애", "고장", "진단", "원인", "조치", "복구", "작동하지", "시작이 되지", "연결", "통신"),
}


class ManualKnowledgeService:
    def __init__(
        self,
        *,
        project_root: Path,
        runtime_root: Path | None = None,
        registry_path: Path | None = None,
        graph_backend: KnowledgeGraphBackend | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.runtime_root = (runtime_root or self.project_root / "memory" / "knowledge" / "manual_rag").resolve()
        self.registry_path = (registry_path or self.project_root / "docs" / "knowledge" / "manuals" / "registry.yaml").resolve()
        self.graph_backend = graph_backend or graph_backend_from_env(self.project_root)
        self._owns_backend = graph_backend is None

    def ingest(self) -> dict[str, Any]:
        result = ManualIngestor().ingest_registry(self.registry_path, self.runtime_root)
        if not result.get("ok"):
            return result
        corpus = self._load_corpus()
        ontology = load_manual_ontology()
        nodes, edges = project_manual_graph(corpus, ontology=ontology)
        validation = validate_manual_graph(nodes, edges, ontology=ontology)
        if not validation["ok"]:
            return {**result, "ok": False, "error": "; ".join(validation["errors"])}
        graph_payload = {
            "schema": "manual_knowledge_graph.v1",
            "ontology_version": str(ontology.get("version_id") or ""),
            "nodes": nodes,
            "edges": edges,
        }
        try:
            semantic_payload = build_semantic_graph(corpus, graph_payload)
        except Exception as exc:
            return {**result, "ok": False, "error": f"semantic projection failed: {exc}"}
        semantic_validation = validate_semantic_provenance(semantic_payload)
        if not semantic_validation["ok"]:
            return {**result, "ok": False, "error": "; ".join(semantic_validation["errors"])}
        _write_json_atomic(self.runtime_root / "manual_graph.json", graph_payload)
        _write_json_atomic(self.runtime_root / "manual_semantic_graph.json", semantic_payload)
        semantic_receipt = {
            "schema": "manual_semantic_rebuild_receipt.v1",
            "ok": True,
            "version": semantic_payload["version"],
            **_semantic_quality_metrics(semantic_payload),
        }
        _write_json_atomic(self.runtime_root / "receipts" / f"semantic-{semantic_payload['version']}.json", semantic_receipt)
        node_result = self.graph_backend.upsert_nodes(nodes)
        edge_result = self.graph_backend.upsert_edges(edges)
        semantic_node_result = self.graph_backend.upsert_nodes(semantic_payload["nodes"])
        semantic_edge_result = self.graph_backend.upsert_edges(semantic_payload["edges"])
        return {
            **result,
            "graph": {"nodes": len(nodes), "edges": len(edges), "node_sync": node_result, "edge_sync": edge_result},
            "semantic_graph": {
                "nodes": len(semantic_payload["nodes"]),
                "edges": len(semantic_payload["edges"]),
                "version": semantic_payload["version"],
                "node_sync": semantic_node_result,
                "edge_sync": semantic_edge_result,
                **_semantic_quality_metrics(semantic_payload),
            },
        }

    def ensure_ingested(self) -> dict[str, Any]:
        if (
            (self.runtime_root / "corpus.json").is_file()
            and (self.runtime_root / "manual_graph.json").is_file()
            and (self.runtime_root / "manual_semantic_graph.json").is_file()
        ):
            return {"ok": True, "status": "ready"}
        return self.ingest()

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        equipment_type = str(payload.get("equipment_type") or "").strip().lower()
        if equipment_type != "utm":
            raise ValueError("equipment_type must be utm")
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("manual query is required")
        purpose = str(payload.get("purpose") or "procedure").strip().lower()
        if purpose not in ALLOWED_PURPOSES:
            raise ValueError(f"unsupported manual query purpose: {purpose}")
        try:
            top_k = max(1, min(int(payload.get("top_k") or 6), 12))
        except (TypeError, ValueError) as exc:
            raise ValueError("top_k must be an integer") from exc
        ready = self.ensure_ingested()
        if not ready.get("ok"):
            return self._empty_context(equipment_type, query, purpose, error=str(ready.get("error") or "manual corpus unavailable"))
        corpus = self._load_corpus()
        source_by_id = {str(item.get("source_id")): item for item in corpus.get("sources", []) if isinstance(item, dict)}
        q_tokens = _search_features(query)
        q_embedding = _stable_embedding(query)
        product_hint = str(payload.get("product_hint") or "").strip().lower()
        version_hint = str(payload.get("version_hint") or "").strip().lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for raw in corpus.get("chunks", []):
            if not isinstance(raw, dict) or str(raw.get("equipment_type") or "").lower() != equipment_type:
                continue
            text = str(raw.get("text") or "")
            section_text = " ".join(str(item) for item in raw.get("section_path", []))
            searchable = f"{section_text} {text}".strip()
            tokens = _search_features(searchable)
            lexical = len(q_tokens & tokens) / max(math.sqrt(len(q_tokens) * max(len(tokens), 1)), 1.0)
            semantic = _cosine(q_embedding, _stable_embedding(searchable))
            purpose_terms = _PURPOSE_TERMS[purpose]
            purpose_matches = sum(1 for term in purpose_terms if term.lower() in searchable.lower())
            purpose_signal = purpose_matches / len(purpose_terms)
            section_matches = sum(1 for term in purpose_terms if term.lower() in section_text.lower())
            section_signal = min(section_matches / 2.0, 1.0)
            source = source_by_id.get(str(raw.get("source_id") or ""), {})
            soft = 0.0
            if product_hint and product_hint in str(source.get("product") or raw.get("product") or "").lower():
                soft += 0.03
            if version_hint and version_hint in str(source.get("version") or raw.get("version") or "").lower():
                soft += 0.02
            scored.append((0.38 * lexical + 0.22 * semantic + 0.25 * purpose_signal + 0.15 * section_signal + soft, raw))
        scored.sort(key=lambda item: (-item[0], int(item[1].get("page") or 0), str(item[1].get("chunk_id") or "")))
        selected = scored[:top_k]
        chunks = []
        for score, raw in selected:
            source = source_by_id.get(str(raw.get("source_id") or ""), {})
            chunks.append(
                {
                    **deepcopy(raw),
                    "score": round(score, 6),
                    "citation": {
                        "source_id": str(raw.get("source_id") or ""),
                        "title": str(source.get("title") or raw.get("source_id") or ""),
                        "page": int(raw.get("page") or 0),
                        "section_path": list(raw.get("section_path") or []),
                        "source_sha256": str(raw.get("source_sha256") or ""),
                    },
                }
            )
        selected_chunk_ids = {str(item["chunk_id"]) for item in chunks}
        graph = self._bounded_graph(selected_chunk_ids, limit=min(100, top_k * 8))
        semantic_graph = self._load_json(self.runtime_root / "manual_semantic_graph.json")
        semantic_projection = project_semantic_subgraph(
            semantic_graph,
            selected_chunk_ids,
            purpose,
            node_limit=40,
            edge_limit=60,
            depth=2,
        )
        coverage = max((item["score"] for item in chunks), default=0.0)
        context = {
            "schema": "manual_context.v1",
            "equipment_type": equipment_type,
            "purpose": purpose,
            "query": query,
            "chunks": chunks,
            "graph": graph,
            "semantic_projection": semantic_projection,
            "coverage": round(coverage, 6),
            "insufficient_evidence": not chunks or coverage < 0.08,
            "insufficient_semantic_evidence": not semantic_projection["nodes"],
            "source_separation": {"manual_only": True, "web_used": False, "runtime_memory_used": False},
        }
        context["context_hash"] = hashlib.sha256(json.dumps(context, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()
        return context

    def status(self) -> dict[str, Any]:
        corpus = self._load_json(self.runtime_root / "corpus.json")
        graph = self._load_json(self.runtime_root / "manual_graph.json")
        semantic_graph = self._load_json(self.runtime_root / "manual_semantic_graph.json")
        receipts = sorted((self.runtime_root / "receipts").glob("*.json")) if (self.runtime_root / "receipts").is_dir() else []
        latest = self._load_json(receipts[-1]) if receipts else {}
        return {
            "ok": bool(corpus),
            "schema": "manual_rag_status.v1",
            "equipment_type": "utm",
            "registry_path": str(self.registry_path),
            "source_count": len(corpus.get("sources", [])),
            "chunk_count": len(corpus.get("chunks", [])),
            "node_count": len(graph.get("nodes", [])),
            "edge_count": len(graph.get("edges", [])),
            "semantic_node_count": len(semantic_graph.get("nodes", [])),
            "semantic_edge_count": len(semantic_graph.get("edges", [])),
            **_semantic_quality_metrics(semantic_graph),
            "latest_receipt": latest,
            "graph_backend": self.graph_backend.health(),
        }

    def graph(self, *, limit: int = 100, view: str = "semantic") -> dict[str, Any]:
        selected_view = str(view or "semantic").strip().lower()
        if selected_view not in {"semantic", "evidence"}:
            raise ValueError("manual graph view must be semantic or evidence")
        graph_path = "manual_semantic_graph.json" if selected_view == "semantic" else "manual_graph.json"
        graph = self._load_json(self.runtime_root / graph_path)
        bounded = max(1, min(int(limit), 300))
        nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
        edges = [item for item in graph.get("edges", []) if isinstance(item, dict)]
        if selected_view == "semantic":
            priority = {
                "Fault": 0,
                "Cause": 1,
                "Remedy": 2,
                "Procedure": 3,
                "ProcedureStep": 4,
                "Warning": 5,
                "Interlock": 6,
                "Parameter": 7,
            }
            edges = [item for item in edges if str(item.get("type") or "") != "SUPPORTED_BY"]
        else:
            priority = {
                "EquipmentType": 0,
                "ManualDocument": 1,
                "ManualSection": 2,
                "ManualChunk": 3,
            }
        selected_nodes = sorted(nodes, key=lambda item: (priority.get(str(item.get("kind") or ""), 50), str(item.get("id") or "")))[:bounded]
        selected_ids = {str(item.get("id") or "") for item in selected_nodes}
        selected_edges = [
            item
            for item in edges
            if str(item.get("source") or "") in selected_ids and str(item.get("target") or "") in selected_ids
        ][: bounded * 2]
        return {
            "ok": bool(graph),
            "schema": str(graph.get("schema") or "manual_knowledge_graph.v1"),
            "view": selected_view,
            "nodes": selected_nodes,
            "edges": selected_edges,
        }

    def close(self) -> None:
        if self._owns_backend:
            self.graph_backend.close()

    def _load_corpus(self) -> dict[str, Any]:
        return self._load_json(self.runtime_root / "corpus.json")

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _bounded_graph(self, chunk_ids: set[str], *, limit: int) -> dict[str, Any]:
        graph = self._load_json(self.runtime_root / "manual_graph.json")
        nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
        edges = [item for item in graph.get("edges", []) if isinstance(item, dict)]
        selected_ids = set(chunk_ids)
        for _ in range(2):
            for edge in edges:
                source = str(edge.get("source") or "")
                target = str(edge.get("target") or "")
                if source in selected_ids or target in selected_ids:
                    selected_ids.update((source, target))
                if len(selected_ids) >= limit:
                    break
        selected_nodes = [node for node in nodes if str(node.get("id") or "") in selected_ids][:limit]
        bounded_ids = {str(node.get("id") or "") for node in selected_nodes}
        selected_edges = [edge for edge in edges if str(edge.get("source") or "") in bounded_ids and str(edge.get("target") or "") in bounded_ids][:limit]
        return {"nodes": selected_nodes, "edges": selected_edges, "depth": 2, "limit": limit}

    @staticmethod
    def _empty_context(equipment_type: str, query: str, purpose: str, *, error: str) -> dict[str, Any]:
        return {
            "schema": "manual_context.v1",
            "equipment_type": equipment_type,
            "purpose": purpose,
            "query": query,
            "chunks": [],
            "graph": {"nodes": [], "edges": [], "depth": 2, "limit": 0},
            "semantic_projection": {
                "schema": "manual_semantic_projection.v1",
                "purpose": purpose,
                "seed_ids": [],
                "nodes": [],
                "edges": [],
                "depth": 2,
                "node_limit": 40,
                "edge_limit": 60,
                "truncated": False,
            },
            "coverage": 0.0,
            "insufficient_evidence": True,
            "insufficient_semantic_evidence": True,
            "error": error,
            "source_separation": {"manual_only": True, "web_used": False, "runtime_memory_used": False},
        }


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _search_features(text: str) -> set[str]:
    features = _tokens(text)
    for word in _HANGUL_RE.findall(text):
        normalized = word.lower()
        for width in (2, 3):
            features.update(normalized[index : index + width] for index in range(max(0, len(normalized) - width + 1)))
    return features


def _stable_embedding(text: str) -> list[float]:
    vector = [0.0] * _EMBED_DIM
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vector[int.from_bytes(digest[:4], "big") % _EMBED_DIM] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _semantic_quality_metrics(graph: dict[str, Any]) -> dict[str, float]:
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
    edges = [item for item in graph.get("edges", []) if isinstance(item, dict)]
    assertions = [*nodes, *edges]
    cited = sum(
        1
        for item in assertions
        if isinstance(item.get("properties"), dict) and item["properties"].get("citations")
    )
    semantic_edges = [edge for edge in edges if str(edge.get("type") or "") != "SUPPORTED_BY"]
    connected = {
        str(endpoint)
        for edge in semantic_edges
        for endpoint in (edge.get("source"), edge.get("target"))
        if endpoint
    }
    isolated = sum(1 for node in nodes if str(node.get("id") or "") not in connected)
    fault_ids = {str(node.get("id") or "") for node in nodes if str(node.get("kind") or "") == "Fault"}
    cause_sources = {str(edge.get("source") or "") for edge in semantic_edges if edge.get("type") == "HAS_CAUSE"}
    remedy_sources = {str(edge.get("source") or "") for edge in semantic_edges if edge.get("type") == "RESOLVED_BY"}
    procedure_ids = {str(node.get("id") or "") for node in nodes if str(node.get("kind") or "") == "Procedure"}
    procedure_sources = {str(edge.get("source") or "") for edge in semantic_edges if edge.get("type") == "HAS_STEP"}
    return {
        "semantic_provenance_coverage": round(cited / len(assertions), 6) if assertions else 0.0,
        "isolated_semantic_node_rate": round(isolated / len(nodes), 6) if nodes else 0.0,
        "fault_chain_completion_rate": round(len(fault_ids & cause_sources & remedy_sources) / len(fault_ids), 6) if fault_ids else 0.0,
        "procedure_chain_completion_rate": round(len(procedure_ids & procedure_sources) / len(procedure_ids), 6) if procedure_ids else 0.0,
    }
