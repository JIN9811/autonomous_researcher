"""Content-free retrieval/delivery/use receipts for agent context evidence."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge.context_service import KnowledgePrincipal


class DeliveryLedger:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "delivery_receipts.json"; self.lock_path = self.root / ".delivery_receipts.lock"

    def record_retrieved(self, principal: "KnowledgePrincipal | None", *, request_id: str, consumer_binding: str,
                         context_pack: dict[str, Any], run_id: str = "", loop_id: str = "", attempt_id: str = "") -> dict[str, Any]:
        owner = self._principal(principal)
        if not isinstance(request_id, str) or not request_id or not isinstance(consumer_binding, str) or not consumer_binding:
            raise ValueError("invalid delivery receipt")
        citations = [item.get("citation_id", item.get("record_id", "")) for item in context_pack.get("items", []) if isinstance(item, dict)]
        if any(not isinstance(value, str) or len(value) > 180 for value in (run_id, loop_id, attempt_id)):
            raise ValueError("invalid delivery provenance")
        no_match = not citations and bool((context_pack.get("diagnostics") or {}).get("no_match"))
        unavailable = context_pack.get('status') == 'unavailable' or bool(context_pack.get('diagnostics', {}).get('unavailable'))
        return self._append(owner, {"receipt_id": "delivery-" + uuid.uuid4().hex, "request_id": request_id,
                                    "consumer_binding": consumer_binding, "stage": "unavailable" if unavailable else "no_match" if no_match else "retrieved", "citation_ids": [] if unavailable else citations,
                                    "delivered_citation_ids": [],
                                    "scope_ref": context_pack.get("scope_ref", ""), "revision": context_pack.get("revision", ""),
                                    "run_id": run_id, "loop_id": loop_id, "attempt_id": attempt_id,
                                    "authorization_scope": self._scope(owner)})

    def record_delivered(self, principal: "KnowledgePrincipal | None", receipt_id: str,
                         *, citation_ids: list[str] | None = None) -> dict[str, Any]:
        return self._advance(self._principal(principal), receipt_id, "delivered", citation_ids)

    def record_excluded(self, principal: "KnowledgePrincipal | None", receipt_id: str) -> dict[str, Any]:
        """Persist that retrieved context was deliberately not presented."""
        return self._advance(self._principal(principal), receipt_id, "excluded", [])

    def record_used(self, principal: "KnowledgePrincipal | None", receipt_id: str, *, citation_ids: list[str]) -> dict[str, Any]:
        if not isinstance(citation_ids, list) or any(not isinstance(item, str) for item in citation_ids):
            raise ValueError("invalid citation ids")
        return self._advance(self._principal(principal), receipt_id, "used" if citation_ids else "excluded", citation_ids)

    def record_use_outcome(self, principal, receipt_id: str, *, citation_ids: list[str], non_use_reason: str = '') -> dict[str, Any]:
        """Validated explanatory provenance, separate from authoritative tool evidence."""
        owner = self._principal(principal)
        if non_use_reason not in {'', 'irrelevant', 'applicability_mismatch', 'owner_evidence_sufficient'}:
            raise ValueError('invalid non-use reason')
        with self._locked(False) as state:
            row = state['receipts'].get(receipt_id)
            if not row or not self._visible(owner, row): raise KeyError('delivery receipt not found')
            if row['stage'] not in {'delivered', 'used', 'excluded'} or not row.get('delivered_citation_ids'):
                raise ValueError('reference was not delivered')
            if not isinstance(citation_ids, list) or any(not isinstance(item, str) for item in citation_ids) or not set(citation_ids) <= set(row['delivered_citation_ids']):
                raise ValueError('citation was not delivered')
            use_status = 'used' if citation_ids else 'excluded' if non_use_reason else 'unknown'
            row.update(stage='delivered' if use_status == 'unknown' else use_status,
                       use_status=use_status, non_use_reason=non_use_reason if not citation_ids else '',
                       used_citation_ids=list(dict.fromkeys(citation_ids)), updated_at=self._now())
            return self._public(row)

    def query(self, principal: "KnowledgePrincipal | None", query: str, *, filters: dict[str, Any] | None = None,
              cursor: str = "", limit: int = 25) -> dict[str, Any]:
        owner = self._principal(principal)
        if filters and set(filters) - {"consumer_binding", "stage", "request_id", "run_id", "loop_id", "attempt_id"}: raise ValueError("unsupported delivery filters")
        if not isinstance(query, str) or len(query) > 2_000 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("invalid delivery query")
        with self._locked(True) as state:
            rows = [row for row in state["receipts"].values() if self._visible(owner, row)]
            if filters: rows = [row for row in rows if all(row.get(key) == value for key, value in filters.items())]
            if query: rows = [row for row in rows if query.lower() in (row["consumer_binding"] + " " + row["request_id"]).lower()]
            rows.sort(key=lambda row: row["created_at"], reverse=True)
            revision = self._revision(rows)
            offset = self._cursor(cursor, query, filters, owner, revision)
            selected = [self._public(row) for row in rows[offset:offset + limit]]
            next_cursor = "" if offset + len(selected) >= len(rows) else self._make_cursor(offset + len(selected), query, filters, owner, revision)
            return {"items": selected, "next_cursor": next_cursor,
                    "scope_ref": "delivery:" + owner.subject_id, "revision": revision, "as_of": self._now(), "status": "ok"}

    def read(self, principal: "KnowledgePrincipal | None", receipt_id: str) -> dict[str, Any] | None:
        owner = self._principal(principal)
        with self._locked(True) as state:
            receipt = state["receipts"].get(receipt_id)
            return self._public(receipt) if receipt and self._visible(owner, receipt) else None

    def count(self, principal: "KnowledgePrincipal | None") -> int:
        owner = self._principal(principal)
        with self._locked(True) as state:
            return sum(1 for receipt in state["receipts"].values() if self._visible(owner, receipt))

    def _advance(self, owner: "KnowledgePrincipal", receipt_id: str, stage: str, citation_ids: list[str] | None = None) -> dict[str, Any]:
        with self._locked(False) as state:
            row = state["receipts"].get(receipt_id)
            if not row or not self._visible(owner, row): raise KeyError("delivery receipt not found")
            if (row["stage"], stage) not in {("retrieved", "delivered"), ("retrieved", "excluded"),
                                              ("delivered", "used"), ("delivered", "excluded")}:
                raise ValueError("invalid delivery transition")
            if stage == "delivered":
                delivered = row["citation_ids"] if citation_ids is None else citation_ids
                if not isinstance(delivered, list) or any(not isinstance(item, str) for item in delivered) or not set(delivered).issubset(set(row["citation_ids"])):
                    raise ValueError("citation was not retrieved")
                row["delivered_citation_ids"] = list(dict.fromkeys(delivered))
            if stage == "used" and citation_ids and not set(citation_ids).issubset(set(row.get("delivered_citation_ids", row["citation_ids"]))):
                raise ValueError("citation was not delivered")
            row["stage"] = stage; row["updated_at"] = self._now(); row["used_citation_ids"] = citation_ids or []
            return self._public(row)

    def _append(self, owner: "KnowledgePrincipal", row: dict[str, Any]) -> dict[str, Any]:
        row.update({"subject_id": owner.subject_id, "created_at": self._now(), "updated_at": self._now(), "used_citation_ids": []})
        with self._locked(False) as state: state["receipts"][row["receipt_id"]] = row
        return self._public(row)

    @staticmethod
    def _principal(value: "KnowledgePrincipal | None") -> "KnowledgePrincipal":
        if value is None or not value.subject_id: raise PermissionError("trusted principal is required for delivery receipts")
        return value
    @staticmethod
    def _visible(owner: "KnowledgePrincipal", row: dict[str, Any]) -> bool:
        if row["subject_id"] != owner.subject_id or (row.get("run_id") and row["run_id"] not in owner.run_ids):
            return False
        required = row.get("authorization_scope", {})
        return (set(required.get("project_ids", [])) <= set(owner.project_ids)
                and set(required.get("session_ids", [])) <= set(owner.session_ids)
                and set(required.get("run_ids", [])) <= set(owner.run_ids))
    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key, [] if key in {"citation_ids", "delivered_citation_ids", "used_citation_ids"} else "")
                for key in ("receipt_id", "request_id", "consumer_binding", "stage", "use_status", "non_use_reason", "citation_ids", "delivered_citation_ids", "used_citation_ids", "scope_ref", "revision", "run_id", "loop_id", "attempt_id", "created_at", "updated_at")}
    @staticmethod
    def _scope(owner: "KnowledgePrincipal") -> dict[str, Any]:
        return {"subject_id": owner.subject_id, "run_ids": sorted(owner.run_ids), "project_ids": sorted(owner.project_ids), "session_ids": sorted(owner.session_ids)}
    @staticmethod
    def _revision(rows: list[dict[str, Any]]) -> str:
        public = [{key: row.get(key, "") for key in ("receipt_id", "stage", "updated_at", "run_id", "loop_id", "attempt_id")} for row in rows]
        return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()[:16]
    def _make_cursor(self, offset: int, query: str, filters: dict[str, Any] | None, owner: "KnowledgePrincipal", revision: str) -> str:
        return json.dumps({"o": offset, "q": query, "f": filters or {}, "s": self._scope(owner), "r": revision}, sort_keys=True).encode().hex()
    def _cursor(self, cursor: str, query: str, filters: dict[str, Any] | None, owner: "KnowledgePrincipal", revision: str) -> int:
        if not cursor: return 0
        try: payload = json.loads(bytes.fromhex(cursor))
        except (ValueError, json.JSONDecodeError) as exc: raise ValueError("invalid cursor") from exc
        if payload != {"o": payload.get("o"), "q": query, "f": filters or {}, "s": self._scope(owner), "r": revision} or not isinstance(payload["o"], int):
            raise ValueError("cursor does not belong to this scope")
        return payload["o"]
    @staticmethod
    def _now() -> str: return datetime.now(timezone.utc).isoformat()
    def _load(self) -> dict[str, Any]: return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"receipts": {}}
    def _save(self, value: dict[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".delivery-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream: json.dump(value, stream, separators=(",", ":")); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    class _Lock:
        def __init__(self, ledger: "DeliveryLedger", read: bool): self.ledger, self.read = ledger, read
        def __enter__(self):
            self.ledger.lock_path.touch(exist_ok=True); self.file = self.ledger.lock_path.open("r+"); fcntl.flock(self.file.fileno(), fcntl.LOCK_SH if self.read else fcntl.LOCK_EX); self.value = self.ledger._load(); return self.value
        def __exit__(self, *args):
            if not self.read and args[0] is None: self.ledger._save(self.value)
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN); self.file.close()
    def _locked(self, read: bool) -> "DeliveryLedger._Lock": return self._Lock(self, read)
