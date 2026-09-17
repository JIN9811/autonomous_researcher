"""Read-only inventory of existing run artifacts; no controller or device access."""
import mimetypes
import re
from pathlib import Path
from urllib.parse import quote

from utils.run_review import safe_child


def artifact_path(root: Path, run_id: str, relative: str) -> Path:
    run = safe_child(Path(root).resolve(), run_id)
    parts = relative.split("/")
    if (not relative or "\\" in relative or any(ord(c) < 32 for c in relative)
            or any(not p or p.startswith(".") for p in parts)
            or parts[0] in {"review", "recovery"} or relative.endswith((".tmp", ".claim"))):
        raise ValueError("Not an experiment artifact")
    path = run.joinpath(*parts)
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != run.parent):
        raise ValueError("Symlink artifacts are not served")
    path = path.resolve()
    if not path.is_relative_to(run) or not path.is_file():
        raise ValueError("Artifact unavailable")
    return path


def preview_kind(path: Path) -> str:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}:
        return "image"
    if path.suffix.lower() in {".json", ".jsonl", ".csv", ".txt", ".log", ".md", ".yaml", ".yml", ".gcode"}:
        return "text"
    return "mesh" if path.suffix.lower() == ".stl" else "download"


def artifact_index(root: Path, run_id: str) -> dict:
    from utils.agent_artifact_archive import list_executions
    run = safe_child(Path(root).resolve(), run_id)
    if not safe_child(safe_child(run, "review"), "index.json").is_file():
        raise ValueError("Not a recorded session")
    executions = list_executions(run)
    owners = {str(Path(item["manifest_path"]).parent): item for item in executions}
    references = {}
    for execution in executions:
        for item in execution.get("artifacts", []):
            if isinstance(item, dict) and item.get("status") == "copied" and item.get("path"):
                references[item["path"]] = item
    files = []
    for candidate in sorted(run.rglob("*")):
        relative = candidate.relative_to(run).as_posix()
        try:
            path = artifact_path(root, run_id, relative)
            stat = path.stat()
        except (ValueError, OSError):
            continue
        parts = Path(relative).parts
        owner = owners.get(Path(*parts[:5]).as_posix(), {}) if len(parts) >= 6 else {}
        loop = owner.get("loop_index")
        agent = owner.get("agent")
        if len(parts) >= 4 and parts[:2] == ("runtime", "loops") and re.fullmatch(r"loop-\d+", parts[2]):
            loop = int(parts[2][5:]) - 1
            agent = agent or (parts[3] if len(parts) > 4 else "orchestrator_agent")
        elif parts[0] == "workspace" and len(parts) > 2:
            agent = {"printer": "specimen"}.get(parts[1], parts[1])
        elif parts[0] in {"planning", "specimens", "design_candidates"}:
            agent = "design"
        elif parts[0] == "vision":
            agent = "vision"
        url = f"/api/review/{quote(run_id, safe='')}/files/{quote(relative, safe='/')}"
        aliases = [str(path), f"runs/{run_id}/{relative}",
                   f"/api/runs/{quote(run_id, safe='')}/artifact-file/{quote(relative, safe='/')}",
                   f"/api/artifacts/{quote(run_id + '::' + quote(relative, safe=''), safe='')}"]
        if (len(parts) == 3 and parts[0] in {"planning", "specimens"}
                and (parts[0] == "planning" or not (run / "planning" / parts[1] / parts[2]).is_file())):
            aliases.append(f"/api/planning/artifacts/{quote(run_id, safe='')}/{quote(parts[1], safe='')}/{quote(parts[2], safe='')}")
        reference = references.get(relative, {})
        if reference.get("source_path"):
            aliases.append(reference["source_path"])
        files.append({"run_id": run_id, "path": relative, "name": path.name,
                      "artifact_id": f"{run_id}::{relative}", "suffix": path.suffix.lower(),
                      "size_bytes": stat.st_size, "preview_kind": preview_kind(path),
                      "url": url, "download_url": url + "?download=1", "aliases": aliases,
                      "loop_index": loop, "agent": agent, "attempt_index": owner.get("attempt_index"),
                      "archive_status": "Session file · not a point-in-time snapshot",
                      "captured_at": reference.get("captured_at"), "modified_at": stat.st_mtime})
    return {"ok": True, "run_id": run_id, "read_only": True,
            "scope": "session_files", "artifacts": files}


def artifact_media_type(path: Path) -> str:
    # Do not render saved HTML or executable documents in the application's origin.
    if preview_kind(path) == "text" or path.suffix.lower() in {".html", ".htm", ".js"}:
        return "text/plain"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
