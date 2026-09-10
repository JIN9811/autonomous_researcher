"""Content-addressed source library with immutable extraction and publication artifacts."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import unicodedata
from collections import Counter
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml

from knowledge.ontology import OntologyRegistry
from knowledge.source_extraction import MAX_BLOCKS, MAX_SOURCE_BYTES, extract_source, source_format


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ID = re.compile(r"source-[0-9a-f]{64}\Z")
_RECORD_ID = re.compile(r"record-[0-9a-f]{64}\Z")
_CATEGORY = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
_STATUSES = frozenset(
    {"discovered", "extracted", "processing", "ready", "needs_review", "failed", "missing"}
)
_SCOPE_FIELDS = frozenset(
    {"source_id", "category", "ontology_type", "status", "tags", "applicability"}
)
_NOTE_FIELDS = frozenset(
    {"title", "body", "category", "ontology_type", "tags", "applicability", "source_block_ids"}
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
MAX_AUDIT_EVENT_BYTES = 4_096
MAX_AUDIT_TRACE_EVENTS = 7 * MAX_BLOCKS + 65
MAX_AUDIT_TRACE_BYTES = 128 * 1024 * 1024


class PublicationValidationError(ValueError):
    """A model-authored note can be corrected without retrying storage writes."""


def _synchronized(method: Any) -> Any:
    @wraps(method)
    def locked(self: "SourceLibrary", *args: Any, **kwargs: Any) -> Any:
        with self._mutex:
            return method(self, *args, **kwargs)

    return locked


class SourceLibrary:
    def __init__(self, root: Path, inbox: Path):
        self.root = Path(root).resolve()
        self.inbox = Path(inbox).resolve()
        if self.root == self.inbox or self.root.is_relative_to(self.inbox):
            raise ValueError("source library output must not be inside its inbox")
        self.root.mkdir(parents=True, exist_ok=True)
        self.inbox.mkdir(parents=True, exist_ok=True)
        self._sources_root = self._contained(self.root / "sources")
        self._sources_root.mkdir(parents=True, exist_ok=True)
        self._catalog_path = self._contained(self.root / "catalog.json")
        self._lock_path = self._contained(self.root / ".library.lock")
        self._ontology = OntologyRegistry.load_default(_PROJECT_ROOT)
        self._mutex = threading.RLock()

    @_synchronized
    def scan(self) -> dict:
        with self._file_lock(exclusive=True):
            catalog = self._load_catalog()
            discovered: dict[str, dict[str, Any]] = {}
            errors: list[str] = []
            for path in sorted(self.inbox.rglob("*")):
                relative = path.relative_to(self.inbox).as_posix()
                if path.is_symlink():
                    errors.append(f"{relative}: symlinks are not accepted")
                    continue
                if not path.is_file():
                    continue
                try:
                    format_name = source_format(path)
                    if path.stat().st_size > MAX_SOURCE_BYTES:
                        raise ValueError(f"source exceeds maximum size {MAX_SOURCE_BYTES}")
                    digest = _sha256_file(path)
                except (OSError, ValueError) as exc:
                    errors.append(f"{relative}: {exc}")
                    continue
                discovered[relative] = {
                    "path": path,
                    "sha256": digest,
                    "format": format_name,
                }

            observations = catalog["observations"]
            live_paths = set(discovered)
            for stale in set(observations) - live_paths:
                del observations[stale]
            for relative, item in discovered.items():
                prior = observations.get(relative, {})
                stable_count = int(prior.get("stable_count", 0)) + 1 if prior.get("sha256") == item["sha256"] else 1
                observations[relative] = {
                    "sha256": item["sha256"],
                    "format": item["format"],
                    "stable_count": min(stable_count, 2),
                }

            sources = catalog["sources"]
            for source in sources.values():
                source["current_paths"] = []
                source["current"] = False
            for relative, item in discovered.items():
                source_id = f"source-{item['sha256']}"
                stable = observations[relative]["stable_count"] >= 2
                if source_id not in sources and not stable:
                    continue
                if source_id not in sources:
                    try:
                        sources[source_id] = self._admit_source(
                            source_id,
                            item["sha256"],
                            item["format"],
                            relative,
                            item["path"],
                        )
                    except (OSError, ValueError) as exc:
                        errors.append(f"{relative}: source changed during admission: {exc}")
                        observations[relative]["stable_count"] = 1
                        continue
                source = sources[source_id]
                source["paths"] = sorted(set(source.get("paths", [])) | {relative})
                source["current_paths"] = sorted(set(source["current_paths"]) | {relative})
                source["current"] = True
                if source["status"] == "missing":
                    source["status"] = source.pop("last_status", "discovered")

            for source in sources.values():
                if not source["current"] and source["status"] != "missing":
                    source["last_status"] = source["status"]
                    source["status"] = "missing"
                self._write_manifest(source)
            catalog["errors"] = errors
            self._write_catalog(catalog)
            public = [self._public_source(item) for _, item in sorted(sources.items())]
            pending = [
                item["source_id"]
                for item in public
                if item["current"] and item["status"] == "discovered"
            ]
            return {"sources": public, "pending_ids": pending, "errors": errors}

    @_synchronized
    def extract(self, source_id: str) -> dict:
        with self._file_lock(exclusive=True):
            catalog = self._load_catalog()
            source = self._get_source(catalog, source_id)
            if not source.get("current"):
                raise ValueError("source is not current")
            source_dir = self._source_dir(source_id)
            original = self._original_path(source)
            if _sha256_file(original) != source["sha256"]:
                raise ValueError("immutable source snapshot hash mismatch")
            extraction_id = f"extraction-{source['sha256']}-pages-v3"
            extraction_dir = self._contained(source_dir / "extractions" / extraction_id)
            try:
                if extraction_dir.exists():
                    pinned = (
                        source.get("extraction_id") == extraction_id
                        and isinstance(source.get("extraction_manifest_sha256"), str)
                    )
                    if pinned:
                        result = self._load_extraction(source, extraction_dir)
                    else:
                        orphan = Path(
                            tempfile.mkdtemp(prefix=".orphan-", dir=extraction_dir.parent)
                        )
                        orphan.rmdir()
                        os.replace(extraction_dir, orphan)
                if not extraction_dir.exists():
                    extracted = extract_source(
                        original,
                        source_id=source_id,
                        format_name=source["format"],
                    )
                    result = self._write_extraction_atomic(
                        source,
                        extraction_id,
                        extraction_dir,
                        extracted,
                    )
            except Exception as exc:
                source["status"] = "failed"
                source["error"] = f"{type(exc).__name__}: {exc}"
                self._persist_source(catalog, source)
                if isinstance(exc, (OSError, TypeError, ValueError)):
                    raise
                raise ValueError(f"source extraction failed: {type(exc).__name__}") from exc
            source["extraction_id"] = extraction_id
            source["extraction_manifest_sha256"] = result.pop(
                "_extraction_manifest_sha256"
            )
            next_status = source["status"] if source["status"] in {"ready", "needs_review"} else "extracted"
            source["status"] = next_status
            source["error"] = ""
            self._persist_source(catalog, source)
            return {**result, "status": next_status}

    @_synchronized
    def inspect(self, source_id: str, *, offset: int = 0, limit: int = 8) -> dict:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 64:
            raise ValueError("limit must be between 1 and 64")
        with self._file_lock(exclusive=False):
            catalog = self._load_catalog()
            source = self._get_source(catalog, source_id)
            extraction = self._current_extraction(source)
            blocks = extraction["blocks"]
            selected = blocks[offset : offset + limit]
            next_offset = offset + len(selected)
            return {
                "source_id": source_id,
                "blocks": selected,
                "total_blocks": len(blocks),
                "offset": offset,
                "next_offset": next_offset if next_offset < len(blocks) else None,
                "ontology_types": sorted(self._ontology.class_names),
                "note_schema": {
                    "title": "non-empty string",
                    "body": "concise Markdown grounded in cited blocks",
                    "category": (
                        "1-80 characters matching ^[a-z0-9][a-z0-9-]{0,79}$; "
                        "use hyphens, for example material-properties"
                    ),
                    "ontology_type": "one of ontology_types",
                    "tags": "list of strings",
                    "applicability": "object preserving source conditions",
                    "source_block_ids": "non-empty list of inspected block IDs",
                },
            }

    @_synchronized
    def validate_notes(self, source_id: str, notes: list[dict]) -> dict:
        """Validate grounded notes without writing or changing source state."""
        with self._file_lock(exclusive=False):
            catalog = self._load_catalog()
            source = self._get_source(catalog, source_id)
            self._assert_source_unchanged(source)
            extraction = self._current_extraction(source)
            block_map = {item["block_id"]: item for item in extraction["blocks"]}
            try:
                records = self._validate_notes(source, notes, block_map)
            except (TypeError, ValueError) as exc:
                raise PublicationValidationError(str(exc)) from exc
            return {"source_id": source_id, "records": records}

    @_synchronized
    def stage_notes(self, source_id: str, notes: list[dict], *, stage_key: str) -> dict:
        """Persist validated intermediate notes outside retrieval publications."""
        if not isinstance(stage_key, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,127}", stage_key
        ):
            raise ValueError("stage_key must be a safe lowercase slug")
        with self._file_lock(exclusive=True):
            catalog = self._load_catalog()
            source = self._get_source(catalog, source_id)
            self._assert_source_unchanged(source)
            extraction = self._current_extraction(source)
            block_map = {item["block_id"]: item for item in extraction["blocks"]}
            try:
                records = self._validate_notes(source, notes, block_map)
            except (TypeError, ValueError) as exc:
                raise PublicationValidationError(str(exc)) from exc
            payload = {
                "source_id": source_id,
                "source_sha256": source["sha256"],
                "stage_key": stage_key,
                "records": records,
            }
            digest = hashlib.sha256(_canonical(payload).encode()).hexdigest()
            stage_id = f"stage-{digest}"
            path = self._contained(
                self._source_dir(source_id)
                / "extractions"
                / source["extraction_id"]
                / "intermediate"
                / stage_key
                / f"{stage_id}.json"
            )
            if not path.exists():
                _write_json_atomic(path, {**payload, "stage_id": stage_id})
            return {
                "source_id": source_id,
                "stage_id": stage_id,
                "stage_key": stage_key,
                "records": records,
                "path": path.as_posix(),
            }

    @_synchronized
    def publish(self, source_id: str, notes: list[dict], *, model: dict, trace: list) -> dict:
        if not isinstance(notes, list) or len(notes) != 1:
            raise PublicationValidationError(
                "final publication notes must contain exactly one entry"
            )
        with self._file_lock(exclusive=True):
            catalog = self._load_catalog()
            source = self._get_source(catalog, source_id)
            self._assert_source_unchanged(source)
            extraction = self._current_extraction(source)
            block_map = {item["block_id"]: item for item in extraction["blocks"]}
            clean_model = self._validate_model(model)
            if not isinstance(trace, list):
                raise TypeError("trace must be a list")
            if len(trace) > MAX_AUDIT_TRACE_EVENTS:
                raise ValueError("trace exceeds maximum event count")
            clean_trace = [
                _finite_json(
                    event,
                    f"trace[{index}]",
                    maximum_bytes=MAX_AUDIT_EVENT_BYTES,
                    maximum_depth=15,
                )
                for index, event in enumerate(trace)
            ]
            clean_trace = _finite_json(
                clean_trace,
                "trace",
                maximum_bytes=MAX_AUDIT_TRACE_BYTES,
                maximum_depth=16,
            )
            try:
                records = self._validate_notes(source, notes, block_map)
            except (TypeError, ValueError) as exc:
                raise PublicationValidationError(str(exc)) from exc
            publication_payload = {
                "source_id": source_id,
                "sha256": source["sha256"],
                "model": clean_model,
                "records": records,
            }
            publication_hash = hashlib.sha256(_canonical(publication_payload).encode()).hexdigest()
            publication_id = f"publication-{publication_hash}"
            publication_dir = self._contained(
                self._source_dir(source_id) / "publications" / publication_id
            )
            for record in records:
                record["path"] = (
                    publication_dir
                    / "notes"
                    / record["category"]
                    / f"{record['record_id']}.md"
                ).as_posix()
            status = "unchanged" if publication_dir.exists() else "published"
            if not publication_dir.exists():
                self._write_publication_atomic(
                    publication_dir,
                    records=records,
                    model=clean_model,
                    trace=clean_trace,
                )
            source["publication_id"] = publication_id
            source["status"] = "ready"
            source["error"] = ""
            self._persist_source(catalog, source)
            return {
                "ok": True,
                "status": status,
                "source_id": source_id,
                "publication_id": publication_id,
                "record_ids": [record["record_id"] for record in records],
                "paths": [record["path"] for record in records],
            }

    @_synchronized
    def mark(self, source_id: str, status: str, *, error: str = "") -> dict:
        if status not in _STATUSES:
            raise ValueError(f"unknown source status: {status}")
        clean_error = _text(error, "error", 4_000, empty=True)
        with self._file_lock(exclusive=True):
            catalog = self._load_catalog()
            source = self._get_source(catalog, source_id)
            if status == "ready" and not source.get("publication_id"):
                raise ValueError("ready status requires a complete publication")
            if not source.get("current") and status != "missing":
                raise ValueError("a missing source cannot be marked current work")
            source["status"] = status
            source["error"] = clean_error
            self._persist_source(catalog, source)
            return self._public_source(source)

    @_synchronized
    def status(self) -> dict:
        with self._file_lock(exclusive=False):
            catalog = self._load_catalog()
            sources = [self._public_source(item) for _, item in sorted(catalog["sources"].items())]
            return {
                "sources": sources,
                "counts": dict(sorted(Counter(item["status"] for item in sources).items())),
                "pending_ids": [
                    item["source_id"]
                    for item in sources
                    if item["current"] and item["status"] == "discovered"
                ],
                "errors": list(catalog.get("errors", [])),
            }

    @_synchronized
    def search(self, query: str, *, scope: dict | None = None, top_k: int = 6) -> dict:
        clean_query = _text(query, "query", 2_000, empty=True)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        clean_scope = self._normalize_scope(scope)
        with self._file_lock(exclusive=False):
            records = self._eligible_records(self._load_catalog())
        ranked: list[tuple[float, str, dict]] = []
        for record in records:
            if not self._matches_scope(record, clean_scope):
                continue
            score = _score(clean_query, record)
            if clean_query and score <= 0:
                continue
            ranked.append((score, record["record_id"], record))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        hits = []
        for score, _, record in ranked[:top_k]:
            hit = {key: value for key, value in record.items() if key not in {"body", "path"}}
            hit["excerpt"] = record["body"][:500]
            hit["score"] = round(score, 6)
            hits.append(hit)
        return {"hits": hits, "scope": clean_scope}

    @_synchronized
    def read(
        self,
        record_id: str,
        *,
        scope: dict | None = None,
        include_source: bool = False,
    ) -> dict:
        if not isinstance(record_id, str) or not _RECORD_ID.fullmatch(record_id):
            raise ValueError("record_id is invalid")
        if not isinstance(include_source, bool):
            raise TypeError("include_source must be a boolean")
        clean_scope = self._normalize_scope(scope)
        with self._file_lock(exclusive=False):
            catalog = self._load_catalog()
            records = self._eligible_records(catalog)
            record = next((item for item in records if item["record_id"] == record_id), None)
            if record is None or not self._matches_scope(record, clean_scope):
                return {"ok": False, "status": "not_found", "record_id": record_id}
            result = dict(record)
            if include_source:
                source = self._get_source(catalog, record["source_id"])
                extraction = self._current_extraction(source)
                result["source_markdown"] = extraction["markdown"]
                result["source_blocks"] = extraction["blocks"]
            return {"ok": True, "status": "found", "record": result}

    def _admit_source(
        self,
        source_id: str,
        digest: str,
        format_name: str,
        relative: str,
        source_path: Path,
    ) -> dict:
        source_dir = self._source_dir(source_id)
        source_dir.mkdir(parents=True, exist_ok=True)
        original = self._contained(source_dir / f"original.{format_name}")
        data = source_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("content hash changed")
        _write_bytes_new(original, data)
        return {
            "source_id": source_id,
            "sha256": digest,
            "paths": [relative],
            "current_paths": [relative],
            "status": "discovered",
            "format": format_name,
            "current": True,
            "error": "",
        }

    def _write_extraction_atomic(
        self,
        source: dict,
        extraction_id: str,
        extraction_dir: Path,
        extracted: dict,
    ) -> dict:
        parent = extraction_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".extraction-", dir=parent))
        try:
            markdown_path = staging / "source.md"
            blocks_path = staging / "blocks.json"
            _write_text(markdown_path, extracted["markdown"])
            _write_json(blocks_path, {"source_id": source["source_id"], "blocks": extracted["blocks"]})
            page_records = []
            for number, text in enumerate(extracted["pages"], start=1):
                relative = f"pages/page-{number:04d}.md"
                _write_text(staging / relative, text)
                page_records.append(
                    {
                        "page": number,
                        "path": relative,
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "block_ids": [
                            block["block_id"]
                            for block in extracted["blocks"]
                            if block["page"] == number
                        ],
                    }
                )
            _write_json(
                staging / "pages.json",
                {"source_id": source["source_id"], "pages": page_records},
            )
            artifacts = {
                path.relative_to(staging).as_posix(): _sha256_file(path)
                for path in sorted(staging.rglob("*"))
                if path.is_file()
            }
            _write_json(
                staging / "extraction.json",
                {
                    "schema": "source_extraction.v1",
                    "source_id": source["source_id"],
                    "source_sha256": source["sha256"],
                    "artifacts": artifacts,
                },
            )
            manifest_sha256 = _sha256_file(staging / "extraction.json")
            os.replace(staging, extraction_dir)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return {
            "source_id": source["source_id"],
            "sha256": source["sha256"],
            "markdown": extracted["markdown"],
            "blocks": extracted["blocks"],
            "pages": page_records,
            "path": (extraction_dir / "source.md").as_posix(),
            "_extraction_manifest_sha256": manifest_sha256,
        }

    def _load_extraction(self, source: dict, extraction_dir: Path) -> dict:
        markdown_path = self._contained(extraction_dir / "source.md")
        blocks_path = self._contained(extraction_dir / "blocks.json")
        manifest_path = self._contained(extraction_dir / "extraction.json")
        expected_manifest_hash = source.get("extraction_manifest_sha256")
        actual_manifest_hash = _sha256_file(manifest_path)
        if expected_manifest_hash != actual_manifest_hash:
            raise ValueError("stored extraction manifest hash mismatch")
        manifest = _read_json(manifest_path)
        if (
            manifest.get("schema") != "source_extraction.v1"
            or manifest.get("source_id") != source["source_id"]
            or manifest.get("source_sha256") != source["sha256"]
            or not isinstance(manifest.get("artifacts"), dict)
        ):
            raise ValueError("stored extraction identity is invalid")
        for relative, digest in manifest["artifacts"].items():
            if not isinstance(relative, str) or not isinstance(digest, str):
                raise ValueError("stored extraction artifact identity is invalid")
            artifact = self._contained(extraction_dir / relative)
            if not artifact.is_relative_to(extraction_dir) or _sha256_file(artifact) != digest:
                raise ValueError("stored extraction artifact hash mismatch")
        payload = _read_json(blocks_path)
        pages_payload = _read_json(self._contained(extraction_dir / "pages.json"))
        blocks = payload.get("blocks")
        pages = pages_payload.get("pages")
        if (
            payload.get("source_id") != source["source_id"]
            or pages_payload.get("source_id") != source["source_id"]
            or not isinstance(blocks, list)
            or not isinstance(pages, list)
        ):
            raise ValueError("stored extraction manifest is invalid")
        expected_artifacts = {"source.md", "blocks.json", "pages.json"}
        expected_artifacts.update(str(page.get("path")) for page in pages)
        if set(manifest["artifacts"]) != expected_artifacts:
            raise ValueError("stored extraction artifact identity is invalid")
        for ordinal, block in enumerate(blocks):
            if not isinstance(block, dict) or set(block) != {"block_id", "text", "page"}:
                raise ValueError("stored block identity is invalid")
            if not isinstance(block["text"], str) or not isinstance(block["page"], int):
                raise ValueError("stored block identity is invalid")
            identity = (
                f"{source['source_id']}\0{ordinal}\0{block['page']}\0{block['text']}"
            )
            expected = f"block-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
            if block["block_id"] != expected:
                raise ValueError("stored block identity is invalid")
        for number, page in enumerate(pages, start=1):
            expected_path = f"pages/page-{number:04d}.md"
            if (
                not isinstance(page, dict)
                or set(page) != {"page", "path", "sha256", "block_ids"}
                or page["page"] != number
                or page["path"] != expected_path
            ):
                raise ValueError("stored page identity is invalid")
            page_path = self._contained(extraction_dir / expected_path)
            if _sha256_file(page_path) != page["sha256"]:
                raise ValueError("stored page hash mismatch")
            expected_ids = [
                block["block_id"] for block in blocks if block["page"] == number
            ]
            if page["block_ids"] != expected_ids:
                raise ValueError("stored page block identity is invalid")
        return {
            "source_id": source["source_id"],
            "sha256": source["sha256"],
            "markdown": markdown_path.read_text(encoding="utf-8"),
            "blocks": blocks,
            "pages": pages,
            "path": markdown_path.as_posix(),
            "_extraction_manifest_sha256": actual_manifest_hash,
        }

    def _current_extraction(self, source: dict) -> dict:
        extraction_id = source.get("extraction_id")
        if not isinstance(extraction_id, str) or not extraction_id.startswith("extraction-"):
            raise ValueError("source has not been extracted")
        directory = self._contained(self._source_dir(source["source_id"]) / "extractions" / extraction_id)
        return self._load_extraction(source, directory)

    def _validate_notes(self, source: dict, notes: Any, blocks: Mapping[str, dict]) -> list[dict]:
        if not isinstance(notes, list) or not 1 <= len(notes) <= 64:
            raise ValueError("notes must contain between 1 and 64 entries")
        records: list[dict] = []
        seen: set[str] = set()
        for note in notes:
            if not isinstance(note, dict) or set(note) != _NOTE_FIELDS:
                raise ValueError("each note must contain the exact source note fields")
            title = _text(note["title"], "title", 300)
            body = _text(note["body"], "body", 65_536, byte_limit=True)
            category = _text(note["category"], "category", 80)
            if not _CATEGORY.fullmatch(category):
                raise ValueError("category must be a safe lowercase slug")
            ontology_type = _text(note["ontology_type"], "ontology_type", 128)
            if ontology_type not in self._ontology.class_names:
                raise ValueError("unknown ontology_type")
            tags = _string_list(note["tags"], "tags", 32, 100)
            applicability = _finite_json(note["applicability"], "applicability", 16_384)
            if not isinstance(applicability, dict):
                raise TypeError("applicability must be a mapping")
            block_ids = _string_list(
                note["source_block_ids"], "source_block_ids", MAX_BLOCKS, 80
            )
            if not block_ids or any(block_id not in blocks for block_id in block_ids):
                raise ValueError("source_block_ids must reference existing source blocks")
            citations = [
                {
                    "source_id": source["source_id"],
                    "block_id": block_id,
                    "page": blocks[block_id]["page"],
                    "source_ref": f"source:{source['source_id']}#{block_id}",
                }
                for block_id in block_ids
            ]
            source_refs = [item["source_ref"] for item in citations]
            content = {
                "source_id": source["source_id"],
                "source_sha256": source["sha256"],
                "title": title,
                "body": body,
                "category": category,
                "ontology_type": ontology_type,
                "tags": tags,
                "applicability": applicability,
                "source_block_ids": block_ids,
                "source_refs": source_refs,
                "citations": citations,
                "status": "ready",
            }
            record_id = f"record-{hashlib.sha256(_canonical(content).encode()).hexdigest()}"
            if record_id in seen:
                raise ValueError("duplicate note content")
            seen.add(record_id)
            content["record_id"] = record_id
            content["path"] = ""
            records.append(content)
        return records

    def _write_publication_atomic(
        self,
        publication_dir: Path,
        *,
        records: list[dict],
        model: dict,
        trace: list,
    ) -> None:
        publication_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".publication-", dir=publication_dir.parent))
        try:
            stored: list[dict] = []
            for record in records:
                path = staging / "notes" / record["category"] / f"{record['record_id']}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                final_path = publication_dir / path.relative_to(staging)
                complete = {**record, "path": final_path.as_posix()}
                _write_text(path, _record_markdown(complete))
                stored.append(complete)
                record["path"] = final_path.as_posix()
            _write_json(staging / "records.json", {"records": stored})
            _write_json(staging / "model.json", model)
            _write_json(staging / "trace.json", trace)
            os.replace(staging, publication_dir)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def _eligible_records(self, catalog: dict) -> list[dict]:
        records: list[dict] = []
        for source in catalog["sources"].values():
            if source.get("status") != "ready" or source.get("current") is not True:
                continue
            publication_id = source.get("publication_id")
            if not isinstance(publication_id, str):
                continue
            path = self._contained(self._source_dir(source["source_id"]) / "publications" / publication_id / "records.json")
            payload = _read_json(path)
            value = payload.get("records")
            if not isinstance(value, list):
                raise ValueError("publication records are invalid")
            records.extend(dict(item) for item in value if isinstance(item, dict))
        return records

    def _normalize_scope(self, scope: dict | None) -> dict:
        if scope is None:
            value: dict[str, Any] = {}
        elif isinstance(scope, dict):
            value = dict(scope)
        else:
            raise TypeError("scope must be a mapping or None")
        unknown = set(value) - _SCOPE_FIELDS
        if unknown:
            raise ValueError(f"unknown scope filters: {', '.join(sorted(unknown))}")
        clean: dict[str, Any] = {}
        for field, expected in value.items():
            if field == "applicability":
                result = _finite_json(expected, "scope.applicability", 16_384)
                if not isinstance(result, dict):
                    raise TypeError("scope.applicability must be a mapping")
                clean[field] = result
            elif isinstance(expected, str):
                clean[field] = _text(expected, f"scope.{field}", 256)
            elif isinstance(expected, list):
                clean[field] = _string_list(expected, f"scope.{field}", 256, 256)
            else:
                raise TypeError(f"scope.{field} must be a string or list")
        clean.setdefault("status", "ready")
        return clean

    @staticmethod
    def _matches_scope(record: Mapping[str, Any], scope: Mapping[str, Any]) -> bool:
        for field, expected in scope.items():
            if field == "tags":
                wanted = [expected] if isinstance(expected, str) else expected
                if not wanted or any(item not in record.get("tags", []) for item in wanted):
                    return False
            elif field == "applicability":
                actual = record.get("applicability", {})
                if any(key not in actual or actual[key] != value for key, value in expected.items()):
                    return False
            elif isinstance(expected, list):
                if not expected or record.get(field) not in expected:
                    return False
            elif record.get(field) != expected:
                return False
        return True

    @staticmethod
    def _validate_model(model: Any) -> dict:
        clean = _finite_json(model, "model", 16_384)
        if not isinstance(clean, dict) or not isinstance(clean.get("model"), str) or not clean["model"]:
            raise ValueError("model metadata requires a model identity")
        if clean.get("mock") is True and clean.get("real") is True:
            raise ValueError("mock model output cannot be marked real")
        return clean

    def _assert_source_unchanged(self, source: dict) -> None:
        if not source.get("current") or not source.get("current_paths"):
            raise ValueError("source is missing or no longer current")
        for relative in source["current_paths"]:
            path = self._inbox_path(relative)
            if path.is_file() and not path.is_symlink() and _sha256_file(path) == source["sha256"]:
                return
        raise ValueError("source changed or disappeared during processing")

    def _original_path(self, source: dict) -> Path:
        return self._contained(self._source_dir(source["source_id"]) / f"original.{source['format']}")

    def _inbox_path(self, relative: str) -> Path:
        candidate = (self.inbox / relative).resolve()
        if not candidate.is_relative_to(self.inbox):
            raise ValueError("source alias escapes inbox")
        return candidate

    def _source_dir(self, source_id: str) -> Path:
        if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
            raise ValueError("source_id is invalid")
        return self._contained(self._sources_root / source_id)

    @staticmethod
    def _get_source(catalog: dict, source_id: str) -> dict:
        if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
            raise ValueError("source_id is invalid")
        source = catalog["sources"].get(source_id)
        if not isinstance(source, dict):
            raise KeyError(source_id)
        return source

    @staticmethod
    def _public_source(source: dict) -> dict:
        return {
            "source_id": source["source_id"],
            "sha256": source["sha256"],
            "paths": list(source.get("paths", [])),
            "current_paths": list(source.get("current_paths", [])),
            "status": source["status"],
            "format": source["format"],
            "current": source.get("current") is True,
            "error": str(source.get("error") or ""),
        }

    def _persist_source(self, catalog: dict, source: dict) -> None:
        catalog["sources"][source["source_id"]] = source
        self._write_manifest(source)
        self._write_catalog(catalog)

    def _write_manifest(self, source: dict) -> None:
        _write_json_atomic(self._source_dir(source["source_id"]) / "manifest.json", source)

    def _write_catalog(self, catalog: dict) -> None:
        _write_json_atomic(self._catalog_path, catalog)

    def _load_catalog(self) -> dict:
        if not self._catalog_path.exists():
            return {
                "schema": "source_library_catalog.v1",
                "observations": {},
                "sources": {},
                "errors": [],
            }
        value = _read_json(self._catalog_path)
        if value.get("schema") != "source_library_catalog.v1":
            raise ValueError("source library catalog schema is invalid")
        if not isinstance(value.get("observations"), dict) or not isinstance(value.get("sources"), dict):
            raise ValueError("source library catalog is invalid")
        return value

    def _contained(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("path escapes source library root")
        return resolved

    @contextmanager
    def _file_lock(self, *, exclusive: bool) -> Iterator[None]:
        with self._lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _record_markdown(record: dict) -> str:
    frontmatter = {key: value for key, value in record.items() if key not in {"body", "path"}}
    header = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{header}\n---\n\n{record['body']}\n"


def _score(query: str, record: Mapping[str, Any]) -> float:
    if not query:
        return 0.0
    normalized = unicodedata.normalize("NFKC", query).casefold()
    title = unicodedata.normalize("NFKC", str(record.get("title", ""))).casefold()
    body = unicodedata.normalize("NFKC", str(record.get("body", ""))).casefold()
    metadata = _canonical(
        {
            "category": record.get("category"),
            "ontology_type": record.get("ontology_type"),
            "tags": record.get("tags"),
            "applicability": record.get("applicability"),
        }
    ).casefold()
    score = 8.0 if normalized in title else 4.0 if normalized in body else 0.0
    for token in _TOKEN.findall(normalized):
        score += title.count(token) * 3 + body.count(token) * 1.5 + metadata.count(token) * 0.5
    return score


def _text(
    value: Any,
    field: str,
    maximum: int,
    *,
    empty: bool = False,
    byte_limit: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    clean = unicodedata.normalize("NFKC", value).strip()
    if not empty and not clean:
        raise ValueError(f"{field} must not be empty")
    size = len(clean.encode("utf-8")) if byte_limit else len(clean)
    if size > maximum:
        raise ValueError(f"{field} exceeds maximum length {maximum}")
    if any(ord(character) < 32 and character not in "\n\t" for character in clean):
        raise ValueError(f"{field} contains control characters")
    return clean


def _string_list(value: Any, field: str, maximum_items: int, maximum_length: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ValueError(f"{field} must be a bounded list")
    result: list[str] = []
    for item in value:
        clean = _text(item, field, maximum_length)
        if clean not in result:
            result.append(clean)
    return result


def _finite_json(
    value: Any,
    field: str,
    maximum_bytes: int,
    *,
    maximum_depth: int = 6,
) -> Any:
    def normalize(item: Any, depth: int) -> Any:
        if depth > maximum_depth:
            raise ValueError(f"{field} exceeds maximum nesting depth")
        if item is None or isinstance(item, (str, bool, int)):
            if isinstance(item, str) and len(item) > 1_000_000:
                raise ValueError(f"{field} string is too large")
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"{field} contains a non-finite number")
            return item
        if isinstance(item, list):
            return [normalize(child, depth + 1) for child in item]
        if isinstance(item, dict):
            if any(not isinstance(key, str) or not key for key in item):
                raise ValueError(f"{field} contains an invalid key")
            return {key: normalize(child, depth + 1) for key, child in item.items()}
        raise TypeError(f"{field} must be JSON-compatible")

    clean = normalize(value, 0)
    if len(_canonical(clean).encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{field} exceeds maximum serialized size {maximum_bytes}")
    return clean


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _write_bytes_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError("immutable artifact already exists with different content")
    finally:
        temporary.unlink(missing_ok=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
