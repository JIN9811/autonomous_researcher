"""Read the latest accepted specimen pose produced by Recording Active Cam."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _valid_pose(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != "specimen_pose.v1":
        return {}
    world_mm = value.get("position_isaac_world_mm")
    if not isinstance(world_mm, dict):
        return {}
    for axis in ("x", "y", "z"):
        try:
            coordinate = float(world_mm.get(axis))
        except (TypeError, ValueError):
            return {}
        if not math.isfinite(coordinate):
            return {}
    return dict(value)


def _pose_from_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("ok") is not True:
        return {}
    return _valid_pose(snapshot.get("pose"))


def load_recording_specimen_pose(path: Path) -> dict[str, Any]:
    """Return a validated pose without triggering a camera or robot operation."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return {}

    direct = _valid_pose(payload.get("pose")) or _pose_from_snapshot(payload.get("snapshot"))
    if direct:
        return direct

    attempts = payload.get("attempts")
    if not isinstance(attempts, list):
        return {}
    for attempt in reversed(attempts):
        result = attempt.get("result") if isinstance(attempt, dict) else None
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        pose = _valid_pose(result.get("pose")) or _pose_from_snapshot(result.get("snapshot"))
        if pose:
            return pose
    return {}
