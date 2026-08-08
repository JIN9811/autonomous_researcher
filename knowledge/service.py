"""Shared operational service for ATR Knowledge persistence and retrieval."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from knowledge.audit_ledger import AuditLedger
from knowledge.activity import KnowledgeActivityReader
from knowledge.durable_outbox import DurableOutbox
from knowledge.event_normalizer import normalize_knowledge_event
from knowledge.graph_backend import KnowledgeGraphBackend, graph_backend_from_env
from knowledge.graph_query_planner import validate_query_plan
from knowledge.graph_retrieval import GraphRetrievalService
from knowledge.graph_sync_worker import GraphSyncWorker
from knowledge.neo4j_repository import Neo4jRepository
from knowledge.ontology.registry import OntologyRegistry
from knowledge.ontology.validator import OntologyValidator


class KnowledgeService:
    def __init__(
        self,
        project_root: Path,
        *,
        backend: KnowledgeGraphBackend,
        registry: OntologyRegistry | None = None,
        max_attempts: int = 5,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.registry = registry or OntologyRegistry.load_default(self.project_root)
        self.validator = OntologyValidator(self.registry)
        memory_root = self.project_root / "memory" / "knowledge"
        self.ledger = AuditLedger(memory_root / "ledger")
        self.outbox = DurableOutbox(memory_root / "outbox", max_attempts=max_attempts)
        self.repository = Neo4jRepository(backend)
        self.worker = GraphSyncWorker(self.outbox, self.repository)
        self.retrieval = GraphRetrievalService(backend)

    @classmethod
    def from_env(cls, project_root: Path) -> "KnowledgeService":
        attempts = max(1, int(os.environ.get("ATR_KNOWLEDGE_GRAPH_MAX_ATTEMPTS", "5")))
        return cls(project_root, backend=graph_backend_from_env(project_root), max_attempts=attempts)

    def ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = normalize_knowledge_event(payload, ontology_version=self.registry.version_id)
        validation = self.validator.validate_event(event)
        ledger_receipt = self.ledger.append(event)
        validation_payload = {
            "ok": validation.ok,
            "errors": list(validation.errors),
            "missing_fields": list(validation.missing_fields),
        }
        if not validation.ok:
            return {
                "ok": False,
                "status": "validation_failed",
                "event_id": event["event_id"],
                "validation": validation_payload,
                "ledger_receipt": ledger_receipt.as_dict(),
                "outbox": self.outbox.stats(),
            }
        item = self.outbox.enqueue(event, ledger_receipt)
        sync = self.worker.sync_pending(limit=100)
        return {
            "ok": True,
            "status": "synchronized" if sync.ok and sync.pending == 0 else "degraded",
            "event_id": event["event_id"],
            "outbox_item_id": item.item_id,
            "validation": validation_payload,
            "ledger_receipt": ledger_receipt.as_dict(),
            "sync": sync.as_dict(),
            "outbox": self.outbox.stats(),
        }

    def sync(self, *, limit: int = 100) -> dict[str, Any]:
        return self.worker.sync_pending(limit=limit).as_dict()

    def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.retrieval.query(validate_query_plan(payload))

    def activity(self, *, run_id: str = "", limit: int = 20) -> dict[str, Any]:
        return KnowledgeActivityReader(self.ledger.root).aggregate(run_id=run_id, limit=limit)

    def status(self) -> dict[str, Any]:
        health = self.repository.health()
        outbox = self.outbox.stats()
        return {
            "ok": bool(health.get("ok", False)) and outbox["dead_letter"] == 0,
            "status": "ready" if health.get("ok", False) and outbox["pending"] == 0 else "degraded",
            "ontology_version": self.registry.version_id,
            "graph": health,
            "outbox": outbox,
        }

    def close(self) -> None:
        self.repository.close()


def event_pipeline_enabled() -> bool:
    explicit = os.environ.get("ATR_KNOWLEDGE_EVENT_PIPELINE_ENABLED")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return os.environ.get("ATR_KNOWLEDGE_GRAPH_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
