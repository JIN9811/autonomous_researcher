"""Opt-in folder watcher; source curation is not an experiment stage."""
from __future__ import annotations

import asyncio
from functools import lru_cache
from dataclasses import replace
import json
import math
from pathlib import Path
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]


def curation_context(ctx):
    """Freeze the existing first-choice route; background intake cannot boot fallbacks."""
    from agents.base_agent import AgentContext
    from backends.model_router import ModelRouter
    if not isinstance(ctx, AgentContext):
        return ctx
    backend = ctx.active_backend
    if ctx.backend_fallbacks.get(backend) == "openai" and "openai" in ctx.primary_backends:
        backend = "openai"  # Same saved API-first policy as AgentContext.complete.
    provider = ctx.primary_backends.get(backend, ctx.primary_backend)
    selected = ctx.model_routers.get(backend, ctx.model_router).select("knowledge_query")
    router = ModelRouter({"models": {selected.role: {"primary": selected.primary}},
                          "task_routes": {"knowledge_query": selected.role}})
    return replace(ctx, active_backend=backend, model_router=router, primary_backend=provider,
        fallback_backend=provider, model_routers={backend: router},
        primary_backends={backend: provider}, fallback_backends={backend: provider},
        backend_fallbacks={backend: backend})


@lru_cache(maxsize=8)
def library_for(project_root: Path = PROJECT):
    from knowledge.source_library import SourceLibrary
    project_root = Path(project_root).resolve()
    return SourceLibrary(project_root / "memory/knowledge/source_library",
                         project_root / "docs/knowledge/manuals/sources")


class SourceIngestionService:
    def __init__(self, library, context_factory, *, poll_interval_s=5.0):
        if not math.isfinite(poll_interval_s) or poll_interval_s <= 0:
            raise ValueError("poll interval must be positive and finite")
        self.library, self.context_factory = library, context_factory
        self.poll_interval_s = poll_interval_s
        self._settings = Path(library.root) / "settings.json"
        self._enabled = False
        self._state, self._error, self._active = "disabled", "", ""
        self._task = None
        self._wake = asyncio.Event()
        self._tick_lock = asyncio.Lock()
        self._last_result = {}
        if self._settings.is_file():
            try:
                settings = json.loads(self._settings.read_text(encoding="utf-8"))
                self._enabled = settings.get("enabled") is True
            except (ValueError, OSError, AttributeError):
                self._error = "invalid_saved_settings"

    def configure(self, *, enabled: bool) -> dict:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        self._settings.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._settings.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
            temporary.replace(self._settings)
        finally:
            temporary.unlink(missing_ok=True)
        self._enabled = enabled
        self._wake.set()
        return self.status()

    def status(self) -> dict:
        return {"enabled": self._enabled, "running": bool(self._task and not self._task.done()),
                "state": self._state, "error": self._error, "active_source_id": self._active,
                "inbox": str(self.library.inbox), "library": self.library.status(),
                "last_result": self._last_result}

    def retry(self, source_id: str) -> dict:
        sources = self.library.status()["sources"]
        source = next((item for item in sources if item["source_id"] == source_id), None)
        if source is None:
            raise KeyError("Unknown source identity")
        if not source.get("current") or source["status"] in {"ready", "processing"}:
            raise ValueError("Only current unfinished sources can be retried")
        self.library.mark(source_id, "discovered")
        self._wake.set()
        return {"scheduled": True, "source_id": source_id}

    def request_scan(self) -> None:
        self._wake.set()

    async def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="knowledge-source-ingestion")

    async def shutdown(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self):
        while True:
            self._wake.clear()
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._state, self._error = "error", type(exc).__name__
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval_s)
            except TimeoutError:
                pass

    async def tick(self):
        from agents.source_curation import curate_source
        async with self._tick_lock:
            if not self._enabled:
                self._state = "disabled"
                return
            scan = await asyncio.to_thread(self.library.scan)
            pending = scan.get("pending_ids", [])
            if not pending:
                self._state = "idle"
                return
            ctx = curation_context(self.context_factory())
            readiness = getattr(ctx, "selected_model_loaded", None)
            if ctx is None or (readiness and not await readiness("knowledge_query")):
                self._state = "waiting_for_model"
                return
            lease = getattr(ctx, "llm_lease", None)
            if lease and (lease.status()["active"] or lease.status()["waiting"]):
                self._state = "waiting_for_workflow"
                return
            if not self._enabled:
                return
            self._active, self._state, self._error = pending[0], "curating", ""
            try:
                result = await curate_source(self.library, self._active, ctx)
                self._last_result = {key: result[key] for key in
                    ("status", "source_id", "model", "duration_s", "error") if key in result}
                self._state = "idle"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.library.mark(self._active, "failed", error=type(exc).__name__)
                self._state, self._error = "error", type(exc).__name__
            finally:
                self._active = ""
