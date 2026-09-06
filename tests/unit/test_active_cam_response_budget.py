import json
import subprocess
from pathlib import Path

import pytest

from scripts.lerobot_isaac_mirror_runtime_wrapper import SpecimenPoseFrameUpdater


@pytest.mark.parametrize(
    "detector_latency,override,expected_ok",
    [(8.0, None, True), (20.0, None, False), (8.0, "2", False)],
)
def test_active_cam_detector_response_budget(
    tmp_path: Path, monkeypatch, detector_latency, override, expected_ok
) -> None:
    # Simulate only the external detector duration; exercise the actual
    # updater's budget, timeout handling, validation, and evidence writes.
    script = tmp_path / "detector.sh"
    script.touch()
    manifest = tmp_path / "frame.json"
    manifest.write_text("{}", encoding="utf-8")
    pending = tmp_path / "pending.json"
    monkeypatch.setenv("ATR_SPECIMEN_POSE_RECORD_START_ENABLED", "1")
    monkeypatch.setenv("ATR_SPECIMEN_POSE_FRAME_SCRIPT", str(script))
    monkeypatch.setenv("ATR_SPECIMEN_POSE_PENDING_PATH", str(pending))
    monkeypatch.delenv("ATR_SPECIMEN_POSE_FRAME_TIMEOUT_S", raising=False)
    if override is not None:
        monkeypatch.setenv("ATR_SPECIMEN_POSE_FRAME_TIMEOUT_S", override)

    def detector(command, **kwargs):
        if detector_latency > kwargs["timeout"]:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "ok": True, "pose": {"position_isaac_world_mm": {"x": 1, "y": 2, "z": 3}},
        }), "")

    monkeypatch.setattr("scripts.lerobot_isaac_mirror_runtime_wrapper.subprocess.run", detector)
    updater = SpecimenPoseFrameUpdater()
    monkeypatch.setattr(updater, "_post_json", lambda *_: {"ok": True})
    result = updater.update_from_manifest(manifest, reason="active_robot_cam_d405")
    assert result["ok"] is expected_ok
    assert pending.exists() is expected_ok
    if not expected_ok:
        assert result["failure_code"] == "SPECIMEN_POSE_FRAME_TIMEOUT"
