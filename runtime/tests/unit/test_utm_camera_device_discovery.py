"""Tests for V4L camera discovery used by the UTM Camera bridge page."""

from __future__ import annotations

from pathlib import Path

from device_bridges.utm_runtime_bridge import discover_v4l2_camera_devices


def test_discover_v4l2_devices_lists_os_camera_candidate_without_model_specific_recommendation(tmp_path: Path) -> None:
    by_id = tmp_path / "dev" / "v4l" / "by-id"
    by_id.mkdir(parents=True)
    target = tmp_path / "dev" / "video0"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")
    symlink = by_id / "usb-046d_Logitech_BRIO_1CD057A6-video-index0"
    symlink.symlink_to(target)

    devices = discover_v4l2_camera_devices(by_id_root=by_id, command_runner=lambda _cmd: (0, "", ""))

    assert devices["ok"] is True
    assert devices["devices"]
    device = devices["devices"][0]
    assert "Logitech BRIO" in device["label"]
    assert device["recommended"] is False
    assert device["by_id_path"].endswith("usb-046d_Logitech_BRIO_1CD057A6-video-index0")


def test_discover_v4l2_devices_reports_missing_v4l2_ctl(tmp_path: Path) -> None:
    by_id = tmp_path / "missing"

    devices = discover_v4l2_camera_devices(by_id_root=by_id, command_runner=lambda _cmd: (127, "", "v4l2-ctl: not found"))

    assert devices["ok"] is False
    assert devices["failure_code"] == "V4L2_CTL_NOT_AVAILABLE"
