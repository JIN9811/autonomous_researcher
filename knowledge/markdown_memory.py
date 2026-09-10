"""Ontology-validated, append-only Markdown knowledge memory."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from collections import Counter
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Mapping

import yaml

from knowledge.ontology import OntologyRegistry


_SCHEMA = "knowledge_markdown.v1"
_RECORD_ID = re.compile(r"km-[0-9a-f]{32}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,179}\Z")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_REQUIRED_FIELDS = (
    "run_id",
    "cycle_id",
    "agent_id",
    "event_id",
    "ontology_type",
    "title",
    "body",
    "source_refs",
)
_NOTE_FIELDS = frozenset(
    (*_REQUIRED_FIELDS, "tags", "applicability", "evidence_kind", "fidelity", "status")
)
_PRODUCER_FIELDS = _NOTE_FIELDS - {"status"}
_SCOPE_FIELDS = frozenset(
    (
        "run_id",
        "cycle_id",
        "agent_id",
        "ontology_type",
        "fidelity",
        "status",
        "tags",
        "applicability",
    )
)
_EVIDENCE_KINDS = frozenset(("observed", "derived", "hypothesis"))
_FIDELITIES = frozenset(("measured", "simulated", "virtual", "unknown"))
_STATUSES = frozenset(("valid", "needs_review", "superseded"))
_NON_CONTENT_FIELDS = frozenset(
    ("schema", "record_id", "revision", "content_hash", "ontology_version", "path")
)
_LOADED_FIELDS = _NOTE_FIELDS | _NON_CONTENT_FIELDS | {"lifecycle_reason", "superseded_by"}


def _synchronized(method: Any) -> Any:
    """Keep one shared store's index/cache projection internally consistent."""

    @wraps(method)
    def locked(self: "MarkdownKnowledgeStore", *args: Any, **kwargs: Any) -> Any:
        with self._mutex:
            return method(self, *args, **kwargs)

    return locked


class MarkdownKnowledgeStore:
    """Store small, immutable Markdown revisions and retrieve their latest projection."""

    def __init__(self, root: Path, ontology: OntologyRegistry) -> None:
        self._mutex = RLock()
        self.root = Path(root).resolve()
        self.ontology = ontology
        self.root.mkdir(parents=True, exist_ok=True)
        self._records_root = self._contained(self.root / "records")
        self._locks_root = self._contained(self.root / ".locks")
        self._records_root.mkdir(parents=True, exist_ok=True)
        self._locks_root.mkdir(parents=True, exist_ok=True)
        self._file_cache: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}
        self._latest: dict[str, dict[str, Any]] = {}
        self._index_errors: list[str] = []

    @_synchronized
    def write_note(self, note: dict[str, Any]) -> dict[str, Any]:
        """Append a revision, or return unchanged for an identical event and content."""
        normalized = self._normalize_note(note)
        if normalized["status"] == "superseded":
            raise ValueError("Use set_status with a validated replacement to supersede a note")
        record_id = self._record_id(normalized)
        record_dir = self._record_dir(normalized, record_id)

        with self._record_lock(record_id):
            latest = self._latest_from_directory(record_dir)
            if latest is not None:
                if self._producer_payload(latest) == self._producer_payload(normalized):
                    return self._receipt("unchanged", latest)
                if latest["status"] == "superseded":
                    raise ValueError("Review lifecycle before changing a superseded note")
                normalized["status"] = latest["status"]
                for field in ("lifecycle_reason", "superseded_by"):
                    if field in latest:
                        normalized[field] = latest[field]
            normalized["content_hash"] = self._content_hash(normalized)
            revision = 1 if latest is None else int(latest["revision"]) + 1
            record = self._complete_record(normalized, record_id=record_id, revision=revision)
            path = self._revision_path(record_dir, revision)
            self._write_atomic_new(path, self._serialize(record))
            record["path"] = path.as_posix()
            self._cache_record(path, record)
            return self._receipt("created" if revision == 1 else "updated", record)

    @_synchronized
    def search(
        self,
        query: str,
        *,
        scope: dict[str, Any] | None = None,
        top_k: int = 6,
    ) -> dict[str, Any]:
        """Search latest records after applying a fail-closed exact scope."""
        query_text = self._bounded_text(query, "query", maximum=1_000, allow_empty=True)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be an integer from 1 to 100")
        normalized_scope = self._normalize_scope(scope)
        index_stats = self._refresh_index()

        ranked: list[tuple[float, str, dict[str, Any]]] = []
        for record_id, record in self._latest.items():
            if not self._matches_scope(record, normalized_scope):
                continue
            score = self._search_score(query_text, record)
            if query_text and score <= 0:
                continue
            ranked.append((score, record_id, record))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        hits = [self._search_hit(record, score=score) for score, _, record in ranked[:top_k]]
        return {
            "ok": True,
            "query": query_text,
            "scope": normalized_scope,
            "hits": hits,
            "index": index_stats,
        }

    @_synchronized
    def read_note(self, record_id: str, *, scope: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read a latest record only when it satisfies the same scope used by search."""
        clean_id = self._validate_record_id(record_id)
        normalized_scope = self._normalize_scope(scope)
        self._refresh_index()
        record = self._latest.get(clean_id)
        if record is None or not self._matches_scope(record, normalized_scope):
            return {"ok": False, "status": "not_found", "record_id": clean_id}
        return {"ok": True, "status": "found", "record": self._public_record(record)}

    @_synchronized
    def set_status(
        self,
        record_id: str,
        status: str,
        *,
        reason: str,
        superseded_by: str = "",
    ) -> dict[str, Any]:
        """Append an operator lifecycle revision without altering older revisions."""
        clean_id = self._validate_record_id(record_id)
        clean_status = self._choice(status, "status", _STATUSES)
        clean_reason = self._bounded_text(reason, "reason", maximum=2_000)
        clean_superseded_by = self._bounded_text(
            superseded_by, "superseded_by", maximum=256, allow_empty=True
        )
        if clean_status == "superseded" and not clean_superseded_by:
            raise ValueError("superseded_by is required when status is superseded")
        target_id = ""
        if clean_status == "superseded":
            target_id = self._validate_record_id(clean_superseded_by)
            if target_id == clean_id:
                raise ValueError("a record cannot supersede itself")
        elif clean_superseded_by:
            raise ValueError("superseded_by is only valid when status is superseded")

        with self._record_locks(clean_id, target_id):
            latest = self._latest_from_disk(clean_id)
            if latest is None:
                return {"ok": False, "status": "not_found", "record_id": clean_id}
            if target_id:
                target = self._latest_from_disk(target_id)
                if target is None:
                    raise ValueError("superseded_by target does not exist")
                if target["status"] != "valid":
                    raise ValueError("superseded_by target must be currently valid")
                if target["ontology_type"] != latest["ontology_type"]:
                    raise ValueError("superseded_by target must have the same ontology_type")
                if target["applicability"] != latest["applicability"]:
                    raise ValueError("superseded_by target must have compatible applicability")
            updated = {
                key: value
                for key, value in latest.items()
                if key not in _NON_CONTENT_FIELDS
            }
            updated["status"] = clean_status
            updated["lifecycle_reason"] = clean_reason
            updated["superseded_by"] = clean_superseded_by
            content_hash = self._content_hash(updated)
            if latest["content_hash"] == content_hash:
                receipt = self._receipt("unchanged", latest)
                receipt["record_status"] = clean_status
                return receipt
            revision = int(latest["revision"]) + 1
            record = self._complete_record(
                updated,
                record_id=clean_id,
                revision=revision,
                content_hash=content_hash,
            )
            record_dir = Path(latest["path"]).parent
            path = self._revision_path(record_dir, revision)
            self._write_atomic_new(path, self._serialize(record))
            record["path"] = path.as_posix()
            self._cache_record(path, record)
            receipt = self._receipt("updated", record)
            receipt["record_status"] = clean_status
            return receipt

    @_synchronized
    def status(self) -> dict[str, Any]:
        """Return a lightweight health and latest-record summary."""
        index = self._refresh_index()
        status_counts = dict(
            sorted(Counter(record["status"] for record in self._latest.values()).items())
        )
        return {
            "ok": True,
            "status": "ready",
            "root": self.root.as_posix(),
            "ontology_version": self.ontology.version_id,
            "records": len(self._latest),
            "revisions": len(self._file_cache),
            "status_counts": status_counts,
            "index": index,
        }

    def _normalize_note(self, note: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(note, dict):
            raise TypeError("note must be a dict")
        unknown = set(note) - _NOTE_FIELDS
        if unknown:
            raise ValueError(f"unknown note fields: {', '.join(sorted(unknown))}")
        missing = [field for field in _REQUIRED_FIELDS if field not in note]
        if missing:
            raise ValueError(f"missing required note fields: {', '.join(missing)}")

        normalized: dict[str, Any] = {
            "run_id": self._identifier(note["run_id"], "run_id"),
            "cycle_id": self._identifier(note["cycle_id"], "cycle_id"),
            "agent_id": self._identifier(note["agent_id"], "agent_id"),
            "event_id": self._identifier(note["event_id"], "event_id"),
            "ontology_type": self._bounded_text(
                note["ontology_type"], "ontology_type", maximum=128
            ),
            "title": self._bounded_text(note["title"], "title", maximum=512),
            "body": self._body(note["body"]),
            "source_refs": self._string_list(
                note["source_refs"],
                "source_refs",
                maximum_items=int(self.ontology.maxima.get("artifact_refs", 256)),
                maximum_length=2_048,
            ),
            "tags": self._string_list(
                note.get("tags") or [], "tags", maximum_items=256, maximum_length=128
            ),
            "applicability": self._applicability(note.get("applicability") or {}),
            "evidence_kind": self._choice(
                note.get("evidence_kind") or "derived", "evidence_kind", _EVIDENCE_KINDS
            ),
            "fidelity": self._choice(note.get("fidelity") or "unknown", "fidelity", _FIDELITIES),
            "status": self._choice(note.get("status") or "valid", "status", _STATUSES),
        }
        if not normalized["source_refs"]:
            raise ValueError("source_refs must contain at least one source identity")
        if normalized["ontology_type"] not in self.ontology.class_names:
            raise ValueError(f"unknown ontology_type: {normalized['ontology_type']}")
        return normalized

    def _normalize_scope(self, scope: dict[str, Any] | None) -> dict[str, Any]:
        if scope is None:
            raw: dict[str, Any] = {}
        elif isinstance(scope, dict):
            raw = dict(scope)
        else:
            raise TypeError("scope must be a dict or None")
        unknown = set(raw) - _SCOPE_FIELDS
        if unknown:
            raise ValueError(f"unknown scope filters: {', '.join(sorted(unknown))}")

        normalized: dict[str, Any] = {}
        for field, value in raw.items():
            if field == "applicability":
                normalized[field] = self._applicability(value)
                continue
            if isinstance(value, str):
                normalized[field] = self._bounded_text(value, f"scope.{field}", maximum=256)
                continue
            if isinstance(value, list):
                normalized[field] = self._string_list(
                    value, f"scope.{field}", maximum_items=256, maximum_length=256
                )
                continue
            raise TypeError(f"scope.{field} must be a string or list of strings")
        normalized.setdefault("status", "valid")
        return normalized

    @staticmethod
    def _matches_scope(record: Mapping[str, Any], scope: Mapping[str, Any]) -> bool:
        for field, expected in scope.items():
            if field == "tags":
                wanted = [expected] if isinstance(expected, str) else expected
                if not wanted or any(tag not in record.get("tags", []) for tag in wanted):
                    return False
            elif field == "applicability":
                actual = record.get("applicability", {})
                if any(
                    key not in actual or actual[key] != value for key, value in expected.items()
                ):
                    return False
            elif isinstance(expected, list):
                if not expected or record.get(field) not in expected:
                    return False
            elif record.get(field) != expected:
                return False
        return True

    def _refresh_index(self) -> dict[str, Any]:
        current: dict[Path, tuple[int, int]] = {}
        for path in self._records_root.glob("*/*/*/km-*/revision-*.md"):
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            current[path] = (stat.st_mtime_ns, stat.st_size)

        for path in set(self._file_cache) - set(current):
            del self._file_cache[path]

        parsed = 0
        errors: list[str] = []
        quarantined: set[str] = set()
        for path, stamp in current.items():
            cached = self._file_cache.get(path)
            if cached is not None and cached[0] == stamp:
                continue
            try:
                record = self._parse(path)
                self._validate_loaded_record(record, path)
            except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
                self._file_cache.pop(path, None)
                errors.append(f"{path.as_posix()}: {exc}")
                if _RECORD_ID.fullmatch(path.parent.name):
                    quarantined.add(path.parent.name)
                continue
            self._file_cache[path] = (stamp, record)
            parsed += 1

        latest: dict[str, dict[str, Any]] = {}
        for _, record in self._file_cache.values():
            record_id = record["record_id"]
            if record_id in quarantined:
                continue
            prior = latest.get(record_id)
            if prior is None or int(record["revision"]) > int(prior["revision"]):
                latest[record_id] = record
        self._latest = latest
        self._index_errors = errors
        return {
            "parsed_files": parsed,
            "cached_files": len(self._file_cache),
            "quarantined_records": len(quarantined),
            "errors": list(errors),
        }

    def _latest_from_directory(self, record_dir: Path) -> dict[str, Any] | None:
        paths = sorted(record_dir.glob("revision-*.md")) if record_dir.exists() else []
        if not paths:
            return None
        record = self._parse(paths[-1])
        self._validate_loaded_record(record, paths[-1])
        return record

    def _latest_from_disk(self, record_id: str) -> dict[str, Any] | None:
        paths = sorted(self._records_root.glob(f"*/*/*/{record_id}/revision-*.md"))
        if not paths:
            return None
        record = self._parse(paths[-1])
        self._validate_loaded_record(record, paths[-1])
        return record

    def _record_dir(self, note: Mapping[str, Any], record_id: str) -> Path:
        path = (
            self._records_root
            / str(note["run_id"])
            / str(note["cycle_id"])
            / str(note["agent_id"])
            / record_id
        )
        return self._contained(path)

    def _revision_path(self, record_dir: Path, revision: int) -> Path:
        if revision < 1:
            raise ValueError("revision must be positive")
        return self._contained(record_dir / f"revision-{revision:06d}.md")

    @contextmanager
    def _record_lock(self, record_id: str) -> Iterator[None]:
        with self._record_locks(record_id):
            yield

    @contextmanager
    def _record_locks(self, *record_ids: str) -> Iterator[None]:
        """Acquire record locks in stable order so cross-record lifecycle checks are atomic."""
        lock_ids = sorted({self._validate_record_id(item) for item in record_ids if item})
        handles: list[Any] = []
        try:
            for lock_id in lock_ids:
                path = self._contained(self._locks_root / f"{lock_id}.lock")
                handle = path.open("a+b")
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                handles.append(handle)
            yield
        finally:
            for handle in reversed(handles):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()

    def _write_atomic_new(self, path: Path, text: str) -> None:
        path = self._contained(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"append-only revision already exists: {path}")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".revision-", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists():
                raise FileExistsError(f"append-only revision already exists: {path}")
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _cache_record(self, path: Path, record: dict[str, Any]) -> None:
        stat = path.stat()
        self._file_cache[path] = ((stat.st_mtime_ns, stat.st_size), dict(record))
        prior = self._latest.get(record["record_id"])
        if prior is None or int(record["revision"]) > int(prior["revision"]):
            self._latest[record["record_id"]] = dict(record)

    def _serialize(self, record: Mapping[str, Any]) -> str:
        frontmatter = {key: value for key, value in record.items() if key not in {"body", "path"}}
        header = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip()
        return f"---\n{header}\n---\n\n{record['body']}\n"

    def _parse(self, path: Path) -> dict[str, Any]:
        contained = self._contained(path)
        text = contained.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError("missing Markdown frontmatter")
        raw_header, marker, raw_body = text[4:].partition("\n---\n")
        if not marker:
            raise ValueError("unterminated Markdown frontmatter")
        frontmatter = yaml.safe_load(raw_header)
        if not isinstance(frontmatter, dict):
            raise ValueError("Markdown frontmatter must be a mapping")
        body = raw_body[1:] if raw_body.startswith("\n") else raw_body
        if body.endswith("\n"):
            body = body[:-1]
        record = dict(frontmatter)
        record["body"] = body
        record["path"] = contained.as_posix()
        return record

    def _validate_loaded_record(self, record: Mapping[str, Any], path: Path) -> None:
        unknown = set(record) - _LOADED_FIELDS
        if unknown:
            raise ValueError(f"unknown Markdown record fields: {', '.join(sorted(unknown))}")
        missing = _NOTE_FIELDS - set(record)
        if missing:
            raise ValueError(f"missing Markdown record fields: {', '.join(sorted(missing))}")
        if record.get("schema") != _SCHEMA:
            raise ValueError("unknown Markdown record schema")
        record_id = self._validate_record_id(record.get("record_id"))
        revision = record.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("invalid revision")
        if path.name != f"revision-{revision:06d}.md":
            raise ValueError("revision does not match its path")
        if record.get("ontology_version") != self.ontology.version_id:
            raise ValueError("ontology version mismatch")
        note = {field: record[field] for field in _NOTE_FIELDS}
        normalized = self._normalize_note(note)
        for field, value in normalized.items():
            if record[field] != value:
                raise ValueError(f"Markdown record field is not normalized: {field}")
        if self._record_id(normalized) != record_id:
            raise ValueError("record_id does not match normalized event identity")
        expected_path = self._revision_path(
            self._record_dir(normalized, record_id), int(revision)
        )
        if path.resolve() != expected_path:
            raise ValueError("record directory does not match run/cycle/agent identity")
        has_reason = "lifecycle_reason" in record
        has_target = "superseded_by" in record
        if has_reason != has_target:
            raise ValueError("lifecycle_reason and superseded_by must appear together")
        if has_reason:
            reason = self._bounded_text(
                record["lifecycle_reason"], "lifecycle_reason", maximum=2_000
            )
            target = self._bounded_text(
                record["superseded_by"], "superseded_by", maximum=256, allow_empty=True
            )
            if reason != record["lifecycle_reason"] or target != record["superseded_by"]:
                raise ValueError("lifecycle metadata is not normalized")
            if record["status"] == "superseded":
                if self._validate_record_id(target) == record_id:
                    raise ValueError("a record cannot supersede itself")
            elif target:
                raise ValueError("superseded_by is only valid when status is superseded")
        content_hash = record.get("content_hash")
        if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise ValueError("content_hash is invalid")
        expected_hash = self._content_hash(
            {
                key: value
                for key, value in record.items()
                if key not in _NON_CONTENT_FIELDS
            }
        )
        if record.get("content_hash") != expected_hash:
            raise ValueError("content hash mismatch")

    @staticmethod
    def _producer_payload(record: Mapping[str, Any]) -> dict[str, Any]:
        return {field: record.get(field) for field in _PRODUCER_FIELDS}

    def _complete_record(
        self,
        note: Mapping[str, Any],
        *,
        record_id: str,
        revision: int,
        content_hash: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "schema": _SCHEMA,
            "record_id": record_id,
            "revision": revision,
            **note,
            "content_hash": content_hash or str(note["content_hash"]),
            "ontology_version": self.ontology.version_id,
        }
        # Keep the normative frontmatter keys in a stable human-readable order.
        order = (
            "schema",
            "record_id",
            "revision",
            "run_id",
            "cycle_id",
            "agent_id",
            "event_id",
            "ontology_type",
            "title",
            "tags",
            "applicability",
            "source_refs",
            "evidence_kind",
            "fidelity",
            "status",
            "content_hash",
            "ontology_version",
            "lifecycle_reason",
            "superseded_by",
            "body",
        )
        return {key: record[key] for key in order if key in record}

    @staticmethod
    def _receipt(status: str, record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": status,
            "record_id": record["record_id"],
            "revision": record["revision"],
            "path": record["path"],
        }

    @staticmethod
    def _public_record(record: Mapping[str, Any], *, score: float | None = None) -> dict[str, Any]:
        public = dict(record)
        if score is not None:
            public["score"] = round(score, 6)
        return public

    @staticmethod
    def _search_hit(record: Mapping[str, Any], *, score: float) -> dict[str, Any]:
        hit = {key: value for key, value in record.items() if key != "body"}
        hit["excerpt"] = str(record.get("body", ""))[:500]
        hit["score"] = round(score, 6)
        return hit

    @staticmethod
    def _record_id(note: Mapping[str, Any]) -> str:
        identity = {key: note[key] for key in ("run_id", "cycle_id", "agent_id", "event_id")}
        digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:32]
        return f"km-{digest}"

    @staticmethod
    def _content_hash(note: Mapping[str, Any]) -> str:
        payload = {
            key: value
            for key, value in note.items()
            if key not in _NON_CONTENT_FIELDS
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def _body(self, value: Any) -> str:
        body = self._bounded_text(
            value,
            "body",
            maximum=int(self.ontology.maxima.get("payload_summary_bytes", 65_536)),
            byte_limit=True,
        )
        return body.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _identifier(value: Any, field: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field} must be a string")
        clean = unicodedata.normalize("NFKC", value).strip()
        if not _SAFE_ID.fullmatch(clean):
            raise ValueError(f"{field} must be a safe identifier")
        return clean

    @staticmethod
    def _validate_record_id(value: Any) -> str:
        if not isinstance(value, str) or not _RECORD_ID.fullmatch(value):
            raise ValueError("record_id is invalid")
        return value

    @staticmethod
    def _bounded_text(
        value: Any,
        field: str,
        *,
        maximum: int,
        allow_empty: bool = False,
        byte_limit: bool = False,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field} must be a string")
        clean = unicodedata.normalize("NFKC", value).strip()
        if not allow_empty and not clean:
            raise ValueError(f"{field} must not be empty")
        size = len(clean.encode("utf-8")) if byte_limit else len(clean)
        if size > maximum:
            raise ValueError(f"{field} exceeds maximum length {maximum}")
        if any(ord(character) < 32 and character not in "\n\t" for character in clean):
            raise ValueError(f"{field} contains control characters")
        return clean

    def _string_list(
        self,
        value: Any,
        field: str,
        *,
        maximum_items: int,
        maximum_length: int,
    ) -> list[str]:
        if not isinstance(value, list):
            raise ValueError(f"{field} must be a list of strings")
        if len(value) > maximum_items:
            raise ValueError(f"{field} exceeds maximum item count {maximum_items}")
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            clean = self._bounded_text(item, field, maximum=maximum_length)
            if clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    def _applicability(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("applicability must be a mapping")
        if len(value) > 256:
            raise ValueError("applicability exceeds maximum item count 256")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            clean_key = self._bounded_text(key, "applicability key", maximum=128)
            normalized[clean_key] = _json_value(item, field=f"applicability.{clean_key}", depth=0)
        if len(_canonical_json(normalized).encode("utf-8")) > 16_384:
            raise ValueError("applicability exceeds maximum serialized size 16384")
        return normalized

    @staticmethod
    def _choice(value: Any, field: str, choices: frozenset[str]) -> str:
        if not isinstance(value, str) or value not in choices:
            raise ValueError(f"{field} must be one of: {', '.join(sorted(choices))}")
        return value

    def _contained(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"path escapes Markdown knowledge root: {path}") from exc
        return resolved

    @staticmethod
    def _search_score(query: str, record: Mapping[str, Any]) -> float:
        if not query:
            return 0.0
        normalized_query = unicodedata.normalize("NFKC", query).casefold()
        title = unicodedata.normalize("NFKC", str(record.get("title", ""))).casefold()
        body = unicodedata.normalize("NFKC", str(record.get("body", ""))).casefold()
        metadata = _canonical_json(
            {
                "ontology_type": record.get("ontology_type", ""),
                "tags": record.get("tags", []),
                "applicability": record.get("applicability", {}),
                "source_refs": record.get("source_refs", []),
            }
        ).casefold()
        tokens = _TOKEN.findall(normalized_query)
        score = 0.0
        if normalized_query in title:
            score += 8.0
        if normalized_query in body:
            score += 4.0
        for token in tokens:
            score += title.count(token) * 3.0
            score += body.count(token) * 1.5
            score += metadata.count(token) * 0.5
        return score


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _json_value(value: Any, *, field: str, depth: int) -> Any:
    if depth > 4:
        raise ValueError(f"{field} exceeds maximum nesting depth")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            clean = unicodedata.normalize("NFKC", value).strip()
            if len(clean) > 512:
                raise ValueError(f"{field} exceeds maximum length 512")
            return clean
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field} must be finite")
        return value
    if isinstance(value, list):
        if len(value) > 64:
            raise ValueError(f"{field} exceeds maximum item count 64")
        return [_json_value(item, field=field, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 64:
            raise ValueError(f"{field} exceeds maximum item count 64")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or len(key.strip()) > 128:
                raise ValueError(f"{field} contains an invalid mapping key")
            result[key.strip()] = _json_value(item, field=field, depth=depth + 1)
        return result
    raise TypeError(f"{field} must contain only finite JSON-compatible values")
