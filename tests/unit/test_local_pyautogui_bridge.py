"""Tests for the ATR-owned localhost PyAutoGUI bridge supervisor."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from utils.local_pyautogui_bridge import LocalPyAutoGUIBridgeSupervisor


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
