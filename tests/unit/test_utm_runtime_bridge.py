"""Tests for UTM ROS runtime bridge and RQT-like graph mapping."""

from __future__ import annotations

import os
import stat
import time
import json
from pathlib import Path

from device_bridges.utm_runtime_bridge import (
    ROS_IMAGE_CAPTURE_SCRIPT,
    ROS_IMAGE_MJPEG_STREAM_SCRIPT,
    SharedMjpegTopicStream,
    UTMCameraConfig,
    UTMCameraProfile,
    UTMGraphSnapshotBuilder,
    UTMRuntimeConfig,
    UTMRuntimeProcessManager,
    _extract_mjpeg_frames,
)

UTM_REPO = Path("/home/jin/external_repos/UTM")


class _FakeRunningProcess:
    pid = 12345

    def poll(self) -> None:
        return None


class _FakeExitedProcess:
    pid = 12346
    returncode = -15

    def poll(self) -> int:
        return self.returncode


class _FakeStream:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def _write_fake_stack_script(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "echo fake-utm-stack-started\n"
        "trap 'exit 0' TERM INT\n"
        "while true; do sleep 0.1; done\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_runtime_config_defaults_to_cloned_utm_repo() -> None:
    config = UTMRuntimeConfig.from_devices_config({}, repo_root=Path("/home/jin/autonomous_researcher"))

    assert config.workspace_root == UTM_REPO
    assert config.script_path == UTM_REPO / "scripts" / "start_utm_vision_stack.sh"
    assert str(config.log_dir).endswith("artifacts/utm_runtime")
    assert "/opt/ros/jazzy/setup.bash" in config.ros_setup_paths


def test_runtime_config_accepts_extra_setup_and_environment(tmp_path: Path) -> None:
    config = UTMRuntimeConfig.from_devices_config(
        {
            "devices": {
                "devices": {
                "utm_vision_runtime": {
                    "workspace_root": str(tmp_path),
                    "script_path": str(tmp_path / "run.sh"),
                    "extra_setup_paths": ["/tmp/yolo/install/setup.bash"],
                    "environment": {"YOLO_MODEL_PATH": "/tmp/yolo.pt"},
                }
                }
            }
        },
        repo_root=Path("/home/jin/autonomous_researcher"),
    )

    assert "/tmp/yolo/install/setup.bash" in config.extra_setup_paths
    assert config.environment["YOLO_MODEL_PATH"] == "/tmp/yolo.pt"


def test_process_manager_starts_reports_running_and_stops(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    log_dir = tmp_path / "logs"
    _write_fake_stack_script(script_path)
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=log_dir,
            stop_timeout_sec=1.0,
            ros_setup_paths=[],
        )
    )

    started = manager.start()
    try:
        assert started["ok"] is True
        assert started["status"] == "running"
        assert started["already_running"] is False
        assert started["pid"]
        assert Path(str(started["log_path"])).parent == log_dir
        assert os.path.exists(str(started["log_path"]))

        second = manager.start()
        assert second["already_running"] is True
        assert second["pid"] == started["pid"]
    finally:
        stopped = manager.stop()

    assert stopped["ok"] is True
    deadline = time.monotonic() + 2.0
    while manager.status()["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert manager.status()["status"] == "stopped"


def test_process_manager_applies_camera_fps_stability_controls_before_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    log_dir = tmp_path / "logs"
    _write_fake_stack_script(script_path)
    video_node = tmp_path / "video0"
    video_node.write_text("", encoding="utf-8")
    camera_config = UTMCameraConfig.load(repo_root=tmp_path)
    camera_config.save_update({"profiles": {"camera_utm_primary": {"device_path": str(video_node)}}})
    calls: list[list[str]] = []

    def fake_run_command(command: list[str], *, timeout_sec: float = 2.0) -> tuple[int, str, str]:
        calls.append(command)
        return 0, "exposure_dynamic_framerate: 0\n", ""

    monkeypatch.setattr("device_bridges.utm_runtime_bridge._run_command", fake_run_command)
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=log_dir,
            stop_timeout_sec=1.0,
            ros_setup_paths=[],
            camera_config=UTMCameraConfig.load(repo_root=tmp_path),
        )
    )

    started = manager.start()
    try:
        assert started["ok"] is True
        assert started["startup_camera_controls"]["ok"] is True
        assert calls == [
            [
                "v4l2-ctl",
                f"--device={video_node}",
                "--set-ctrl=exposure_dynamic_framerate=0",
            ],
            [
                "v4l2-ctl",
                f"--device={video_node}",
                "--get-ctrl=exposure_dynamic_framerate,auto_exposure,exposure_time_absolute,brightness,gain",
            ],
        ]
    finally:
        manager.stop()


def test_process_manager_does_not_block_start_when_camera_control_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    _write_fake_stack_script(script_path)
    camera_config = UTMCameraConfig.load(repo_root=tmp_path)
    camera_config.save_update({"profiles": {"camera_utm_primary": {"device_path": "/dev/missing-camera"}}})

    def fake_run_command(command: list[str], *, timeout_sec: float = 2.0) -> tuple[int, str, str]:
        return 1, "", "unknown control 'exposure_dynamic_framerate'"

    monkeypatch.setattr("device_bridges.utm_runtime_bridge._run_command", fake_run_command)
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            stop_timeout_sec=1.0,
            ros_setup_paths=[],
            camera_config=UTMCameraConfig.load(repo_root=tmp_path),
        )
    )

    started = manager.start()
    try:
        assert started["ok"] is True
        assert started["startup_camera_controls"]["ok"] is False
        assert started["startup_camera_controls"]["failure_code"] == "CAMERA_CONTROL_APPLY_FAILED"
    finally:
        manager.stop()


def test_process_manager_reports_missing_script(tmp_path: Path) -> None:
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=tmp_path / "missing.sh",
            log_dir=tmp_path / "logs",
        )
    )

    result = manager.start()

    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["failure_code"] == "UTM_RUNTIME_SCRIPT_NOT_FOUND"
    assert "missing.sh" in result["message"]


def test_status_cleans_shared_mjpeg_streams_after_runtime_exit(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            ros_setup_paths=[],
        )
    )
    stream = _FakeStream()
    manager._process = _FakeExitedProcess()  # type: ignore[assignment]
    manager._mjpeg_streams["/image_utm|15|82"] = stream  # type: ignore[assignment]

    status = manager.status()

    assert status["status"] == "error"
    assert status["returncode"] == -15
    assert stream.stopped is True
    assert manager._mjpeg_streams == {}
    assert manager._process is None


def test_status_reports_external_runtime_after_gui_restart(tmp_path: Path) -> None:
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=tmp_path / "start_utm_vision_stack.sh",
            log_dir=tmp_path / "logs",
            ros_setup_paths=[],
        )
    )
    manager._iter_process_cmdlines = lambda: [  # type: ignore[method-assign]
        {"pid": 501, "cmd": "/opt/ros/jazzy/lib/usb_cam/usb_cam_node_exe --ros-args -r __ns:=/camera"},
        {"pid": 502, "cmd": "python3 -c class MjpegStreamSubscriber atr_utm_frame_mjpeg_stream"},
        {"pid": 503, "cmd": "rg green_dot_monitor"},
    ]

    status = manager.status()

    assert status["ok"] is True
    assert status["status"] == "running"
    assert status["managed"] is False
    assert status["pid"] == 501
    assert status["external_pids"] == [501]


def test_process_manager_sources_workspace_install_when_present(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    install_setup = tmp_path / "install" / "setup.bash"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    install_setup.parent.mkdir(parents=True)
    install_setup.write_text("# fake install setup\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            ros_setup_paths=["/opt/ros/jazzy/setup.bash"],
            extra_setup_paths=["/tmp/yolo/install/setup.bash"],
            environment={"YOLO_MODEL_PATH": "/tmp/yolov8m.pt"},
        )
    )

    command = " ".join(manager._command_preview())

    assert "PATH=\"$HOME/.local/bin:$PATH\"" in command
    assert "install/setup.bash" in command
    assert "/tmp/yolo/install/setup.bash" in command
    assert "YOLO_MODEL_PATH" in command
    assert str(script_path) in command


def test_process_manager_ros_probe_sources_same_runtime_paths(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    install_setup = tmp_path / "install" / "setup.bash"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    install_setup.parent.mkdir(parents=True)
    install_setup.write_text("# fake install setup\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            ros_setup_paths=["/opt/ros/jazzy/setup.bash"],
            extra_setup_paths=["/tmp/yolo/install/setup.bash"],
            environment={"YOLO_MODEL_PATH": "/tmp/yolov8m.pt"},
        )
    )

    command = " ".join(manager._ros_command_preview(["ros2", "node", "list"]))

    assert "PATH=\"$HOME/.local/bin:$PATH\"" in command
    assert "/opt/ros/jazzy/setup.bash" in command
    assert "/tmp/yolo/install/setup.bash" in command
    assert "install/setup.bash" in command
    assert "ros2 node list" in command


def test_expected_graph_follows_cloned_utm_launch_flow() -> None:
    builder = UTMGraphSnapshotBuilder(workspace_root=UTM_REPO)

    graph = builder.expected_graph()
    nodes = {node["id"] for node in graph["nodes"]}
    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}

    assert graph["source"] == "cloned_utm_repository"
    assert graph["workspace_root"] == str(UTM_REPO)
    assert "camera/usb_cam" in nodes
    assert "camera/rectify_node" in nodes
    assert "compression_tester_monitor/green_dot_monitor" in nodes
    assert "yolo_bringup/yolov8" in nodes
    assert "/camera/image_raw" in nodes
    assert "/camera/image_rect" in nodes
    assert "/image_utm" in nodes
    assert "/compression_tester/summary" in nodes
    assert "/yolo/detections" in nodes
    assert ("camera/usb_cam", "/camera/image_raw") in edges
    assert ("/camera/image_raw", "camera/rectify_node") in edges
    assert ("camera/rectify_node", "/camera/image_rect") in edges
    assert ("/camera/image_rect", "compression_tester_monitor/green_dot_monitor") in edges
    assert ("compression_tester_monitor/green_dot_monitor", "/image_utm") in edges
    assert ("/image_utm", "yolo_bringup/yolov8") in edges
    assert any("camera_rect.launch.py" in item for item in graph["source_files"])
    assert any("green_dot_monitor.launch.py" in item for item in graph["source_files"])
    assert any("yolo.sh" in item for item in graph["source_files"])


def test_graph_snapshot_is_hash_stable_without_actual_ros() -> None:
    commands: list[list[str]] = []

    def fake_runner(command: list[str], *, timeout_sec: float = 2.0) -> tuple[int, str, str]:
        commands.append(command)
        return (127, "", "ros2: command not found")

    builder = UTMGraphSnapshotBuilder(workspace_root=UTM_REPO, command_runner=fake_runner)

    first = builder.snapshot()
    second = builder.snapshot(previous_hash=first["graph_hash"])

    assert first["ok"] is True
    assert first["expected_graph"]["nodes"]
    assert first["actual_graph"]["nodes"] == []
    assert first["diagnostics"]["ros2_available"] is False
    assert first["graph_hash"] == second["graph_hash"]
    assert second["changed"] is False
    assert any(cmd[:3] == ["ros2", "node", "list"] for cmd in commands)


def test_actual_graph_parses_ros_node_info_edges() -> None:
    def fake_runner(command: list[str]) -> tuple[int, str, str]:
        if command == ["ros2", "node", "list"]:
            return 0, "/camera/usb_cam\n/camera/rectify_node\n", ""
        if command == ["ros2", "topic", "list"]:
            return 0, "/camera/image_raw\n/camera/image_rect\n", ""
        if command == ["ros2", "node", "info", "/camera/usb_cam"]:
            return (
                0,
                "Publishers:\n"
                "  /camera/image_raw: sensor_msgs/msg/Image\n"
                "Subscribers:\n",
                "",
            )
        if command == ["ros2", "node", "info", "/camera/rectify_node"]:
            return (
                0,
                "Subscribers:\n"
                "  /camera/image_raw: sensor_msgs/msg/Image\n"
                "Publishers:\n"
                "  /camera/image_rect: sensor_msgs/msg/Image\n",
                "",
            )
        return 127, "", "unexpected"

    builder = UTMGraphSnapshotBuilder(workspace_root=UTM_REPO, command_runner=fake_runner)

    snapshot = builder.snapshot()
    edges = {
        (edge["source"], edge["target"], edge["kind"])
        for edge in snapshot["actual_graph"]["edges"]
    }

    assert ("/camera/usb_cam", "/camera/image_raw", "publishes") in edges
    assert ("/camera/image_raw", "/camera/rectify_node", "subscribes") in edges
    assert ("/camera/rectify_node", "/camera/image_rect", "publishes") in edges


def test_frame_capture_uses_ros_image_topic_and_returns_data_url(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            frame_topic="/image_utm",
            ros_setup_paths=[],
        )
    )
    commands: list[list[str]] = []
    manager._process = _FakeRunningProcess()  # type: ignore[assignment]

    def fake_ros_command(command: list[str], *, timeout_sec: float = 3.0) -> tuple[int, str, str]:
        commands.append(command)
        return (
            0,
            json.dumps(
                {
                    "ok": True,
                    "topic": "/image_utm",
                    "width": 640,
                    "height": 480,
                    "encoding": "rgb8",
                    "format": "jpeg",
                    "data_url": "data:image/jpeg;base64,ZmFrZS1qcGVn",
                    "frame_age_ms": 12.5,
                }
            ),
            "",
        )

    manager._run_ros_frame_command = fake_ros_command  # type: ignore[method-assign]

    frame = manager.frame()

    assert frame["ok"] is True
    assert frame["mode"] == "ros_image_topic"
    assert frame["frame_available"] is True
    assert frame["topic"] == "/image_utm"
    assert frame["data_url"] == "data:image/jpeg;base64,ZmFrZS1qcGVn"
    assert commands and commands[0][:2] == ["python3", "-c"]


def test_raw_frame_capture_prioritizes_unannotated_camera_topic(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            frame_topic="/image_utm",
            ros_setup_paths=[],
        )
    )
    commands: list[list[str]] = []
    manager._process = _FakeRunningProcess()  # type: ignore[assignment]

    def fake_ros_command(command: list[str], *, timeout_sec: float = 3.0) -> tuple[int, str, str]:
        commands.append(command)
        topic = command[-2]
        return (
            0,
            json.dumps(
                {
                    "ok": True,
                    "topic": topic,
                    "width": 640,
                    "height": 480,
                    "encoding": "rgb8",
                    "format": "jpeg",
                    "data_url": "data:image/jpeg;base64,ZmFrZS1qcGVn",
                }
            ),
            "",
        )

    manager._run_ros_frame_command = fake_ros_command  # type: ignore[method-assign]

    frame = manager.raw_frame()

    assert frame["ok"] is True
    assert frame["mode"] == "ros_raw_image_topic"
    assert frame["topic"] == "/camera/image_raw"
    assert commands[0][-2] == "/camera/image_raw"


def test_raw_frame_capture_keeps_live_observation_stream_running(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            frame_topic="/image_utm",
            ros_setup_paths=[],
        )
    )
    stream = _FakeStream()
    manager._process = _FakeRunningProcess()  # type: ignore[assignment]
    manager._mjpeg_streams["/image_utm|15|82"] = stream  # type: ignore[assignment]
    manager._run_ros_frame_command = lambda command, timeout_sec=3.0: (  # type: ignore[method-assign]
        0,
        json.dumps(
            {
                "ok": True,
                "topic": command[-2],
                "width": 640,
                "height": 480,
                "data_url": "data:image/jpeg;base64,ZmFrZS1qcGVn",
            }
        ),
        "",
    )

    frame = manager.raw_frame()

    assert frame["ok"] is True
    assert manager._mjpeg_streams["/image_utm|15|82"] is stream
    assert stream.stopped is False


def test_frame_capture_skips_ros_when_runtime_is_stopped(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            frame_topic="/image_utm",
            ros_setup_paths=[],
        )
    )
    commands: list[list[str]] = []

    def fake_ros_command(command: list[str], *, timeout_sec: float = 3.0) -> tuple[int, str, str]:
        commands.append(command)
        return 2, "", "should not be called"

    manager._run_ros_frame_command = fake_ros_command  # type: ignore[method-assign]

    frame = manager.frame()

    assert frame["ok"] is False
    assert frame["failure_code"] == "UTM_RUNTIME_NOT_RUNNING"
    assert frame["attempts"] == []
    assert commands == []


def test_frame_capture_reports_topic_unavailable_with_attempts(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            frame_topic="/image_utm",
            ros_setup_paths=[],
        )
    )

    def fake_ros_command(command: list[str], *, timeout_sec: float = 3.0) -> tuple[int, str, str]:
        topic = command[-2]
        return 2, json.dumps({"ok": False, "topic": topic, "failure_code": "ROS_IMAGE_TIMEOUT"}), ""

    manager._process = _FakeRunningProcess()  # type: ignore[assignment]
    manager._run_ros_frame_command = fake_ros_command  # type: ignore[method-assign]

    frame = manager.frame()

    assert frame["ok"] is False
    assert frame["mode"] == "ros_image_topic"
    assert frame["frame_available"] is False
    assert frame["failure_code"] == "ROS_IMAGE_FRAME_UNAVAILABLE"
    assert len(frame["attempts"]) >= 3


def test_stale_cleanup_matcher_ignores_probe_commands(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            ros_setup_paths=[],
        )
    )

    assert manager._looks_like_utm_runtime_process("python3 -c import rclpy; node = MjpegStreamSubscriber() atr_utm_frame_mjpeg_stream /image_utm 15.000 82")
    assert manager._looks_like_utm_runtime_process("ros2 launch compression_tester_monitor camera_rect.launch.py video_device:=/dev/video0")
    assert manager._looks_like_utm_runtime_process("/opt/ros/jazzy/lib/usb_cam/usb_cam_node_exe --ros-args -r __ns:=/camera")

    assert not manager._looks_like_utm_runtime_process(f"bash -lc source {tmp_path}/install/setup.bash; source /home/jin/external_repos/yolo_ros/install/setup.bash; ros2 node list")
    assert not manager._looks_like_utm_runtime_process(f"bash -lc source {tmp_path}/install/setup.bash; source /home/jin/external_repos/yolo_ros/install/setup.bash; ros2 topic list")
    assert not manager._looks_like_utm_runtime_process("bash -lc python3 -c 'class OneShotImageSubscriber: pass' /image_utm 1.25")
    assert not manager._looks_like_utm_runtime_process("bash -lc ps aux | awk '/atr_utm_frame_mjpeg_stream|MjpegStreamSubscriber/'")


def test_frame_stream_normalizes_raw_camera_topics_to_utm_output(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            frame_topic="/image_utm",
            ros_setup_paths=[],
        )
    )
    profile = UTMCameraProfile(
        ros_image_topic="/camera/image_raw",
        ros_rect_topic="/camera/image_rect",
        ros_output_topic="/image_utm",
    )

    assert manager._stream_topic_for_request("/camera/image_rect", profile) == "/image_utm"
    assert manager._stream_topic_for_request("/camera/image_raw", profile) == "/image_utm"
    assert manager._stream_topic_for_request("/image_utm", profile) == "/image_utm"
    assert manager._stream_topic_for_request("/custom/debug", profile) == "/custom/debug"


def test_ros_image_subscribers_use_reliable_qos_depth_one() -> None:
    for script in (ROS_IMAGE_CAPTURE_SCRIPT, ROS_IMAGE_MJPEG_STREAM_SCRIPT):
        assert "ReliabilityPolicy.RELIABLE" in script
        assert "HistoryPolicy.KEEP_LAST" in script
        assert "DurabilityPolicy.VOLATILE" in script
        assert "depth=1" in script
        assert "self.create_subscription(Image, topic, self._callback, sensor_image_qos())" in script


def test_mjpeg_stream_does_not_keep_ineffective_cuda_color_path() -> None:
    assert "cv2.cuda" not in ROS_IMAGE_MJPEG_STREAM_SCRIPT
    assert "ATR_UTM_COLOR_BACKEND" not in ROS_IMAGE_MJPEG_STREAM_SCRIPT
    assert "COLOR_YUV2BGR_YUY2" in ROS_IMAGE_MJPEG_STREAM_SCRIPT
    assert "return cv2.cvtColor(array, code)" in ROS_IMAGE_MJPEG_STREAM_SCRIPT


def test_mjpeg_stream_does_not_drop_already_capped_source_frames() -> None:
    assert "should_emit" not in ROS_IMAGE_MJPEG_STREAM_SCRIPT
    assert "emit_tokens" not in ROS_IMAGE_MJPEG_STREAM_SCRIPT
    assert "emit_interval_tolerance" not in ROS_IMAGE_MJPEG_STREAM_SCRIPT
    assert "now - self.last_emit" not in ROS_IMAGE_MJPEG_STREAM_SCRIPT


def test_frame_stream_skips_worker_when_runtime_is_stopped(tmp_path: Path) -> None:
    script_path = tmp_path / "start_utm_vision_stack.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    manager = UTMRuntimeProcessManager(
        UTMRuntimeConfig(
            workspace_root=tmp_path,
            script_path=script_path,
            log_dir=tmp_path / "logs",
            frame_topic="/image_utm",
            ros_setup_paths=[],
        )
    )

    assert list(manager.frame_stream(topic="/image_utm", fps=15)) == []
    assert manager._mjpeg_streams == {}


def test_mjpeg_parser_extracts_complete_frames_and_keeps_tail() -> None:
    frame1 = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\nabcd\r\n"
    frame2_partial = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 6\r\n\r\nef"
    frames, tail = _extract_mjpeg_frames(frame1 + frame2_partial)

    assert frames == [frame1]
    assert tail == frame2_partial

    frames2, tail2 = _extract_mjpeg_frames(tail + b"ghij\r\n")

    assert frames2 == [b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 6\r\n\r\nefghij\r\n"]
    assert tail2 == b""


def test_shared_mjpeg_stream_reports_rolling_delivery_stats(monkeypatch) -> None:
    stream = SharedMjpegTopicStream(
        key="preview",
        command=["true"],
        cwd=".",
        topic="/image_utm",
        target_fps=30.0,
        jpeg_quality=82,
    )
    stream._record_frames(1, observed_at=10.0)
    stream._record_frames(1, observed_at=10.04)
    stream._record_frames(1, observed_at=10.08)
    stream._record_frames(1, observed_at=10.12)
    monkeypatch.setattr("device_bridges.utm_runtime_bridge.time.monotonic", lambda: 10.12)

    stats = stream.stats()

    assert stats["topic"] == "/image_utm"
    assert stats["requested_fps"] == 30.0
    assert stats["measured_fps"] == 25.0
    assert stats["frames"] == 4
    assert stats["estimated_dropped_frames"] == 0
