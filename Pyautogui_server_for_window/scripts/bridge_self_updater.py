"""Replace bounded ATR Windows Worker files and roll back failed restarts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import signal
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


def _safe_relative_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"invalid update path: {raw!r}")
    return path.as_posix()


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def apply_staged_release(
    *,
    package_root: Path,
    stage_root: Path,
    backup_root: Path,
    manifest: dict[str, Any],
    backup_id: str,
) -> dict[str, Any]:
    package_root = Path(package_root).resolve()
    stage_root = Path(stage_root).resolve()
    backup_dir = Path(backup_root).resolve() / str(backup_id)
    backup_files: list[dict[str, Any]] = []
    for item in manifest.get("files", []):
        relative = _safe_relative_path(item.get("path") if isinstance(item, dict) else item)
        source = (stage_root / relative).resolve()
        destination = (package_root / relative).resolve()
        if not source.is_relative_to(stage_root) or not destination.is_relative_to(package_root) or not source.is_file():
            raise ValueError(f"invalid staged update file: {relative}")
        existed = destination.is_file()
        if existed:
            _atomic_copy(destination, backup_dir / relative)
        backup_files.append({"path": relative, "existed": existed})
    _atomic_json(
        backup_dir / "backup_manifest.json",
        {
            "schema": "atr.windows_bridge_backup.v1",
            "version": str(manifest.get("version") or ""),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "files": backup_files,
        },
    )
    for item in backup_files:
        _atomic_copy(stage_root / item["path"], package_root / item["path"])
    return {"ok": True, "status": "applied", "backup_id": backup_id, "backup_dir": str(backup_dir)}


def restore_backup(*, package_root: Path, backup_dir: Path) -> dict[str, Any]:
    package_root = Path(package_root).resolve()
    backup_dir = Path(backup_dir).resolve()
    manifest = json.loads((backup_dir / "backup_manifest.json").read_text(encoding="utf-8"))
    restored: list[str] = []
    for item in manifest.get("files", []):
        relative = _safe_relative_path(item.get("path") if isinstance(item, dict) else item)
        destination = (package_root / relative).resolve()
        if not destination.is_relative_to(package_root):
            raise ValueError(f"invalid backup destination: {relative}")
        if bool(item.get("existed")):
            source = (backup_dir / relative).resolve()
            if not source.is_relative_to(backup_dir) or not source.is_file():
                raise ValueError(f"backup file missing: {relative}")
            _atomic_copy(source, destination)
        elif destination.exists():
            destination.unlink()
        restored.append(relative)
    return {"ok": True, "status": "rolled_back", "backup_id": backup_dir.name, "files": restored}


def _wait_for_exit(pid: int, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + max(1.0, timeout_s)
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (OSError, SystemError):
            return
        time.sleep(0.2)
    raise TimeoutError(f"bridge process {pid} did not exit")


def _terminate_process_tree(pid: int) -> None:
    """Terminate only the stale Worker process tree after graceful shutdown stalls."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(int(pid)), "/T", "/F"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return
    os.kill(int(pid), signal.SIGKILL)


def _ensure_process_exit(pid: int) -> None:
    try:
        _wait_for_exit(pid)
    except TimeoutError:
        _terminate_process_tree(pid)
        _wait_for_exit(pid, timeout_s=10.0)


def _launch(command: list[str], cwd: Path) -> subprocess.Popen[Any]:
    flags = 0
    if os.name == "nt":
        flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )  # type: ignore[attr-defined]
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        creationflags=flags,
        close_fds=os.name != "nt",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def sync_python_dependencies(
    *,
    command: list[str],
    package_root: Path,
    previous_requirements: Path | None = None,
) -> dict[str, Any]:
    """Install Worker requirements for script installs; frozen builds bundle them."""
    package_root = Path(package_root).resolve()
    requirements = package_root / "requirements-windows.txt"
    if not requirements.is_file():
        return {"ok": True, "status": "not_configured", "requirements": "requirements-windows.txt"}
    previous = Path(previous_requirements).resolve() if previous_requirements is not None else None
    if previous is not None and previous.is_file() and previous.read_bytes() == requirements.read_bytes():
        return {"ok": True, "status": "unchanged", "requirements": "requirements-windows.txt"}
    executable = str(command[0] if command else "").strip()
    launcher = PureWindowsPath(executable).name.lower()
    is_python = launcher in {"py", "py.exe", "python", "python.exe", "python3", "python3.exe"} or (
        launcher.startswith("python") and launcher.endswith(".exe")
    )
    if not is_python:
        return {"ok": True, "status": "bundled_runtime", "requirements": "requirements-windows.txt"}
    subprocess.run(
        [
            executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements),
        ],
        check=True,
        cwd=str(package_root),
        timeout=300,
    )
    return {"ok": True, "status": "installed", "requirements": "requirements-windows.txt"}


def _wait_for_health(url: str, timeout_s: float, *, expected_version: str = "") -> bool:
    deadline = time.monotonic() + max(1.0, timeout_s)
    expected_version = str(expected_version or "").strip()
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1.0) as response:
                payload = response.read().decode("ascii", errors="strict").strip()
            if payload.startswith("{"):
                legacy = json.loads(payload)
                ready = legacy.get("ok") is True
                current_version = str(legacy.get("server_version") or "").rsplit("/", 1)[-1]
            else:
                parts = payload.split(maxsplit=1)
                ready = parts[:1] == ["ok"]
                current_version = parts[1] if len(parts) == 2 else ""
            if ready and (not expected_version or current_version == expected_version):
                return True
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return False


def _run(args: argparse.Namespace) -> int:
    package_root = Path(args.package_root).resolve()
    update_root = Path(args.update_root).resolve()
    state_path = update_root / "status.json"
    command = json.loads(args.command_json)
    if not isinstance(command, list) or not command:
        raise ValueError("restart command must be a non-empty JSON list")
    command = [str(value) for value in command]
    update_lock = update_root / "update_in_progress.json"
    _atomic_json(
        update_lock,
        {
            "status": "applying" if args.mode == "apply" else "rolling_back",
            "updater_pid": os.getpid(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
    backup_dir: Path | None = None
    process: subprocess.Popen[Any] | None = None
    try:
        _ensure_process_exit(int(args.pid))
        if args.mode == "apply":
            stage_root = Path(args.stage_root).resolve()
            manifest = json.loads((stage_root / "manifest.json").read_text(encoding="utf-8"))
            backup_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            applied = apply_staged_release(
                package_root=package_root,
                stage_root=stage_root,
                backup_root=update_root / "backups",
                manifest=manifest,
                backup_id=backup_id,
            )
            backup_dir = Path(applied["backup_dir"])
            target_version = str(manifest.get("version") or "")
        else:
            backup_dir = Path(args.backup_dir).resolve()
            restore_backup(package_root=package_root, backup_dir=backup_dir)
            target_version = "rollback"
        previous_requirements = backup_dir / "requirements-windows.txt" if args.mode == "apply" and backup_dir else None
        dependency_sync = sync_python_dependencies(
            command=command,
            package_root=package_root,
            previous_requirements=previous_requirements,
        )
        process = _launch(command, package_root)
        expected_version = target_version if args.mode == "apply" else ""
        if not _wait_for_health(
            args.health_url,
            float(args.health_timeout_s),
            expected_version=expected_version,
        ):
            try:
                process.terminate()
            except OSError:
                pass
            raise RuntimeError("updated bridge failed health verification")
        _atomic_json(
            state_path,
            {
                "ok": True,
                "status": "updated" if args.mode == "apply" else "rolled_back",
                "version": target_version,
                "backup_id": backup_dir.name if backup_dir else "",
                "dependency_sync": dependency_sync,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        return 0
    except Exception as exc:
        recovery_status = "not_attempted"
        recovery_error = ""
        if args.mode == "apply" and backup_dir is not None:
            try:
                restore_backup(package_root=package_root, backup_dir=backup_dir)
                _launch(command, package_root)
                recovered = _wait_for_health(args.health_url, float(args.health_timeout_s))
                recovery_status = "previous_worker_restarted" if recovered else "previous_worker_restart_unverified"
            except Exception as recovery_exc:
                recovery_status = "recovery_failed"
                recovery_error = f"{recovery_exc.__class__.__name__}: {str(recovery_exc)[:240]}"
        _atomic_json(
            state_path,
            {
                "ok": False,
                "status": "failed",
                "failure_code": "PYAUTOGUI_UPDATE_RESTART_FAILED",
                "message": str(exc),
                "recovery_status": recovery_status,
                "recovery_error": recovery_error,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        return 1
    finally:
        try:
            update_lock.unlink(missing_ok=True)
        except OSError:
            pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ATR Windows Worker self updater")
    parser.add_argument("--mode", choices=("apply", "rollback"), required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--update-root", required=True)
    parser.add_argument("--stage-root", default="")
    parser.add_argument("--backup-dir", default="")
    parser.add_argument("--command-json", required=True)
    parser.add_argument("--health-url", required=True)
    parser.add_argument("--health-timeout-s", type=float, default=30.0)
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(_run(_parse_args()))
