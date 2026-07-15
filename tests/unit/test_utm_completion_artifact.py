"""Tests for the canonical UTM completion display artifact lifecycle."""

from pathlib import Path

from utils.utm_completion_artifact import apply_utm_completion_artifact_update


def test_no_update_preserves_latest_utm_completion_artifact() -> None:
    latest = {
        "schema": "utm_completion_run_artifact.v1",
        "status": "stored",
        "path": "/runs/utm-frame-1.png",
        "session_id": "rollout-1",
        "specimen_id": "specimen-1",
    }
    metadata = {"latest_utm_completion_artifact": dict(latest)}

    changed = apply_utm_completion_artifact_update(metadata, None)

    assert changed is False
    assert metadata["latest_utm_completion_artifact"] == latest


def test_stored_update_replaces_latest_utm_completion_artifact() -> None:
    metadata = {
        "latest_utm_completion_artifact": {
            "status": "stored",
            "path": "/runs/old.png",
            "session_id": "rollout-old",
        }
    }
    update = {
        "schema": "utm_completion_run_artifact.v1",
        "status": "stored",
        "path": "/runs/new.png",
        "session_id": "rollout-new",
        "specimen_id": "specimen-new",
    }

    changed = apply_utm_completion_artifact_update(metadata, update)

    assert changed is True
    assert metadata["latest_utm_completion_artifact"] == update


def test_failed_attempt_clears_pointer_but_keeps_prior_file(tmp_path: Path) -> None:
    prior = tmp_path / "prior.png"
    prior.write_bytes(b"prior")
    metadata = {
        "latest_utm_completion_artifact": {
            "status": "stored",
            "path": str(prior),
            "session_id": "rollout-prior",
        }
    }

    changed = apply_utm_completion_artifact_update(
        metadata,
        {
            "schema": "utm_completion_run_artifact.v1",
            "status": "not_detected",
            "session_id": "rollout-current",
            "failure_code": "UTM_SPECIMEN_NOT_DETECTED",
        },
    )

    assert changed is True
    assert "latest_utm_completion_artifact" not in metadata
    assert prior.read_bytes() == b"prior"
