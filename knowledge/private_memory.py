"""Locked private v2 memory with explicit lifecycle and erasure semantics."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING
from knowledge.credential_guard import admit_credential_free_text

if TYPE_CHECKING:
    from knowledge.context_service import KnowledgePrincipal

_ID = re.compile(r"mem-[0-9a-f]{32}\Z")
_KINDS = {"preference", "research_context", "decision", "instruction", "experience", "knowledge"}
_ACTIONS = {"propose", "confirm", "dismiss", "edit", "expire", "forget"}


class PrivateMemory:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "private_memory_v2.json"
        self.lock_path = self.root / ".private_memory_v2.lock"

    def command(self, principal: "KnowledgePrincipal | None", *, action: str, payload: dict[str, Any], idempotency_key: str,
                target_id: str = "", expected_revision: int | None = None) -> dict[str, Any]:
        principal = self._principal(principal)
        if action not in _ACTIONS or not isinstance(payload, dict) or not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError("invalid memory command")
        if action in {'propose', 'edit'}:
            admit_credential_free_text(payload.get('content'), limit=4_000)
        fingerprint = self._digest({"action": action, "payload": payload, "target_id": target_id, "expected_revision": expected_revision})
        with self._locked_state() as state:
            old = state["idempotency"].get(f"{principal.subject_id}:{idempotency_key}")
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("idempotency key conflicts with different command")
                return old["receipt"]
            if action == "propose":
                receipt = self._propose(state, principal, payload)
            else:
                receipt = self._transition(state, principal, action, target_id, expected_revision, payload)
            state["idempotency"][f"{principal.subject_id}:{idempotency_key}"] = {"fingerprint": fingerprint, "receipt": receipt}
            return receipt

    def query(self, principal: "KnowledgePrincipal | None", query: str, *, filters: dict[str, Any] | None = None,
              cursor: str = "", limit: int = 25, include_content: bool = False) -> dict[str, Any]:
        principal = self._principal(principal)
        if not isinstance(query, str) or len(query) > 2_000:
            raise ValueError("query must be a bounded string")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        if filters and set(filters) - {"kind", "status", "scope"}:
            raise ValueError("unsupported memory filters")
        with self._locked_state(read_only=True) as state:
            records = [r for r in state["records"].values() if self._visible(principal, r) and self._filtered(r, filters)]
            terms = set(re.findall(r"[^\W_]+", query.lower(), re.UNICODE))
            ranked = [(sum(t in (r["content"] + " " + r["kind"]).lower() for t in terms), r) for r in records]
            if terms:
                ranked = [entry for entry in ranked if entry[0]]
            ranked.sort(key=lambda entry: (-entry[0], entry[1]["record_id"]))
            revision = self._revision(state)
            offset = self._cursor(cursor, query, filters, principal, revision)
            chosen = [(self._public(record) if include_content else self._summary(record)) for _, record in ranked[offset:offset + limit]]
            return self._envelope(chosen, offset + len(chosen), len(ranked), query, filters, principal, revision)

    def read(self, principal: "KnowledgePrincipal | None", record_id: str) -> dict[str, Any] | None:
        if principal is None or not _ID.fullmatch(record_id):
            return None
        with self._locked_state(read_only=True) as state:
            record = state["records"].get(record_id)
            return self._public(record) if record and self._visible(principal, record) else None

    def count(self, principal: "KnowledgePrincipal | None") -> int:
        principal = self._principal(principal)
        with self._locked_state(read_only=True) as state:
            return sum(1 for record in state["records"].values() if self._visible(principal, record))

    def _propose(self, state: dict[str, Any], principal: "KnowledgePrincipal", payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"kind", "content", "source_refs", "scope", "automatic", "explicit", "expires_at"}
        if set(payload) - allowed or payload.get("kind") not in _KINDS:
            raise ValueError("invalid memory proposal")
        content = payload.get("content")
        refs = payload.get("source_refs")
        if not isinstance(content, str) or not content.strip() or len(content) > 4_000 or not isinstance(refs, list) or not refs:
            raise ValueError("invalid memory proposal")
        if any(not isinstance(ref, str) or len(ref) > 512 for ref in refs):
            raise ValueError("invalid source reference")
        scope = self._scope(principal, payload.get("scope"))
        expires_at = self._expiry(payload.get("expires_at", ""), required=scope["kind"] in {"session", "run"})
        if payload.get("automatic") and not payload.get("explicit"):
            blocked = set(refs) & set(state["tombstones"].get(principal.subject_id, []))
            if blocked:
                raise ValueError("source is tombstoned against automatic reingestion")
        record_id = "mem-" + uuid.uuid4().hex
        now = self._now()
        record = {"record_id": record_id, "kind": payload["kind"], "subject_id": principal.subject_id, "scope": scope,
                  "content": content.strip(), "source_refs": refs, "confirmation": "pending", "status": "candidate",
                  "created_at": now, "updated_at": now, "expires_at": expires_at, "revision": 1, "history": []}
        state["records"][record_id] = record
        return self._receipt(record)

    def _transition(self, state: dict[str, Any], principal: "KnowledgePrincipal", action: str, target_id: str,
                    expected_revision: int | None, payload: dict[str, Any]) -> dict[str, Any]:
        if not _ID.fullmatch(target_id):
            raise ValueError("invalid record id")
        record = state["records"].get(target_id)
        if not record or not self._visible(principal, record):
            raise KeyError("record not found")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision != record["revision"]:
            raise ValueError("revision conflict")
        transitions = {"confirm": ("candidate", "active"), "dismiss": ("candidate", "deleted"),
                       "expire": (None, "expired"), "edit": (None, None), "forget": (None, "deleted")}
        prior, next_status = transitions[action]
        if prior and record["status"] != prior:
            raise ValueError("invalid lifecycle transition")
        if action in {"edit", "expire"} and record["status"] not in {"candidate", "active"}:
            raise ValueError("invalid lifecycle transition")
        if action == "edit":
            if set(payload) != {"content"} or not isinstance(payload["content"], str) or not payload["content"].strip() or len(payload["content"]) > 4_000:
                raise ValueError("invalid edit")
            record["history"].append({"revision": record["revision"], "content": record["content"]})
            record["content"] = payload["content"].strip()
        elif payload:
            raise ValueError("unexpected command payload")
        if action == "forget":
            state["tombstones"].setdefault(principal.subject_id, [])
            state["tombstones"][principal.subject_id] = sorted(set(state["tombstones"][principal.subject_id]) | set(record["source_refs"]))
            del state["records"][target_id]
            # Receipts never contained private text; remove any historical command records for this target.
            for key in [key for key, value in state["idempotency"].items() if value["receipt"].get("record_id") == target_id]:
                del state["idempotency"][key]
            return {"record_id": target_id, "revision": record["revision"] + 1, "status": "deleted", "deleted": True}
        record["history"].append({"revision": record["revision"], "content": record["content"]})
        record["revision"] += 1
        record["status"] = next_status or record["status"]
        record["confirmation"] = "confirmed" if action == "confirm" else record["confirmation"]
        record["expires_at"] = self._now() if action == "expire" else record["expires_at"]
        record["updated_at"] = self._now()
        return self._receipt(record)

    @staticmethod
    def _principal(principal: "KnowledgePrincipal | None") -> "KnowledgePrincipal":
        if principal is None or not principal.subject_id:
            raise PermissionError("trusted principal is required for private memory")
        return principal

    @staticmethod
    def _scope(principal: "KnowledgePrincipal", raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict) or set(raw) - {"kind", "project_id", "session_id", "run_id"} or raw.get("kind") not in {"user", "project", "session", "run"}:
            raise ValueError("invalid scope")
        kind = raw["kind"]
        key = {"project": "project_id", "session": "session_id", "run": "run_id"}.get(kind)
        if kind == "user":
            if len(raw) != 1:
                raise ValueError("invalid user scope")
            return {"kind": kind}
        value = raw.get(key)
        allowed = getattr(principal, key[:-3] + "_ids")
        if not isinstance(value, str) or value not in allowed:
            raise PermissionError("scope is not allowed for this principal")
        return {"kind": kind, key: value}

    @staticmethod
    def _visible(principal: "KnowledgePrincipal", record: dict[str, Any]) -> bool:
        if record["subject_id"] != principal.subject_id or record["status"] == "deleted":
            return False
        scope = record["scope"]
        kind = scope["kind"]
        if kind == "user":
            return True
        key = {"project": "project_id", "session": "session_id", "run": "run_id"}[kind]
        return scope.get(key) in getattr(principal, key[:-3] + "_ids")

    @staticmethod
    def _filtered(record: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True
        return all((PrivateMemory._effective_status(record) if key == "status" else record.get(key)) == value for key, value in filters.items())

    @staticmethod
    def _summary(record: dict[str, Any]) -> dict[str, Any]:
        return {**{key: record[key] for key in ("record_id", "kind", "scope", "confirmation", "updated_at", "revision")},
                "status": PrivateMemory._effective_status(record)}

    def _public(self, record: dict[str, Any]) -> dict[str, Any]:
        return {**self._summary(record), "content": record["content"], "source_refs": list(record["source_refs"]),
                "created_at": record["created_at"], "expires_at": record["expires_at"]}

    @staticmethod
    def _receipt(record: dict[str, Any]) -> dict[str, Any]:
        return {"record_id": record["record_id"], "revision": record["revision"], "status": PrivateMemory._effective_status(record),
                "confirmation": record["confirmation"], "scope_ref": record["scope"]["kind"] + ":" + record["subject_id"]}

    def _envelope(self, items: list[dict[str, Any]], next_offset: int, total: int, query: str, filters: dict[str, Any] | None,
                  principal: "KnowledgePrincipal", revision: str) -> dict[str, Any]:
        cursor = "" if next_offset >= total else self._make_cursor(next_offset, query, filters, principal, revision)
        return {"items": items, "next_cursor": cursor, "scope_ref": "private:" + principal.subject_id, "revision": revision,
                "as_of": self._now(), "status": "ok"}

    @staticmethod
    def _digest(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _revision(self, state: dict[str, Any]) -> str:
        return self._digest({key: self._summary(value) for key, value in state["records"].items()})[:16]

    def _make_cursor(self, offset: int, query: str, filters: dict[str, Any] | None, principal: "KnowledgePrincipal", revision: str) -> str:
        return json.dumps({"o": offset, "q": query, "f": filters or {}, "s": self._principal_scope(principal), "r": revision}, sort_keys=True).encode().hex()

    def _cursor(self, cursor: str, query: str, filters: dict[str, Any] | None, principal: "KnowledgePrincipal", revision: str) -> int:
        if not cursor:
            return 0
        try:
            payload = json.loads(bytes.fromhex(cursor))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid cursor") from exc
        if payload != {"o": payload.get("o"), "q": query, "f": filters or {}, "s": self._principal_scope(principal), "r": revision} or not isinstance(payload["o"], int):
            raise ValueError("cursor does not belong to this scope")
        return payload["o"]

    @staticmethod
    def _principal_scope(principal: "KnowledgePrincipal") -> dict[str, Any]:
        return {"subject_id": principal.subject_id, "project_ids": sorted(principal.project_ids),
                "session_ids": sorted(principal.session_ids), "run_ids": sorted(principal.run_ids)}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _expiry(value: Any, *, required: bool) -> str:
        if not value:
            if required:
                raise ValueError("expires_at is required for session/run scope")
            return ""
        if not isinstance(value, str):
            raise ValueError("expires_at must be an RFC3339 timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("expires_at must be an RFC3339 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _effective_status(record: dict[str, Any]) -> str:
        expires = record.get("expires_at", "")
        if record.get("status") == "active" and expires:
            try:
                if datetime.fromisoformat(expires).astimezone(timezone.utc) <= datetime.now(timezone.utc):
                    return "expired"
            except ValueError:
                return "expired"
        return record["status"]

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"records": {}, "idempotency": {}, "tombstones": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, state: dict[str, Any]) -> None:
        fd, temp = tempfile.mkstemp(prefix=".private-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    class _State:
        def __init__(self, owner: "PrivateMemory", read_only: bool) -> None: self.owner, self.read_only, self.file = owner, read_only, None
        def __enter__(self):
            self.owner.lock_path.touch(exist_ok=True); self.file = self.owner.lock_path.open("r+")
            fcntl.flock(self.file.fileno(), fcntl.LOCK_SH if self.read_only else fcntl.LOCK_EX); self.state = self.owner._load(); return self.state
        def __exit__(self, *args):
            if not self.read_only and args[0] is None: self.owner._save(self.state)
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN); self.file.close()

    def _locked_state(self, read_only: bool = False) -> "PrivateMemory._State": return self._State(self, read_only)
