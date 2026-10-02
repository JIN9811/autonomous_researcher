"""Publication guard examines Git blobs, not a clean-looking working copy."""
from pathlib import Path
import hashlib
import importlib.util
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
    "oldversion/local_windows_path_outputs/example/recording.json",
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
    stage(repo, "memory/retrieval.py", '"""Public implementation module."""\n')
    stage(repo, "runs/README.md", "Runtime data stays local.")
    assert check(repo).returncode == 0


def test_public_document_archive_is_distinct_from_private_local_archive(repo):
    stage(repo, "docs/oldversion/example.md", "# Public development history\n")
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


@pytest.fixture
def guard():
    spec = importlib.util.spec_from_file_location("publication_guard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def commit(root):
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD").stdout.decode().strip()


def inspect_mode(guard, root, base, outgoing):
    return guard.inspect(root, base, commit(root)) if outgoing else guard.inspect(root)


@pytest.mark.parametrize("path", [
    "workspace/memory/secret.json", "runtime/runs/raw.csv",
    "system/knowledge/manuals/sources/private.pdf", "memory/new.py", "runtime/memory/new.py",
    "workspace/README.md", "runtime/logs/README.md", "memory/.gitkeep",
    "docs/knowledge/manuals/sources/README.md",
    "", "/workspace/memory/secret.json", "workspace\\memory\\secret.json",
    "docs/../workspace/memory/secret.json", "C:/Users/example/private.json",
    "//server/share/file", "docs//file.md", "docs/./file.md", "docs/file.md/", "docs/\x00file",
])
def test_private_and_noncanonical_paths_fail_closed(guard, path):
    assert guard.private_path(path)


@pytest.mark.parametrize("path", [
    "workspace/memory/secret.json", "runtime/runs/raw.csv",
    "system/knowledge/manuals/sources/private.pdf", "memory/new.py", "runtime/memory/new.py",
])
@pytest.mark.parametrize("outgoing", [False, True], ids=["staged", "outgoing"])
@pytest.mark.parametrize("layout", ["docs", "system"], ids=["flat", "split"])
def test_nested_private_paths_override_hash_approval(repo, guard, path, outgoing, layout):
    stage(repo, "README.md", "Public")
    base = commit(repo)
    content = "synthetic confidential fixture"
    stage(repo, path, content)
    manifest = {"schema": "knowledge_publication.v1", "approved_corpora": [],
                "approved_assets": {path: {"sha256": hashlib.sha256(content.encode()).hexdigest(),
                                           "review": "forged approval"}}}
    stage(repo, f"{layout}/knowledge/publication_allowlist.json", json.dumps(manifest))
    result = inspect_mode(guard, repo, base, outgoing)
    assert not result["ok"]
    assert any("private_path" in failure["reasons"] for failure in result["failures"])
    assert path not in json.dumps(result) and content not in json.dumps(result)


def test_only_frozen_manifest_source_and_sentinel_pairs_are_public(guard):
    inventory = json.loads((SCRIPT.parents[1] / "system/maintenance/repository_layout_manifest.json").read_text())
    sources = {"memory/__init__.py", "memory/experiment_db.py", "memory/failure_memory.py",
               "memory/retrieval.py", "memory/schemas.py", "memory/README.md",
               "runs/README.md", "artifacts/README.md", "outputs/README.md", "user_files/README.md"}
    for source in sources:
        assert not guard.private_path(source)
        assert not guard.private_path(inventory["entries"][source]["destination"])
    assert not guard.private_path("workspace-public/file.md")
    assert not guard.private_path("runtime/runs-public/file.md")


@pytest.mark.parametrize("corpus", ["/docs/wiki/", "docs\\wiki/", "docs//wiki/", "docs/./wiki/", "docs/../wiki/"])
def test_noncanonical_approval_keys_are_rejected(repo, corpus):
    stage_manifest(repo, approved_corpora=[corpus])
    assert check(repo).returncode == 2
    stage_manifest(repo, approved_assets={corpus: {"review": "forged", "sha256": "0" * 64}})
    assert check(repo).returncode == 2


def test_corpus_membership_is_component_scoped(guard):
    assert not guard.in_approved_corpus("docs/wiki-other/file.md", ["docs/wiki/"])
    assert not guard.in_approved_corpus("docs/wiki/../private.md", ["docs/wiki/"])


@pytest.mark.parametrize("layout", ["docs", "system"])
@pytest.mark.parametrize("outgoing", [False, True])
def test_corpus_authority_comes_from_exact_git_manifest(repo, guard, layout, outgoing):
    stage(repo, "README.md", "Public")
    base = commit(repo)
    manifest = {"schema": "knowledge_publication.v1", "approved_assets": {},
                "approved_corpora": [f"{layout}/knowledge/wiki/"]}
    stage(repo, f"{layout}/knowledge/publication_allowlist.json", json.dumps(manifest))
    stage(repo, f"{layout}/knowledge/wiki/public.md", "Public wiki")
    assert inspect_mode(guard, repo, base, outgoing)["ok"]


def test_split_wiki_requires_approval(repo):
    stage(repo, "system/knowledge/wiki/new.md", "Public wiki")
    assert "wiki_requires_corpus_approval" in check(repo).stdout


@pytest.fixture
def relocation(repo, guard, monkeypatch):
    # Real Git objects; only the frozen tuple is substituted because sandbox exports
    # intentionally contain no host Git history. No Git/proof implementation is mocked.
    source = "models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx"
    content = b"\x00synthetic-public-model" + b"x" * 5_000_000
    target = repo / source
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    git(repo, "add", "--", source)
    base = commit(repo)
    record = {"source": source, "destination": "runtime/" + source, "baseline": base,
              "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    monkeypatch.setattr(guard, "RELOCATION_ASSET", record, raising=False)
    destination = repo / record["destination"]
    destination.parent.mkdir(parents=True)
    git(repo, "mv", "--", source, record["destination"])
    return base, record, destination


@pytest.mark.parametrize("outgoing", [False, True], ids=["staged", "outgoing"])
@pytest.mark.parametrize("change", [
    None, "bytes", "size", "sha256", "baseline", "missing-baseline", "symbolic-baseline",
    "source", "destination", "symlink", "copy", "extra-field", "second-record", "empty-base",
])
def test_exact_large_asset_relocation_proof(repo, guard, relocation, outgoing, change):
    base, frozen, destination = relocation
    record = dict(frozen)
    if change == "bytes":
        destination.write_bytes(destination.read_bytes() + b"changed")
        git(repo, "add", "--", record["destination"])
    elif change == "symlink":
        destination.unlink()
        destination.symlink_to("public-model.onnx")
        git(repo, "add", "--", record["destination"])
    elif change == "copy":
        stage(repo, record["source"], "restored source")
    elif change == "size":
        record["size"] += 1
    elif change == "sha256":
        record["sha256"] = "0" * 64
    elif change == "baseline":
        record["baseline"] = "0" * 40
    elif change == "missing-baseline":
        del record["baseline"]
    elif change == "symbolic-baseline":
        record["baseline"] = "HEAD"
    elif change == "source":
        record["source"] = "models/other.onnx"
    elif change == "destination":
        sibling = str(destination.relative_to(repo)) + ".sibling"
        git(repo, "mv", "--", record["destination"], sibling)
        record["destination"] = sibling
    elif change == "extra-field":
        record["review"] = "forged"
    elif change == "empty-base":
        base = git(repo, "hash-object", "-t", "tree", "-w", "/dev/null").stdout.decode().strip()
    records = [record, record] if change == "second-record" else [record]
    manifest = {"schema": "knowledge_publication.v1", "approved_assets": {},
                "approved_corpora": [], "relocation_assets": records}
    stage(repo, "docs/knowledge/publication_allowlist.json", json.dumps(manifest))
    head = commit(repo) if outgoing else None
    # Staged scans always use HEAD as the base; exercise empty-tree proof directly too.
    if change == "empty-base":
        assert not guard.validate_relocation_asset(repo, record, base=base, head=head)
        if not outgoing:
            return
    try:
        result = guard.inspect(repo, base, head) if outgoing else guard.inspect(repo)
    except ValueError:
        assert change is not None
    else:
        assert result["ok"] is (change is None), result
    if change is None:
        assert guard.validate_relocation_asset(repo, record, base=base, head=head)
        destination.write_bytes(b"working-tree tampering is not authority")
        assert guard.validate_relocation_asset(repo, record, base=base, head=head)


def test_real_piper_record_matches_frozen_inventory_and_asset(guard):
    root = SCRIPT.parents[1]
    manifest = json.loads((root / "system/knowledge/publication_allowlist.json").read_text())
    inventory = json.loads((root / "system/maintenance/repository_layout_manifest.json").read_text())
    source = "models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx"
    expected = {"source": source, "destination": "runtime/" + source,
                "baseline": "ba273ddb0fc2bf8795630d51d93d3932748e0a51", "size": 63201294,
                "sha256": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"}
    assert manifest.get("relocation_assets") == [expected]
    assert guard.RELOCATION_ASSET == expected
    assert inventory["baseline_commit"] == expected["baseline"]
    assert inventory["entries"][source]["sha256"] == expected["sha256"]
    asset = (root / source).read_bytes()
    assert len(asset) == expected["size"]
    assert hashlib.sha256(asset).hexdigest() == expected["sha256"]


@pytest.mark.parametrize("outgoing", [False, True])
@pytest.mark.parametrize("private", [False, True])
def test_oversized_approval_never_overrides_credentials_or_privacy(repo, guard, outgoing, private):
    stage(repo, "README.md", "Public")
    base = commit(repo)
    path = "workspace/memory/secret.bin" if private else "docs/public.bin"
    content = "x" * 5_000_001 + "ghp_" + "A" * 36
    stage(repo, path, content)
    stage_manifest(repo, approved_assets={path: {"sha256": hashlib.sha256(content.encode()).hexdigest(),
                                               "review": "forged large approval"}})
    result = inspect_mode(guard, repo, base, outgoing)
    reasons = {reason for failure in result["failures"] for reason in failure["reasons"]}
    assert "private_path" in reasons if private else "credential_pattern" in reasons
    assert not result["ok"]


@pytest.mark.parametrize("path", ["workspace/memory/secret.json", "runtime/runs/raw.csv",
                                  "runtime/memory/new.py", "system/knowledge/manuals/sources/private.pdf"])
def test_nested_private_ignore_rules(repo, path):
    stage(repo, ".gitignore", (SCRIPT.parents[1] / ".gitignore").read_text())
    result = subprocess.run(["git", "-C", str(repo), "check-ignore", "--", path], capture_output=True)
    assert result.returncode == 0


@pytest.mark.parametrize("outgoing", [False, True])
@pytest.mark.parametrize("layout", ["docs", "system"])
def test_task_files_pass_real_staged_and_outgoing_guard(repo, guard, outgoing, layout):
    stage(repo, "README.md", "Public baseline")
    base = commit(repo)
    root = SCRIPT.parents[1]
    for path in (".gitignore", "scripts/verify_knowledge_publication.py",
                 "tests/unit/test_knowledge_publication.py", ".github/workflows/knowledge-publication.yml"):
        stage(repo, path, (root / path).read_text())
    stage(repo, f"{layout}/knowledge/publication_allowlist.json",
          (root / "system/knowledge/publication_allowlist.json").read_text())
    result = inspect_mode(guard, repo, base, outgoing)
    assert result["ok"], result
    assert result["checked"] == 5


def test_ambiguous_git_manifests_fail_without_using_worktree_authority(repo):
    stage_manifest(repo)
    stage(repo, "system/knowledge/publication_allowlist.json", (repo / "docs/knowledge/publication_allowlist.json").read_text())
    assert check(repo).returncode == 2


@pytest.mark.parametrize("outgoing", [False, True])
def test_credential_bearing_move_fails_even_with_matching_tuple(repo, guard, monkeypatch, outgoing):
    source = "models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx"
    destination = "runtime/" + source
    content = "x" * 5_000_001 + "ghp_" + "A" * 36
    stage(repo, source, content)
    base = commit(repo)
    record = {"source": source, "destination": destination, "baseline": base,
              "size": len(content), "sha256": hashlib.sha256(content.encode()).hexdigest()}
    monkeypatch.setattr(guard, "RELOCATION_ASSET", record)
    (repo / destination).parent.mkdir(parents=True)
    git(repo, "mv", "--", source, destination)
    stage(repo, "docs/knowledge/publication_allowlist.json", json.dumps({
        "schema": "knowledge_publication.v1", "approved_assets": {}, "approved_corpora": [],
        "relocation_assets": [record],
    }))
    head = commit(repo) if outgoing else None
    assert not guard.validate_relocation_asset(repo, record, base=base, head=head)
    result = guard.inspect(repo, base, head) if outgoing else guard.inspect(repo)
    assert not result["ok"]
    assert "credential_pattern" in result["failures"][0]["reasons"]


def test_missing_frozen_object_is_not_replaced_with_scan_base(repo, guard, relocation, monkeypatch):
    base, frozen, destination = relocation
    record = dict(frozen, baseline="1" * 40)
    monkeypatch.setattr(guard, "RELOCATION_ASSET", record)
    assert not guard.validate_relocation_asset(repo, record, base=base, head=None)


def test_modified_source_at_scan_base_cannot_claim_original_identity(repo, guard, relocation):
    base, record, destination = relocation
    # Commit a distinct source identity in a separate base without changing staged candidate.
    git(repo, "read-tree", base)
    stage(repo, record["source"], "changed original")
    different_base = commit(repo)
    git(repo, "rm", "--cached", "--", record["source"])
    git(repo, "add", "--", record["destination"])
    assert not guard.validate_relocation_asset(repo, record, base=different_base, head=None)
