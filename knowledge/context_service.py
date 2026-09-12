"""Common scoped facade for public Wiki, private memory and delivery evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from knowledge.delivery import DeliveryLedger
from knowledge.private_memory import PrivateMemory
from knowledge.wiki import WikiCatalog


@dataclass(frozen=True)
class KnowledgePrincipal:
    """Server-authenticated scope snapshot. It is never constructed from HTTP payloads."""
    subject_id: str
    project_ids: frozenset[str] = field(default_factory=frozenset)
    session_ids: frozenset[str] = field(default_factory=frozenset)
    run_ids: frozenset[str] = field(default_factory=frozenset)
    local_model_consent: bool = False
    remote_model_consent: bool = False
    is_admin: bool = False


class KnowledgeContextService:
    def __init__(self, project_root: Path | str, data_root: Path | str | None = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.data_root = Path(data_root).resolve() if data_root else self.project_root / "memory" / "knowledge"
        self.wiki = WikiCatalog(self.project_root)
        private_root = self.data_root / "private"
        self.memory = PrivateMemory(private_root)
        self.delivery = DeliveryLedger(private_root)

    def query(self, principal: KnowledgePrincipal | None, query: str, *, consumer: str, filters: dict[str, Any] | None = None,
              cursor: str = "", limit: int = 25, model_target: str = "none") -> dict[str, Any]:
        """Build a bounded, reference-only context pack; no model invocation occurs."""
        if not isinstance(consumer, str) or not consumer or len(consumer) > 120: raise ValueError("invalid consumer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100: raise ValueError("limit must be an integer from 1 to 100")
        filters = filters or {}
        if set(filters) - {"corpora", "wiki", "memory"}: raise ValueError("unsupported context filters")
        corpora = filters.get("corpora", ["ax4lab_wiki"])
        if not isinstance(corpora, list) or not corpora or len(corpora) != len(set(corpora)) or set(corpora) - {"ax4lab_wiki", "private_memory"}:
            raise ValueError("unsupported corpus")
        if model_target not in {"none", "local", "remote"}: raise ValueError("invalid model target")
        if principal is None and "private_memory" in corpora: raise PermissionError("private corpus requires trusted principal")
        if "private_memory" in corpora and model_target == "local" and not principal.local_model_consent:
            raise PermissionError("local model consent is required for private context")
        if "private_memory" in corpora and model_target == "remote" and not principal.remote_model_consent:
            raise PermissionError("remote model consent is required for private context")
        memory_filters = filters.get("memory") or {}
        if not isinstance(memory_filters, dict): raise ValueError("invalid memory filters")
        if "private_memory" in corpora and memory_filters.get("status", "active") != "active":
            raise ValueError("context memory status must be active")
        memory_filters = {**memory_filters, "status": "active"}
        wiki_result = self.wiki.query(query, filters=filters.get("wiki"), limit=1) if "ax4lab_wiki" in corpora else None
        private = self.memory.query(principal, query, filters=memory_filters, limit=1) if "private_memory" in corpora else None
        revision = self._combined_revision(corpora, wiki_result, private)
        state = self._combined_cursor(cursor, query, filters, principal, revision, corpora)
        phase = state["p"]
        wiki_items: list[dict[str, Any]] = []
        stale_wiki = False
        wiki_next = state["w"]
        if phase == "wiki":
            page = self.wiki.query(query, filters=filters.get("wiki"), cursor=state["w"], limit=limit)
            wiki_next = page["next_cursor"]
            for item in page["items"]:
                if item["freshness"] != "fresh":
                    stale_wiki = True
                    continue
                detail = self.wiki.read(item["record_id"])
                if detail:
                    wiki_items.append({**item, "content": detail["content"][:2_000], "corpus": "ax4lab_wiki", "citation_id": item["record_id"]})
        private_items: list[dict[str, Any]] = []
        private_next = state["m"]
        private_phase = phase == "private" or (phase == "wiki" and not wiki_next)
        private_pending = private_phase and "private_memory" in corpora and len(wiki_items) >= limit
        if private_phase and "private_memory" in corpora and not private_pending:
            page = self.memory.query(principal, query, filters=memory_filters, cursor=state["m"], limit=max(1, limit - len(wiki_items)), include_content=True)
            private_next = page["next_cursor"]
            for item in page["items"]:
                if item["status"] == "active":
                    private_items.append({**item, "corpus": "private_memory", "citation_id": item["record_id"]})
        selected = (wiki_items + private_items)[:limit]
        if wiki_next:
            next_cursor = self._make_combined_cursor({"p": "wiki", "w": wiki_next, "m": state["m"]}, query, filters, principal, revision, corpora)
        elif private_next or private_pending:
            next_cursor = self._make_combined_cursor({"p": "private", "w": "", "m": private_next}, query, filters, principal, revision, corpora)
        else:
            next_cursor = ""
        return {"request": {"consumer": consumer}, "scope_ref": "public" if principal is None else "scoped:" + principal.subject_id,
                "revision": revision, "items": selected, "next_cursor": next_cursor,
                "as_of": datetime.now(timezone.utc).isoformat(), "status": "ok", "diagnostics": {"no_match": not selected, "truncated": bool(next_cursor), "stale_wiki_excluded": stale_wiki},
                "authority": "reference_only"}

    def read_context(self, principal: KnowledgePrincipal | None, record_id: str) -> dict[str, Any] | None:
        if record_id.startswith("wiki:"):
            item = self.wiki.read(record_id)
            return item if item and item["freshness"] == "fresh" else None
        if record_id.startswith("mem-"):
            item = self.memory.read(principal, record_id)
            return item if item and item["status"] == "active" else None
        return None

    def summary(self, principal: KnowledgePrincipal | None) -> dict[str, Any]:
        wiki = self.wiki.query("", limit=1)
        memory = self.memory.query(principal, "", limit=1) if principal else None
        delivery = self.delivery.query(principal, "", limit=1) if principal else None
        return {"wiki": {"count": self.wiki.count(), "revision": wiki["revision"]},
                "memory": {"count": self.memory.count(principal), "revision": memory["revision"]} if memory else {"count": 0, "status": "public_only"},
                "delivery": {"count": self.delivery.count(principal), "revision": delivery["revision"]} if delivery else {"count": 0, "status": "public_only"},
                "scope_ref": "public" if principal is None else "scoped:" + principal.subject_id, "status": "ok"}

    @staticmethod
    def _scope_snapshot(principal: KnowledgePrincipal | None) -> dict[str, Any]:
        if principal is None: return {"public": True}
        return {"subject_id": principal.subject_id, "project_ids": sorted(principal.project_ids),
                "session_ids": sorted(principal.session_ids), "run_ids": sorted(principal.run_ids)}

    def _combined_revision(self, corpora: list[str], wiki: dict[str, Any] | None, private: dict[str, Any] | None) -> str:
        return hashlib.sha256(json.dumps({"corpora": corpora, "wiki": wiki and wiki["revision"], "private": private and private["revision"]}, sort_keys=True).encode()).hexdigest()[:16]

    def _make_combined_cursor(self, state: dict[str, str], query: str, filters: dict[str, Any], principal: KnowledgePrincipal | None, revision: str, corpora: list[str]) -> str:
        return json.dumps({"c": corpora, "p": state["p"], "w": state["w"], "m": state["m"], "q": query, "f": filters, "s": self._scope_snapshot(principal), "r": revision}, sort_keys=True).encode().hex()

    def _combined_cursor(self, cursor: str, query: str, filters: dict[str, Any], principal: KnowledgePrincipal | None, revision: str, corpora: list[str]) -> dict[str, str]:
        if not cursor:
            return {"p": "wiki" if "ax4lab_wiki" in corpora else "private", "w": "", "m": ""}
        try: value = json.loads(bytes.fromhex(cursor))
        except (ValueError, json.JSONDecodeError) as exc: raise ValueError("invalid context cursor") from exc
        if value != {"c": corpora, "p": value.get("p"), "w": value.get("w"), "m": value.get("m"), "q": query, "f": filters, "s": self._scope_snapshot(principal), "r": revision} or value["p"] not in {"wiki", "private"} or not isinstance(value["w"], str) or not isinstance(value["m"], str):
            raise ValueError("context cursor does not belong to this scope")
        return {"p": value["p"], "w": value["w"], "m": value["m"]}
