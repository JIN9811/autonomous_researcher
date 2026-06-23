"""Tests for in-process LeRobot -> Isaac mirror publication."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.lerobot_isaac_mirror_runtime_wrapper import IsaacMirrorPublisher


def test_isaac_mirror_runtime_wrapper_does_not_precreate_record_parent_before_first_sample(tmp_path: Path, monkeypatch) -> None:
    record_path = tmp_path / "dataset" / "sidecar" / "isaac_mirror" / "mirror.jsonl"
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(record_path))

    IsaacMirrorPublisher()

    assert not record_path.parent.exists()
    assert not (tmp_path / "dataset").exists()


def test_isaac_mirror_runtime_wrapper_applies_calibration_to_payload_and_sidecar(tmp_path: Path, monkeypatch) -> None:
    calibration_path = tmp_path / "isaac_omx_mirror_calibration.json"
    record_path = tmp_path / "mirror.jsonl"
    calibration_path.write_text(json.dumps({"joints": {"shoulder_pan": {"offset_deg": 10.0}}}), encoding="utf-8")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_CALIBRATION_PATH", str(calibration_path))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_RECORD_PATH", str(record_path))
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SAMPLE_HZ", "999")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_SESSION_ID", "mirror-test-session")
    monkeypatch.setenv("ATR_ISAAC_MIRROR_PROFILE_ID", "robotis_omx_ai")

    publisher = IsaacMirrorPublisher()
    posted: list[dict[str, object]] = []
    monkeypatch.setattr(publisher, "_post", lambda payload: posted.append(payload) or {"ok": True, "status_code": 200})

    publisher.maybe_publish({"shoulder_pan.pos": 5.0})

    assert len(posted) == 1
    assert posted[0]["session_id"] == "mirror-test-session"
    assert posted[0]["calibration"]["loaded"] is True  # type: ignore[index]
    assert posted[0]["joint_state"][0]["motor_name"] == "shoulder_pan"  # type: ignore[index]
    assert posted[0]["joint_state"][0]["position_deg"] == 15.0  # type: ignore[index]
    record = json.loads(record_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["calibration"]["path"] == str(calibration_path)
    assert record["sync_metrics"]["receiver_accepted"] is True
