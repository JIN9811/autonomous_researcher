"""Migration accounting must describe Git objects, never private working files."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_consumer_ast_warning_retains_source_filename():
    import warnings
    from tools.repository_layout.manifest import _consumers
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('always', SyntaxWarning)
        _consumers('runtime/fixture_invalid_escape.py', b"pattern = '\\s'\n")
    assert len(recorded) == 1
    assert recorded[0].filename == 'runtime/fixture_invalid_escape.py'
    assert recorded[0].lineno == 1


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


def test_task11_requires_literal_selection_before_inventory():
    from tools.repository_layout.checks import main
    with pytest.raises(SystemExit) as rejected:
        main(["check", "11"])
    assert rejected.value.code == 2


def test_literal_selection_rejects_unbounded_or_ambiguous_batches():
    from tools.repository_layout.checks import literal_selection
    payload = {"id": "fixture-01", "timeout": 30,
               "command": ["/deps/bin/python3", "-S", "-m", "pytest", "-v", "tests/unit/test_example.py"]}
    assert literal_selection(payload) == payload
    for update in ({"timeout": 0}, {"timeout": 1201}, {"command": []},
                   {"id": "../escape"}, {"command": ["node", "--test", "tests/js"]},
                   {"command": ["python", "-m", "pytest", "tests"]},
                   {"command": ["python", "-m", "pytest", "tests/unit/*.py"]},
                   {"command": ["python", "-m", "pytest"]}):
        with pytest.raises(ValueError):
            literal_selection({**payload, **update})


def test_receipt_directory_is_exclusive(tmp_path):
    from tools.repository_layout.checks import receipt_directory
    output = receipt_directory(tmp_path, "fixture-01")
    (output / "prior.log").write_text("immutable")
    with pytest.raises(FileExistsError):
        receipt_directory(tmp_path, "fixture-01")
    assert (output / "prior.log").read_text() == "immutable"


@pytest.mark.parametrize('command', [
    ['bash', '-c', 'python -m pytest tests'],
    ['python', '-c', 'import pytest; pytest.main(["tests"])'],
    ['env', 'python', '-m', 'pytest', 'tests/unit/test_example.py'],
    ['python', '-m', 'pytest', '@selection.txt', 'tests/unit/test_example.py'],
    ['python', '-m', 'pytest', '--pyargs', 'tests/unit/test_example.py'],
    ['python', '-m', 'pytest', '-c', 'custom.ini', 'tests/unit/test_example.py'],
    ['python', '-m', 'pytest', '-p', 'unreviewed.plugin', 'tests/unit/test_example.py'],
    ['python', '-m', 'pytest', 'tests/unit/test_example.py', 'tests/integration'],
    ['python', '-m', 'pytest', 'tests/../outside.py'],
    ['node', '--test', '--import=unreviewed.mjs', 'tests/js/example.cjs'],
    ['node', '--eval', 'require("node:test")', 'tests/js/example.cjs'],
    ['node', '--test', '@selection.txt', 'tests/js/example.cjs'],
])
def test_literal_selection_rejects_wrappers_and_indirection(command):
    from tools.repository_layout.checks import literal_selection
    with pytest.raises(ValueError):
        literal_selection({'id': 'fixture', 'timeout': 30, 'command': command})


@pytest.mark.parametrize('command', [
    ['/deps/bin/python3', '-S', '-u', '-m', 'pytest', '-v', '--tb=short', '-rA',
     '-p', 'pytest_asyncio.plugin', 'tests/unit/test_example.py::test_case[one]'],
    ['node', '--test', '--test-name-pattern=exact case', 'tests/js/example.cjs'],
    ['node', '--test', 'tests/js/omx_environment_layout.test.cjs'],
    ['node', '--test', 'tests/js/example.test.js'],
])
def test_literal_selection_accepts_direct_bounded_runners(command):
    from tools.repository_layout.checks import literal_selection
    payload = {'id': 'fixture', 'timeout': 30, 'command': command}
    assert literal_selection(payload) == payload


def test_bounded_log_preserves_success_stdout_and_stderr(tmp_path):
    from tools.repository_layout.sandbox import run_bounded
    output = tmp_path / "raw.log"
    result = run_bounded([sys.executable, "-S", "-c",
        "import sys; print('success-output',flush=True); print('success-warning',file=sys.stderr)"],
        timeout=10, output_path=output)
    assert result.returncode == 0
    assert result.stdout == output.read_text() == "success-output\nsuccess-warning\n"
    with pytest.raises(FileExistsError):
        run_bounded([sys.executable, "-V"], timeout=10, output_path=output)


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
