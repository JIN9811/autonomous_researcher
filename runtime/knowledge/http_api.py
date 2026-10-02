"""Graph retirement and Markdown Knowledge HTTP contracts; no device ownership."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


class KnowledgeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", max_length=2000)
    scope: dict[str, Any] | None = None
    top_k: int = Field(default=6, ge=1, le=50, strict=True)


class KnowledgeRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1, max_length=200)
    scope: dict[str, Any] | None = None


class KnowledgeLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    reason: str = Field(min_length=1, max_length=2000)
    superseded_by: str = ""


class ArchiveIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(default="", max_length=180, pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_.-]*)?$")
    limit: int = Field(default=100, ge=1, le=500, strict=True)
    cursor: str = Field(default="", max_length=1000)


def _save_job(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def install_markdown_routes(app: FastAPI, *, store_factory: Callable, run_root_factory: Callable,
                            memory_root_factory: Callable) -> None:
    """Install local-only endpoints; factories preserve app/test root ownership."""
    @app.get("/api/knowledge/status")
    async def knowledge_status():
        result = await asyncio.to_thread(store_factory().status)
        return {"ok": True, "storage": "markdown", "markdown": result,
                "graph": {"enabled": False, "status": "retired"}, "workspace_url": "/knowledge"}

    @app.post("/api/knowledge/markdown/query")
    async def query_knowledge(request: KnowledgeQuery):
        try:
            result = await asyncio.to_thread(store_factory().search, request.query, scope=request.scope, top_k=request.top_k)
            return {"ok": True, **result}
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    async def read_record(record_id: str, scope: dict | None):
        try:
            result = await asyncio.to_thread(store_factory().read_note, record_id, scope=scope)
            if not result or result.get("ok") is False:
                raise HTTPException(404, detail="Knowledge record not found within requested scope")
            return {"ok": True, **result}
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, detail="Knowledge record not found within requested scope") from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    @app.post("/api/knowledge/markdown/read")
    async def read_knowledge(request: KnowledgeRead):
        return await read_record(request.record_id, request.scope)

    @app.post("/api/knowledge/markdown/intake")
    async def start_intake(request: ArchiveIntake, background_tasks: BackgroundTasks):
        if request.cursor and (Path(request.cursor).is_absolute() or ".." in Path(request.cursor).parts):
            raise HTTPException(422, detail="Invalid intake cursor")
        job_id = uuid4().hex
        path = Path(memory_root_factory()) / "markdown_jobs" / f"{job_id}.json"
        job = {"job_id": job_id, "status": "queued", "request": request.model_dump(),
               "physical_actuation": False, "llm_used": False}
        await asyncio.to_thread(_save_job, path, job)
        store, run_root = store_factory(), Path(run_root_factory())

        async def process():
            from knowledge.markdown_runtime import intake_archives
            try:
                await asyncio.to_thread(_save_job, path, {**job, "status": "running"})
                result = await asyncio.to_thread(intake_archives, run_root, store=store, **request.model_dump())
                await asyncio.to_thread(_save_job, path, {**job, "status": "completed" if result["ok"] else "partial", "result": result})
            except Exception as exc:
                await asyncio.to_thread(_save_job, path, {**job, "status": "failed", "error": type(exc).__name__})

        background_tasks.add_task(process)
        return {"ok": True, **job}

    @app.get("/api/knowledge/markdown/intake/{job_id}")
    async def intake_status(job_id: str):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise HTTPException(422, detail="Invalid job identity")
        path = Path(memory_root_factory()) / "markdown_jobs" / f"{job_id}.json"
        try:
            return await asyncio.to_thread(lambda: json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError as exc:
            raise HTTPException(404, detail="Intake job not found") from exc

    @app.get("/api/knowledge/markdown/{record_id}")
    async def get_knowledge(record_id: str):
        return await read_record(record_id, None)

    @app.post("/api/knowledge/markdown/{record_id}/status")
    async def update_knowledge_status(record_id: str, request: KnowledgeLifecycle):
        try:
            result = await asyncio.to_thread(store_factory().set_status, record_id, request.status,
                                             reason=request.reason, superseded_by=request.superseded_by)
            if not result.get("ok"):
                raise HTTPException(404, detail="Knowledge record not found")
            return result
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, detail="Knowledge record not found") from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc


def retire_graph_routes(app: FastAPI) -> None:
    """Retire only Knowledge graph routes; executable runtime graphs are untouched."""
    prefixes = ("/api/knowledge/graph", "/api/knowledge/graphify", "/api/knowledge/relations")

    def retired_path(path: str) -> bool:
        return path == "/api/knowledge/manuals/graph" or any(
            path == prefix or path.startswith(prefix + "/") for prefix in prefixes
        )

    app.router.routes[:] = [route for route in app.router.routes
                           if not retired_path(getattr(route, "path", ""))]

    async def retired(rest: str = ""):
        return JSONResponse(status_code=410, content={
            "ok": False, "status": "retired", "component": "knowledge_graph",
            "message": "Knowledge graph retired. Ontology, Markdown memory and manual retrieval remain available.",
        })

    for prefix in prefixes:
        app.add_api_route(prefix, retired, methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
        app.add_api_route(prefix + "/{rest:path}", retired, methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    app.add_api_route("/api/knowledge/manuals/graph", retired, methods=["GET", "POST"], include_in_schema=False)
    app.openapi_schema = None
