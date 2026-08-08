#!/usr/bin/env python3
"""Validate the paper-first public documentation and claim-evidence package."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml


CLAIM_STATUSES = {
    "supported",
    "partially_supported",
    "not_evaluated",
    "contradicted",
}
EVIDENCE_ENVIRONMENTS = {
    "inspection",
    "test",
    "replay",
    "simulation",
    "browser",
    "live",
}
REQUIRED_ROOT_FILES = (
    "README.md",
    "README.ko.md",
    "CITATION.cff",
    "LICENSE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "REQUIREMENTS.md",
)
REQUIRED_PAPER_FILES = (
    "docs/paper/README.md",
    "docs/paper/01_problem_and_contributions.md",
    "docs/paper/02_system_architecture.md",
    "docs/paper/03_closed_loop_method.md",
    "docs/paper/04_platform_architecture.md",
    "docs/paper/05_experimental_setup.md",
    "docs/paper/06_evaluation_and_results.md",
    "docs/paper/07_reproducibility.md",
    "docs/paper/08_safety_ethics_and_limitations.md",
    "docs/paper/09_claim_evidence_traceability.md",
    "docs/paper/appendix_a_interfaces.md",
    "docs/paper/appendix_b_hardware_and_deployment.md",
    "docs/paper/artifact_manifest.yaml",
)
REQUIRED_EVIDENCE_FIELDS = {
    "id",
    "environment",
    "verified_commit",
    "command",
    "inputs",
    "outputs",
    "result",
}
PERSONAL_PATH_PATTERNS = (
    re.compile(r"/home/[^/\s]+(?:/|\b)"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+(?:\\|\b)"),
)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML mapping or raise a precise schema error."""

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("YAML document must be a mapping")
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duplicate_errors(kind: str, identifiers: list[str]) -> list[str]:
    return [
        f"artifact manifest: duplicate {kind} id {identifier}"
        for identifier, count in Counter(identifiers).items()
        if count > 1
    ]


def _validate_evidence_record(
    root: Path, record: Any, index: int
) -> tuple[list[str], str | None]:
    label = f"artifact manifest evidence[{index}]"
    if not isinstance(record, dict):
        return [f"{label}: must be a mapping"], None

    errors: list[str] = []
    missing = sorted(REQUIRED_EVIDENCE_FIELDS - set(record))
    for field in missing:
        errors.append(f"{label}: missing required field {field}")

    evidence_id = record.get("id")
    if not isinstance(evidence_id, str) or not evidence_id:
        errors.append(f"{label}: id must be a non-empty string")
        evidence_id = None

    environment = record.get("environment")
    if environment not in EVIDENCE_ENVIRONMENTS:
        errors.append(f"{label}: invalid environment {environment}")

    for field in ("verified_commit", "command", "result"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}: {field} must be a non-empty string")

    inputs = record.get("inputs")
    if not isinstance(inputs, list) or not all(
        isinstance(item, str) and item for item in inputs
    ):
        errors.append(f"{label}: inputs must be a list of repository paths")
    else:
        for item in inputs:
            path = _safe_repository_path(root, item)
            if path is None:
                errors.append(f"{label}: unsafe input path {item}")
            elif not path.exists():
                errors.append(f"{label}: missing input path {item}")

    outputs = record.get("outputs")
    if not isinstance(outputs, list):
        errors.append(f"{label}: outputs must be a list")
    else:
        for output_index, output in enumerate(outputs):
            output_label = f"{label}.outputs[{output_index}]"
            if not isinstance(output, dict):
                errors.append(f"{output_label}: must be a mapping")
                continue
            relative_path = output.get("path")
            checksum = output.get("sha256")
            if not isinstance(relative_path, str) or not relative_path:
                errors.append(f"{output_label}: path must be a non-empty string")
                continue
            path = _safe_repository_path(root, relative_path)
            if path is None:
                errors.append(f"{label}: unsafe output path {relative_path}")
                continue
            if not path.is_file():
                errors.append(f"{label}: missing output path {relative_path}")
                continue
            if not isinstance(checksum, str) or not re.fullmatch(
                r"[0-9a-f]{64}", checksum
            ):
                errors.append(f"{output_label}: sha256 must be 64 lowercase hex characters")
            elif _sha256_file(path) != checksum:
                errors.append(f"{output_label}: sha256 mismatch for {relative_path}")

    return errors, evidence_id


def validate_artifact_manifest(root: Path, path: Path) -> list[str]:
    """Return claim-evidence schema and integrity defects."""

    try:
        manifest = load_yaml_mapping(path)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        return [f"artifact manifest: {exc}"]

    errors: list[str] = []
    if manifest.get("version") != 1:
        errors.append("artifact manifest: version must be 1")
    if manifest.get("release_status") not in {"development", "candidate", "released"}:
        errors.append("artifact manifest: invalid release_status")
    if not isinstance(manifest.get("verified_commit"), str):
        errors.append("artifact manifest: verified_commit must be a string")

    evidence_records = manifest.get("evidence")
    if not isinstance(evidence_records, list):
        errors.append("artifact manifest: evidence must be a list")
        evidence_records = []
    evidence_ids: list[str] = []
    for index, record in enumerate(evidence_records):
        record_errors, evidence_id = _validate_evidence_record(root, record, index)
        errors.extend(record_errors)
        if evidence_id is not None:
            evidence_ids.append(evidence_id)
    errors.extend(_duplicate_errors("evidence", evidence_ids))
    known_evidence_ids = set(evidence_ids)

    claims = manifest.get("claims")
    if not isinstance(claims, list):
        errors.append("artifact manifest: claims must be a list")
        claims = []
    claim_ids: list[str] = []
    for index, claim in enumerate(claims):
        label = f"artifact manifest claims[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{label}: must be a mapping")
            continue
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not claim_id:
            errors.append(f"{label}: id must be a non-empty string")
        else:
            claim_ids.append(claim_id)
        status = claim.get("status")
        if status not in CLAIM_STATUSES:
            errors.append(f"{label}: invalid status {status}")
        research_questions = claim.get("research_questions")
        if not isinstance(research_questions, list) or not all(
            isinstance(item, str) and re.fullmatch(r"RQ[1-9][0-9]*", item)
            for item in research_questions
        ):
            errors.append(f"{label}: research_questions must contain RQ identifiers")
        referenced = claim.get("evidence_ids")
        if not isinstance(referenced, list) or not all(
            isinstance(item, str) and item for item in referenced
        ):
            errors.append(f"{label}: evidence_ids must be a list of identifiers")
            referenced = []
        if status in {"supported", "partially_supported"} and not referenced:
            errors.append(f"{label}: supported claim requires evidence_ids")
        for evidence_id in referenced:
            if evidence_id not in known_evidence_ids:
                errors.append(f"{label}: unknown evidence id {evidence_id}")
    errors.extend(_duplicate_errors("claim", claim_ids))
    return errors


def _validate_readme_order(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    system = re.search(r"^##\s+System Contribution\s*$", text, re.MULTILINE)
    platform = re.search(r"^##\s+Platform Contribution\s*$", text, re.MULTILINE)
    errors: list[str] = []
    if system is None:
        errors.append("README.md: missing System Contribution heading")
    if platform is None:
        errors.append("README.md: missing Platform Contribution heading")
    if system is not None and platform is not None and system.start() > platform.start():
        errors.append(
            "README.md: System Contribution must appear before Platform Contribution"
        )
    return errors


def _validate_public_paths(root: Path) -> list[str]:
    paths = [root / "README.md", root / "README.ko.md"]
    paper_root = root / "docs/paper"
    if paper_root.is_dir():
        paths.extend(sorted(paper_root.rglob("*.md")))
    errors: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in PERSONAL_PATH_PATTERNS:
            if pattern.search(text):
                relative = path.resolve().relative_to(root.resolve()).as_posix()
                errors.append(f"{relative}: personal absolute path is not allowed")
                break
    return errors


def _validate_figures(root: Path) -> list[str]:
    figure_root = root / "docs/paper/assets/figures"
    if not figure_root.is_dir():
        return ["docs/paper/assets/figures: missing figure directory"]
    sources = sorted(figure_root.glob("*.dot"))
    errors: list[str] = []
    if len(sources) < 6:
        errors.append("docs/paper/assets/figures: at least six figure sources are required")
    for source in sources:
        rendered = source.with_suffix(".svg")
        if not rendered.is_file():
            errors.append(f"{source.relative_to(root)}: missing rendered figure {rendered.name}")
    return errors


def validate_paper_structure(root: Path) -> list[str]:
    """Return missing-file, narrative-order, figure, and privacy defects."""

    errors: list[str] = []
    for relative_path in (*REQUIRED_ROOT_FILES, *REQUIRED_PAPER_FILES):
        if not (root / relative_path).is_file():
            errors.append(f"missing required publication file: {relative_path}")
    errors.extend(_validate_readme_order(root))
    errors.extend(_validate_figures(root))
    errors.extend(_validate_public_paths(root))
    return errors


def validate_publication(root: Path) -> list[str]:
    """Return all defects in the public paper documentation surface."""

    root = root.resolve()
    errors = validate_paper_structure(root)
    manifest_path = root / "docs/paper/artifact_manifest.yaml"
    if manifest_path.is_file():
        errors.extend(validate_artifact_manifest(root, manifest_path))
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args(argv)
    errors = validate_publication(args.root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("paper publication validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
