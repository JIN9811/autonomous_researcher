from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from textwrap import dedent

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate_paper_publication.py"

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
)


def _load_validator():
    assert VALIDATOR_PATH.exists(), "paper publication validator script is missing"
    spec = importlib.util.spec_from_file_location(
        "validate_paper_publication", VALIDATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, relative_path: str, content: str = "") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_manifest(
    root: Path,
    *,
    claims: list[dict[str, object]],
    evidence: list[dict[str, object]],
) -> Path:
    return _write(
        root,
        "docs/paper/artifact_manifest.yaml",
        yaml.safe_dump(
            {
                "version": 1,
                "release_status": "development",
                "verified_commit": "abc1234",
                "claims": claims,
                "evidence": evidence,
            },
            sort_keys=False,
        ),
    )


def _evidence(
    output_path: str,
    checksum: str,
    *,
    evidence_id: str = "E-TEST-001",
    environment: str = "test",
) -> dict[str, object]:
    return {
        "id": evidence_id,
        "environment": environment,
        "verified_commit": "abc1234",
        "command": "python -m pytest -q",
        "inputs": ["REQUIREMENTS.md"],
        "outputs": [{"path": output_path, "sha256": checksum}],
        "result": "pass",
    }


def _write_required_publication_tree(root: Path) -> None:
    for relative_path in REQUIRED_ROOT_FILES:
        _write(root, relative_path, "publication file\n")
    _write(
        root,
        "README.md",
        dedent(
            """\
            # Autonomous Researcher Framework

            ## System Contribution

            System narrative.

            ## Platform Contribution

            Platform narrative.
            """
        ),
    )
    for relative_path in REQUIRED_PAPER_FILES:
        _write(root, relative_path, "# Paper section\n")
    for index in range(1, 7):
        stem = f"{index:02d}_figure"
        _write(root, f"docs/paper/assets/figures/{stem}.dot", "digraph G {}\n")
        _write(root, f"docs/paper/assets/figures/{stem}.svg", "<svg/>\n")
    _write_manifest(root, claims=[], evidence=[])


def test_supported_claim_requires_existing_evidence(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = _write_manifest(
        tmp_path,
        claims=[
            {
                "id": "C-SYS-01",
                "status": "supported",
                "research_questions": ["RQ1"],
                "evidence_ids": ["E-404"],
            }
        ],
        evidence=[],
    )

    errors = module.validate_artifact_manifest(tmp_path, manifest)

    assert any("unknown evidence id E-404" in error for error in errors)


def test_supported_claim_requires_at_least_one_evidence_id(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = _write_manifest(
        tmp_path,
        claims=[
            {
                "id": "C-SYS-01",
                "status": "supported",
                "research_questions": ["RQ1"],
                "evidence_ids": [],
            }
        ],
        evidence=[],
    )

    errors = module.validate_artifact_manifest(tmp_path, manifest)

    assert any("supported claim requires evidence_ids" in error for error in errors)


def test_not_evaluated_claim_may_have_no_evidence(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = _write_manifest(
        tmp_path,
        claims=[
            {
                "id": "C-LIVE-01",
                "status": "not_evaluated",
                "research_questions": ["RQ3"],
                "evidence_ids": [],
            }
        ],
        evidence=[],
    )

    assert module.validate_artifact_manifest(tmp_path, manifest) == []


def test_duplicate_claim_and_evidence_ids_are_rejected(tmp_path: Path) -> None:
    module = _load_validator()
    output = _write(tmp_path, "docs/paper/evidence/report.md", "measured\n")
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = _write_manifest(
        tmp_path,
        claims=[
            {
                "id": "C-SYS-01",
                "status": "not_evaluated",
                "research_questions": ["RQ1"],
                "evidence_ids": [],
            },
            {
                "id": "C-SYS-01",
                "status": "not_evaluated",
                "research_questions": ["RQ1"],
                "evidence_ids": [],
            },
        ],
        evidence=[
            _evidence("docs/paper/evidence/report.md", checksum),
            _evidence("docs/paper/evidence/report.md", checksum),
        ],
    )

    errors = module.validate_artifact_manifest(tmp_path, manifest)

    assert any("duplicate claim id C-SYS-01" in error for error in errors)
    assert any("duplicate evidence id E-TEST-001" in error for error in errors)


def test_evidence_output_checksum_must_match(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "REQUIREMENTS.md", "requirements\n")
    _write(tmp_path, "docs/paper/evidence/report.md", "measured\n")
    manifest = _write_manifest(
        tmp_path,
        claims=[],
        evidence=[_evidence("docs/paper/evidence/report.md", "0" * 64)],
    )

    errors = module.validate_artifact_manifest(tmp_path, manifest)

    assert any("sha256 mismatch" in error for error in errors)


def test_evidence_paths_must_stay_inside_repository(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = _write_manifest(
        tmp_path,
        claims=[],
        evidence=[_evidence("../outside.md", "0" * 64)],
    )

    errors = module.validate_artifact_manifest(tmp_path, manifest)

    assert any("unsafe output path ../outside.md" in error for error in errors)


def test_evidence_environment_is_allowlisted(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = _write_manifest(
        tmp_path,
        claims=[],
        evidence=[_evidence("docs/report.md", "0" * 64, environment="production")],
    )

    errors = module.validate_artifact_manifest(tmp_path, manifest)

    assert any("invalid environment production" in error for error in errors)


def test_structure_requires_publication_files(tmp_path: Path) -> None:
    module = _load_validator()
    _write(tmp_path, "README.md", "# Project\n")

    errors = module.validate_paper_structure(tmp_path)

    assert any("missing required publication file: CITATION.cff" in error for error in errors)
    assert any(
        "missing required publication file: docs/paper/02_system_architecture.md"
        in error
        for error in errors
    )


def test_readme_places_system_before_platform(tmp_path: Path) -> None:
    module = _load_validator()
    _write_required_publication_tree(tmp_path)
    _write(
        tmp_path,
        "README.md",
        "# Project\n\n## Platform Contribution\n\n## System Contribution\n",
    )

    errors = module.validate_paper_structure(tmp_path)

    assert any("System Contribution must appear before Platform Contribution" in error for error in errors)


def test_public_paper_rejects_personal_absolute_paths(tmp_path: Path) -> None:
    module = _load_validator()
    _write_required_publication_tree(tmp_path)
    _write(
        tmp_path,
        "docs/paper/README.md",
        "Run a script under /home/alice/private-project.\n",
    )

    errors = module.validate_paper_structure(tmp_path)

    assert any("personal absolute path" in error for error in errors)


def test_figure_source_requires_matching_svg(tmp_path: Path) -> None:
    module = _load_validator()
    _write_required_publication_tree(tmp_path)
    (tmp_path / "docs/paper/assets/figures/01_figure.svg").unlink()

    errors = module.validate_paper_structure(tmp_path)

    assert any("missing rendered figure" in error for error in errors)


def test_valid_publication_has_no_errors(tmp_path: Path) -> None:
    module = _load_validator()
    _write_required_publication_tree(tmp_path)

    assert module.validate_publication(tmp_path) == []
