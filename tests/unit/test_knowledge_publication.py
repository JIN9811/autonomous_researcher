"""Publication guard examines Git blobs, not a clean-looking working copy."""
from pathlib import Path
import hashlib
import json
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/verify_knowledge_publication.py"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def stage(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(root, "add", "-f", "--", path)
    return target


def check(root, *args):
    return subprocess.run(["python3", str(SCRIPT), "--repo", str(root), *args], capture_output=True, text=True)


def stage_manifest(root, approved_assets=None, approved_corpora=None):
    manifest = {
        "schema": "knowledge_publication.v1",
        "approved_assets": approved_assets or {},
        "approved_corpora": approved_corpora or [],
    }
    stage(root, "docs/knowledge/publication_allowlist.json", json.dumps(manifest))


@pytest.mark.parametrize("path", [
    "memory/knowledge/private/user/note.md", "runs/example/transcript.json", "output/session.json",
    "docs/knowledge/manuals/sources/private-source.pdf", "artifacts/experiment/result.csv",
])
def test_force_added_private_data_is_blocked(repo, path):
    stage(repo, path, "synthetic private content")
    result = check(repo)
    assert result.returncode == 1, result.stderr
    assert "private_path" in result.stdout
    assert "synthetic private content" not in result.stdout


def test_secret_in_staged_blob_is_blocked_even_when_worktree_cleaned(repo):
    secret = "ghp_" + "A" * 36
    path = stage(repo, "docs/knowledge/wiki/example.md", f"Token: {secret}")
    path.write_text("# Clean working copy")
    result = check(repo)
    assert result.returncode == 1
    assert "credential_pattern" in result.stdout
    assert secret not in result.stdout + result.stderr


def test_safe_public_wiki_and_memory_source_code_allowed(repo):
    stage_manifest(repo, approved_corpora=["docs/knowledge/wiki/"])
    stage(repo, "docs/knowledge/wiki/example.md", "# Wiki\nSource-backed system knowledge.")
    stage(repo, "memory/example.py", '"""Public implementation module."""\n')
    stage(repo, "runs/README.md", "Runtime data stays local.")
    assert check(repo).returncode == 0


def test_wiki_requires_explicit_corpus_approval(repo):
    stage(repo, "docs/knowledge/wiki/example.md", "# Wiki\nSource-backed system knowledge.")
    result = check(repo)
    assert result.returncode == 1
    assert "wiki_requires_corpus_approval" in result.stdout


def test_public_personal_path_is_blocked_without_echoing_content(repo):
    private_path = "/home/" + "synthetic-person/Documents/private.txt"
    stage(repo, "docs/knowledge/wiki/example.md", f"Local file {private_path}")
    result = check(repo)
    assert result.returncode == 1
    assert "personal_path" in result.stdout
    assert "synthetic-person" not in result.stdout


def test_unreviewed_public_evidence_is_blocked(repo):
    stage(repo, "docs/knowledge/evidence/study.md", "# Sanitized evidence")
    result = check(repo)
    assert result.returncode == 1
    assert "evidence_requires_publication_review" in result.stdout


def test_hash_review_allows_public_text_evidence(repo):
    evidence = "# Sanitized evidence"
    stage_manifest(repo, approved_assets={
        "docs/knowledge/evidence/study.md": {
            "sha256": hashlib.sha256(evidence.encode()).hexdigest(),
            "review": "synthetic public fixture",
        }
    })
    stage(repo, "docs/knowledge/evidence/study.md", evidence)
    assert check(repo).returncode == 0


def test_evidence_doc_type_requires_hash_review_inside_wiki_corpus(repo):
    stage_manifest(repo, approved_corpora=["docs/knowledge/wiki/"])
    stage(repo, "docs/knowledge/wiki/study.md", "---\ndoc_type: evidence\n---\n# Study")
    result = check(repo)
    assert result.returncode == 1
    assert "evidence_requires_publication_review" in result.stdout


def test_hash_review_allows_evidence_doc_type_inside_wiki(repo):
    evidence = "---\ndoc_type: evidence\n---\n# Study"
    stage_manifest(repo, approved_assets={
        "docs/knowledge/wiki/study.md": {
            "sha256": hashlib.sha256(evidence.encode()).hexdigest(),
            "review": "synthetic public fixture",
        }
    })
    stage(repo, "docs/knowledge/wiki/study.md", evidence)
    assert check(repo).returncode == 0


def test_atr_doc_evidence_metadata_requires_hash_review(repo):
    evidence = "<!-- atr-doc\ndoc_type: evidence\nsubtype: benchmark\n-->\n# Results"
    stage(repo, "docs/paper/results.md", evidence)
    result = check(repo)
    assert result.returncode == 1
    assert "evidence_requires_publication_review" in result.stdout


def test_body_prose_that_mentions_evidence_metadata_is_not_a_metadata_header(repo):
    stage(repo, "docs/paper/readme.md", "# Notes\nThis prose mentions doc_type: evidence.")
    assert check(repo).returncode == 0


def test_ordinary_public_product_document_does_not_need_hash_review(repo):
    stage(repo, "README.md", "# Product\nPublic setup instructions.")
    assert check(repo).returncode == 0


def test_public_source_personal_path_is_blocked_without_echoing_content(repo):
    private_path = "/home/" + "synthetic-person/Documents/private.txt"
    stage(repo, "tools/settings.toml", f"input_path = {private_path!r}\n")
    result = check(repo)
    assert result.returncode == 1
    assert "personal_path" in result.stdout
    assert "synthetic-person" not in result.stdout


def test_revision_range_checks_committed_blob(repo):
    stage(repo, "README.md", "Public")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "baseline")
    base = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    stage(repo, "memory/knowledge/private/note.md", "Private fixture")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "private")
    result = check(repo, "--base", base, "--head", "HEAD")
    assert result.returncode == 1
    assert "private_path" in result.stdout


def test_reviewed_binary_requires_matching_publication_hash(repo):
    image = repo / "docs/figure.png"
    image.parent.mkdir()
    image.write_bytes(b"synthetic-image\x00payload")
    git(repo, "add", "--", "docs/figure.png")
    assert check(repo).returncode == 1
    manifest = {"schema": "knowledge_publication.v1", "approved_assets": {
        "docs/figure.png": {"sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                            "review": "synthetic public fixture"},
    }, "approved_corpora": []}
    stage(repo, "docs/knowledge/publication_allowlist.json", json.dumps(manifest))
    assert check(repo).returncode == 0
    image.write_bytes(b"changed\x00private")
    git(repo, "add", "--", "docs/figure.png")
    assert check(repo).returncode == 1
