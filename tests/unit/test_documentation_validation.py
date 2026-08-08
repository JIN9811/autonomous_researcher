from __future__ import annotations

import importlib.util
from pathlib import Path
from textwrap import dedent

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate_documentation.py"


VALID_REFERENCE = dedent(
    """\
    ---
    doc_type: reference
    subtype: runtime
    status: active
    authority: descriptive
    audience:
      - developer
    scope:
      - runtime
    summary: Current runtime behavior.
    source_of_truth:
      - app/main.py
    last_verified: 2026-08-08
    verified_against: 09bbe32
    related_docs:
      - docs/related.md
    supersedes: []
    ---
    # Runtime Reference
    """
)

VALID_INDEX = dedent(
    """\
    ---
    doc_type: index
    subtype: index
    status: active
    authority: navigation
    audience:
      - developer
    scope:
      - repository
    summary: Repository documentation index.
    related_docs: []
    supersedes: []
    ---
    # Index
    """
)

VALID_SNAPSHOT = VALID_INDEX + dedent(
    """\

    FastAPI APIRoute count: 332
    Total app.routes count: 339
    Graph nodes: 19
    Graph edges: 68
    stage_dispatch edges: 12
    """
)


def _write(root: Path, relative_path: str, content: str = "") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_manifest(
    root: Path,
    documents: list[str],
    *,
    snapshot_expected: dict[str, int] | None = None,
) -> Path:
    manifest: dict[str, object] = {
        "version": 1,
        "documents": documents,
        "legacy_scope": {
            "status": "migration_debt",
            "note": "Remaining Markdown is migrated in later batches.",
        },
    }
    if snapshot_expected is not None:
        manifest["snapshot"] = {
            "document": "docs/runtime/current_code_snapshot.md",
            "expected": snapshot_expected,
        }
    return _write(
        root,
        "docs/document_manifest.yaml",
        yaml.safe_dump(manifest, sort_keys=False),
    )


def _load_validator():
    assert VALIDATOR_PATH.exists(), "documentation validator script is missing"
    spec = importlib.util.spec_from_file_location(
        "validate_documentation", VALIDATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_front_matter_returns_metadata_and_body() -> None:
    module = _load_validator()

    metadata, body = module.split_front_matter(
        "---\ndoc_type: index\nstatus: active\n---\n# Index\n"
    )

    assert metadata["doc_type"] == "index"
    assert metadata["status"] == "active"
    assert body == "# Index\n"


def test_active_reference_requires_verification_fields(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write(
        tmp_path,
        "docs/runtime.md",
        VALID_REFERENCE.replace("source_of_truth:\n  - app/main.py\n", "")
        .replace("last_verified: 2026-08-08\n", "")
        .replace("verified_against: 09bbe32\n", ""),
    )

    errors = module.validate_document(document, tmp_path)

    assert any("source_of_truth" in error for error in errors)
    assert any("last_verified" in error for error in errors)
    assert any("verified_against" in error for error in errors)


def test_source_and_related_paths_must_exist(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write(tmp_path, "docs/runtime.md", VALID_REFERENCE)

    errors = module.validate_document(document, tmp_path)

    assert any("missing source_of_truth path: app/main.py" in error for error in errors)
    assert any("missing related_docs path: docs/related.md" in error for error in errors)


def test_valid_reference_has_no_errors(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "app/main.py")
    _write(tmp_path, "docs/related.md")
    document = _write(tmp_path, "docs/runtime.md", VALID_REFERENCE)

    assert module.validate_document(document, tmp_path) == []


def test_document_rejects_missing_local_markdown_link(tmp_path: Path) -> None:
    module = _load_validator()
    document = _write(
        tmp_path,
        "docs/index.md",
        VALID_INDEX + "\n[Missing Guide](guides/missing.md)\n",
    )

    errors = module.validate_document(document, tmp_path)

    assert any("missing local link: guides/missing.md" in error for error in errors)


def test_document_accepts_existing_local_and_external_links(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "docs/guides/ready.md", "# Ready\n")
    document = _write(
        tmp_path,
        "docs/index.md",
        VALID_INDEX
        + "\n[Ready](guides/ready.md#start)\n"
        + "[API](http://localhost:7860/docs)\n",
    )

    assert module.validate_document(document, tmp_path) == []


def test_manifest_rejects_duplicate_documents(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "README.md", VALID_INDEX)
    manifest = _write_manifest(tmp_path, ["README.md", "README.md"])

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("duplicate document: README.md" in error for error in errors)


def test_manifest_rejects_missing_documents(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = _write_manifest(tmp_path, ["docs/missing.md"])

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("missing manifest document: docs/missing.md" in error for error in errors)


def test_manifest_rejects_unknown_schema_version(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = _write_manifest(tmp_path, [])
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("version: 1", "version: 2"),
        encoding="utf-8",
    )

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("version must be 1" in error for error in errors)


def test_manifest_rejects_stale_snapshot_values(tmp_path: Path) -> None:
    module = _load_validator()
    _write(
        tmp_path,
        "docs/runtime/current_code_snapshot.md",
        VALID_SNAPSHOT.replace("Graph nodes: 19", "Graph nodes: 18"),
    )
    manifest = _write_manifest(
        tmp_path,
        ["docs/runtime/current_code_snapshot.md"],
        snapshot_expected={
            "api_routes": 332,
            "app_routes": 339,
            "graph_nodes": 19,
            "graph_edges": 68,
            "stage_dispatch_edges": 12,
        },
    )

    errors = module.validate_manifest(tmp_path, manifest)

    assert any("Graph nodes: expected 19, found 18" in error for error in errors)


def test_valid_manifest_has_no_errors(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "docs/runtime/current_code_snapshot.md", VALID_SNAPSHOT)
    manifest = _write_manifest(
        tmp_path,
        ["docs/runtime/current_code_snapshot.md"],
        snapshot_expected={
            "api_routes": 332,
            "app_routes": 339,
            "graph_nodes": 19,
            "graph_edges": 68,
            "stage_dispatch_edges": 12,
        },
    )

    assert module.validate_manifest(tmp_path, manifest) == []
