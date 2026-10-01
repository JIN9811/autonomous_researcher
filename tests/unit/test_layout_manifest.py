"""Migration accounting must describe Git objects, never private working files."""
import copy
import hashlib
import subprocess


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
