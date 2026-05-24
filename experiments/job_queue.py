"""
File purpose:
- Provide lightweight per-device FIFO execution metadata for tool calls.

Key classes/functions:
- DeviceJobQueue

Inputs/outputs:
- Input: device name, tool handler, payload
- Output: original tool result decorated with job/session/experiment IDs

Modification guide:
- Safe places to edit: history size, metadata fields
- Risky places to edit: synchronous lock behavior around live hardware tools
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from utils.ids import make_experiment_id

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class _DeviceQueueState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    counter: int = 0
    active_job_id: str | None = None
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))


class DeviceJobQueue:
    """Synchronous per-device FIFO wrapper for hardware-facing tool handlers."""

    def __init__(self) -> None:
        self._states: dict[str, _DeviceQueueState] = defaultdict(_DeviceQueueState)
        self._global_lock = threading.Lock()

    @staticmethod
    def _clean(value: Any, default: str) -> str:
        text = str(value or "").strip()
        return text or default

    def _next_job_id(self, device: str) -> str:
        with self._global_lock:
            state = self._states[device]
            state.counter += 1
            return f"job-{device.replace(':', '-')}-{state.counter:04d}"

    def submit_sync(
        self,
        *,
        device: str,
        tool_name: str,
        handler: ToolHandler,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one device job under that device lock and decorate the result."""
        normalized = dict(payload or {})
        experiment_id = self._clean(normalized.get("experiment_id"), make_experiment_id())
        session_id = self._clean(
            normalized.get("session_id") or normalized.get("run_id"),
            f"session-{experiment_id}",
        )
        job_id = self._clean(normalized.get("job_id"), self._next_job_id(device))
        normalized.setdefault("experiment_id", experiment_id)
        normalized.setdefault("session_id", session_id)
        normalized.setdefault("job_id", job_id)

        state = self._states[device]
        queued_at = _now_iso()
        queue_started = time.monotonic()
        with state.lock:
            wait_sec = round(time.monotonic() - queue_started, 6)
            started_at = _now_iso()
            state.active_job_id = job_id
            base_job = {
                "job_id": job_id,
                "device": device,
                "tool": tool_name,
                "experiment_id": experiment_id,
                "session_id": session_id,
                "queued_at": queued_at,
                "started_at": started_at,
                "queue_wait_sec": wait_sec,
                "status": "running",
            }
            state.history.append(dict(base_job))
            try:
                result = handler(normalized)
                if not isinstance(result, dict):
                    result = {"ok": False, "status": "invalid_tool_result", "raw_result": result}
                ok = bool(result.get("ok", True))
                status = str(result.get("status") or ("ok" if ok else "failed"))
                finished = {**base_job, "finished_at": _now_iso(), "status": status, "ok": ok}
                state.history.append(finished)
                decorated = dict(result)
                decorated.setdefault("experiment_id", experiment_id)
                decorated.setdefault("session_id", session_id)
                decorated["job_id"] = job_id
                decorated["job"] = finished
                return decorated
            except Exception as exc:
                failed = {
                    **base_job,
                    "finished_at": _now_iso(),
                    "status": "error",
                    "ok": False,
                    "error": str(exc),
                }
                state.history.append(failed)
                raise
            finally:
                state.active_job_id = None

    def status(self) -> dict[str, Any]:
        """Return queue state for GUI and diagnostics."""
        devices: dict[str, Any] = {}
        for device, state in self._states.items():
            devices[device] = {
                "active_job_id": state.active_job_id,
                "submitted_count": state.counter,
                "history": list(state.history),
            }
        return {"ok": True, "tool": "experiment.queue.status", "devices": devices}
