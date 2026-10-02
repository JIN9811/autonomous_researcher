"""Exercise real namespace denial before any application import."""
import json
import os
import subprocess
import sys
from types import ModuleType
from pathlib import Path

import pytest


def test_parent_and_filtered_child_use_same_isolated_interpreter():
    assert sys.flags.no_site == 1
    assert sys.executable.startswith('/deps/bin/')
    result = subprocess.run([sys.executable, '-c',
        'import json,sys,numpy; print(json.dumps([sys.executable,numpy.__file__,sys.path]))'],
        env={'HOME': '/tmp/home', 'PYTHONNOUSERSITE': '1'},
        capture_output=True, text=True, timeout=20, check=True)
    executable, origin, paths = json.loads(result.stdout)
    assert executable == sys.executable
    assert Path(origin).is_relative_to('/deps')
    assert not any('/home/jin' in value or '/tmp/home/.local' in value for value in paths)


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


def test_node_uses_isolated_validation_tools_with_boundary_intact():
    import shutil
    from tools.repository_layout.sandbox import require_boundary
    require_boundary()
    assert shutil.which('node') == '/deps/validation-tools/bin/node'
    result = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True)
    assert result.stdout.strip().startswith('v22.')


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


def test_native_identity_profile_mounts_only_four_synthetic_readonly_files(tmp_path):
    from tools.repository_layout.sandbox import sandbox_command
    snapshot = tmp_path / 'snapshot'
    snapshot.mkdir()
    deps = tmp_path / 'deps'
    (deps / 'lib/python3.12/site-packages').mkdir(parents=True)
    (deps / 'bin').mkdir()
    (deps / 'bin/python3').write_text('fixture')
    command = sandbox_command(snapshot, deps, ['python', '-V'], cwd='/snapshot', native_identity=True)
    fixture = snapshot / '.atr-native-identity'
    assert {p.name for p in fixture.iterdir()} == {'passwd', 'group', 'hosts', 'nsswitch.conf'}
    expected = {'passwd': f'audit:x:{os.getuid()}:{os.getgid()}:Audit fixture:/tmp/home:/bin/sh\n',
                'group': f'audit:x:{os.getgid()}:\n', 'hosts': '127.0.0.1 localhost\n::1 localhost\n',
                'nsswitch.conf': 'passwd: files\ngroup: files\nhosts: files\n'}
    for name, content in expected.items():
        assert (fixture / name).read_text() == content
        index = command.index('/etc/' + name)
        assert command[index - 2:index] == ['--ro-bind', str(fixture / name)]


@pytest.mark.skipif(os.environ.get('ATR_NATIVE_IDENTITY') != '1', reason='explicit native identity profile')
def test_native_identity_profile_is_readonly_and_retains_os_boundary():
    import pwd
    import socket
    from tools.repository_layout.sandbox import boundary_probe
    assert set(p.name for p in Path('/etc').iterdir()) == {'passwd', 'group', 'hosts', 'nsswitch.conf'}
    assert pwd.getpwuid(os.getuid()).pw_name == 'audit'
    assert pwd.getpwuid(os.getuid()).pw_dir == '/tmp/home'
    assert {row[4][0] for row in socket.getaddrinfo('localhost', 80)} <= {'127.0.0.1', '::1'}
    for name in ('passwd', 'group', 'hosts', 'nsswitch.conf'):
        with pytest.raises(OSError):
            Path('/etc', name).open('a')
    boundary = boundary_probe()
    assert boundary['host_paths_visible'] == boundary['device_nodes'] == []
    assert not boundary['non_loopback_connected'] and not boundary['host_pid_visible']


def _verify_fixture_process(lifespan_mode):
    from tools.repository_layout.sandbox import require_boundary
    require_boundary()
    result = subprocess.run(
        [sys.executable, "-S", "-m", "tools.repository_layout.fixture_server", "verify", lifespan_mode],
        capture_output=True, text=True, timeout=90,
    )
    # -rA retains successful child diagnostics in the enclosing raw receipt too.
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.splitlines()[-1])


def test_successful_fixture_child_diagnostics_are_retained(monkeypatch, capsys):
    result = subprocess.CompletedProcess([], 0, 'child diagnostic\n{"ok": true}\n',
                                         'synthetic child warning\n')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: result)
    assert _verify_fixture_process('import_only') == {'ok': True}
    captured = capsys.readouterr()
    assert captured.out == result.stdout
    assert captured.err == result.stderr


@pytest.mark.parametrize('mode', ['import_only', 'fake_services'])
def test_real_route_receipt_has_roots_origins_and_effect_counters(mode):
    result = _verify_fixture_process(mode)
    for route in ('/', '/ide', '/live', '/knowledge', '/api/graphs', '/api/modules', '/api/docs/agent-baseline'):
        assert result['routes'][route] == 200
    assert result['roots']['runtime_root'] == '/snapshot/runtime'
    assert result['roots']['repository_root'] == '/snapshot'
    assert result['roots']['system_root'] == '/snapshot/system'
    assert result['roots']['memory_root'].startswith('/tmp/atr-fixture-')
    assert result['import_origins']['app.main'] == '/snapshot/runtime/app/main.py'
    assert result['effects']['model_calls'] == 0
    assert result['effects']['plc_start'] == (1 if mode == 'fake_services' else 0)
    assert result['effects']['plc_stop'] == (1 if mode == 'fake_services' else 0)
    assert result['unexpected_effects'] == []


@pytest.mark.parametrize("already_imported", [False, True], ids=["fresh-parent", "collected-app-in-parent"])
def test_real_routes_inside_fixture_import_mode(monkeypatch, already_imported):
    if already_imported:
        # Model another suite's collection-time import without importing the app here.
        collected_module = ModuleType("app.main")
        monkeypatch.setitem(sys.modules, "app.main", collected_module)
    result = _verify_fixture_process("import_only")
    assert result["routes"]["/api/state"] == 200
    assert result["routes"]["/static/favicon.svg"] == 200
    assert result["module_assets"] >= 1
    assert result["unexpected_effects"] == []
    assert result["outside_imports"] == []
    if already_imported:
        assert sys.modules["app.main"] is collected_module


def test_real_lifespan_uses_injected_services():
    # Separate interpreter: imports and application globals cannot leak between modes.
    payload = _verify_fixture_process("fake_services")
    assert payload["lifespan_started"] is True
    assert payload["lifespan_stopped"] is True
    assert payload["unexpected_effects"] == []


def test_every_pinned_pytest_command_runs_async_tests(tmp_path):
    from tools.repository_layout.checks import CHECKS
    from tools.repository_layout.sandbox import require_boundary
    require_boundary()
    probe = tmp_path / "test_async_dispatch.py"
    probe.write_text(
        "import asyncio\nimport pytest\n"
        "@pytest.mark.asyncio\nasync def test_async_dispatch():\n"
        "    await asyncio.sleep(0)\n"
    )
    failures = {}
    for task_id, commands in CHECKS.items():
        for command in commands:
            if command[:3] != ["python", "-m", "pytest"]:
                continue
            plugins = [value for index, value in enumerate(command) if
                       value == "-p" or (index and command[index - 1] == "-p")]
            result = subprocess.run(
                [sys.executable, "-S", "-m", "pytest", *plugins, "-q", "-c", "/dev/null", str(probe)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode:
                failures[task_id] = result.stdout + result.stderr
    assert failures == {}, failures
