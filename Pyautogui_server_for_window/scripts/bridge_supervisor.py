"""Independent watchdog for the ATR Windows PyAutoGUI Worker."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen


@dataclass
class CompletedProcess:
    """Small process contract used by the supervisor and its tests."""

    pid: int

    def poll(self) -> int | None:
        return None


class SupervisorConsole:
    """Small, low-noise status display for the persistent supervisor window."""

    _LABELS = {
        "worker_ready": "READY",
        "worker_started": "STARTING",
        "worker_starting": "STARTING",
        "update_in_progress": "UPDATING",
    }

    def __init__(self, *, endpoint: str, release_version: str, stream: Any = sys.stdout) -> None:
        self.endpoint = str(endpoint).removesuffix("/ping")
        self.release_version = str(release_version or "unknown")
        self.stream = stream
        self._last_state: tuple[str, int, int] | None = None

    def _write(self, text: str) -> None:
        self.stream.write(text + "\n")
        flush = getattr(self.stream, "flush", None)
        if callable(flush):
            flush()

    def show_header(self) -> None:
        self._write("=" * 62)
        self._write(" ATR PyAutoGUI Bridge Supervisor")
        self._write(" Keeps the Worker available for ATR equipment control.")
        self._write("")
        self._write(f" Release     {self.release_version}")
        self._write(f" Endpoint    {self.endpoint}")
        self._write(" Keep this window open while using ATR equipment control.")
        self._write("=" * 62)

    def show_status(self, payload: dict[str, Any]) -> None:
        status = str(payload.get("status") or "unknown")
        worker_pid = int(payload.get("worker_pid") or 0)
        replaced_pid = int(payload.get("replaced_unhealthy_pid") or 0)
        state = (status, worker_pid, replaced_pid)
        if state == self._last_state:
            return
        self._last_state = state
        label = self._LABELS.get(status, status.replace("_", " ").upper())
        updated_at = str(payload.get("updated_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        pid_text = str(worker_pid) if worker_pid else "-"
        suffix = f" | Replaced unhealthy PID {replaced_pid}" if replaced_pid else ""
        self._write(f"[{updated_at}] {label:<10} Worker PID  {pid_text}{suffix}")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _default_health_check(url: str) -> bool:
    try:
        with urlopen(url, timeout=1.0) as response:
            payload = response.read().decode("ascii", errors="strict").strip()
        return payload == "ok" or payload.startswith("ok ")
    except (OSError, URLError, ValueError, UnicodeDecodeError):
        return False


def _default_launcher(command: list[str], cwd: Path) -> subprocess.Popen[Any]:
    return subprocess.Popen(command, cwd=str(cwd))


def load_worker_command(*, command_file: Path | None = None, command_json: str = "") -> list[str]:
    """Load the Worker argv without relying on native-shell JSON quoting."""
    if command_file is not None:
        raw_command = Path(command_file).read_text(encoding="utf-8-sig")
    else:
        raw_command = command_json
    command = json.loads(raw_command)
    if not isinstance(command, list) or not command or not all(isinstance(value, str) and value for value in command):
        raise ValueError("Worker command must contain a non-empty list of strings")
    return command


class BridgeSupervisor:
    """Keep one canonical Worker alive without coupling its lifecycle to updates."""

    def __init__(
        self,
        *,
        command: list[str],
        package_root: Path,
        update_lock: Path,
        status_path: Path,
        health_check: Callable[[], bool],
        launcher: Callable[[list[str], Path], Any] = _default_launcher,
        monotonic: Callable[[], float] = time.monotonic,
        startup_timeout_s: float = 30.0,
    ) -> None:
        if not command:
            raise ValueError("Worker command is required")
        self.command = [str(value) for value in command]
        self.package_root = Path(package_root).resolve()
        self.update_lock = Path(update_lock).resolve()
        self.status_path = Path(status_path).resolve()
        self.health_check = health_check
        self.launcher = launcher
        self.monotonic = monotonic
        self.startup_timeout_s = max(1.0, float(startup_timeout_s))
        self.worker: Any | None = None
        self._worker_started_at: float | None = None
        self._launched_once = False

    def _write_status(self, status: str, **extra: Any) -> dict[str, Any]:
        payload = {
            "ok": status in {"worker_ready", "worker_started", "worker_starting", "update_in_progress"},
            "status": status,
            "supervisor_pid": os.getpid(),
            "worker_pid": int(getattr(self.worker, "pid", 0) or 0),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **extra,
        }
        _atomic_json(self.status_path, payload)
        return payload

    def step(self) -> dict[str, Any]:
        if self.update_lock.is_file():
            return self._write_status("update_in_progress")
        if self.health_check():
            return self._write_status("worker_ready")
        if self.worker is not None and callable(getattr(self.worker, "poll", None)) and self.worker.poll() is None:
            started_at = self._worker_started_at if self._worker_started_at is not None else self.monotonic()
            if self.monotonic() - started_at <= self.startup_timeout_s:
                return self._write_status("worker_starting")
            replaced_unhealthy_pid = int(getattr(self.worker, "pid", 0) or 0)
            self.worker.terminate()
            try:
                self.worker.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                kill = getattr(self.worker, "kill", None)
                if callable(kill):
                    kill()
            self.worker = None
        else:
            replaced_unhealthy_pid = 0
        command = list(self.command)
        if self._launched_once and "--open-browser" in command:
            command.remove("--open-browser")
        self.worker = self.launcher(command, self.package_root)
        self._worker_started_at = self.monotonic()
        self._launched_once = True
        extra = {"replaced_unhealthy_pid": replaced_unhealthy_pid} if replaced_unhealthy_pid else {}
        return self._write_status("worker_started", **extra)


def _acquire_singleton(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ATR Windows Bridge supervisor")
    command_source = parser.add_mutually_exclusive_group(required=True)
    command_source.add_argument("--command-file")
    command_source.add_argument("--command-json")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--health-url", required=True)
    parser.add_argument("--update-lock", required=True)
    parser.add_argument("--status-path", required=True)
    parser.add_argument("--singleton-lock", required=True)
    parser.add_argument("--interval-s", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    singleton = _acquire_singleton(Path(args.singleton_lock))
    if singleton is None:
        return 0
    command = load_worker_command(
        command_file=Path(args.command_file) if args.command_file else None,
        command_json=str(args.command_json or ""),
    )
    supervisor = BridgeSupervisor(
        command=[str(value) for value in command],
        package_root=Path(args.package_root),
        update_lock=Path(args.update_lock),
        status_path=Path(args.status_path),
        health_check=lambda: _default_health_check(str(args.health_url)),
    )
    try:
        release_payload = json.loads((Path(args.package_root) / "release_manifest.json").read_text(encoding="utf-8"))
        release_version = str(release_payload.get("version") or "unknown")
    except (OSError, ValueError, TypeError):
        release_version = "unknown"
    console = SupervisorConsole(
        endpoint=str(args.health_url),
        release_version=release_version,
    )
    console.show_header()
    try:
        while True:
            console.show_status(supervisor.step())
            time.sleep(max(0.2, float(args.interval_s)))
    except KeyboardInterrupt:
        return 0
    finally:
        singleton.close()


if __name__ == "__main__":
    sys.exit(main())
