from __future__ import annotations

import importlib.util
import json
from io import StringIO
import sys
from pathlib import Path


def _load_supervisor_module():
    path = Path(__file__).resolve().parents[2] / "Pyautogui_server_for_window" / "scripts" / "bridge_supervisor.py"
    spec = importlib.util.spec_from_file_location("windows_bridge_supervisor_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_supervisor_starts_canonical_worker_when_health_is_down(tmp_path: Path) -> None:
    module = _load_supervisor_module()
    launched: list[list[str]] = []
    supervisor = module.BridgeSupervisor(
        command=["python", str(tmp_path / "bridge" / "server.py")],
        package_root=tmp_path,
        update_lock=tmp_path / "updates" / "update_in_progress.json",
        status_path=tmp_path / "supervisor_status.json",
        health_check=lambda: False,
        launcher=lambda command, _cwd: launched.append(list(command)) or module.CompletedProcess(pid=42),
    )

    status = supervisor.step()

    assert status["status"] == "worker_started"
    assert launched == [["python", str(tmp_path / "bridge" / "server.py")]]


def test_supervisor_never_starts_worker_while_update_lock_is_active(tmp_path: Path) -> None:
    module = _load_supervisor_module()
    update_lock = tmp_path / "updates" / "update_in_progress.json"
    update_lock.parent.mkdir(parents=True)
    update_lock.write_text(json.dumps({"status": "applying"}), encoding="utf-8")
    supervisor = module.BridgeSupervisor(
        command=["python", "bridge.py"],
        package_root=tmp_path,
        update_lock=update_lock,
        status_path=tmp_path / "supervisor_status.json",
        health_check=lambda: False,
        launcher=lambda *_args: (_ for _ in ()).throw(AssertionError("worker must stay stopped during update")),
    )

    status = supervisor.step()

    assert status["status"] == "update_in_progress"


def test_supervisor_does_not_duplicate_a_healthy_worker(tmp_path: Path) -> None:
    module = _load_supervisor_module()
    supervisor = module.BridgeSupervisor(
        command=["python", "bridge.py"],
        package_root=tmp_path,
        update_lock=tmp_path / "updates" / "update_in_progress.json",
        status_path=tmp_path / "supervisor_status.json",
        health_check=lambda: True,
        launcher=lambda *_args: (_ for _ in ()).throw(AssertionError("healthy worker must not be duplicated")),
    )

    status = supervisor.step()

    assert status["status"] == "worker_ready"


def test_supervisor_replaces_worker_that_never_becomes_healthy(tmp_path: Path) -> None:
    module = _load_supervisor_module()
    now = [0.0]
    launched = []

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout: float):
            return self.returncode

    def launch(_command, _cwd):
        process = Process(100 + len(launched))
        launched.append(process)
        return process

    supervisor = module.BridgeSupervisor(
        command=["python", "bridge.py"],
        package_root=tmp_path,
        update_lock=tmp_path / "updates" / "update_in_progress.json",
        status_path=tmp_path / "supervisor_status.json",
        health_check=lambda: False,
        launcher=launch,
        monotonic=lambda: now[0],
        startup_timeout_s=30.0,
    )

    supervisor.step()
    now[0] = 31.0
    status = supervisor.step()

    assert len(launched) == 2
    assert launched[0].terminated is True
    assert status["status"] == "worker_started"
    assert status["replaced_unhealthy_pid"] == 100


def test_supervisor_loads_worker_command_from_file_without_cli_json_quoting(tmp_path: Path) -> None:
    module = _load_supervisor_module()
    command_path = tmp_path / "worker-command.json"
    expected = [r"C:\Program Files\ATR\.venv\Scripts\python.exe", r"C:\Program Files\ATR\bridge\worker.py"]
    command_path.write_text(json.dumps(expected), encoding="utf-8")

    command = module.load_worker_command(command_file=command_path)

    assert command == expected


def test_supervisor_health_check_accepts_compact_plaintext_ping(monkeypatch) -> None:
    module = _load_supervisor_module()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b"ok 2026.08.29.17"

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: Response())

    assert module._default_health_check("http://127.0.0.1:8765/ping") is True


def test_supervisor_defaults_to_five_second_probe_interval(monkeypatch, tmp_path: Path) -> None:
    module = _load_supervisor_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bridge_supervisor.py",
            "--command-json",
            '["python","worker.py"]',
            "--package-root",
            str(tmp_path),
            "--health-url",
            "http://127.0.0.1:8765/ping",
            "--update-lock",
            str(tmp_path / "update.lock"),
            "--status-path",
            str(tmp_path / "status.json"),
            "--singleton-lock",
            str(tmp_path / "supervisor.lock"),
        ],
    )

    assert module._parse_args().interval_s == 5.0


def test_supervisor_console_prints_identity_and_only_state_changes() -> None:
    module = _load_supervisor_module()
    output = StringIO()
    console = module.SupervisorConsole(
        endpoint="http://127.0.0.1:8765",
        release_version="2026.08.30.21",
        stream=output,
    )

    console.show_header()
    console.show_status(
        {
            "status": "worker_ready",
            "worker_pid": 1234,
            "updated_at": "2026-08-30T01:30:00Z",
        }
    )
    console.show_status(
        {
            "status": "worker_ready",
            "worker_pid": 1234,
            "updated_at": "2026-08-30T01:30:05Z",
        }
    )
    console.show_status(
        {
            "status": "update_in_progress",
            "worker_pid": 0,
            "updated_at": "2026-08-30T01:30:10Z",
        }
    )

    rendered = output.getvalue()
    assert "ATR PyAutoGUI Bridge Supervisor" in rendered
    assert "Release     2026.08.30.21" in rendered
    assert "Endpoint    http://127.0.0.1:8765" in rendered
    assert rendered.count("READY") == 1
    assert rendered.count("UPDATING") == 1
    assert "Worker PID  1234" in rendered
    assert "Keep this window open" in rendered
