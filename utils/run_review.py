"""Best-effort, bounded presentation archive. Never executes or resumes a run."""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)
AGENTS = ("orchestrator", "design", "specimen", "vision", "manipulation", "equipment", "analysis", "knowledge", "bo", "guardian")
SECRET = re.compile(r"password|secret|token|api_key|access_code|authorization|credential", re.I)
capture_sink = None


def observe_capture(state, slot, preview):
    """Observe the existing display publication, before review; no authority."""
    if capture_sink is None:
        return
    try:
        capture_sink({"run_id": state.run_id, "event_type": "vision.capture_recorded",
                      "ts": preview.get("captured_at"), "agent": "vision",
                      "payload": {"checkpoint": slot, "preview": preview},
                      "state": {"run_id": state.run_id, "mode": str(getattr(state.mode, "value", state.mode)),
                                "loop_count": state.loop_count, "stage": "vision"}})
    except Exception:
        pass


def safe_child(root: Path, name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", name):
        raise ValueError("Invalid archive identifier")
    result = (root / name).resolve()
    if result.parent != root.resolve():
        raise ValueError("Archive path escapes its root")
    return result


def bounded(value, budget=None, depth=0):
    """Cap memory/disk amplification and exclude credentials from exported data."""
    budget = budget if budget is not None else [3000]
    budget[0] -= 1
    if budget[0] < 0 or depth > 9:
        return "Not recorded (size limit)"
    if isinstance(value, dict):
        return {str(k): bounded(v, budget, depth + 1) for k, v in list(value.items())[:100]
                if not SECRET.search(str(k))}
    if isinstance(value, list):
        return [bounded(v, budget, depth + 1) for v in value[:60]]
    if isinstance(value, str):
        return value[:6000]
    return value if value is None or isinstance(value, (bool, int, float)) else str(value)[:300]


def atomic_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class RunReviewRecorder:
    """Only new run IDs; producer never waits for filesystem work or queue space.

    Input is an already-created GUI event, not live state or a device connection.
    Overload drops review events, not experiment events. All I/O is on one daemon.
    """
    def __init__(self, root: Path, excluded_run: str):
        self.root = Path(root).resolve()
        self.excluded_run = excluded_run
        self.queue = queue.Queue(maxsize=8)
        self.dropped = 0
        self.errors = 0
        self.closed = threading.Event()
        self.run_id = None
        self.index = []
        self.cards = {}
        self.chat = []
        self.cycle = None
        self.presentation_state = {}
        self.events = []
        self.asset_bytes = 0
        self.json_bytes = 0
        self.blocked_runs = {excluded_run}
        self.thread = threading.Thread(target=self._work, name="run-review-writer", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.closed.set()

    def offer(self, event):
        run = event.get("run_id") or (event.get("state") or {}).get("run_id")
        if self.closed.is_set() or not run or run in self.blocked_runs:
            return
        if (event.get("state") or {}).get("mode") == "replay":
            return
        try:
            # Shallow envelope copy only: never serialize experiment state here.
            self.queue.put_nowait({**event, "review_received_at": datetime.now(timezone.utc).isoformat(),
                                  "review_received_ns": time.time_ns()})
        except queue.Full:
            self.dropped += 1

    def _work(self):
        while not self.closed.is_set() or not self.queue.empty():
            try:
                event = self.queue.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                self.record(event)
            except Exception:
                self.errors += 1
                if self.errors == 1 or self.errors % 100 == 0:
                    LOG.warning("Read-only replay archive write failed; experiment unaffected", exc_info=True)
            finally:
                self.queue.task_done()

    def _images(self, value, run_dir, archive, cutoff_ns):
        found = {}
        def walk(obj, label=""):
            if len(found) >= 12:
                return
            if isinstance(obj, dict):
                for key, child in obj.items():
                    walk(child, str(key))
            elif isinstance(obj, list):
                for child in obj:
                    walk(child, label)
            elif isinstance(obj, str) and Path(obj).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                path = Path(obj)
                if not path.is_absolute():
                    path = self.root.parent / path
                path = path.resolve()
                if not path.is_relative_to(run_dir) or not path.is_file():
                    return
                before = path.stat()
                if before.st_mtime_ns > cutoff_ns:
                    return  # A later capture replaced this path while queued.
                size = before.st_size
                if size > 8_000_000 or self.asset_bytes + size > 512_000_000:
                    return
                data = path.read_bytes()
                after = path.stat()
                if (after.st_mtime_ns, after.st_size) != (before.st_mtime_ns, before.st_size):
                    return  # A producer is still writing; never archive a torn frame.
                name = hashlib.sha256(data).hexdigest() + path.suffix.lower()
                target = safe_child(safe_child(archive, "assets"), name)
                if not target.exists():
                    target.write_bytes(data)
                    self.asset_bytes += len(data)
                found[name] = {"name": name, "label": label, "source": path.name, "source_path": str(path)}
        walk(value)
        return list(found.values())

    def record(self, event):
        state = event.get("state") or {}
        run_id = str(event.get("run_id") or state.get("run_id") or "")
        if not run_id or run_id in self.blocked_runs or state.get("mode") == "replay":
            return
        if state.get("run_id") not in (None, "", run_id):
            return
        run_dir = safe_child(self.root, run_id)
        if not run_dir.is_dir():
            return
        archive = safe_child(run_dir, "review")
        archive.mkdir(exist_ok=True)
        safe_child(archive, "assets").mkdir(exist_ok=True)
        if run_id != self.run_id:
            self.run_id, self.index, self.cards, self.chat, self.cycle = run_id, [], {}, [], None
            # Never overwrite an archive created by another recorder/restarted server.
            if (archive / "index.json").exists():
                self.blocked_runs.add(run_id)
                return
            self.asset_bytes = 0
            self.json_bytes = 0
        if len(self.index) >= 5000 or self.json_bytes > 128_000_000:
            self.dropped += 1
            atomic_json(archive / "index.json", {"run_id": run_id, "points": self.index,
                        "dropped_events": self.dropped, "write_errors": self.errors, "limit_reached": True})
            return
        payload = event.get("payload") or {}
        cycle = state.get("loop_count", payload.get("loop_index", self.cycle if self.cycle is not None else 0))
        if cycle != self.cycle:
            self.cards, self.chat, self.cycle = {}, [], cycle
            self.presentation_state, self.events = {}, []
        event_type = str(event.get("event_type") or event.get("type") or "event")
        stage = str(state.get("stage") or payload.get("stage") or event.get("timestamp_stage") or "")
        agent_text = str(payload.get("agent_id") or payload.get("module_id") or event.get("agent") or event.get("module_id") or stage)
        agent = next((a for a in AGENTS if a in agent_text.lower()), "orchestrator")
        timestamp = event.get("ts") or event.get("timestamp") or event.get("review_received_at") or datetime.now(timezone.utc).isoformat()
        metadata = state.get("run_metadata") or {}
        cutoff_ns = event.get("review_received_ns", time.time_ns())
        public_state = {key: bounded(value) for key, value in state.items()
                        if key in {"run_id", "experiment_id", "active_session_id", "mode", "stage", "loop_count",
                                   "active_goal", "current_experiment_spec", "observation", "artifacts", "device_health"}}
        if metadata:
            public_state["run_metadata"] = {key: bounded(value) for key, value in metadata.items()
                if (key.endswith(("_report", "_agent_payload", "_result", "_visualization", "_metrics", "_packet", "_contract"))
                    or key in {"utm_verifications", "bo_initial_design", "bo_agent", "next_design_request", "cycle_contract"})
                and not SECRET.search(key)}
        self.presentation_state.update(public_state)
        specimen_id = (state.get("current_experiment_spec") or {}).get("specimen_id")
        for owner in AGENTS:
            report = metadata.get(f"latest_{owner}_agent_report")
            # Old "latest" reports can remain in state across cycles. Require an
            # explicit match; absence is preferable to showing another specimen.
            brief = report.get("execution_brief", {}) if isinstance(report, dict) else {}
            scoped = isinstance(report, dict) and (
                (specimen_id and (report.get("specimen_id") == specimen_id or brief.get("target_object") == specimen_id))
                or (report.get("run_id") == run_id and report.get("loop_index", report.get("loop_id")) == cycle))
            if scoped:
                data = bounded(report)
                self.cards[owner] = {"data": data, "images": self._images(data, run_dir, archive, cutoff_ns), "timestamp": timestamp}
        verification = metadata.get("utm_verifications") or {}
        if verification.get("run_id") != run_id or verification.get("loop_id") != cycle:
            verification = None
        data = bounded({"event": event_type, "message": event.get("message"), "payload": payload,
                        "specimen": state.get("current_experiment_spec"),
                        "observation": state.get("observation") if agent == "vision" else None,
                        "verification": verification if agent == "vision" else None})
        previous = self.cards.get(agent, {})
        images = self._images(data, run_dir, archive, cutoff_ns)
        self.cards[agent] = {**previous, "event": data, "images": images or previous.get("images", []), "timestamp": timestamp}
        latest = payload.get("latest")
        if isinstance(latest, dict):
            self.chat.append(bounded({k: latest.get(k) for k in ("role", "content", "timestamp")}))
            self.chat = self.chat[-60:]
        point_id = f"{len(self.index) + 1:06d}"
        self.events.append(bounded({key: value for key, value in event.items() if key not in {"state", "review_received_ns"}}))
        self.events = self.events[-120:]
        summary = {"id": point_id, "timestamp": timestamp, "cycle": cycle, "stage": stage,
                   "agent": agent, "event": payload.get("checkpoint") or event_type}
        point = {**summary, "run_id": run_id, "schema": "run_review.v1", "read_only": True,
                 "cards": self.cards, "chat": self.chat, "dropped_events": self.dropped, "write_errors": self.errors}
        point["state"] = self.presentation_state
        point["events"] = self.events
        point["images"] = self._images(self.presentation_state, run_dir, archive, cutoff_ns)
        atomic_json(archive / f"{point_id}.json", point)
        self.json_bytes += (archive / f"{point_id}.json").stat().st_size
        self.index.append(summary)
        atomic_json(archive / "index.json", {"run_id": run_id, "points": self.index,
                    "dropped_events": self.dropped, "write_errors": self.errors})
