from __future__ import annotations

from pathlib import Path

from device_bridges.specimen_pose_tracker import (
    SpecimenPoseTrackerBridge,
    SpecimenPoseTrackerConfig,
)


def _bridge(tmp_path: Path) -> SpecimenPoseTrackerBridge:
    return SpecimenPoseTrackerBridge(
        SpecimenPoseTrackerConfig(
            enabled=True,
            d455f_serial="341522300873",
            script_path=tmp_path / "run_specimen_pose_snapshot.sh",
            log_dir=tmp_path / "logs",
            artifact_dir=tmp_path / "artifacts",
            ros_setup_paths=[],
            extra_setup_paths=[],
            max_runtime_sec=8.0,
            release_timeout_sec=5.0,
            allow_virtual_pose_in_test=True,
        )
    )


def test_virtual_snapshot_returns_pose_and_released_camera(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.snapshot({"mode": "test", "specimen_id": "specimen-1"})

    assert result["ok"] is True
    assert result["tool"] == "vision.specimen_pose_snapshot"
    assert result["pose"]["schema"] == "specimen_pose.v1"
    assert result["pose"]["specimen_id"] == "specimen-1"
    assert result["pose"]["camera_owner_before"] == "vla_runtime"
    assert result["pose"]["camera_owner_after"] == "vla_runtime"
    assert result["pose"]["port_released"] is True
    assert result["pose"]["vla_camera_precheck_ok"] is True
    assert result["lease"]["owner"] == "vla_runtime"


def test_live_snapshot_blocks_when_script_missing(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.snapshot({"mode": "live", "specimen_id": "specimen-1"})

    assert result["ok"] is False
    assert result["failure_code"] == "SPECIMEN_POSE_TRACKER_SCRIPT_NOT_FOUND"
    assert result["lease"]["owner"] in {"free", "vla_runtime"}


def test_release_status_reports_vla_owner(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    status = bridge.release({"mode": "test"})

    assert status["ok"] is True
    assert status["tool"] == "vision.specimen_pose.release"
    assert status["lease"]["owner"] == "vla_runtime"
    assert status["camera_returned_to_vla"] is True


def test_status_payload_is_gui_safe(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    status = bridge.status()

    assert status["ok"] is True
    assert status["tool"] == "vision.specimen_pose.status"
    assert status["enabled"] is True
    assert status["camera_id"] == "d455f_global"
    assert "api_key" not in str(status).lower()


def test_live_snapshot_command_parses_json_stdout(tmp_path: Path) -> None:
    script = tmp_path / "run_specimen_pose_snapshot.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "echo '{\"ok\": true, \"pose\": {\"schema\": \"specimen_pose.v1\", \"confidence\": 0.88}}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    bridge = SpecimenPoseTrackerBridge(
        SpecimenPoseTrackerConfig(script_path=script, log_dir=tmp_path / "logs", artifact_dir=tmp_path / "artifacts")
    )

    result = bridge.snapshot({"mode": "live", "specimen_id": "specimen-live"})

    assert result["ok"] is True
    assert result["pose"]["schema"] == "specimen_pose.v1"
    assert result["pose"]["camera_owner_after"] == "vla_runtime"
    assert result["pose"]["port_released"] is True


def test_ros_wrapper_matches_snapshot_node_contract() -> None:
    script = Path("scripts/vision/run_specimen_pose_snapshot.sh").read_text(encoding="utf-8")
    node = Path("ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker/specimen_pose_node.py").read_text(encoding="utf-8")

    assert '${1:-{}}' not in script
    assert "set +u" in script
    assert "--frame-id" not in script
    assert "--color-topic" in script
    assert "--depth-topic" in script
    assert "--info-topic" in script
    assert "create_subscription(Image" in node
    assert "CameraInfo" in node
    assert "specimen_pose_debug.pgm" not in node
