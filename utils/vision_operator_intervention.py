from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any


INTERVENTION_SCHEMA = "vision_operator_intervention.v1"
VALID_CHECKPOINTS = frozenset({"active_cam_ejection", "utm_post_place"})
ACTIVE_STATUSES = frozenset({"waiting_for_specimen", "retrying"})


def _validate_checkpoint(checkpoint: str) -> str:
    normalized = str(checkpoint or "").strip()
    if normalized not in VALID_CHECKPOINTS:
        raise ValueError(f"Unsupported vision intervention checkpoint={normalized!r}")
    return normalized


def _stored_record(metadata: dict[str, Any]) -> dict[str, Any]:
    record = metadata.get("vision_operator_intervention")
    if not isinstance(record, dict) or record.get("schema") != INTERVENTION_SCHEMA:
        return {}
    return record


def _capture_value(capture: dict[str, Any], primary: str, fallback: str) -> str:
    return str(capture.get(primary) or capture.get(fallback) or "")


def begin_intervention(
    metadata: dict[str, Any],
    *,
    run_id: str,
    checkpoint: str,
    capture: dict[str, Any],
    now: datetime,
    automatic_recovery: bool = False,
    timeout_seconds: int = 300,
    rollout_session_id: str = "",
) -> dict[str, Any]:
    checkpoint = _validate_checkpoint(checkpoint)
    previous = _stored_record(metadata)
    same_utm_recovery = bool(
        automatic_recovery
        and checkpoint == "utm_post_place"
        and previous.get("checkpoint") == checkpoint
        and previous.get("status") == "retrying"
        and previous.get("retry_started_at")
        and previous.get("retry_deadline_at")
    )
    if same_utm_recovery:
        retry_started_at = str(previous["retry_started_at"])
        retry_deadline_at = str(previous["retry_deadline_at"])
        retry_count = int(previous.get("retry_count") or 0) + 1
    else:
        retry_started_at = now.isoformat() if automatic_recovery else ""
        retry_deadline_at = (
            (now + timedelta(seconds=max(1, int(timeout_seconds)))).isoformat()
            if automatic_recovery
            else ""
        )
        retry_count = 0

    record: dict[str, Any] = {
        "schema": INTERVENTION_SCHEMA,
        "run_id": str(run_id or ""),
        "checkpoint": checkpoint,
        "status": "retrying" if automatic_recovery else "waiting_for_specimen",
        "reason": "specimen_not_detected",
        "capture_path": _capture_value(capture, "capture_path", "frame_path"),
        "capture_url": _capture_value(capture, "capture_url", "frame_url"),
        "camera_key": str(capture.get("camera_key") or ""),
        "placement_status": str(capture.get("placement_status") or "not_detected"),
        "detection_failure_code": str(capture.get("detection_failure_code") or ""),
        "requested_at": now.isoformat(),
        "retry_started_at": retry_started_at,
        "retry_deadline_at": retry_deadline_at,
        "retry_count": retry_count,
        "rollout_session_id": str(rollout_session_id or previous.get("rollout_session_id") or ""),
        "rollout_stopped": bool(previous.get("rollout_stopped")) if same_utm_recovery else False,
    }
    metadata["vision_operator_intervention"] = record
    return deepcopy(record)


def mark_intervention_retrying(
    metadata: dict[str, Any],
    *,
    checkpoint: str,
    now: datetime,
) -> dict[str, Any]:
    checkpoint = _validate_checkpoint(checkpoint)
    record = _stored_record(metadata)
    if record.get("checkpoint") != checkpoint:
        raise ValueError(f"Vision intervention checkpoint mismatch: expected={record.get('checkpoint')!r} received={checkpoint!r}")
    if record.get("status") != "retrying":
        record["status"] = "retrying"
        record["retry_count"] = int(record.get("retry_count") or 0) + 1
        record["requested_at"] = now.isoformat()
    metadata["vision_operator_intervention"] = record
    return deepcopy(record)


def mark_intervention_waiting(
    metadata: dict[str, Any],
    *,
    checkpoint: str,
    now: datetime,
    rollout_stop: dict[str, Any],
) -> dict[str, Any]:
    """Expose operator placement only after UTM rollout stop and port reclaim complete."""
    checkpoint = _validate_checkpoint(checkpoint)
    record = _stored_record(metadata)
    if record.get("checkpoint") != checkpoint:
        raise ValueError(f"Vision intervention checkpoint mismatch: expected={record.get('checkpoint')!r} received={checkpoint!r}")
    stop_status = str(rollout_stop.get("status") or "").strip().upper()
    port_status = str(rollout_stop.get("port_reclaim_status") or "").strip().lower()
    camera_lease = rollout_stop.get("active_camera_lease") if isinstance(rollout_stop.get("active_camera_lease"), dict) else {}
    camera_returned = bool(camera_lease.get("returned_to_vla"))
    port_returned = port_status in {"attempted", "reclaimed", "released", "ready"} or camera_returned
    if not (rollout_stop.get("ok") and stop_status == "STOPPED" and port_returned):
        raise ValueError("UTM operator wait requires controlled stop and camera-port return evidence")
    record.update(
        {
            "status": "waiting_for_specimen",
            "requested_at": now.isoformat(),
            "rollout_stopped": True,
            "camera_port_returned": True,
            "rollout_stop": {
                key: rollout_stop.get(key)
                for key in (
                    "ok",
                    "tool",
                    "status",
                    "session_id",
                    "profile_id",
                    "port_reclaim_status",
                    "stopped_session_ids",
                )
                if key in rollout_stop
            },
        }
    )
    metadata["vision_operator_intervention"] = record
    return deepcopy(record)


def resolve_intervention(
    metadata: dict[str, Any],
    *,
    checkpoint: str,
    now: datetime,
    capture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checkpoint = _validate_checkpoint(checkpoint)
    record = _stored_record(metadata)
    if record.get("checkpoint") != checkpoint:
        raise ValueError(f"Vision intervention checkpoint mismatch: expected={record.get('checkpoint')!r} received={checkpoint!r}")
    if capture is not None:
        record.update(
            {
                "capture_path": _capture_value(capture, "capture_path", "frame_path"),
                "capture_url": _capture_value(capture, "capture_url", "frame_url"),
                "camera_key": str(capture.get("camera_key") or record.get("camera_key") or ""),
                "placement_status": str(capture.get("placement_status") or "inside"),
                "detection_failure_code": str(capture.get("detection_failure_code") or ""),
            }
        )
    record["status"] = "resolved"
    record["resolved_at"] = now.isoformat()
    metadata["vision_operator_intervention"] = record
    return deepcopy(record)


def intervention_deadline_expired(record: dict[str, Any], *, now: datetime) -> bool:
    if (
        record.get("schema") != INTERVENTION_SCHEMA
        or record.get("checkpoint") != "utm_post_place"
        or record.get("status") != "retrying"
    ):
        return False
    raw_deadline = str(record.get("retry_deadline_at") or "").strip()
    if not raw_deadline:
        return False
    try:
        deadline = datetime.fromisoformat(raw_deadline.replace("Z", "+00:00"))
    except ValueError:
        return False
    return now >= deadline


def active_intervention(metadata: dict[str, Any]) -> dict[str, Any]:
    record = _stored_record(metadata)
    if record.get("status") not in ACTIVE_STATUSES:
        return {}
    return deepcopy(record)
