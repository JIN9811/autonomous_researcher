"""Canonical UTM completion display-pointer lifecycle helpers."""

from __future__ import annotations

from typing import Any


def apply_utm_completion_artifact_update(metadata: dict[str, Any], update: Any) -> bool:
    """Apply one UTM verification attempt without reusing stale success evidence."""
    if not isinstance(update, dict):
        return False
    status = str(update.get("status") or "").strip().lower()
    if status == "stored" and update.get("path"):
        metadata["latest_utm_completion_artifact"] = dict(update)
        return True
    if status in {"failed", "blocked", "error", "not_detected"}:
        metadata.pop("latest_utm_completion_artifact", None)
        return True
    return False
