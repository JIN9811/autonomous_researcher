"""Execution-scoped evidence inside the existing run artifact filesystem.

This observes agent/tool calls; it never retries a call or changes device gates.
Archive failures are reported independently of the agent's scientific outcome.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
from typing import Any
from uuid import uuid4

_CURRENT: ContextVar[Any] = ContextVar("agent_artifact_execution", default=None)
_LOOP: ContextVar[Any] = ContextVar("artifact_stage_loop", default=None)
_LOG = logging.getLogger(__name__)
_SECRET = re.compile(r"(^|_)(password|passwd|secret|token|api_key|access_code|authorization|credential)(s|$)", re.I)
_EXTENSIONS = {".csv", ".json", ".jsonl", ".png", ".jpg", ".jpeg", ".svg", ".webp",
               ".stl", ".3mf", ".gcode", ".txt", ".log", ".inp", ".dat", ".frd", ".mp4", ".rrd"}


def current_execution():
    return _CURRENT.get()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: Any) -> str:
    text = str(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,179}", text):
        raise ValueError("Invalid artifact identity")
    return text


def _public(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if _SECRET.search(str(k)) else _public(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_public(v) for v in value]
    if hasattr(value, "model_dump"):
        return _public(value.model_dump(mode="json"))
    return value


def _json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(_public(value), handle, indent=2, ensure_ascii=False, default=str)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _error(state, exc: Exception) -> None:
    # Do not serialize arbitrary exception text containing credentials.
    try:
        error = {"at": _now(), "code": type(exc).__name__, "component": "artifact_archive"}
        previous = state.run_metadata.get("artifact_archive_errors")
        errors = previous if isinstance(previous, list) else []
        state.run_metadata["artifact_archive_errors"] = [*errors[-99:], error]
        _LOG.warning("Agent artifact preservation incomplete: %s", type(exc).__name__)
    except Exception:
        # Reporting a storage problem must never become an agent/device failure.
        pass


def _file_candidates(value: Any, key: str = "result"):
    if isinstance(value, dict):
        for name, child in value.items():
            if _SECRET.search(str(name)) or str(name) in {"artifact_execution", "checkpoint_path", "policy_path", "model_path"}:
                continue
            yield from _file_candidates(child, f"{key}.{name}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _file_candidates(child, f"{key}[{index}]")
    elif isinstance(value, (str, Path)):
        text = str(value)
        if len(text) < 4096 and "\n" not in text and "://" not in text:
            path = Path(text)
            if path.suffix.lower() in _EXTENSIONS or key.endswith(("_path", ".path", "_file")):
                yield key, path


class AgentArtifactExecution:
    """One invocation, with an exclusive on-disk attempt number and frozen identity."""

    def __init__(self, run_root: Path, state, agent: str):
        self.state = state
        self.run_root = Path(run_root).resolve()
        self.run_dir = (self.run_root / _safe(state.run_id)).resolve()
        if not self.run_dir.is_relative_to(self.run_root):
            raise ValueError("Archive run directory escapes run root")
        self.project_root = self.run_root.parent
        loop_index = int(state.loop_count)
        if loop_index < 0:
            raise ValueError("Negative loop index")
        parent = self.run_dir / "runtime" / "loops" / f"loop-{loop_index + 1:06d}" / _safe(agent)
        if not parent.resolve().is_relative_to(self.run_dir):
            raise ValueError("Archive attempt directory escapes run")
        parent.mkdir(parents=True, exist_ok=True)
        # mkdir is the cross-process arbiter, not an in-memory counter.
        attempt = 1
        while True:
            self.directory = parent / f"attempt-{attempt:06d}"
            try:
                self.directory.mkdir()
                break
            except FileExistsError:
                attempt += 1
        self.lock = threading.RLock()
        self.owner_task = asyncio.current_task()
        self.errors: list[str] = []
        self.closed = False
        self.pending_tools = 0
        self._seen: set[tuple[str, str]] = set()
        specimen = state.current_experiment_spec.get("specimen_id")
        self.manifest = {
            "schema": "atr.agent_artifact_execution.v1", "run_id": state.run_id,
            "loop_index": loop_index, "loop_number": loop_index + 1,
            "agent": agent, "stage": state.stage.value, "attempt_index": attempt,
            "execution_id": uuid4().hex, "specimen_id": str(specimen or ""),
            "experiment_id": state.experiment_id, "started_at": _now(),
            "status": "running", "archive_status": "recording", "artifacts": [],
            "events_path": self.relative(self.directory / "events.jsonl"),
            "manifest_path": self.relative(self.directory / "manifest.json"),
        }
        _json(self.directory / "manifest.json", self.manifest)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.run_dir).as_posix()

    def descriptor(self) -> dict[str, Any]:
        return {key: self.manifest[key] for key in ("run_id", "loop_index", "loop_number", "agent", "stage",
                "attempt_index", "execution_id", "specimen_id", "manifest_path", "status", "archive_status")}

    def event(self, kind: str, payload: Any) -> None:
        with self.lock:
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": _now(), "event": kind, "payload": _public(payload)}, default=str) + "\n")

    def refresh_status(self) -> None:
        self.manifest["archive_errors"] = list(self.errors)
        self.manifest["pending_tools"] = self.pending_tools
        incomplete = self.errors or any(item["status"] != "copied" for item in self.manifest["artifacts"])
        self.manifest["archive_status"] = "incomplete" if incomplete else (
            "recording" if self.pending_tools or not self.closed else "complete")

    def capture(self, payload: Any) -> None:
        with self.lock:
            for key, candidate in _file_candidates(payload):
                source = (candidate if candidate.is_absolute() else self.project_root / candidate).resolve()
                roots = (self.run_root, self.project_root / "artifacts", self.project_root / "memory" / "equipment_runtime",
                         self.project_root / "memory" / "knowledge")
                if source.is_relative_to(self.directory):
                    continue
                item = {"key": key, "source_path": str(source), "status": "external"}
                if not any(source.is_relative_to(root.resolve()) for root in roots):
                    if item not in self.manifest["artifacts"]:
                        self.manifest["artifacts"].append(item)
                    continue
                if not source.is_file():
                    item["status"] = "missing"
                    if item not in self.manifest["artifacts"]:
                        self.manifest["artifacts"].append(item)
                    continue
                target_dir = self.directory / "files"
                target_dir.mkdir(exist_ok=True)
                temp = target_dir / f".{uuid4().hex}.tmp"
                try:
                    before = source.stat()
                    digest = hashlib.sha256()
                    size = 0
                    with source.open("rb") as src, temp.open("xb") as dst:
                        # A bounded snapshot, even if a producer keeps appending.
                        remaining = before.st_size
                        while remaining:
                            chunk = src.read(min(1024 * 1024, remaining))
                            if not chunk:
                                break
                            dst.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                            remaining -= len(chunk)
                    checksum = digest.hexdigest()
                    if (str(source), checksum) in self._seen:
                        continue
                    after = source.stat()
                    stable = size == before.st_size and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
                    name = re.sub(r"[^A-Za-z0-9_.-]", "_", source.name)[-120:]
                    target = target_dir / f"{checksum}_{name}"
                    temp.replace(target)
                    item.update(path=self.relative(target), sha256=checksum, size_bytes=size,
                                status="copied" if stable else "partial", captured_at=_now())
                    self._seen.add((str(source), checksum))
                    self.manifest["artifacts"].append(item)
                except OSError as exc:
                    item.update(status="error", error=type(exc).__name__)
                    self.manifest["artifacts"].append(item)
                finally:
                    temp.unlink(missing_ok=True)
            self.refresh_status()
            _json(self.directory / "manifest.json", self.manifest)

    def finish(self, status: str, result: Any, summary: str = "") -> None:
        with self.lock:
            self.capture(result)
            _json(self.directory / "result.json", {"status": status, "summary": summary, "data": result})
            self.manifest.update(status=status, finished_at=_now(), result_path=self.relative(self.directory / "result.json"))
            self.closed = True
            self.refresh_status()
            self.event("agent_finished", {"status": status})
            _json(self.directory / "manifest.json", self.manifest)


def archive_agent_run(function):
    """Opt-in context enables the same evidence contract for loop and direct calls."""
    @wraps(function)
    async def wrapped(self, state, ctx, *args, **kwargs):
        root = getattr(ctx, "artifact_run_root", None)
        active = current_execution()
        if not root or (active and not active.closed and active.owner_task is asyncio.current_task()
                        and active.state is state and active.manifest["agent"] == self.name):
            return await function(self, state, ctx, *args, **kwargs)
        execution = None
        try:
            execution = AgentArtifactExecution(Path(root), state, self.name)
            _json(execution.directory / "input.json", {"state": state.model_dump(mode="json"), "args": args, "kwargs": kwargs})
            execution.event("agent_started", execution.descriptor())
        except Exception as exc:
            if execution:
                execution.errors.append(type(exc).__name__)
            _error(state, exc)
        token = _CURRENT.set(execution)
        try:
            result = await function(self, state, ctx, *args, **kwargs)
        except BaseException as exc:
            if execution:
                try:
                    await asyncio.to_thread(execution.finish,
                                            "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                                            {"error_type": type(exc).__name__})
                except Exception as archive_exc:
                    _error(state, archive_exc)
            raise
        else:
            if execution:
                try:
                    await asyncio.to_thread(execution.finish, "completed" if result.success else "failed", result.data, result.summary)
                    result.data["artifact_execution"] = execution.descriptor()
                except Exception as exc:
                    _error(state, exc)
            return result
        finally:
            _CURRENT.reset(token)
    return wrapped


def record_tool_artifact(kind: str, name: str, payload: Any) -> None:
    execution = current_execution()
    if execution:
        try:
            with execution.lock:
                if kind == "tool_started":
                    execution.pending_tools += 1
                elif kind in {"tool_result", "tool_failed"}:
                    execution.pending_tools = max(0, execution.pending_tools - 1)
                execution.event(kind, {"tool": name, "data": payload})
                if kind in {"tool_result", "evidence_result"}:
                    execution.capture(payload)
                execution.refresh_status()
                _json(execution.directory / "manifest.json", execution.manifest)
        except Exception as exc:
            execution.errors.append(type(exc).__name__)
            _error(execution.state, exc)


def archive_runtime_stage(function):
    """Freeze event ownership before Guardian increments the shared loop counter."""
    @wraps(function)
    async def wrapped(self, *args, **kwargs):
        token = _LOOP.set((id(self._state), int(self._state.loop_count)))
        try:
            return await function(self, *args, **kwargs)
        finally:
            _LOOP.reset(token)
    return wrapped


def append_loop_event(run_dir: Path, state, event: dict[str, Any]) -> None:
    """Preserve runtime routing/gate outcomes alongside agent artifacts."""
    try:
        payload = event.get("payload", {})
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        owner = result.get("artifact_execution", {}) if isinstance(result, dict) else {}
        scoped = _LOOP.get()
        stage_index = scoped[1] if scoped and scoped[0] == id(state) else state.loop_count
        index = int(event.get("loop_index", owner.get("loop_index", stage_index)))
        if index < 0:
            raise ValueError("Negative loop index")
        directory = Path(run_dir) / "runtime" / "loops" / f"loop-{index + 1:06d}"
        if not directory.resolve().is_relative_to(Path(run_dir).resolve()):
            raise ValueError("Loop event directory escapes run")
        directory.mkdir(parents=True, exist_ok=True)
        # Agent input snapshots carry full state; events retain their own full payload.
        record = {key: value for key, value in event.items() if key != "state"}
        record["loop_index"] = index
        with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_public(record), default=str) + "\n")
    except Exception as exc:
        _error(state, exc)


def list_executions(run_dir: Path, *, loop_index: int | None = None, agent: str | None = None) -> list[dict[str, Any]]:
    """Read disk history, including interrupted invocations; no live state needed."""
    run_dir = Path(run_dir).resolve()
    entries = []
    for path in sorted((run_dir / "runtime" / "loops").glob("loop-*/*/attempt-*/manifest.json")):
        if not path.resolve().is_relative_to(run_dir):
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if item.get("schema") != "atr.agent_artifact_execution.v1":
                continue
            if loop_index is not None and item.get("loop_index") != loop_index:
                continue
            if agent is not None and item.get("agent") != agent:
                continue
            item["streams"] = []
            for stream in sorted(path.parent.glob("streams/*/session.json")):
                if not stream.resolve().is_relative_to(run_dir):
                    continue
                try:
                    saved = json.loads(stream.read_text())
                    saved["path"] = stream.relative_to(run_dir).as_posix()
                    item["streams"].append(saved)
                except (OSError, ValueError):
                    continue
            item["invocation_archive_status"] = item["archive_status"]
            for stream in item["streams"]:
                if str(stream.get("status", "")).upper() not in {"STOPPED", "COMPLETED", "FAILED", "CANCELLED"}:
                    if item["archive_status"] != "incomplete":
                        item["archive_status"] = "recording"
                elif not stream.get("tracking_artifacts", {}).get("ok"):
                    item["archive_status"] = "incomplete"
            entries.append(item)
        except (OSError, ValueError, AttributeError, KeyError, TypeError):
            continue
    return entries
