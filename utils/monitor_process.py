"""One bounded, loopback-only read worker per monitoring domain.

Spawn fresh interpreters, never fork the controller/device ownership graph.
Configuration (including camera credentials) travels over stdin, not argv.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import secrets
import selectors
import subprocess
import sys
import threading


class MonitorProcess:
    def __init__(self, kind: str, config: dict):
        self.kind, self.config = kind, config
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "utils.monitor_worker"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, start_new_session=True,
        )
        try:
            self.update({"kind": kind, "token": self.token, "config": config})
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                if not selector.select(12):
                    raise TimeoutError("Read-only monitor worker startup timed out")
                ready = json.loads(self.process.stdout.readline())
            self.port = int(ready["port"])
        except Exception:
            self.close()
            raise

    def update(self, payload: dict):
        # Context is bounded by its producer; there is no accumulated queue.
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        if len(line.encode()) > 1024 * 1024:
            raise ValueError("Monitor context exceeds 1 MiB")
        with self.lock:
            self.process.stdin.write(line)
            self.process.stdin.flush()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}/{self.token}/{path}"

    def control(self, payload: dict) -> dict:
        """Configure display readers over the private pipe, never a browser API."""
        line = json.dumps({"monitor_control": payload}) + "\n"
        if len(line.encode()) > 1024 * 1024:
            raise ValueError("Monitor configuration exceeds 1 MiB")
        with self.lock:
            self.process.stdin.write(line)
            self.process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                if not selector.select(5):
                    # An unacknowledged reply must not be mistaken for the next one.
                    self.close()
                    raise TimeoutError("Monitor configuration timed out")
                reply = json.loads(self.process.stdout.readline())
            if not reply.get("ok"):
                raise RuntimeError(reply.get("error", "Monitor configuration failed"))
            return reply

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        for handle in (self.process.stdin, self.process.stdout):
            if handle:
                handle.close()


_workers: dict[str, MonitorProcess] = {}
_lock = threading.Lock()


def monitor_process(kind: str, config: dict) -> MonitorProcess:
    if kind not in {"video", "robot"}:
        raise ValueError("Unknown monitoring domain")
    with _lock:
        worker = _workers.get(kind)
        if kind == "video" and worker and worker.process.poll() is None:
            # Vision and printer share the video server, not each other's source.
            if config and worker.config != config:
                worker.control({"operation": "printer", "config": config})
                worker.config = config
            return worker
        if worker and worker.process.poll() is None and worker.config == config:
            return worker
        if worker:
            worker.close()
        worker = MonitorProcess(kind, config)
        _workers[kind] = worker
        return worker


def close_monitor_processes():
    with _lock:
        for worker in _workers.values():
            worker.close()
        _workers.clear()


def existing_monitor_process(kind: str) -> MonitorProcess | None:
    """Reuse an active reader for snapshots without opening another camera feed."""
    with _lock:
        worker = _workers.get(kind)
        return worker if worker and worker.process.poll() is None else None


atexit.register(close_monitor_processes)
