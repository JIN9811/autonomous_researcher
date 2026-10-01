"""Exercise real namespace denial before any application import."""
import json
import os
from pathlib import Path
import subprocess


def test_os_boundary_denies_host_resources():
    from tools.repository_layout.sandbox import boundary_probe, require_boundary
    require_boundary()
    boundary = boundary_probe()
    assert boundary["host_paths_visible"] == []
    assert boundary["device_nodes"] == []
    assert boundary["host_pid_visible"] is False
    assert boundary["non_loopback_connected"] is False
    assert boundary["denied_attempts"] >= 4
    assert boundary["capabilities"] == "0000000000000000"


def test_dependency_tree_rejects_executable_pth_and_editable_finders(tmp_path):
    from tools.repository_layout.sandbox import validate_dependencies
    import pytest
    site = tmp_path / "lib/python3.12/site-packages"
    site.mkdir(parents=True)
    (site / "danger.pth").write_text("import editable_finder\n")
    with pytest.raises(ValueError, match="pth|editable"):
        validate_dependencies(tmp_path)


def test_command_rejects_cwd_escape(tmp_path):
    from tools.repository_layout.sandbox import sandbox_command
    import pytest
    with pytest.raises(ValueError, match="cwd"):
        sandbox_command(tmp_path, tmp_path, ["python", "-V"], cwd="/home/operator")


def test_real_routes_inside_fixture_import_mode():
    from tools.repository_layout.fixture_server import verify_routes
    result = verify_routes(lifespan_mode="import_only")
    assert result["routes"]["/api/state"] == 200
    assert result["routes"]["/static/favicon.svg"] == 200
    assert result["module_assets"] >= 1
    assert result["unexpected_effects"] == []
    assert result["outside_imports"] == []


def test_real_lifespan_uses_injected_services():
    # Separate interpreter: imports and application globals cannot leak between modes.
    result = subprocess.run(
        [os.sys.executable, "-S", "-m", "tools.repository_layout.fixture_server", "verify", "fake_services"],
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload["lifespan_started"] is True
    assert payload["lifespan_stopped"] is True
    assert payload["unexpected_effects"] == []
