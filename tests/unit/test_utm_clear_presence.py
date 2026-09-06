"""Generated fixtures below are synthetic software tests, not empty-hardware validation."""
from datetime import datetime, timezone
from io import BytesIO
import base64
import numpy as np
from PIL import Image
import pytest
from utils import utm_specimen_presence as presence


def frame(red=False):
    arr = np.full((480, 640, 3), 160, dtype=np.uint8)
    arr[363:373, 235:245] = [20, 220, 40]
    arr[363:373, 347:357] = [20, 220, 40]
    if red: arr[319:349, 258:316] = [225, 30, 35]
    return arr


def inspect(arr, tmp_path, **kwargs):
    output = BytesIO()
    Image.fromarray(arr).save(output, format="PNG")
    now = datetime.now(timezone.utc).timestamp()
    evidence = {"topic": "/camera/image_rect", "camera_profile_id": "camera_utm_primary", "frame_timestamp": now,
        "after_timestamp": now - 1, "material": "high_chroma_red"}
    evidence.update(kwargs)
    return presence.inspect_specimen_presence("data:image/png;base64," + base64.b64encode(output.getvalue()).decode(),
        output_dir=tmp_path, specimen_id="s1", frame_id="synthetic", purpose="utm_clear_verification", capture_evidence=evidence)


@pytest.mark.parametrize("red,expected", [(False, "clear"), (True, "occupied")])
@pytest.mark.parametrize("topic", ["/camera/image_raw", "/camera/image_rect"])
def test_registered_synthetic_clear_and_compressed_positive(tmp_path, red, expected, topic):
    result = inspect(frame(red), tmp_path, topic=topic)
    assert result["status"] == expected
    assert result["clear_confirmed"] is (not red)


@pytest.mark.parametrize("topic", ["/camera/image_raw", "/camera/image_rect"])
def test_fragment_aggregation_survives_opening_loss(tmp_path, topic):
    arr = frame()
    for y in range(280, 301, 4): arr[y:y+1, 230:270] = [225, 30, 35]
    assert inspect(arr, tmp_path, topic=topic)["status"] == "occupied"


@pytest.mark.parametrize("failure", [{"topic": "/image_utm"}, {"camera_profile_id": "other"}, {"frame_timestamp": 0},
    {"frame_timestamp": 1}, {"material": "blue"}, {"material": ""}, {"after_timestamp": 1e20}])
def test_invalid_evidence_is_unknown(tmp_path, failure):
    result = inspect(frame(), tmp_path, **failure)
    assert result["status"] == "unknown"
    assert result["clear_confirmed"] is False


@pytest.mark.parametrize("topic", ["/camera/image_raw", "/camera/image_rect"])
def test_missing_anchor_and_off_roi_red(tmp_path, topic):
    arr = frame()
    arr[10:100, 10:100] = [225, 30, 35]
    assert inspect(arr, tmp_path, topic=topic)["status"] == "clear"
    arr[360:380, 230:250] = 160
    assert inspect(arr, tmp_path, topic=topic)["status"] == "unknown"


@pytest.mark.parametrize("topic", ["/camera/image_raw", "/camera/image_rect"])
def test_capture_boundary_uses_ros_timestamp_profile_unique_artifacts(tmp_path, topic):
    from tests.unit.test_camera_tools_utm_runtime import FakeRuntimeManager
    from mcp_tools.camera_tools import _utm_specimen_presence_capture
    output = BytesIO()
    Image.fromarray(frame()).save(output, format="PNG")
    stamp = datetime.now(timezone.utc).timestamp()
    manager = FakeRuntimeManager(frame={"ok": True, "frame_id": "repeated", "topic": topic,
        "camera_profile_id": "camera_utm_primary", "frame_timestamp": stamp,
        "data_url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()})
    payload = {"purpose": "utm_clear_verification", "runtime_mode": "live", "auto_start_runtime": False,
        "output_dir": str(tmp_path), "run_id": "r", "loop_id": 0, "specimen_id": "s", "session_id": "child",
        "material": "high_chroma_red", "after_timestamp": stamp - 1}
    first = _utm_specimen_presence_capture(payload, utm_runtime_manager=manager)
    second = _utm_specimen_presence_capture(payload, utm_runtime_manager=manager)
    assert first["status"] == "clear"
    assert first["frame_timestamp"] == stamp
    assert first["loop_id"] == 0
    assert first["raw_frame_path"] != second["raw_frame_path"]
    assert manager.start_calls == 0
    assert manager.raw_frame_calls == 2
    assert manager.frame_calls == 0
    manager._frame.pop("frame_timestamp")
    assert _utm_specimen_presence_capture(payload, utm_runtime_manager=manager)["status"] == "unknown"


@pytest.mark.parametrize("topic", ["/camera/image_raw", "/camera/image_rect"])
def test_elongated_compressed_specimen_is_not_rejected_by_shape(tmp_path, topic):
    arr = frame()
    arr[327:347, 225:380] = [225, 30, 35]
    result = inspect(arr, tmp_path, topic=topic)
    assert result["status"] == "occupied"
    assert result["clear_confirmed"] is False
    assert result["residual_width_px"] > 140
    assert result["residual_aspect_ratio"] > 7


@pytest.mark.parametrize("path,bbox,area", [
    ("tests/fixtures/utm_clear/upright_raw.png", [256, 290, 320, 352], 3336),
    ("tests/fixtures/utm_clear/compressed_raw.png", [257, 318, 316, 350], 1540),
])
def test_immutable_real_positive_references(tmp_path, path, bbox, area):
    from pathlib import Path
    assert Path(path).is_file()
    with Image.open(path) as img: arr = np.asarray(img.convert("RGB"))
    result = inspect(arr, tmp_path)
    assert result["status"] == "occupied"
    assert result["bbox_xyxy"] == bbox
    assert result["largest_component_area_px"] == area


def test_raw_ros_contract_exposes_header_stamp(monkeypatch, capsys):
    # Execute the actual ROS snippet with fake ROS modules; no ROS process/device calls.
    import sys
    import json
    from types import SimpleNamespace
    from device_bridges.utm_runtime_bridge import ROS_IMAGE_CAPTURE_SCRIPT
    class FakeNode:
        def __init__(self, *args): pass
        def create_subscription(self, cls, topic, callback, qos):
            callback(SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=123, nanosec=500000000)),
                width=2, height=2, encoding="bgr8", data=bytes([1]*12), step=6))
        def destroy_node(self): pass
    modules = {"rclpy": SimpleNamespace(init=lambda **k: None, shutdown=lambda: None),
        "rclpy.node": SimpleNamespace(Node=FakeNode),
        "rclpy.qos": SimpleNamespace(QoSProfile=lambda **k: k, ReliabilityPolicy=SimpleNamespace(RELIABLE=1),
            HistoryPolicy=SimpleNamespace(KEEP_LAST=1), DurabilityPolicy=SimpleNamespace(VOLATILE=1)),
        "sensor_msgs.msg": SimpleNamespace(Image=object), "cv_bridge": None,
        "cv2": SimpleNamespace(imencode=lambda *a: (True, np.array([1,2], dtype=np.uint8)), IMWRITE_JPEG_QUALITY=1)}
    for key, value in modules.items(): monkeypatch.setitem(sys.modules, key, value)
    monkeypatch.setattr(sys, "argv", ["snapshot", "/camera/image_rect", "0.1"])
    exec(ROS_IMAGE_CAPTURE_SCRIPT, {})
    result = json.loads(capsys.readouterr().out)
    assert result["frame_timestamp"] == 123.5
