"""Local Knowledge adapters for existing agent archives; never replay execution."""
from __future__ import annotations

from functools import lru_cache
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any

from knowledge.ontology.registry import OntologyRegistry

_PROJECT = Path(__file__).resolve().parents[1]
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,179}\Z")


def applicability_for(state) -> dict:
    """Copy explicit Knowledge conditions and current objective identity, never infer them."""
    settings = state.run_metadata.get("knowledge_settings", {})
    if not isinstance(settings, dict) or not isinstance(settings.get("scope", {}), dict):
        raise ValueError("Knowledge settings and scope must be objects")
    result = {}
    for conditions in (settings.get("applicability", {}), settings.get("scope", {}).get("applicability", {})):
        if not isinstance(conditions, dict):
            raise ValueError("Knowledge applicability must be an object")
        for key, value in conditions.items():
            if key in result and result[key] != value:
                raise ValueError("Conflicting explicit Knowledge conditions")
            result[key] = deepcopy(value)
    analysis = state.latest_analysis
    payload = analysis.get("knowledge_payload", {})
    evaluation = analysis.get("objective_evaluation") or (
        payload.get("objective_evaluation", {}) if isinstance(payload, dict) else {})
    for objective in (state.current_experiment_objective, evaluation):
        if not isinstance(objective, dict):
            raise ValueError("Objective identity must be an object")
        for key in ("objective_id", "objective_hash"):
            if objective.get(key):
                value = str(objective[key])
                if key in result and result[key] != value:
                    raise ValueError("Knowledge scope conflicts with current objective")
                result[key] = value
    # No silent NaN/stringification of declared conditions.
    json.dumps(result, allow_nan=False)
    return result


@lru_cache(maxsize=32)
def _store(root: str):
    from knowledge.markdown_memory import MarkdownKnowledgeStore
    return MarkdownKnowledgeStore(Path(root), OntologyRegistry.load_default(_PROJECT))


def store_for(ctx=None, *, project_root: Path | None = None, memory_root: Path | None = None):
    """Honor isolated artifact roots in tests/direct calls; ontology stays code-owned."""
    if memory_root is None:
        if project_root is None:
            run_root = getattr(ctx, "artifact_run_root", None)
            project_root = Path(run_root).resolve().parent if run_root else _PROJECT
        memory_root = Path(project_root) / "memory" / "knowledge"
    return _store(str((Path(memory_root) / "markdown").resolve()))


def _read_json(path: Path, root: Path, *, limit: int = 4_000_000) -> dict:
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Archive source escapes the configured run root")
    if path.stat().st_size > limit:
        raise ValueError("Archive source exceeds intake size limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Archive source must contain an object")
    return value


def ingest_archive_manifest(run_root: Path, manifest_path: Path, *, store=None) -> dict[str, Any]:
    """One frozen terminal archive -> one idempotent observed MD note."""
    run_root, manifest_path = Path(run_root).resolve(), Path(manifest_path).resolve()
    if not manifest_path.is_relative_to(run_root) or manifest_path.name != "manifest.json":
        raise ValueError("Invalid archive manifest path")
    manifest = _read_json(manifest_path, run_root, limit=1_000_000)
    if manifest.get("knowledge_scope_error"):
        raise ValueError("Archive has invalid Knowledge applicability")
    status = str(manifest.get("status") or "")
    if status not in {"completed", "success", "failed", "cancelled"}:
        return {"ok": True, "status": "skipped", "reason": "Archive is not terminal"}
    run_id = str(manifest.get("run_id") or "")
    if not _ID.fullmatch(run_id):
        raise ValueError("Invalid archive run identity")
    run_dir = (run_root / run_id).resolve()
    if not manifest_path.is_relative_to(run_dir):
        raise ValueError("Manifest does not belong to declared run")
    result_path = (run_dir / str(manifest.get("result_path") or "")).resolve()
    # Only the result beside this manifest is the same execution's evidence.
    if result_path != manifest_path.with_name("result.json"):
        raise ValueError("Result does not belong to this archive execution")
    result = _read_json(result_path, run_dir)
    if result.get("status") != status:
        raise ValueError("Archive result and manifest status disagree")
    execution_id = str(manifest.get("execution_id") or "")
    if not _ID.fullmatch(execution_id):
        raise ValueError("Archive execution identity missing")
    loop_number = int(manifest.get("loop_number") or 0)
    if loop_number < 1:
        raise ValueError("Archive loop number missing")
    agent = str(manifest.get("agent") or "")
    if not _ID.fullmatch(agent):
        raise ValueError("Archive agent identity missing")
    summary = str(result.get("summary") or "").strip()[:2000]
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    classification = ("Operator or runtime cancellation; not evidence of a device fault."
                      if status == "cancelled" else "Recorded execution outcome; no inferred root cause.")
    relative = manifest_path.relative_to(run_root).as_posix()
    note = {
        "run_id": run_id, "cycle_id": f"loop-{loop_number:06d}", "agent_id": agent,
        "event_id": execution_id, "ontology_type": "Observation", "title": f"{agent}: {status}",
        "body": f"## Observation\n\nExecution status: {status}.\n\n{summary}\n\n"
                f"## Interpretation boundary\n\n{classification}\n\n"
                f"Error type: {str(data.get('error_type') or 'none')[:100]}.\n",
        "tags": ["execution", status], "evidence_kind": "observed", "fidelity": "unknown",
        "applicability": {**manifest.get("knowledge_applicability", {}),
                          "runtime_mode": str(manifest.get("runtime_mode") or "unknown")},
        "source_refs": [f"runs/{relative}", f"runs/{result_path.relative_to(run_root).as_posix()}"],
    }
    return (store or store_for(project_root=run_root.parent)).write_note(note)


def intake_archives(run_root: Path, *, store=None, run_id: str = "", limit: int = 100, cursor: str = "") -> dict:
    """Bounded explicit post-processing. Caller runs this outside the control loop."""
    if run_id and not _ID.fullmatch(run_id):
        raise ValueError("Invalid run_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if cursor and (Path(cursor).is_absolute() or ".." in Path(cursor).parts):
        raise ValueError("Invalid intake cursor")
    run_root = Path(run_root).resolve()
    pattern = f"{run_id or '*'}/runtime/loops/loop-*/*/attempt-*/manifest.json"
    selected = []
    for path in sorted(run_root.glob(pattern)):
        if path.relative_to(run_root).as_posix() > cursor:
            selected.append(path)
            if len(selected) > limit:
                break
    more = len(selected) > limit
    results = []
    for path in selected[:limit]:
        relative = path.relative_to(run_root).as_posix()
        try:
            result = ingest_archive_manifest(run_root, path, store=store)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result = {"ok": False, "status": "error", "error": type(exc).__name__}
        results.append({"source": relative, **result})
    return {"ok": all(item.get("ok", False) for item in results), "processed": len(results),
            "results": results, "has_more": more,
            "next_cursor": results[-1]["source"] if results else cursor,
            "physical_actuation": False, "llm_used": False}
