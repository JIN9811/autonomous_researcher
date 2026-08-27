"""Typed records for source-separated equipment manual knowledge."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ManualSource:
    source_id: str
    equipment_type: str
    title: str
    path: str
    product: str = ""
    version: str = ""
    source_kind: str = "manual"
    language: str = "ko"
    source_sha256: str = ""
    page_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ManualChunk:
    chunk_id: str
    source_id: str
    equipment_type: str
    page: int
    section_path: tuple[str, ...]
    text: str
    source_sha256: str
    product: str = ""
    version: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["section_path"] = list(self.section_path)
        payload["keywords"] = list(self.keywords)
        return payload


@dataclass(frozen=True, slots=True)
class SemanticNode:
    node_id: str
    kind: str
    label: str
    equipment_type: str
    confidence: float
    supporting_chunk_ids: tuple[str, ...]
    citations: tuple[dict[str, Any], ...]
    extraction_method: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        properties = {
            "equipment_type": self.equipment_type,
            "confidence": float(self.confidence),
            "supporting_chunk_ids": list(self.supporting_chunk_ids),
            "citations": [dict(item) for item in self.citations],
            "extraction_method": self.extraction_method,
            "aliases": list(self.aliases),
            "graph_source": "manual_semantic",
        }
        properties.update(self.metadata)
        return {
            "id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "properties": properties,
        }


@dataclass(frozen=True, slots=True)
class SemanticEdge:
    edge_id: str
    source: str
    target: str
    relation: str
    confidence: float
    supporting_chunk_ids: tuple[str, ...]
    citations: tuple[dict[str, Any], ...]
    extraction_method: str
    review_state: str = "accepted"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.edge_id,
            "source": self.source,
            "target": self.target,
            "type": self.relation,
            "properties": {
                "confidence": float(self.confidence),
                "supporting_chunk_ids": list(self.supporting_chunk_ids),
                "citations": [dict(item) for item in self.citations],
                "extraction_method": self.extraction_method,
                "review_state": self.review_state,
                "graph_source": "manual_semantic",
            },
        }
