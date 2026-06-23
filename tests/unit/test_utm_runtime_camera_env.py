"""Tests for injecting Camera bridge settings into the UTM runtime command."""

from __future__ import annotations

import stat
from pathlib import Path

from device_bridges.utm_runtime_bridge import UTMRuntimeConfig, UTMRuntimeProcessManager, UTMCameraConfig


def _script(path: Path) -> None:
    path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_runtime_command_injects_default_camera_env(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    _script(script_path)
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            ros_setup_paths=[],
            camera_config=UTMCameraConfig.load(repo_root=tmp_path),
        )
    )

    command = " ".join(manager._command_preview())

    assert "UTM_CAMERA_WIDTH=640" in command
    assert "UTM_CAMERA_HEIGHT=480" in command
    assert "UTM_CAMERA_FPS=15.0" in command
    assert "UTM_CAMERA_PIXEL_FORMAT=yuyv2rgb" in command
    assert "UTM_CAMERA_BRIGHTNESS=128" in command
    assert "UTM_CAMERA_GAIN=-1" in command
    assert "UTM_CAMERA_INFO_URL=" in command


def test_runtime_command_injects_saved_camera_override(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    _script(script_path)
    camera_config = UTMCameraConfig.load(repo_root=tmp_path)
    camera_config.save_update(
        {
            "profiles": {
                "camera_utm_primary": {
                    "device_path": "/dev/v4l/by-id/test-camera",
                    "width": 800,
                    "height": 600,
                    "fps": 25,
                    "brightness": 90,
                    "gain": 4,
                    "calibration_file": str(tmp_path / "calibration.yaml"),
                }
            }
        }
    )
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            ros_setup_paths=[],
            camera_config=UTMCameraConfig.load(repo_root=tmp_path),
        )
    )

    command = " ".join(manager._command_preview())

    assert "UTM_CAMERA_DEVICE=/dev/v4l/by-id/test-camera" in command
    assert "UTM_CAMERA_WIDTH=800" in command
    assert "UTM_CAMERA_HEIGHT=600" in command
    assert "UTM_CAMERA_FPS=25.0" in command
    assert "UTM_CAMERA_BRIGHTNESS=90" in command
    assert "UTM_CAMERA_GAIN=4" in command
    assert "UTM_CAMERA_INFO_URL=file://" in command


def test_runtime_command_resolves_camera_symlink_for_usb_cam(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    _script(script_path)
    dev_root = tmp_path / "dev"
    by_id_root = dev_root / "v4l" / "by-id"
    by_id_root.mkdir(parents=True)
    video_node = dev_root / "video0"
    video_node.write_text("", encoding="utf-8")
    by_id = by_id_root / "usb-test-camera-video-index0"
    by_id.symlink_to(Path("../../video0"))
    camera_config = UTMCameraConfig.load(repo_root=tmp_path)
    camera_config.save_update(
        {
            "profiles": {
                "camera_utm_primary": {
                    "device_path": str(by_id),
                }
            }
        }
    )
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            ros_setup_paths=[],
            camera_config=UTMCameraConfig.load(repo_root=tmp_path),
        )
    )

    command = " ".join(manager._command_preview())

    assert f"UTM_CAMERA_DEVICE={video_node}" in command
    assert "../../video0" not in command


def test_runtime_command_formats_fps_as_ros_double(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    _script(script_path)
    camera_config = UTMCameraConfig.load(repo_root=tmp_path)
    camera_config.save_update({"profiles": {"camera_utm_primary": {"fps": 15}}})
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            ros_setup_paths=[],
            camera_config=UTMCameraConfig.load(repo_root=tmp_path),
        )
    )

    command = " ".join(manager._command_preview())

    assert "UTM_CAMERA_FPS=15.0" in command
    assert "UTM_CAMERA_FPS=15;" not in command
