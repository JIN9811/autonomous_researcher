from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_updater_module():
    path = Path(__file__).resolve().parents[2] / "Pyautogui_server_for_window" / "scripts" / "bridge_self_updater.py"
    spec = importlib.util.spec_from_file_location("windows_bridge_self_updater_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_windows_updater_launch_breaks_away_from_parent_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_updater_module()
    observed: dict[str, object] = {}
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(module.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(module.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000, raising=False)

    def fake_popen(command, **kwargs):
        observed.update({"command": command, **kwargs})
        return SimpleNamespace(pid=42)

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    module._launch(["python", "bridge.py"], tmp_path)

    assert observed["creationflags"] == 0x01000208
    assert observed["cwd"] == str(tmp_path)
    assert observed["stdin"] is module.subprocess.DEVNULL
    assert observed["stdout"] is module.subprocess.DEVNULL
    assert observed["stderr"] is module.subprocess.DEVNULL


def test_windows_updater_syncs_requirements_with_the_bridge_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_updater_module()
    requirements = tmp_path / "requirements-windows.txt"
    requirements.write_text("pynput>=1.7.7,<2\n", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.sync_python_dependencies(
        command=[r"C:\\ATR\\.venv\\Scripts\\python.exe", r"C:\\ATR\\bridge\\server.py"],
        package_root=tmp_path,
    )

    assert result["status"] == "installed"
    assert calls == [
        (
            [
                r"C:\\ATR\\.venv\\Scripts\\python.exe",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(requirements),
            ],
            {"check": True, "cwd": str(tmp_path), "timeout": 300},
        )
    ]


def test_windows_updater_skips_pip_when_requirements_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_updater_module()
    requirements = tmp_path / "package" / "requirements-windows.txt"
    previous = tmp_path / "backup" / "requirements-windows.txt"
    requirements.parent.mkdir(parents=True)
    previous.parent.mkdir(parents=True)
    requirements.write_text("pynput>=1.7.7,<2\n", encoding="utf-8")
    previous.write_text(requirements.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("pip must not run for unchanged requirements"),
    )

    result = module.sync_python_dependencies(
        command=[r"C:\ATR\.venv\Scripts\python.exe", r"C:\ATR\bridge\server.py"],
        package_root=requirements.parent,
        previous_requirements=previous,
    )

    assert result["status"] == "unchanged"


def test_windows_updater_skips_pip_for_frozen_bridge_executable(tmp_path: Path) -> None:
    module = _load_updater_module()
    (tmp_path / "requirements-windows.txt").write_text("pynput>=1.7.7,<2\n", encoding="utf-8")

    result = module.sync_python_dependencies(
        command=[r"C:\\ATR\\WindowsPyAutoGUIBridge.exe"],
        package_root=tmp_path,
    )

    assert result == {"ok": True, "status": "bundled_runtime", "requirements": "requirements-windows.txt"}


def test_apply_failure_restores_backup_and_restarts_previous_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_updater_module()
    package_root = tmp_path / "package"
    stage_root = tmp_path / "stage"
    update_root = tmp_path / "updates"
    backup_dir = update_root / "backups" / "backup-1"
    package_root.mkdir()
    stage_root.mkdir()
    backup_dir.mkdir(parents=True)
    (stage_root / "manifest.json").write_text(json.dumps({"version": "2026.08.29.10", "files": []}))
    calls: list[str] = []
    monkeypatch.setattr(module, "_wait_for_exit", lambda _pid: None)
    monkeypatch.setattr(
        module,
        "apply_staged_release",
        lambda **_kwargs: {"ok": True, "backup_dir": str(backup_dir), "backup_id": "backup-1"},
    )
    monkeypatch.setattr(
        module,
        "sync_python_dependencies",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("pip unavailable")),
    )
    monkeypatch.setattr(module, "restore_backup", lambda **_kwargs: calls.append("restore") or {"ok": True})
    monkeypatch.setattr(module, "_launch", lambda _command, _cwd: calls.append("launch") or SimpleNamespace(pid=42))
    monkeypatch.setattr(module, "_wait_for_health", lambda *_args, **_kwargs: True)
    args = SimpleNamespace(
        mode="apply",
        pid=123,
        package_root=str(package_root),
        update_root=str(update_root),
        stage_root=str(stage_root),
        backup_dir="",
        command_json=json.dumps(["python", "bridge.py"]),
        health_url="http://127.0.0.1:8765/discovery",
        health_timeout_s=30.0,
    )

    returncode = module._run(args)
    status = json.loads((update_root / "status.json").read_text(encoding="utf-8"))

    assert returncode == 1
    assert calls == ["restore", "launch"]
    assert status["recovery_status"] == "previous_worker_restarted"


def test_run_force_terminates_worker_that_does_not_finish_graceful_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_updater_module()
    package_root = tmp_path / "package"
    stage_root = tmp_path / "stage"
    update_root = tmp_path / "updates"
    backup_dir = update_root / "backups" / "backup-1"
    package_root.mkdir()
    stage_root.mkdir()
    backup_dir.mkdir(parents=True)
    (stage_root / "manifest.json").write_text(json.dumps({"version": "2026.08.29.12", "files": []}))
    waits: list[int] = []
    terminated: list[int] = []

    def wait_for_exit(pid: int, timeout_s: float = 30.0) -> None:
        waits.append(pid)
        if len(waits) == 1:
            raise TimeoutError("graceful shutdown stalled")

    monkeypatch.setattr(module, "_wait_for_exit", wait_for_exit)
    monkeypatch.setattr(
        module,
        "_terminate_process_tree",
        lambda pid: terminated.append(pid),
        raising=False,
    )
    monkeypatch.setattr(
        module,
        "apply_staged_release",
        lambda **_kwargs: {"ok": True, "backup_dir": str(backup_dir), "backup_id": "backup-1"},
    )
    monkeypatch.setattr(
        module,
        "sync_python_dependencies",
        lambda **_kwargs: {"ok": True, "status": "unchanged"},
    )
    monkeypatch.setattr(module, "_launch", lambda _command, _cwd: SimpleNamespace(pid=42))
    monkeypatch.setattr(module, "_wait_for_health", lambda *_args, **_kwargs: True)
    args = SimpleNamespace(
        mode="apply",
        pid=123,
        package_root=str(package_root),
        update_root=str(update_root),
        stage_root=str(stage_root),
        backup_dir="",
        command_json=json.dumps(["python", "bridge.py"]),
        health_url="http://127.0.0.1:8765/discovery",
        health_timeout_s=30.0,
    )

    returncode = module._run(args)
    status = json.loads((update_root / "status.json").read_text(encoding="utf-8"))

    assert returncode == 0
    assert waits == [123, 123]
    assert terminated == [123]
    assert status["status"] == "updated"


def test_wait_for_exit_accepts_windows_system_error_as_process_already_gone(monkeypatch) -> None:
    module = _load_updater_module()
    monkeypatch.setattr(module.os, "kill", lambda *_args: (_ for _ in ()).throw(SystemError("kill probe failed")))

    module._wait_for_exit(123, timeout_s=1.0)


def test_update_lock_is_present_during_apply_and_removed_after_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_updater_module()
    package_root = tmp_path / "package"
    stage_root = tmp_path / "stage"
    update_root = tmp_path / "updates"
    backup_dir = update_root / "backups" / "backup-1"
    package_root.mkdir()
    stage_root.mkdir()
    backup_dir.mkdir(parents=True)
    (stage_root / "manifest.json").write_text(json.dumps({"version": "next", "files": []}))
    observed: list[bool] = []
    monkeypatch.setattr(module, "_ensure_process_exit", lambda _pid: observed.append((update_root / "update_in_progress.json").is_file()))
    monkeypatch.setattr(
        module,
        "apply_staged_release",
        lambda **_kwargs: {"ok": True, "backup_dir": str(backup_dir), "backup_id": "backup-1"},
    )
    monkeypatch.setattr(module, "sync_python_dependencies", lambda **_kwargs: {"ok": True, "status": "unchanged"})
    monkeypatch.setattr(module, "_launch", lambda *_args: SimpleNamespace(pid=42))
    monkeypatch.setattr(module, "_wait_for_health", lambda *_args, **_kwargs: True)
    args = SimpleNamespace(
        mode="apply",
        pid=123,
        package_root=str(package_root),
        update_root=str(update_root),
        stage_root=str(stage_root),
        backup_dir="",
        command_json=json.dumps(["python", "bridge.py"]),
        health_url="http://127.0.0.1:8765/discovery",
        health_timeout_s=30.0,
    )

    assert module._run(args) == 0
    assert observed == [True]
    assert not (update_root / "update_in_progress.json").exists()


def test_apply_staged_release_creates_backup_and_replaces_only_manifest_files(tmp_path: Path) -> None:
    module = _load_updater_module()
    package_root = tmp_path / "package"
    stage_root = tmp_path / "stage"
    backup_root = tmp_path / "backups"
    relative = "bridge/windows_pyautogui_bridge_server.py"
    current = package_root / relative
    staged = stage_root / relative
    current.parent.mkdir(parents=True)
    staged.parent.mkdir(parents=True)
    current.write_text("old\n", encoding="utf-8")
    staged.write_text("new\n", encoding="utf-8")
    manifest = {"version": "2026.08.28.2", "files": [{"path": relative}]}

    result = module.apply_staged_release(
        package_root=package_root,
        stage_root=stage_root,
        backup_root=backup_root,
        manifest=manifest,
        backup_id="backup-1",
    )

    assert result["ok"] is True
    assert current.read_text(encoding="utf-8") == "new\n"
    assert (backup_root / "backup-1" / relative).read_text(encoding="utf-8") == "old\n"
    assert json.loads((backup_root / "backup-1" / "backup_manifest.json").read_text(encoding="utf-8"))["version"] == "2026.08.28.2"


def test_restore_backup_restores_previous_files(tmp_path: Path) -> None:
    module = _load_updater_module()
    package_root = tmp_path / "package"
    backup_dir = tmp_path / "backups" / "backup-1"
    relative = "bridge/windows_pyautogui_bridge_server.py"
    current = package_root / relative
    backup = backup_dir / relative
    current.parent.mkdir(parents=True)
    backup.parent.mkdir(parents=True)
    current.write_text("new\n", encoding="utf-8")
    backup.write_text("old\n", encoding="utf-8")
    (backup_dir / "backup_manifest.json").write_text(
        json.dumps({"files": [{"path": relative, "existed": True}]}),
        encoding="utf-8",
    )

    result = module.restore_backup(package_root=package_root, backup_dir=backup_dir)

    assert result["ok"] is True
    assert current.read_text(encoding="utf-8") == "old\n"


def test_health_verification_requires_target_release_version(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_updater_module()
    responses = [
        b"ok 2026.08.29.2",
        b"ok 2026.08.29.5",
    ]

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: _Response(responses.pop(0)))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    assert module._wait_for_health(
        "http://127.0.0.1:8765/ping",
        1.0,
        expected_version="2026.08.29.5",
    ) is True
    assert responses == []


def test_health_verification_accepts_legacy_discovery_json_during_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_updater_module()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"ok": True, "server_version": "WindowsPyAutoGUIBridge/2026.08.29.17"}
            ).encode("utf-8")

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: _Response())

    assert module._wait_for_health(
        "http://127.0.0.1:8765/discovery",
        1.0,
        expected_version="2026.08.29.17",
    ) is True
