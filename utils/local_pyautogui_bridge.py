"""ATR-owned localhost PyAutoGUI bridge process supervision."""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx


class LocalPyAutoGUIBridgeSupervisor:
    """Start and stop only the localhost bridge process owned by ATR."""

    alias = "local_development"
    host = "127.0.0.1"
    port = 8767

    def __init__(self, repo_root: Path, *, python_executable: Path | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        venv_python = self.repo_root / ".venv" / "bin" / "python"
        self.python_executable = Path(python_executable or (venv_python if venv_python.exists() else sys.executable))
        self.server_path = self.repo_root / "Pyautogui_server_for_window" / "bridge" / "windows_pyautogui_bridge_server.py"
        self.runtime_root = self.repo_root / "runs" / "local_pyautogui_bridge"
        self.artifact_root = self.runtime_root / "artifacts"
        self.locator_root = self.repo_root / "memory" / "local_pyautogui_locators"
        self.program_root = self.repo_root / "memory" / "local_pyautogui_programs"
        self.token_path = self.repo_root / "memory" / "local_pyautogui_bridge.token"
        self.pid_path = self.runtime_root / "local_bridge.pid"
        self.log_path = self.runtime_root / "local_bridge.log"
        self.bridge_url = f"http://{self.host}:{self.port}"
        self._process: subprocess.Popen[bytes] | None = None

    def ensure_token(self) -> str:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            token = self.token_path.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if not token:
            token = secrets.token_urlsafe(32)
            self.token_path.write_text(token + "\n", encoding="utf-8")
        self.token_path.chmod(0o600)
        return token

    def build_command(self) -> list[str]:
        return [
            str(self.python_executable),
            str(self.server_path),
            "--platform",
            "linux",
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--token-file",
            str(self.token_path),
            "--artifact-dir",
            str(self.artifact_root),
            "--reference-dir",
            str(self.locator_root),
            "--utm-export-dir",
            str(self.runtime_root / "utm_exports"),
            "--program-dir",
            str(self.program_root),
        ]

    def status(self) -> dict[str, Any]:
        pid = self._read_pid()
        running = bool(pid and self._pid_running(pid) and self._owns_pid(pid))
        health = self._health() if running else {}
        healthy = bool(health.get("ok") and health.get("pyautogui", {}).get("available"))
        return {
            "ok": True,
            "status": "running" if running else "stopped",
            "running": running,
            "healthy": healthy,
            "pid": pid if running else None,
            "bridge_url": self.bridge_url,
            "candidate_alias": self.alias,
            "platform": "linux",
            "scope": "localhost",
            "token_configured": self.token_path.exists(),
            "artifact_root": str(self.artifact_root),
            "locator_root": str(self.locator_root),
            "program_root": str(self.program_root),
            "log_path": str(self.log_path),
            "health": health,
        }

    def start(self) -> dict[str, Any]:
        current = self.status()
        if current.get("running"):
            return {**current, "idempotent": True}
        self.ensure_token()
        for path in (self.runtime_root, self.artifact_root, self.locator_root, self.program_root):
            path.mkdir(parents=True, exist_ok=True)
        log_handle = self.log_path.open("ab", buffering=0)
        try:
            process = subprocess.Popen(
                self.build_command(),
                cwd=str(self.repo_root),
                env=dict(os.environ),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_handle.close()
        self._process = process
        self.pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            health = self._health()
            if health.get("ok"):
                return {**self.status(), "status": "running", "idempotent": False}
            time.sleep(0.2)
        return {
            **self.status(),
            "ok": False,
            "status": "failed",
            "failure_code": "LOCAL_PYAUTOGUI_START_FAILED",
            "message": f"Local bridge did not become healthy. Inspect {self.log_path}.",
        }

    def stop(self) -> dict[str, Any]:
        pid = self._read_pid()
        if not pid or not self._pid_running(pid):
            self._clear_pid()
            return {**self.status(), "status": "stopped", "idempotent": True}
        if not self._owns_pid(pid):
            return {
                **self.status(),
                "ok": False,
                "status": "blocked",
                "failure_code": "LOCAL_PYAUTOGUI_PROCESS_NOT_OWNED",
                "message": f"Refusing to stop unowned pid {pid}.",
            }
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and self._pid_running(pid):
            time.sleep(0.1)
        if self._pid_running(pid):
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        self._clear_pid()
        self._process = None
        return {**self.status(), "status": "stopped", "idempotent": False}

    def ensure_candidate(self, bridge: Any, *, select: bool) -> dict[str, Any]:
        token = self.ensure_token()
        saved = bridge.save_connection(
            {
                "candidate_alias": self.alias,
                "bridge_url": self.bridge_url,
                "host": self.host,
                "port": self.port,
                "token": token,
                "platform": "linux",
                "scope": "localhost",
                "managed_local": True,
                "allow_live_execute": True,
                "select": select,
            }
        )
        if not saved.get("ok"):
            return {**saved, "selected": False}
        result = bridge.select_candidate({"candidate_alias": self.alias}) if select else saved
        return {**result, "selected": select, "candidate_alias": self.alias}

    def _health(self) -> dict[str, Any]:
        token = self.ensure_token()
        try:
            response = httpx.get(
                f"{self.bridge_url}/health",
                headers={"X-Bridge-Token": token},
                timeout=0.8,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _read_pid(self) -> int | None:
        try:
            value = int(self.pid_path.read_text(encoding="utf-8").strip())
            return value if value > 1 else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _pid_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False

    def _owns_pid(self, pid: int) -> bool:
        try:
            command = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
        except OSError:
            return False
        return str(self.server_path) in command and f"--port {self.port}" in command and "--platform linux" in command

    def _clear_pid(self) -> None:
        try:
            self.pid_path.unlink()
        except FileNotFoundError:
            pass
