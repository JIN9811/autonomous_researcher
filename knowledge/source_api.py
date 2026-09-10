"""Folder-owned source APIs; clients cannot select server filesystem roots."""
import asyncio

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from knowledge.http_api import KnowledgeQuery, KnowledgeRead


def retire_manual_routes(app):
    """Retire active legacy endpoints without deleting original corpus files."""
    prefix = "/api/knowledge/manuals/"
    paths = {route.path for route in app.router.routes if getattr(route, "path", "").startswith(prefix)}
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", "") not in paths]

    async def retired():
        return JSONResponse(status_code=410, content={"ok": False, "status": "retired",
            "replacement": "/api/knowledge/sources/status"})

    for path in paths:
        app.add_api_route(path, retired, methods=["GET", "POST"], include_in_schema=False)


class SourceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class SourceRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=100)


def install_source_routes(app, *, service_factory):
    prefix = "/api/knowledge/sources"

    async def call(function, *args, **kwargs):
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, detail="Source not found within requested scope") from exc

    @app.get(prefix + "/status")
    async def status():
        return {"ok": True, **await call(service_factory().status)}

    @app.post(prefix + "/settings")
    async def settings(request: SourceSettings):
        # Event wake-up belongs to the request event loop, not a worker thread.
        return {"ok": True, **service_factory().configure(enabled=request.enabled)}

    @app.post(prefix + "/scan")
    async def scan():
        service = service_factory()
        found = await call(service.library.scan)
        service.request_scan()
        return {"ok": True, "scheduled": service.status()["enabled"], **found}

    @app.post(prefix + "/retry")
    async def retry(request: SourceRetry):
        try:
            return {"ok": True, **service_factory().retry(request.source_id)}
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, detail="Unknown source identity") from exc

    @app.post(prefix + "/query")
    async def query(request: KnowledgeQuery):
        return {"ok": True, **await call(service_factory().library.search, request.query,
            scope=request.scope, top_k=request.top_k)}

    @app.post(prefix + "/read")
    async def read(request: KnowledgeRead):
        result = await call(service_factory().library.read, request.record_id, scope=request.scope, include_source=True)
        if not result or result.get("ok") is False:
            raise HTTPException(404, detail="Source not found within requested scope")
        return {"ok": True, **result}
