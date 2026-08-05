from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from utils.vision_operator_intervention import (
    active_intervention,
    begin_intervention,
    intervention_deadline_expired,
    mark_intervention_retrying,
    mark_intervention_waiting,
    resolve_intervention,
)


NOW = datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc)


def test_begin_active_cam_wait_preserves_fresh_frame() -> None:
    metadata: dict[str, object] = {}

    record = begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="active_cam_ejection",
        capture={
            "capture_path": "/tmp/frame.png",
            "capture_url": "/api/frame.png",
            "camera_key": "wrist",
            "placement_status": "outside",
            "detection_failure_code": "SPECIMEN_OUTSIDE_A4",
        },
        now=NOW,
    )

    assert record["schema"] == "vision_operator_intervention.v1"
    assert record["status"] == "waiting_for_specimen"
    assert record["reason"] == "specimen_not_detected"
    assert record["capture_path"] == "/tmp/frame.png"
    assert record["capture_url"] == "/api/frame.png"
    assert record["placement_status"] == "outside"
    assert record["detection_failure_code"] == "SPECIMEN_OUTSIDE_A4"
    assert metadata["vision_operator_intervention"] == record


def test_begin_utm_recovery_sets_exact_five_minute_deadline() -> None:
    metadata: dict[str, object] = {}

    record = begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="utm_post_place",
        capture={"frame_path": "/tmp/utm.png", "camera_key": "utm"},
        now=NOW,
        automatic_recovery=True,
        timeout_seconds=300,
        rollout_session_id="lr-rollout-1",
    )

    assert record["status"] == "retrying"
    assert record["retry_started_at"] == NOW.isoformat()
    assert record["retry_deadline_at"] == (NOW + timedelta(seconds=300)).isoformat()
    assert record["rollout_session_id"] == "lr-rollout-1"
    assert record["rollout_stopped"] is False


def test_repeated_utm_non_detection_keeps_original_deadline_and_refreshes_frame() -> None:
    metadata: dict[str, object] = {}
    first = begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="utm_post_place",
        capture={"capture_path": "/tmp/utm-1.png", "camera_key": "utm"},
        now=NOW,
        automatic_recovery=True,
    )

    second = begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="utm_post_place",
        capture={"capture_path": "/tmp/utm-2.png", "camera_key": "utm"},
        now=NOW + timedelta(seconds=30),
        automatic_recovery=True,
    )

    assert second["retry_started_at"] == first["retry_started_at"]
    assert second["retry_deadline_at"] == first["retry_deadline_at"]
    assert second["capture_path"] == "/tmp/utm-2.png"
    assert second["retry_count"] == 1


def test_retry_is_idempotent_while_already_retrying() -> None:
    metadata: dict[str, object] = {}
    begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="active_cam_ejection",
        capture={"capture_path": "/tmp/frame.png"},
        now=NOW,
    )

    first = mark_intervention_retrying(metadata, checkpoint="active_cam_ejection", now=NOW)
    second = mark_intervention_retrying(metadata, checkpoint="active_cam_ejection", now=NOW)

    assert first["status"] == "retrying"
    assert second["retry_count"] == first["retry_count"]


def test_resolve_intervention_preserves_evidence_and_is_not_active() -> None:
    metadata: dict[str, object] = {}
    begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="active_cam_ejection",
        capture={"capture_path": "/tmp/frame.png"},
        now=NOW,
    )

    record = resolve_intervention(metadata, checkpoint="active_cam_ejection", now=NOW)

    assert record["status"] == "resolved"
    assert record["capture_path"] == "/tmp/frame.png"
    assert active_intervention(metadata) == {}


def test_resolve_intervention_replaces_failed_frame_with_retry_evidence() -> None:
    metadata: dict[str, object] = {}
    begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="active_cam_ejection",
        capture={
            "capture_path": "/tmp/failed-frame.png",
            "capture_url": "/api/failed-frame.png",
            "camera_key": "wrist",
        },
        now=NOW,
    )

    record = resolve_intervention(
        metadata,
        checkpoint="active_cam_ejection",
        now=NOW + timedelta(seconds=5),
        capture={
            "capture_path": "/tmp/retry-frame.png",
            "capture_url": "/api/retry-frame.png",
            "camera_key": "wrist",
            "placement_status": "inside",
        },
    )

    assert record["status"] == "resolved"
    assert record["capture_path"] == "/tmp/retry-frame.png"
    assert record["capture_url"] == "/api/retry-frame.png"
    assert record["placement_status"] == "inside"


def test_deadline_expiry_requires_retrying_utm_record() -> None:
    metadata: dict[str, object] = {}
    record = begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="utm_post_place",
        capture={"capture_path": "/tmp/utm.png"},
        now=NOW,
        automatic_recovery=True,
    )

    assert intervention_deadline_expired(record, now=NOW + timedelta(seconds=299)) is False
    assert intervention_deadline_expired(record, now=NOW + timedelta(seconds=300)) is True


def test_utm_operator_wait_requires_controlled_stop_and_port_return_evidence() -> None:
    metadata: dict[str, object] = {}
    begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="utm_post_place",
        capture={"capture_path": "/tmp/utm.png"},
        now=NOW,
        automatic_recovery=True,
    )

    with pytest.raises(ValueError, match="controlled stop"):
        mark_intervention_waiting(
            metadata,
            checkpoint="utm_post_place",
            now=NOW + timedelta(seconds=300),
            rollout_stop={"ok": False, "status": "FAILED"},
        )

    record = mark_intervention_waiting(
        metadata,
        checkpoint="utm_post_place",
        now=NOW + timedelta(seconds=301),
        rollout_stop={
            "ok": True,
            "status": "STOPPED",
            "session_id": "lr-rollout-1",
            "port_reclaim_status": "attempted",
        },
    )

    assert record["status"] == "waiting_for_specimen"
    assert record["rollout_stopped"] is True
    assert record["camera_port_returned"] is True
    assert record["rollout_stop"]["status"] == "STOPPED"


def test_invalid_checkpoint_is_rejected() -> None:
    with pytest.raises(ValueError, match="checkpoint"):
        begin_intervention(
            {},
            run_id="run-1",
            checkpoint="printer",
            capture={},
            now=NOW,
        )
