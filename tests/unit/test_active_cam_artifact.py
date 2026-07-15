"""Tests for the canonical Active Cam display artifact lifecycle."""

from pathlib import Path

from utils.active_cam_artifact import apply_active_cam_artifact_update


def test_no_update_preserves_latest_active_cam_artifact() -> None:
    latest = {
        "schema": "active_cam_run_artifact.v1",
        "status": "stored",
        "path": "/runs/frame-1.jpg",
    }
    metadata = {"latest_active_cam_artifact": dict(latest)}

    changed = apply_active_cam_artifact_update(metadata, None)

    assert changed is False
    assert metadata["latest_active_cam_artifact"] == latest


def test_stored_update_replaces_latest_active_cam_artifact() -> None:
    metadata = {"latest_active_cam_artifact": {"status": "stored", "path": "/runs/old.jpg"}}
    update = {
        "schema": "active_cam_run_artifact.v1",
        "status": "stored",
        "path": "/runs/new.jpg",
    }

    changed = apply_active_cam_artifact_update(metadata, update)

    assert changed is True
    assert metadata["latest_active_cam_artifact"] == update


def test_failed_update_clears_pointer_but_not_artifact_files(tmp_path: Path) -> None:
    prior = tmp_path / "prior.jpg"
    prior.write_bytes(b"prior")
    metadata = {"latest_active_cam_artifact": {"status": "stored", "path": str(prior)}}

    changed = apply_active_cam_artifact_update(
        metadata,
        {
            "schema": "active_cam_run_artifact.v1",
            "status": "failed",
            "failure_code": "CAPTURE_FAILED",
        },
    )

    assert changed is True
    assert "latest_active_cam_artifact" not in metadata
    assert prior.read_bytes() == b"prior"
