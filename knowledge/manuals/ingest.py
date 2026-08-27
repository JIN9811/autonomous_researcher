"""Extract registered PDF manuals into page-aware, citation-safe chunks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from knowledge.manuals.models import ManualChunk, ManualSource


PageExtractor = Callable[[Path], list[str]]
_HEADING_RE = re.compile(
    r"^(?:[IVXLCⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.．]?\s*|\d{1,2}[.．]\s*|[○■▷▶]\s*|WARNING\b)(.+)$",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_]+")


class ManualIngestor:
    def __init__(self, *, page_extractor: PageExtractor | None = None, max_chunk_chars: int = 2200) -> None:
        self.page_extractor = page_extractor or extract_pdf_pages
        self.max_chunk_chars = max(500, int(max_chunk_chars))

    def ingest_registry(self, registry_path: Path, output_root: Path) -> dict[str, Any]:
        output_root.mkdir(parents=True, exist_ok=True)
        receipt_root = output_root / "receipts"
        receipt_root.mkdir(parents=True, exist_ok=True)
        started_at = _now()
        try:
            registry = _load_registry(registry_path)
            sources: list[ManualSource] = []
            chunks: list[ManualChunk] = []
            for raw_source in registry["sources"]:
                source_path = (registry_path.parent / str(raw_source["path"])).resolve()
                if not source_path.is_file():
                    raise FileNotFoundError(f"manual source not found: {source_path}")
                source_hash = _sha256_file(source_path)
                pages = self.page_extractor(source_path)
                if not pages:
                    raise ValueError(f"manual source yielded no text pages: {source_path}")
                source = ManualSource(
                    source_id=str(raw_source["source_id"]),
                    equipment_type=str(raw_source.get("equipment_type") or "").lower(),
                    title=str(raw_source.get("title") or raw_source["source_id"]),
                    path=str(source_path),
                    product=str(raw_source.get("product") or ""),
                    version=str(raw_source.get("version") or ""),
                    source_kind=str(raw_source.get("source_kind") or "manual"),
                    language=str(raw_source.get("language") or "ko"),
                    source_sha256=source_hash,
                    page_count=len(pages),
                )
                if source.equipment_type != "utm":
                    raise ValueError(f"manual source equipment_type must be utm: {source.source_id}")
                sources.append(source)
                chunks.extend(self._chunks_for_source(source, pages))
            if not chunks:
                raise ValueError("manual registry produced no chunks")
            corpus = {
                "schema": "manual_corpus.v1",
                "generated_at": _now(),
                "registry_path": str(registry_path.resolve()),
                "sources": [source.as_dict() for source in sources],
                "chunks": [chunk.as_dict() for chunk in chunks],
            }
            _write_json_atomic(output_root / "corpus.json", corpus)
            receipt = {
                "schema": "manual_ingest_receipt.v1",
                "ok": True,
                "started_at": started_at,
                "completed_at": _now(),
                "source_count": len(sources),
                "chunk_count": len(chunks),
                "source_hashes": {source.source_id: source.source_sha256 for source in sources},
            }
        except Exception as exc:
            receipt = {
                "schema": "manual_ingest_receipt.v1",
                "ok": False,
                "started_at": started_at,
                "completed_at": _now(),
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        _write_json_atomic(receipt_root / f"{_receipt_id()}.json", receipt)
        return receipt

    def _chunks_for_source(self, source: ManualSource, pages: list[str]) -> list[ManualChunk]:
        chunks: list[ManualChunk] = []
        current_section = "Document"
        for page_number, page_text in enumerate(pages, start=1):
            blocks, current_section = _section_blocks(page_text, current_section=current_section)
            for block_number, (section, text) in enumerate(blocks, start=1):
                for part_number, snippet in enumerate(_bounded_chunks(text, self.max_chunk_chars), start=1):
                    chunk_key = f"{source.source_id}\0{page_number}\0{section}\0{block_number}\0{part_number}\0{snippet}"
                    chunk_id = f"manual-chunk:{hashlib.sha256(chunk_key.encode('utf-8')).hexdigest()[:24]}"
                    keywords = tuple(sorted(set(token.lower() for token in _TOKEN_RE.findall(snippet))))
                    chunks.append(
                        ManualChunk(
                            chunk_id=chunk_id,
                            source_id=source.source_id,
                            equipment_type=source.equipment_type,
                            page=page_number,
                            section_path=(section,),
                            text=snippet,
                            source_sha256=source.source_sha256,
                            product=source.product,
                            version=source.version,
                            keywords=keywords,
                        )
                    )
        return chunks


def extract_pdf_pages(path: Path) -> list[str]:
    process = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    pages = process.stdout.replace("\r\n", "\n").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return [page.strip() for page in pages]


def _load_registry(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "manual_source_registry.v1":
        raise ValueError("manual registry schema must be manual_source_registry.v1")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("manual registry requires at least one source")
    seen: set[str] = set()
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("manual registry source must be an object")
        source_id = str(item.get("source_id") or "").strip()
        if not source_id or source_id in seen or not str(item.get("path") or "").strip():
            raise ValueError("manual registry source_id/path must be unique and non-empty")
        seen.add(source_id)
    return payload


def _section_blocks(page_text: str, *, current_section: str) -> tuple[list[tuple[str, str]], str]:
    blocks: list[tuple[str, list[str]]] = []
    section = current_section
    for raw_line in page_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if len(line) <= 110 and _HEADING_RE.match(line):
            section = line
            blocks.append((section, [line]))
        elif blocks:
            blocks[-1][1].append(line)
        else:
            blocks.append((section, [line]))
    return [(name, "\n".join(lines).strip()) for name, lines in blocks if lines], section


def _bounded_chunks(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    paragraphs = [item.strip() for item in text.split("\n") if item.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if current and size + len(paragraph) + 1 > limit:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(paragraph)
        size += len(paragraph) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _receipt_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
