"""Bounded JSON API for detached packages. Host supplies the validation service."""
import json
from typing import Callable
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from packages.service import MAX_PACKAGE_BYTES, PackageService


def make_packages_router(service_factory: Callable[[], PackageService]) -> APIRouter:
    router = APIRouter(prefix="/api/packages", tags=["packages"])

    @router.get("")
    async def catalog():
        return service_factory().catalog()

    async def process(request: Request, *, exporting: bool):
        def failure(message, status):
            return JSONResponse(status_code=status, content={"ok": False, "errors": [message],
                "package" if exporting else "draft": None, "activated": False, "persisted": False,
                **({} if exporting else {"unresolved_bindings": []})})

        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_PACKAGE_BYTES:
                return failure("Package exceeds 1048576 byte limit", 413)
            body.extend(chunk)
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("Duplicate JSON key")
                result[key] = value
            return result
        def reject_constant(value):
            raise ValueError("Non-finite JSON")
        try:
            payload = json.loads(body, object_pairs_hook=pairs, parse_constant=reject_constant)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return failure("Invalid JSON object or duplicate key", 400)
        service = service_factory()
        return service.export_experimental(payload) if exporting else service.import_experimental(payload)

    @router.post("/experimental/export")
    async def export(request: Request):
        return await process(request, exporting=True)

    @router.post("/experimental/import")
    async def import_draft(request: Request):
        return await process(request, exporting=False)

    return router
