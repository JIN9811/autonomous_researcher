#!/usr/bin/env python3
"""Validate governed ATR documentation without rewriting prose."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any
from urllib.parse import unquote

import yaml


DOCUMENT_SUBTYPES = {
    "index": {"index"},
    "standard": {"documentation", "repository", "safety", "contract"},
    "reference": {"system", "runtime", "api", "schema", "current_snapshot"},
    "guide": {"tutorial", "how_to", "operations_runbook", "troubleshooting"},
    "design": {"feature", "architecture", "adr"},
    "plan": {"implementation", "migration"},
    "evidence": {"research", "audit", "test_report", "benchmark"},
}
DOCUMENT_STATUSES = {"draft", "review", "active", "superseded", "archived"}
AUTHORITIES = {
    "navigation",
    "normative",
    "descriptive",
    "procedural",
    "proposal",
    "execution",
    "evidentiary",
}
DESIGN_STATUSES = {"proposed", "approved", "rejected", "superseded"}
PLAN_STATUSES = {"planned", "in_progress", "blocked", "completed", "cancelled"}
REQUIRED_FIELDS = {
    "doc_type",
    "subtype",
    "status",
    "authority",
    "audience",
    "scope",
    "summary",
    "related_docs",
    "supersedes",
}
PATH_FIELDS = {
    "source_of_truth",
    "related_docs",
    "supersedes",
    "superseded_by",
    "governing_design",
}
SNAPSHOT_LABELS = {
    "api_routes": "FastAPI APIRoute count",
    "app_routes": "Total app.routes count",
    "graph_nodes": "Graph nodes",
    "graph_edges": "Graph edges",
    "stage_dispatch_edges": "stage_dispatch edges",
}


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Return a leading YAML front matter mapping and Markdown body."""

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing leading YAML front matter")

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        raise ValueError("unterminated YAML front matter")

    loaded = yaml.safe_load("".join(lines[1:closing_index])) or {}
    if not isinstance(loaded, dict):
        raise ValueError("YAML front matter must be a mapping")
    return loaded, "".join(lines[closing_index + 1 :])


def _document_label(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _is_non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _path_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _validate_paths(
    metadata: dict[str, Any], root: Path, label: str
) -> list[str]:
    errors: list[str] = []
    resolved_root = root.resolve()
    for field in PATH_FIELDS:
        value = metadata.get(field)
        if value is not None and not isinstance(value, (str, list)):
            errors.append(f"{label}: {field} must be a path or list of paths")
            continue
        for item in _path_values(value):
            candidate = Path(item)
            if candidate.is_absolute():
                errors.append(f"{label}: absolute {field} path is not allowed: {item}")
                continue
            resolved = (root / candidate).resolve()
            try:
                resolved.relative_to(resolved_root)
            except ValueError:
                errors.append(f"{label}: escaping {field} path is not allowed: {item}")
                continue
            if not resolved.exists():
                errors.append(f"{label}: missing {field} path: {item}")
    return errors


def _markdown_link_targets(body: str) -> list[str]:
    targets: list[str] = []
    for match in re.finditer(r"!?\[[^\]]*\]\(([^)\n]+)\)", body):
        raw = match.group(1).strip()
        if raw.startswith("<") and ">" in raw:
            target = raw[1 : raw.index(">")]
        else:
            target = raw.split(maxsplit=1)[0]
        targets.append(unquote(target))
    return targets


def _validate_local_links(path: Path, body: str, root: Path, label: str) -> list[str]:
    errors: list[str] = []
    resolved_root = root.resolve()
    for target in _markdown_link_targets(body):
        if (
            not target
            or target.startswith(("#", "/"))
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target)
        ):
            continue
        local_part = target.split("#", 1)[0].split("?", 1)[0]
        if not local_part:
            continue
        resolved = (path.parent / local_part).resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            errors.append(f"{label}: escaping local link is not allowed: {target}")
            continue
        if not resolved.exists():
            errors.append(f"{label}: missing local link: {target}")
    return errors


def validate_document(path: Path, root: Path) -> list[str]:
    """Return all governance defects found in one Markdown document."""

    label = _document_label(path, root)
    try:
        metadata, body = split_front_matter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        return [f"{label}: {exc}"]

    errors: list[str] = []
    for field in sorted(REQUIRED_FIELDS):
        if field not in metadata:
            errors.append(f"{label}: missing required field: {field}")

    doc_type = metadata.get("doc_type")
    subtype = metadata.get("subtype")
    status = metadata.get("status")
    authority = metadata.get("authority")

    if doc_type not in DOCUMENT_SUBTYPES:
        errors.append(f"{label}: invalid doc_type: {doc_type}")
    elif subtype not in DOCUMENT_SUBTYPES[doc_type]:
        errors.append(f"{label}: invalid subtype for {doc_type}: {subtype}")
    if status not in DOCUMENT_STATUSES:
        errors.append(f"{label}: invalid status: {status}")
    if authority not in AUTHORITIES:
        errors.append(f"{label}: invalid authority: {authority}")

    for field in ("audience", "scope"):
        if field in metadata and not _is_non_empty_list(metadata[field]):
            errors.append(f"{label}: {field} must be a non-empty list of strings")
    if "summary" in metadata and not (
        isinstance(metadata["summary"], str) and metadata["summary"].strip()
    ):
        errors.append(f"{label}: summary must be a non-empty string")
    for field in ("related_docs", "supersedes"):
        if field in metadata and not isinstance(metadata[field], list):
            errors.append(f"{label}: {field} must be a list")

    if status == "active" and doc_type in {"reference", "guide"}:
        if not _is_non_empty_list(metadata.get("source_of_truth")):
            errors.append(f"{label}: active {doc_type} requires source_of_truth")
        for field in ("last_verified", "verified_against"):
            if not metadata.get(field):
                errors.append(f"{label}: active {doc_type} requires {field}")

    if doc_type == "design" and metadata.get("decision_status") not in DESIGN_STATUSES:
        errors.append(f"{label}: design requires a valid decision_status")
    if doc_type == "plan":
        if metadata.get("execution_status") not in PLAN_STATUSES:
            errors.append(f"{label}: plan requires a valid execution_status")
        if not metadata.get("maintenance_plan") and not metadata.get("governing_design"):
            errors.append(f"{label}: plan requires governing_design or maintenance_plan")
    if doc_type == "evidence":
        for field in ("evidence_date", "method"):
            if not metadata.get(field):
                errors.append(f"{label}: evidence requires {field}")
    if status == "superseded" and not (
        _path_values(metadata.get("supersedes"))
        or _path_values(metadata.get("superseded_by"))
    ):
        errors.append(f"{label}: superseded document requires a replacement path")

    errors.extend(_validate_paths(metadata, root, label))
    errors.extend(_validate_local_links(path, body, root, label))
    return errors


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("manifest must be a YAML mapping")
    return loaded


def _safe_repository_path(root: Path, relative_path: str) -> Path | None:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        return None
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _validate_snapshot(
    root: Path, snapshot: Any, manifest_label: str
) -> list[str]:
    if snapshot is None:
        return []
    if not isinstance(snapshot, dict):
        return [f"{manifest_label}: snapshot must be a mapping"]

    document = snapshot.get("document")
    expected = snapshot.get("expected")
    if not isinstance(document, str) or not document:
        return [f"{manifest_label}: snapshot.document must be a path"]
    if not isinstance(expected, dict):
        return [f"{manifest_label}: snapshot.expected must be a mapping"]

    document_path = _safe_repository_path(root, document)
    if document_path is None:
        return [f"{manifest_label}: unsafe snapshot document path: {document}"]
    if not document_path.is_file():
        return [f"{manifest_label}: missing snapshot document: {document}"]

    body = document_path.read_text(encoding="utf-8")
    errors: list[str] = []
    for key, label in SNAPSHOT_LABELS.items():
        wanted = expected.get(key)
        if not isinstance(wanted, int):
            errors.append(f"{manifest_label}: snapshot.expected.{key} must be an integer")
            continue
        match = re.search(rf"^{re.escape(label)}:\s*(\d+)\s*$", body, re.MULTILINE)
        if match is None:
            errors.append(f"{document}: missing snapshot label: {label}")
            continue
        found = int(match.group(1))
        if found != wanted:
            errors.append(f"{document}: {label}: expected {wanted}, found {found}")
    return errors


def validate_manifest(root: Path, manifest_path: Path) -> list[str]:
    """Validate the governed document set declared by one manifest."""

    label = _document_label(manifest_path, root)
    try:
        manifest = _load_yaml_mapping(manifest_path)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        return [f"{label}: {exc}"]

    errors: list[str] = []
    if manifest.get("version") != 1:
        errors.append(f"{label}: version must be 1")

    documents = manifest.get("documents")
    if not isinstance(documents, list) or not all(
        isinstance(item, str) and item for item in documents
    ):
        errors.append(f"{label}: documents must be a list of repository paths")
        documents = []

    legacy_scope = manifest.get("legacy_scope")
    if not isinstance(legacy_scope, dict) or legacy_scope.get("status") != "migration_debt":
        errors.append(f"{label}: legacy_scope.status must be migration_debt")
    elif not legacy_scope.get("note"):
        errors.append(f"{label}: legacy_scope.note is required")

    for item, count in Counter(documents).items():
        if count > 1:
            errors.append(f"{label}: duplicate document: {item}")

    for item in dict.fromkeys(documents):
        document_path = _safe_repository_path(root, item)
        if document_path is None:
            errors.append(f"{label}: unsafe manifest document path: {item}")
        elif not document_path.is_file():
            errors.append(f"{label}: missing manifest document: {item}")
        else:
            errors.extend(validate_document(document_path, root))

    errors.extend(_validate_snapshot(root, manifest.get("snapshot"), label))
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/document_manifest.yaml"),
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    errors = validate_manifest(root, manifest_path)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("documentation validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
