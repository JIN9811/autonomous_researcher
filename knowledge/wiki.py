"""Reviewed, file-backed public AX4LAB Wiki corpus."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_ALIASES = {"플랫폼": "platform", "에이전트": "agent", "역할": "role", "사용법": "usage", "지식": "knowledge",
            "디자인": "design", "매니퓰레이션": "manipulation", "놀리지": "knowledge", "오케스트레이터": "orchestrator",
            "스페시먼": "specimen", "비전": "vision", "가디언": "guardian", "분석": "analysis", "장비": "equipment"}
_KOREAN_ALIAS_PARTICLES = ("으로부터", "에게서", "에서는", "으로", "까지", "부터", "보다", "처럼", "에게", "에서",
                            "은", "는", "이", "가", "을", "를", "과", "와", "도", "로", "에", "의", "만")


class WikiCatalog:
    """Small, deterministic public corpus; it never scans outside wiki pages."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        preferred = self.project_root / "docs" / "knowledge" / "wiki"
        bundled_project = Path(__file__).resolve().parents[1]
        self.root = preferred if preferred.exists() else bundled_project / "docs" / "knowledge" / "wiki"
        self.source_root = self.project_root if preferred.exists() else bundled_project

    def query(self, query: str, *, filters: dict[str, Any] | None = None, cursor: str = "", limit: int = 25) -> dict[str, Any]:
        clean_limit = self._limit(limit)
        documents = self._documents(filters)
        query_terms = self._terms(query)
        ranked = [(self._score(query_terms, doc, query), doc)
                  for doc in documents]
        if query_terms:
            ranked = [item for item in ranked if item[0]]
        ranked.sort(key=lambda item: (-item[0], item[1]["topic_id"]))
        offset = self._cursor(cursor, query, filters, self.revision())
        selected = [self._summary(doc) for _, doc in ranked[offset:offset + clean_limit]]
        return self._envelope(selected, offset + len(selected), len(ranked), query, filters)

    def read(self, record_id: str, *, filters: dict[str, Any] | None = None) -> dict[str, Any] | None:
        for doc in self._documents(filters):
            if doc["record_id"] == record_id or doc["topic_id"] == record_id:
                return {**self._summary(doc), "content": doc["content"]}
        return None

    def reindex(self) -> dict[str, Any]:
        """Validate the reviewed corpus. There is no model, device, Git or network work."""
        docs = self._documents(None)
        return {"status": "ok", "records": len(docs), "revision": self.revision(), "model_used": False,
                "device_used": False, "git_used": False}

    def count(self) -> int:
        return len(self._documents(None))

    def revision(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.root.glob("*.md")):
            if path.is_symlink():
                continue
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
            # Source hashes and their fresh/stale relationship are part of the
            # observable catalog semantics, so cursor/cache revisions include them.
            document = self._parse(path)
            digest.update(document["freshness"].encode())
            digest.update(json.dumps(document["source_revision"], sort_keys=True).encode())
            for source in document["source_refs"]:
                candidate = (self.source_root / source).resolve()
                digest.update(source.encode())
                digest.update(hashlib.sha256(candidate.read_bytes()).digest())
        return digest.hexdigest()[:16]

    def _documents(self, filters: dict[str, Any] | None) -> list[dict[str, Any]]:
        if filters and set(filters) - {"topic_id", "status"}:
            raise ValueError("unsupported Wiki filters")
        docs: list[dict[str, Any]] = []
        root = self.root.resolve()
        for path in sorted(root.glob("*.md")):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            parsed = self._parse(path)
            if filters and filters.get("topic_id") and parsed["topic_id"] != filters["topic_id"]:
                continue
            if filters and filters.get("status") and parsed["status"] != filters["status"]:
                continue
            docs.append(parsed)
        return docs

    def _parse(self, path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            raise ValueError("Wiki page lacks reviewed metadata")
        _, front, content = raw.split("---\n", 2)
        metadata = json.loads(front)
        required = {"topic_id", "owner", "source_refs", "source_revision", "verified_at", "applicability", "status"}
        if set(metadata) < required or metadata["status"] != "reviewed":
            raise ValueError("Wiki page is not reviewed")
        source_refs = metadata["source_refs"]
        if not isinstance(source_refs, list) or not source_refs:
            raise ValueError("Wiki page has no source reference")
        hashes: dict[str, str] = {}
        for source in source_refs:
            candidate = (self.source_root / source).resolve()
            if candidate.is_symlink() or not candidate.is_relative_to(self.source_root) or not candidate.is_file():
                raise ValueError("Wiki source is unavailable")
            hashes[source] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        expected = metadata["source_revision"]
        freshness = "fresh" if isinstance(expected, dict) and expected == hashes else "stale"
        return {"record_id": "wiki:" + metadata["topic_id"], "topic_id": metadata["topic_id"], "owner": metadata["owner"],
                "source_refs": source_refs, "source_revision": expected, "verified_at": metadata["verified_at"],
                "applicability": metadata["applicability"], "status": metadata["status"], "freshness": freshness,
                "title": next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), metadata["topic_id"]),
                "content": content.strip()}

    def _summary(self, document: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in document.items() if key not in {"content", "title"}}

    def _envelope(self, items: list[dict[str, Any]], next_offset: int, total: int, query: str, filters: dict[str, Any] | None) -> dict[str, Any]:
        revision = self.revision()
        cursor = "" if next_offset >= total else self._make_cursor(next_offset, query, filters, revision)
        return {"items": items, "next_cursor": cursor, "scope_ref": "ax4lab_wiki", "revision": revision,
                "as_of": datetime.now(timezone.utc).isoformat(), "status": "ok"}

    @staticmethod
    def _terms(value: str) -> set[str]:
        if not isinstance(value, str) or len(value) > 2_000:
            raise ValueError("query must be a bounded string")
        lowered = value.lower()
        terms = set(_TOKEN.findall(lowered))
        aliases = {term for term in terms if term in _ALIASES}
        # Korean role questions attach ordinary particles directly to an alias
        # (for example, ``에이전트의`` and ``역할은``).  Only peel a suffix
        # when the remaining complete token is a known alias: this is not a
        # general stemmer and cannot turn unrelated Korean text into a role.
        for term in terms:
            for particle in _KOREAN_ALIAS_PARTICLES:
                if term.endswith(particle) and term[:-len(particle)] in _ALIASES:
                    aliases.add(term[:-len(particle)])
                    break
        return terms | {_ALIASES[term] for term in aliases}

    @staticmethod
    def _document_terms(value: str) -> set[str]:
        """Document indexing is bounded by reviewed-file policy, not query size."""
        return set(_TOKEN.findall(value.lower()))

    def _score(self, query_terms: set[str], document: dict[str, Any], query: str = "") -> int:
        topic_terms = self._document_terms(document["topic_id"])
        title_terms = self._document_terms(document["title"])
        content_terms = self._document_terms(document["content"])
        score = sum((20 if term in topic_terms else 0) + (10 if term in title_terms else 0) + (1 if term in content_terms else 0) for term in query_terms)
        # Role pages are the concise consumer-facing contract when both an
        # older topical seed and a current per-role page match the same role.
        role_name = document["topic_id"].removesuffix("-role")
        if document["topic_id"].endswith("-role") and role_name in query_terms:
            score += 25
        explicit_topics = {"플랫폼": "platform", "매니퓰레이션": "manipulation", "놀리지": "knowledge"}
        for phrase, topic in explicit_topics.items():
            if phrase in query and topic in topic_terms:
                score += 30
        return score

    @staticmethod
    def _limit(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        return value

    @staticmethod
    def _make_cursor(offset: int, query: str, filters: dict[str, Any] | None, revision: str) -> str:
        payload = json.dumps({"o": offset, "q": query, "f": filters or {}, "r": revision}, sort_keys=True).encode()
        return payload.hex()

    def _cursor(self, cursor: str, query: str, filters: dict[str, Any] | None, revision: str) -> int:
        if not cursor:
            return 0
        try:
            payload = json.loads(bytes.fromhex(cursor))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid cursor") from exc
        if payload != {"o": payload.get("o"), "q": query, "f": filters or {}, "r": revision} or not isinstance(payload["o"], int):
            raise ValueError("cursor does not belong to this scope")
        return payload["o"]
