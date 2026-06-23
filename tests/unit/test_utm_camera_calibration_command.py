"""Tests for checkerboard calibration command support."""

from __future__ import annotations

import stat
from pathlib import Path

from device_bridges.utm_runtime_bridge import UTMRuntimeConfig, UTMRuntimeProcessManager, UTMCameraConfig


def _script(path: Path) -> None:
    path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_calibration_command_uses_ros_camera_calibration_and_saved_camera_topics(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    _script(script_path)
    camera_config = UTMCameraConfig.load(repo_root=tmp_path)
    camera_config.save_update(
        {
            "profiles": {
                "camera_utm_primary": {
                    "checkerboard_size": "9x6",
                    "checkerboard_square_m": 0.021,
                }
            }
        }
    )
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            ros_setup_paths=["/opt/ros/jazzy/setup.bash"],
            camera_config=UTMCameraConfig.load(repo_root=tmp_path),
        )
    )

    payload = manager.calibration_command()
    command = " ".join(payload["command"])

    assert payload["ok"] is True
    assert "camera_calibration" in command
    assert "cameracalibrator" in command
    assert "--size 9x6" in command
    assert "--square 0.021" in command
    assert "image:=/camera/image_raw" in command
    assert "camera:=/camera" in command
    assert payload["calibration_file"].endswith("utm_camera_default_cam.yaml")
