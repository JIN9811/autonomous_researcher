"""Canonical Active Cam display-pointer lifecycle helpers."""

from __future__ import annotations

from typing import Any


def apply_active_cam_artifact_update(metadata: dict[str, Any], update: Any) -> bool:
    """Apply one explicit capture result without disturbing no-update handoffs."""
    if not isinstance(update, dict):
        return False
    status = str(update.get("status") or "").strip().lower()
    if status == "stored" and update.get("path"):
        metadata["latest_active_cam_artifact"] = dict(update)
        return True
    if status in {"failed", "blocked", "error"}:
        metadata.pop("latest_active_cam_artifact", None)
        return True
    return False
