"""Static contract checks for the cloned UTM runtime stack script."""

from __future__ import annotations

from pathlib import Path


UTM_REPO = Path("/home/jin/external_repos/UTM")


def test_cloned_utm_stack_script_runs_camera_monitor_and_yolo() -> None:
    script = UTM_REPO / "scripts" / "start_utm_vision_stack.sh"
    text = script.read_text(encoding="utf-8")

    assert "camera_rect.launch.py" in text
    assert "green_dot_monitor.launch.py" in text
    assert "yolov8.launch.py" in text
    assert "input_image_topic:=/camera/image_rect" in text
    assert "output_image_topic:=/image_utm" in text
    assert "input_image_topic:=/image_utm" in text
    assert "image_reliability:=2" in text
    assert "UTM_VISION_ROOT" in text
    assert "YOLO_MODEL_PATH" in text
    assert 'CAMERA_DEVICE="${UTM_CAMERA_DEVICE' in text
    assert 'CAMERA_WIDTH="${UTM_CAMERA_WIDTH' in text
    assert 'CAMERA_HEIGHT="${UTM_CAMERA_HEIGHT' in text
    assert 'CAMERA_FPS="${UTM_CAMERA_FPS:-15.0}"' in text
    assert 'CAMERA_INFO_URL="${UTM_CAMERA_INFO_URL' in text
    assert 'video_device:="$CAMERA_DEVICE"' in text
    assert 'image_width:="$CAMERA_WIDTH"' in text
    assert 'image_height:="$CAMERA_HEIGHT"' in text
    assert 'framerate:="$CAMERA_FPS"' in text
    assert 'camera_info_url:="$CAMERA_INFO_URL"' in text


def test_cloned_utm_launch_files_match_atr_expected_topics() -> None:
    camera_rect = (UTM_REPO / "src/compression_tester_monitor/launch/camera_rect.launch.py").read_text(encoding="utf-8")
    green_dot = (UTM_REPO / "src/compression_tester_monitor/launch/green_dot_monitor.launch.py").read_text(encoding="utf-8")
    green_dot_node = (
        UTM_REPO / "src/compression_tester_monitor/compression_tester_monitor/green_dot_monitor.py"
    ).read_text(encoding="utf-8")

    assert 'namespace="camera"' in camera_rect
    assert 'name="usb_cam"' in camera_rect
    assert 'name="rectify_node"' in camera_rect
    assert '("image", "image_raw")' in camera_rect
    assert '("image_rect", "image_rect")' in camera_rect
    assert 'default_value="/camera/image_rect"' in green_dot
    assert 'default_value="/image_utm"' in green_dot
    assert 'executable="green_dot_monitor"' in green_dot
    assert "QoSReliabilityPolicy.BEST_EFFORT" in green_dot_node
    assert "QoSHistoryPolicy.KEEP_LAST" in green_dot_node
    assert "depth=1" in green_dot_node
    assert "self.output_image_pub = self.create_publisher(Image, output_image_topic, image_qos_profile)" in green_dot_node
    assert "self.create_subscription(Image, \"image\", self.image_cb, image_qos_profile)" in green_dot_node
