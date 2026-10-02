"""Scoped Workspace HTTP routes; request bodies never choose a private identity."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal


class WorkspaceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", max_length=2_000)
    filters: dict[str, Any] = Field(default_factory=dict)
    cursor: str = Field(default="", max_length=8_000)
    limit: int = Field(default=25, ge=1, le=100, strict=True)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1, max_length=200)
    filters: dict[str, Any] = Field(default_factory=dict)


class MemoryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(min_length=1, max_length=24)
    target_id: str = Field(default="", max_length=200)
    expected_revision: int | None = Field(default=None, ge=1, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


def trusted_local_profile_resolver(profile: KnowledgePrincipal | None = None) -> Callable[[Request], KnowledgePrincipal | None]:
    """Return an explicit installation hook, never an IP/loopback-based identity guess.

    A deployment may pass a verified local profile or replace this resolver with
    a session/auth integration. Passing no profile deliberately keeps HTTP
    requests public-only.
    """
    return lambda request: profile


def install_workspace_routes(app, *, service_factory: Callable[[], KnowledgeContextService],
                             principal_resolver: Callable[[Request], KnowledgePrincipal | None],
                             admin_origins: frozenset[str] = frozenset(),
                             private_mutation_origins: frozenset[str] = frozenset()) -> None:
    """Install v2 endpoints without changing legacy markdown/source routes."""
    prefix = "/api/knowledge"

    @app.middleware("http")
    async def workspace_no_store_errors(request: Request, call_next):
        """Validation and exception responses need the same private-cache guard."""
        response = await call_next(request)
        if request.url.path.startswith(prefix + "/workspace") or request.url.path.startswith(prefix + "/wiki") or request.url.path.startswith(prefix + "/memory") or request.url.path.startswith(prefix + "/delivery") or request.url.path.startswith(prefix + "/context"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def principal(request: Request) -> KnowledgePrincipal | None:
        value = principal_resolver(request)
        if value is not None and not isinstance(value, KnowledgePrincipal):
            raise RuntimeError("principal resolver returned an invalid principal")
        return value

    def no_store(payload: Any, status_code: int = 200) -> JSONResponse:
        return JSONResponse(status_code=status_code, content=payload, headers={"Cache-Control": "no-store"})

    async def invoke(function, *args, **kwargs):
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except PermissionError as exc:
            raise HTTPException(401, detail="Private Knowledge access requires a trusted server principal") from exc
        except KeyError as exc:
            raise HTTPException(404, detail="Knowledge record not found within requested scope") from exc
        except ValueError as exc:
            code = 409 if "conflict" in str(exc) else 422
            raise HTTPException(code, detail=str(exc)) from exc

    def read_envelope(item: dict[str, Any] | None, scope_ref: str) -> dict[str, Any]:
        if item is None: raise HTTPException(404, detail="Knowledge record not found within requested scope")
        return {"items": [item], "next_cursor": "", "scope_ref": scope_ref, "revision": str(item.get("revision", "")),
                "as_of": item.get("updated_at", item.get("verified_at", "")), "status": "ok"}

    @app.get(prefix + "/workspace/summary")
    async def workspace_summary(request: Request):
        return no_store(await invoke(service_factory().summary, principal(request)))

    @app.post(prefix + "/wiki/query")
    async def wiki_query(request: Request, body: WorkspaceQuery):
        return no_store(await invoke(service_factory().wiki.query, body.query, filters=body.filters, cursor=body.cursor, limit=body.limit))

    @app.post(prefix + "/wiki/read")
    async def wiki_read(request: Request, body: WorkspaceRead):
        item = await invoke(service_factory().wiki.read, body.record_id, filters=body.filters)
        return no_store(read_envelope(item, "ax4lab_wiki"))

    @app.post(prefix + "/wiki/reindex")
    async def wiki_reindex(request: Request):
        actor = principal(request)
        if actor is None or not actor.is_admin: raise HTTPException(403, detail="Administrative authorization is required")
        if not admin_origins or request.headers.get("origin") not in admin_origins:
            raise HTTPException(403, detail="Administrative request origin is not allowed")
        return no_store(await invoke(service_factory().wiki.reindex))

    @app.post(prefix + "/memory/query")
    async def memory_query(request: Request, body: WorkspaceQuery):
        return no_store(await invoke(service_factory().memory.query, principal(request), body.query, filters=body.filters, cursor=body.cursor, limit=body.limit))

    @app.post(prefix + "/memory/read")
    async def memory_read(request: Request, body: WorkspaceRead):
        actor = principal(request)
        if actor is None: raise HTTPException(401, detail="Private Knowledge access requires a trusted server principal")
        item = await invoke(service_factory().memory.read, actor, body.record_id)
        return no_store(read_envelope(item, "private:" + actor.subject_id))

    @app.post(prefix + "/memory/commands")
    async def memory_commands(request: Request, body: MemoryCommand):
        actor = principal(request)
        if actor is not None and (not private_mutation_origins or request.headers.get("origin") not in private_mutation_origins):
            raise HTTPException(403, detail="Private memory mutation origin is not allowed")
        return no_store(await invoke(service_factory().memory.command, actor, action=body.action, payload=body.payload,
                                     idempotency_key=body.idempotency_key, target_id=body.target_id,
                                     expected_revision=body.expected_revision))

    @app.post(prefix + "/delivery/query")
    async def delivery_query(request: Request, body: WorkspaceQuery):
        return no_store(await invoke(service_factory().delivery.query, principal(request), body.query, filters=body.filters, cursor=body.cursor, limit=body.limit))

    @app.post(prefix + "/delivery/read")
    async def delivery_read(request: Request, body: WorkspaceRead):
        actor = principal(request)
        if actor is None: raise HTTPException(401, detail="Private Knowledge access requires a trusted server principal")
        item = await invoke(service_factory().delivery.read, actor, body.record_id)
        return no_store(read_envelope(item, "delivery:" + actor.subject_id))

    @app.post(prefix + "/context/query")
    async def context_query(request: Request, body: WorkspaceQuery):
        consumer = body.filters.pop("consumer", "workspace")
        return no_store(await invoke(service_factory().query, principal(request), body.query, consumer=consumer,
                                     filters=body.filters, cursor=body.cursor, limit=body.limit))

    @app.post(prefix + "/context/read")
    async def context_read(request: Request, body: WorkspaceRead):
        actor = principal(request)
        item = await invoke(service_factory().read_context, actor, body.record_id)
        return no_store(read_envelope(item, "public" if actor is None else "scoped:" + actor.subject_id))
