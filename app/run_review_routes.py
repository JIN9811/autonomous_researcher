"""Read-only archive routes: deliberately no controller/device dependency."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from utils.run_review import safe_child


def review_router(root: Path, templates):
    router = APIRouter()
    root = Path(root).resolve()

    def archive(run_id):
        return safe_child(safe_child(root, run_id), "review")

    def read(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(404, "Not recorded")

    @router.get("/replay")
    def page(request: Request):
        origin = str(request.base_url).rstrip("/")
        response = templates.TemplateResponse(request=request, name="planning.html",
            context={"title": "Replay GUI", "replay": True})
        # Defense in depth: shared LIVE renderers cannot reach control/camera APIs,
        # even through an image, form, websocket, or a future accidental fetch.
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            f"connect-src {origin}/api/review/ {origin}/static/ {origin}/module-assets/; "
            f"img-src data: blob: {origin}/static/ {origin}/api/review/; "
            "media-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; worker-src 'none'; base-uri 'self'")
        return response

    @router.get("/api/review/layout")
    def layout():
        # Same installed frontend packages, not live runtime state or devices.
        import re
        from utils.run_review import AGENTS
        agents = []
        package_root = Path(__file__).resolve().parents[1] / "agents"
        for owner in AGENTS:
            source = package_root / owner / "frontend" / "live_report.js"
            item = {"id": owner, "stage": owner, "module_id": owner, "enabled": True}
            if source.is_file():
                namespace = re.search(r"global\.(AX4LAB\w+UI)\s*=", source.read_text())
                if namespace:
                    item["implementation"] = {"frontend": {"asset_url": f"/module-assets/{owner}/live_report.js",
                        "namespace": namespace[1], "factory": "createFrontend", "report_api": f"/api/agents/{owner}/report"}}
            agents.append(item)
        return {"ok": True, "agents": agents}

    @router.get("/api/review/runs")
    def runs():
        items = []
        for path in sorted(root.glob("*/review/index.json"), reverse=True):
            try:
                resolved = safe_child(archive(path.parent.parent.name), "index.json")
                data = read(resolved)
                items.append({"run_id": data["run_id"], "points": len(data["points"])})
            except (ValueError, KeyError, HTTPException):
                continue
            if len(items) >= 200:
                break
        return {"runs": items, "read_only": True}

    @router.get("/api/review/{run_id}/points")
    def points(run_id: str):
        try:
            return read(safe_child(archive(run_id), "index.json"))
        except ValueError:
            raise HTTPException(404, "Not recorded")

    @router.get("/api/review/{run_id}/points/{point_id}")
    def point(run_id: str, point_id: str):
        if len(point_id) != 6 or not point_id.isdigit():
            raise HTTPException(404, "Not recorded")
        try:
            return read(safe_child(archive(run_id), f"{point_id}.json"))
        except ValueError:
            raise HTTPException(404, "Not recorded")

    @router.get("/api/review/{run_id}/assets/{name}")
    def asset(run_id: str, name: str):
        try:
            path = safe_child(safe_child(archive(run_id), "assets"), name)
            if path.suffix not in {".png", ".jpg", ".jpeg", ".webp"} or not path.is_file():
                raise ValueError()
            return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable",
                                               "X-Content-Type-Options": "nosniff"})
        except ValueError:
            raise HTTPException(404, "Not recorded")

    @router.get("/api/review/{run_id}/artifacts")
    def artifacts(run_id: str):
        from utils.run_review_artifacts import artifact_index
        try:
            return artifact_index(root, run_id)
        except (ValueError, OSError):
            raise HTTPException(404, "Recorded session artifacts unavailable")

    @router.get("/api/review/{run_id}/files/{relative:path}")
    def artifact_file(run_id: str, relative: str, download: bool = False):
        from utils.run_review_artifacts import artifact_path, artifact_media_type
        try:
            if not safe_child(archive(run_id), "index.json").is_file():
                raise ValueError()
            path = artifact_path(root, run_id, relative)
            return FileResponse(path, media_type=artifact_media_type(path), filename=path.name,
                                content_disposition_type="attachment" if download else "inline",
                                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                         "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"})
        except (ValueError, OSError):
            raise HTTPException(404, "Recorded artifact unavailable")

    return router
