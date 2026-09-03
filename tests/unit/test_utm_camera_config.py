"""Tests for UTM Camera device bridge configuration."""

from __future__ import annotations

from pathlib import Path

from device_bridges.utm_runtime_bridge import UTMCameraConfig


def test_default_camera_config_matches_cloned_utm_launch_defaults(tmp_path: Path) -> None:
    config = UTMCameraConfig.load(repo_root=tmp_path)
    profile = config.active_profile()

    assert profile.label.startswith("Camera")
    assert profile.width == 640
    assert profile.height == 480
    assert profile.fps == 60
    assert profile.pixel_format == "mjpeg2rgb"
    assert profile.brightness == 128
    assert profile.gain == -1
    assert profile.ros_image_topic == "/camera/image_raw"
    assert profile.rectified_topic == "/camera/image_rect"
    assert profile.utm_annotated_topic == "/image_utm"


def test_camera_config_saves_operator_override_without_touching_devices_yaml(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory" / "device_bridge" / "utm_camera_config.json"
    config = UTMCameraConfig.load(repo_root=tmp_path, memory_path=memory_path)

    saved = config.save_update(
        {
            "active_profile_id": "camera_utm_primary",
            "profiles": {
                "camera_utm_primary": {
                    "device_path": "/dev/v4l/by-id/test-camera",
                    "width": 800,
                    "height": 600,
                    "fps": 25,
                    "brightness": 100,
                    "gain": 5,
                    "checkerboard_size": "9x6",
                    "checkerboard_square_m": 0.021,
                }
            },
        }
    )

    assert memory_path.is_file()
    loaded = UTMCameraConfig.load(repo_root=tmp_path, memory_path=memory_path)
    profile = loaded.active_profile()
    assert saved["ok"] is True
    assert profile.device_path == "/dev/v4l/by-id/test-camera"
    assert profile.width == 800
    assert profile.height == 600
    assert profile.fps == 25
    assert profile.brightness == 100
    assert profile.gain == 5
    assert profile.checkerboard_size == "9x6"
    assert profile.checkerboard_square_m == 0.021
