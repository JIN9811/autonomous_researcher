"""Provenance helpers for Knowledge Agent records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from knowledge.schemas import ProvenanceRef


def safe_slug(value: str, *, fallback: str = "item") -> str:
    """Return a filesystem/key safe slug."""
    text = str(value or "").strip().lower().replace(" ", "-")
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in text)
    clean = "-".join(part for part in clean.split("-") if part)
    return clean[:120] or fallback


def stable_id(prefix: str, *parts: Any, length: int = 10) -> str:
    """Build a deterministic id from JSON-serializable content."""
    payload = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:length]
    return f"{safe_slug(prefix)}-{digest}"


def compute_artifact_fingerprint(path: str | Path) -> str:
    """Return sha256 for one artifact path, or an empty string if unavailable."""
    try:
        item = Path(path)
        if not item.exists() or not item.is_file():
            return ""
        h = hashlib.sha256()
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def artifact_ref_path(ref: Any) -> str:
    """Extract a path-like string from a runtime artifact reference."""
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        for key in ("path", "artifact_path", "file", "linux_path", "source_ref", "artifact_id"):
            value = ref.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def build_provenance_ref(
    *,
    run_id: str,
    used: list[str] | None = None,
    associated_with: list[str] | None = None,
    derived_from: list[str] | None = None,
    artifact_refs: list[Any] | None = None,
    project_root: Path | None = None,
) -> ProvenanceRef:
    """Build a minimal PROV-like record with artifact hashes when paths are local."""
    used_items = [str(item) for item in (used or []) if str(item)]
    fingerprints: dict[str, str] = {}
    base = project_root or Path.cwd()
    for ref in artifact_refs or []:
        raw = artifact_ref_path(ref)
        if not raw:
            continue
        used_items.append(raw)
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = base / candidate
        digest = compute_artifact_fingerprint(candidate)
        if digest:
            fingerprints[raw] = digest
    derived = [str(item) for item in (derived_from or []) if str(item)] or [run_id]
    return ProvenanceRef(
        used=sorted(set(used_items)),
        was_associated_with=sorted(set(str(item) for item in (associated_with or []) if str(item))),
        was_derived_from=sorted(set(derived)),
        artifact_fingerprints=fingerprints,
    )


def validate_artifact_refs(refs: list[Any], *, project_root: Path | None = None) -> dict[str, Any]:
    """Return simple completeness evidence for artifact references."""
    base = project_root or Path.cwd()
    total = 0
    existing = 0
    missing: list[str] = []
    for ref in refs:
        raw = artifact_ref_path(ref)
        if not raw:
            continue
        total += 1
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = base / candidate
        if candidate.exists():
            existing += 1
        else:
            missing.append(raw)
    coverage = 1.0 if total == 0 else existing / total
    return {"total": total, "existing": existing, "missing": missing, "coverage": round(coverage, 4)}
