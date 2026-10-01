"""Tests for the ATR-owned localhost PyAutoGUI bridge supervisor."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest

from utils.local_pyautogui_bridge import LocalPyAutoGUIBridgeSupervisor


def test_injected_bridge_separates_source_state_and_desktop_environment(tmp_path, monkeypatch):
    from tests.unit.test_runtime_worker_origins import bound_layout
    paths, _, _ = bound_layout(tmp_path)
    python = paths.repository_root / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.touch()
    supervisor = LocalPyAutoGUIBridgeSupervisor(paths.repository_root, paths=paths)
    command = supervisor.build_command()
    assert command[0] == str(python)
    assert command[1] == str(paths.runtime_root / 'Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py')
    for option, target in {
        '--token-file': paths.memory_root / 'local_pyautogui_bridge.token',
        '--reference-dir': paths.memory_root / 'local_pyautogui_locators',
        '--program-dir': paths.memory_root / 'local_pyautogui_programs',
        '--artifact-dir': paths.artifact_root / 'local_pyautogui_bridge/artifacts',
        '--utm-export-dir': paths.output_root / 'local_pyautogui_bridge/utm_exports',
        '--recording-dir': paths.user_file_root / 'local_pyautogui_bridge/recordings',
        '--demo-dir': paths.runtime_root / 'Pyautogui_server_for_window/demo',
    }.items():
        assert command[command.index(option) + 1] == str(target)
    assert supervisor.pid_path == paths.run_root / 'local_pyautogui_bridge/local_bridge.pid'
    assert supervisor.log_path == paths.log_root / 'local_pyautogui_bridge/local_bridge.log'
    monkeypatch.setenv('DISPLAY', ':fixture')
    monkeypatch.setenv('XAUTHORITY', '/tmp/fixture-authority')
    monkeypatch.setenv('XDG_SESSION_TYPE', 'x11')
    monkeypatch.setenv('XDG_RUNTIME_DIR', '/tmp/fixture-session')
    monkeypatch.setenv('WAYLAND_DISPLAY', 'fixture-wayland')
    monkeypatch.setenv('DBUS_SESSION_BUS_ADDRESS', 'not-required')
    monkeypatch.setenv('UNRELATED_SECRET', 'not-for-bridge')
    monkeypatch.setenv('PYTHONPATH', '/original/source')
    monkeypatch.setenv('ATR_WINDOWS_BRIDGE_PACKAGE_ROOT', '/original/package')
    monkeypatch.setenv('WINDOWS_PYAUTOGUI_RECORDING_DIR', '/original/recordings')
    launched = []
    def launch(argv, **kwargs):
        launched.append((argv, kwargs))
        return SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr('utils.local_pyautogui_bridge.subprocess.Popen', launch)
    monkeypatch.setattr(supervisor, 'status', lambda: {'running': False})
    monkeypatch.setattr(supervisor, '_health', lambda: {'ok': True})
    assert supervisor.start()['status'] == 'running'
    argv, options = launched[0]
    assert options['cwd'] == str(paths.runtime_root)
    assert options['env']['DISPLAY'] == ':fixture'
    assert options['env']['XAUTHORITY'] == '/tmp/fixture-authority'
    assert options['env']['XDG_SESSION_TYPE'] == 'x11'
    assert options['env']['XDG_RUNTIME_DIR'] == '/tmp/fixture-session'
    assert options['env']['WAYLAND_DISPLAY'] == 'fixture-wayland'
    assert options['env']['ATR_WINDOWS_BRIDGE_PACKAGE_ROOT'] == str(paths.runtime_root / 'Pyautogui_server_for_window')
    assert options['env']['WINDOWS_PYAUTOGUI_RECORDING_DIR'] == str(paths.user_file_root / 'local_pyautogui_bridge/recordings')
    assert options['env']['WINDOWS_PYAUTOGUI_BRIDGE_ARTIFACT_ROOT'] == str(paths.artifact_root / 'local_pyautogui_bridge/artifacts')
    assert not {'PYTHONPATH', 'UNRELATED_SECRET', 'DBUS_SESSION_BUS_ADDRESS'} & options['env'].keys()
    assert not (paths.runtime_root / 'runs').exists()


def test_bridge_rejects_contradictory_repository_before_store_access(tmp_path):
    from tests.unit.test_runtime_worker_origins import bound_layout
    paths, _, _ = bound_layout(tmp_path)
    with pytest.raises(ValueError, match='repository_root'):
        LocalPyAutoGUIBridgeSupervisor(tmp_path / 'wrong', paths=paths)
    assert not paths.memory_root.exists()


def test_local_bridge_token_is_private_and_reused(tmp_path: Path) -> None:
    supervisor = LocalPyAutoGUIBridgeSupervisor(tmp_path)

    first = supervisor.ensure_token()
    second = supervisor.ensure_token()

    assert first == second
    assert len(first) >= 32
    assert supervisor.token_path.stat().st_mode & 0o777 == 0o600


def test_local_bridge_command_is_localhost_linux_and_uses_shared_server(tmp_path: Path) -> None:
    supervisor = LocalPyAutoGUIBridgeSupervisor(tmp_path, python_executable=Path("/test/python"))

    command = supervisor.build_command()

    assert command[0] == "/test/python"
    assert str(tmp_path / "Pyautogui_server_for_window" / "bridge" / "windows_pyautogui_bridge_server.py") in command
    assert command[command.index("--platform") + 1] == "linux"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8767"
    assert command[command.index("--token-file") + 1] == str(supervisor.token_path)


def test_local_bridge_start_is_idempotent_when_owned_process_is_healthy(tmp_path: Path, monkeypatch) -> None:
    supervisor = LocalPyAutoGUIBridgeSupervisor(tmp_path)
    monkeypatch.setattr(
        supervisor,
        "status",
        lambda: {
            "ok": True,
            "status": "running",
            "running": True,
            "healthy": True,
            "pid": 123,
            "bridge_url": supervisor.bridge_url,
        },
    )

    result = supervisor.start()

    assert result["status"] == "running"
    assert result["idempotent"] is True


def test_local_bridge_start_does_not_duplicate_a_running_degraded_process(tmp_path: Path, monkeypatch) -> None:
    supervisor = LocalPyAutoGUIBridgeSupervisor(tmp_path)
    monkeypatch.setattr(
        supervisor,
        "status",
        lambda: {
            "ok": True,
            "status": "running",
            "running": True,
            "healthy": False,
            "pid": 123,
            "bridge_url": supervisor.bridge_url,
        },
    )

    result = supervisor.start()

    assert result["status"] == "running"
    assert result["idempotent"] is True


def test_local_bridge_candidate_is_registered_without_implicit_selection(tmp_path: Path) -> None:
    supervisor = LocalPyAutoGUIBridgeSupervisor(tmp_path)
    calls: list[dict[str, object]] = []

    class _Bridge:
        def save_connection(self, payload):
            calls.append(dict(payload))
            return {"ok": True, "selected_candidate": payload["candidate_alias"]}

    result = supervisor.ensure_candidate(_Bridge(), select=False)

    assert result["ok"] is True
    assert calls[0]["candidate_alias"] == "local_development"
    assert calls[0]["bridge_url"] == "http://127.0.0.1:8767"
    assert calls[0]["platform"] == "linux"
    assert calls[0]["scope"] == "localhost"
    assert calls[0]["managed_local"] is True
    assert result["selected"] is False


def test_local_bridge_candidate_can_be_explicitly_selected(tmp_path: Path) -> None:
    supervisor = LocalPyAutoGUIBridgeSupervisor(tmp_path)
    selected: list[str] = []

    class _Bridge:
        def save_connection(self, payload):
            return {"ok": True, "selected_candidate": payload["candidate_alias"]}

        def select_candidate(self, payload):
            selected.append(str(payload["candidate_alias"]))
            return {"ok": True, "selected_candidate": payload["candidate_alias"]}

    result = supervisor.ensure_candidate(_Bridge(), select=True)

    assert selected == ["local_development"]
    assert result["selected"] is True


def test_local_bridge_stop_refuses_unowned_pid(tmp_path: Path, monkeypatch) -> None:
    supervisor = LocalPyAutoGUIBridgeSupervisor(tmp_path)
    supervisor.pid_path.parent.mkdir(parents=True, exist_ok=True)
    supervisor.pid_path.write_text("456\n", encoding="utf-8")
    monkeypatch.setattr(supervisor, "_pid_running", lambda _pid: True)
    monkeypatch.setattr(supervisor, "_owns_pid", lambda _pid: False)

    result = supervisor.stop()

    assert result["ok"] is False
    assert result["failure_code"] == "LOCAL_PYAUTOGUI_PROCESS_NOT_OWNED"
