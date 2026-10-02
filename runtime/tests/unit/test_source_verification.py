"""Verification fixtures stay isolated, with optional external evidence retention."""
from pathlib import Path

import pytest


@pytest.mark.parametrize("fail", [False, True])
def test_probe_retains_complete_workspace_outside_repository(tmp_path, fail):
    from scripts.verify_source_curation import fixture_workspace

    archive = tmp_path / "validation"
    try:
        with fixture_workspace(artifacts_dir=archive) as root:
            (root / "curated.md").write_text("# Retained evidence\n17.5 mm", encoding="utf-8")
            if fail:
                raise RuntimeError("verification failed")
    except RuntimeError:
        assert fail
    assert not root.exists()
    saved = archive / f"{root.name}-archive"
    assert (saved / "curated.md").read_text() == "# Retained evidence\n17.5 mm"
    assert (saved / "inputs" / "conditions.md").is_file()


def test_probe_can_archive_under_system_temp_parent(tmp_path, monkeypatch):
    import tempfile
    from scripts.verify_source_curation import fixture_workspace

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with fixture_workspace(artifacts_dir=tmp_path) as root:
        assert root.parent == tmp_path
    assert not root.exists()
    assert (tmp_path / f"{root.name}-archive" / "inputs" / "conditions.md").is_file()


@pytest.mark.parametrize("path", ["validation", "memory/knowledge/source_library"])
def test_probe_rejects_artifact_retention_inside_repository(path):
    from scripts.verify_source_curation import ROOT, fixture_workspace

    with pytest.raises(ValueError, match="outside"):
        with fixture_workspace(artifacts_dir=ROOT / path):
            pytest.fail("repository retention must be rejected")


def test_probe_inputs_and_generated_artifacts_are_removed():
    from scripts.verify_source_curation import fixture_workspace

    with fixture_workspace() as root:
        assert (root / "inputs" / "conditions.md").is_file()
        assert (root / "inputs" / "structured.csv").is_file()
        assert (root / "inputs" / "layout.docx").is_file()
        derived = root / "library" / "notes"
        derived.mkdir(parents=True)
        (derived / "generated.md").write_text("derived fixture", encoding="utf-8")
        path = root
    assert not path.exists()


def test_probe_cleanup_also_covers_failure_and_downloads():
    from scripts.verify_source_curation import fixture_workspace

    path = None
    with pytest.raises(RuntimeError, match="verification failed"):
        with fixture_workspace() as root:
            path = root
            (root / "inputs" / "publication.pdf").write_bytes(b"downloaded content")
            raise RuntimeError("verification failed")
    assert isinstance(path, Path) and not path.exists()


def test_registered_knowledge_routes_allow_structured_curation_output():
    from backends.vllm_client import DEFAULT_MAX_TOKENS_BY_TASK as local_limits
    from backends.openai_client import OPENAI_MAX_COMPLETION_TOKENS_BY_TASK as api_limits
    assert local_limits["knowledge_query"] == 4096
    assert api_limits["knowledge_query"] == 4096


@pytest.mark.parametrize("answer,expected", [
    ("225 pages, with OCR disabled.", True),
    ("225 pages; OCR was not enabled in this benchmark.", True),
    ("225 pages with OCR enabled.", False),
    ("225 pages; it is unknown whether OCR was enabled.", False),
])
def test_probe_checks_qualification_not_just_keyword(answer, expected):
    from scripts.verify_source_curation import answer_checks
    checks = answer_checks(answer, ["225", "ocr"], qualification="ocr_disabled")
    assert all(checks.values()) is expected
