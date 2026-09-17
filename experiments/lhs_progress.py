"""Presentation-only design milestones, separate from measured BO observations."""
from copy import deepcopy
import hashlib
import inspect
import json
import math


def point_key(parameters):
    try:
        values = [float(parameters[k]) for k in ("cell_size_mm", "wall_thickness_mm")]
        if not all(math.isfinite(v) for v in values):
            return None
        return tuple(round(v, 8) for v in values)
    except (KeyError, TypeError, ValueError):
        return None


def project_design_progress(visualization, metadata):
    result = deepcopy(visualization)
    keys = {point_key(row.get("parameters", {})) for row in metadata.get("lhs_designed_candidates", [])
            if row.get("run_id") == visualization.get("run_id")}
    keys.discard(None)
    previous = metadata.get("lhs_visualization") or {}
    measured = {point_key(row.get("parameters")) for row in (previous.get("initial_design") or {}).get("points", [])
                if previous.get("run_id") == visualization.get("run_id") and row.get("status") == "measured"}
    measured.discard(None)
    initial = result.get("initial_design", {})
    for point in initial.get("points", []):
        if point_key(point.get("parameters")) in measured:
            point["status"] = "measured"
        elif point.get("status") != "measured" and point_key(point.get("parameters")) in keys:
            point["status"] = "designed"
    initial["completed"] = sum(p.get("status") == "measured" for p in initial.get("points", []))
    initial["designed"] = sum(p.get("status") in {"designed", "measured"} for p in initial.get("points", []))
    target = max(1, int(initial.get("target") or 1))
    result.setdefault("diagnostics", {})["coverage_fraction"] = initial["completed"] / target
    result["status"] = "complete" if initial["completed"] >= target else "active"
    return result


def progress_fingerprint(visualization):
    payload = {key: visualization.get(key) for key in ("run_id", "step", "design_space", "initial_design")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


async def record_design_ready(state, ctx, spec):
    key = point_key(spec)
    if key is None:
        return
    rows = state.run_metadata.setdefault("lhs_designed_candidates", [])
    if any(row.get("run_id") == state.run_id and point_key(row.get("parameters")) == key for row in rows):
        return
    rows.append({"run_id": state.run_id, "candidate_id": spec.get("candidate_id", ""),
                 "specimen_id": spec.get("specimen_id", ""),
                 "parameters": {k: spec[k] for k in ("cell_size_mm", "wall_thickness_mm")}})
    del rows[:-512]
    callback = getattr(ctx, "emit_execution_event", None)
    if callable(callback):
        try:
            result = callback({"type": "design.candidate_ready", "payload": {
                "run_id": state.run_id, "module_id": "design", "status": "designed",
                "candidate_id": spec.get("candidate_id", ""), "loop_index": state.loop_count,
            }})
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass  # Plot publication cannot change design/experiment success.
