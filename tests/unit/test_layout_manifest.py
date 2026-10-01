"""Migration accounting must describe Git objects, never private working files."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    for name, content in {"README.md": b"intro", "app/main.py": b"print('ok')", "LICENSE": b"license"}.items():
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
    (root / "app/main.py").chmod(0o755)
    (root / "link").symlink_to("/private/never-read")
    git(root, "add", "README.md", "app/main.py", "LICENSE", "link")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@invalid", "commit", "-qm", "fixture")
    (root / "private-secret").write_text("must not inventory")
    return root


def test_git_inventory_preserves_modes_bytes_and_symlinks(tmp_path):
    from tools.repository_layout.manifest import build_manifest, validate_manifest
    root = repository(tmp_path)
    manifest = build_manifest(root, "HEAD")
    assert set(manifest["entries"]) == {"README.md", "app/main.py", "LICENSE", "link"}
    assert manifest["entries"]["app/main.py"]["mode"] == "100755"
    assert manifest["entries"]["app/main.py"]["destination"] == "runtime/app/main.py"
    assert manifest["entries"]["LICENSE"]["destination"] == "runtime/LICENSE"
    assert manifest["entries"]["link"]["symlink_target"] == "/private/never-read"
    assert manifest["entries"]["link"]["sha256"] == hashlib.sha256(b"/private/never-read").hexdigest()
    assert validate_manifest(manifest) == []


def test_invalid_accounting_is_rejected(tmp_path):
    from tools.repository_layout.manifest import build_manifest, validate_manifest
    manifest = build_manifest(repository(tmp_path), "HEAD")
    for mutation in ("missing", "duplicate", "escaping", "unknown-disposition", "parent-collision"):
        broken = copy.deepcopy(manifest)
        if mutation == "missing":
            del broken["entries"]["LICENSE"]
        elif mutation == "duplicate":
            broken["entries"]["LICENSE"]["destination"] = "README.md"
        elif mutation == "escaping":
            broken["entries"]["LICENSE"]["destination"] = "../secret"
        elif mutation == "unknown-disposition":
            broken["entries"]["LICENSE"]["disposition"] = "ignore"
        else:
            broken["entries"]["LICENSE"]["destination"] = "runtime/app"
        assert validate_manifest(broken), mutation


def test_export_excludes_untracked_and_never_follows_git_symlinks(tmp_path):
    from tools.repository_layout.sandbox import export_tracked
    root = repository(tmp_path)
    target = tmp_path / "snapshot"
    export_tracked(root, target, revision="HEAD")
    assert not (target / "private-secret").exists()
    assert (target / "app/main.py").read_bytes() == b"print('ok')"
    assert (target / "link").is_symlink()
    assert (target / "app/main.py").stat().st_mode & 0o111


def test_public_manifest_redacts_personal_targets_and_expressions(tmp_path):
    from tools.repository_layout.manifest import build_manifest
    import json
    root = repository(tmp_path)
    (root / "personal").symlink_to("/home/private-owner/production/secret")
    (root / "app/main.py").write_text("import os\nos.getenv('CACHE', '/home/private-owner/cache')\n")
    git(root, "add", "personal", "app/main.py")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@invalid", "commit", "-qm", "personal reference")
    manifest = build_manifest(root, "HEAD")
    assert "/home/private-owner" not in json.dumps(manifest)
    assert manifest["entries"]["personal"]["symlink_target_class"] == "external_personal_path"


def test_checks_reject_unknown_task_without_importing_application():
    from tools.repository_layout.checks import main
    import pytest
    with pytest.raises(SystemExit) as rejected:
        main(["check", "not-a-task"])
    assert rejected.value.code != 0


def test_document_manifest_moves_to_system_root(tmp_path):
    from tools.repository_layout.manifest import build_manifest, validate_manifest
    root = repository(tmp_path)
    (root / "docs").mkdir()
    (root / "docs/document_manifest.yaml").write_text("documents: []\n")
    git(root, "add", "docs/document_manifest.yaml")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@invalid", "commit", "-qm", "document metadata")
    manifest = build_manifest(root, "HEAD")
    entry = manifest["entries"]["docs/document_manifest.yaml"]
    assert entry["destination"] == "system/document_manifest.yaml"
    assert entry["disposition"] == "move"
    assert validate_manifest(manifest) == []


@pytest.mark.parametrize(
    "revision_manifest,checkout_manifest,expected_status",
    [("valid", "invalid", 0), ("valid", "missing", 0),
     ("invalid", "valid", 1), ("missing", "valid", 1), ("stale", "valid", 1)],
)
def test_check_inventory_is_bound_to_revision_not_checkout(
    tmp_path, revision_manifest, checkout_manifest, expected_status,
):
    from tools.repository_layout import checks
    from tools.repository_layout.manifest import build_manifest
    from tools.repository_layout.sandbox import require_boundary
    require_boundary()
    root = repository(tmp_path)
    baseline = git(root, "rev-parse", "HEAD").decode().strip()
    valid = build_manifest(root, baseline)
    manifest_path = root / "docs/maintenance/repository_layout_manifest.json"
    manifest_path.parent.mkdir(parents=True)

    def set_manifest(state):
        if state == "missing":
            manifest_path.unlink(missing_ok=True)
        elif state == "invalid":
            manifest_path.write_text("{ invalid JSON")
        else:
            payload = copy.deepcopy(valid)
            if state == "stale":
                payload["baseline_commit"] = "0" * 40
            manifest_path.write_text(json.dumps(payload))

    # Nested probes execute actual containment code, never a mocked success result.
    tools_root = root / "tools/repository_layout"
    tools_root.mkdir(parents=True)
    for name in ("__init__.py", "manifest.py", "sandbox.py", "checks.py"):
        shutil.copyfile(Path(checks.__file__).parent / name, tools_root / name)
    set_manifest(revision_manifest)
    git(root, "add", "tools")
    if manifest_path.exists():
        git(root, "add", "docs/maintenance/repository_layout_manifest.json")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@invalid", "commit", "-qm", "revision under test")
    revision = git(root, "rev-parse", "HEAD").decode().strip()
    set_manifest(checkout_manifest)
    runner = (
        "import sys; from tools.repository_layout import checks; "
        "checks.BASELINE=sys.argv[1]; "
        "checks.CHECKS={'1': [['python', '-c', \"print('revision-check-passed')\"]]}; "
        "raise SystemExit(checks.main(sys.argv[2:]))"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", runner, baseline, "check", "1", "--revision", revision,
         "--dependencies", "/deps", "--timeout", "30"],
        cwd=root, capture_output=True, text=True, timeout=90,
    )
    output = result.stdout + result.stderr
    assert result.returncode == expected_status, output
    if expected_status:
        assert "manifest_errors" in output, output
        assert "revision-check-passed" not in output, output
    else:
        assert "revision-check-passed" in output, output
