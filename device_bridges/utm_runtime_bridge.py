"""
UTM ROS runtime bridge and RQT-like graph snapshot builder.

The expected graph is intentionally derived from the cloned UTM repository flow:
camera_rect -> green_dot_monitor -> yolo. Actual ROS graph evidence is overlaid
when ROS 2 is available, but the expected topology remains the clone's launch
contract.
"""

from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Iterator

CommandRunner = Callable[[list[str]], tuple[int, str, str]]

DEFAULT_UTM_REPO = Path("/home/jin/external_repos/UTM")
DEFAULT_CAMERA_CONFIG_RELATIVE = Path("memory/device_bridge/utm_camera_config.json")
DEFAULT_CAMERA_CALIBRATION_RELATIVE = Path("memory/device_bridge/calibration/utm_camera_default_cam.yaml")
DEFAULT_UTM_CAMERA_DEVICE = ""
DEFAULT_CAMERA_CALIBRATION_YAML = """image_width: 640
image_height: 480
camera_name: default_cam
camera_matrix:
  rows: 3
  cols: 3
  data: [600.0, 0.0, 320.0, 0.0, 600.0, 240.0, 0.0, 0.0, 1.0]
distortion_model: plumb_bob
distortion_coefficients:
  rows: 1
  cols: 5
  data: [0.0, 0.0, 0.0, 0.0, 0.0]
rectification_matrix:
  rows: 3
  cols: 3
  data: [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
projection_matrix:
  rows: 3
  cols: 4
  data: [600.0, 0.0, 320.0, 0.0, 0.0, 600.0, 240.0, 0.0, 0.0, 0.0, 1.0, 0.0]
"""
EXPECTED_SOURCE_FILES = [
    "scripts/start_utm_vision_stack.sh",
    "src/compression_tester_monitor/launch/camera_rect.launch.py",
    "src/compression_tester_monitor/launch/green_dot_monitor.launch.py",
    "scripts/yolo.sh",
]

ROS_IMAGE_CAPTURE_SCRIPT = r"""
import base64
import json
import sys
import time

topic = sys.argv[1]
timeout_sec = float(sys.argv[2])

try:
    import cv2
    import numpy as np
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image
except Exception as exc:
    print(json.dumps({
        "ok": False,
        "topic": topic,
        "failure_code": "ROS_IMAGE_IMPORT_FAILED",
        "message": f"{type(exc).__name__}: {exc}",
    }))
    raise SystemExit(3)

try:
    from cv_bridge import CvBridge
except Exception:
    CvBridge = None


def sensor_image_qos():
    return QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        durability=DurabilityPolicy.VOLATILE,
        depth=1,
    )


def image_to_array(msg):
    if CvBridge is not None:
        bridge = CvBridge()
        return bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
    channels = {
        "bgr8": 3,
        "rgb8": 3,
        "mono8": 1,
        "bgra8": 4,
        "rgba8": 4,
    }.get(str(msg.encoding).lower())
    if channels is None:
        raise ValueError(f"unsupported image encoding without cv_bridge: {msg.encoding}")
    array = np.frombuffer(msg.data, dtype=np.uint8)
    if channels == 1:
        array = array.reshape((msg.height, msg.width))
        return cv2.cvtColor(array, cv2.COLOR_GRAY2BGR)
    array = array.reshape((msg.height, msg.width, channels))
    if str(msg.encoding).lower() == "rgb8":
        return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
    if str(msg.encoding).lower() == "rgba8":
        return cv2.cvtColor(array, cv2.COLOR_RGBA2BGR)
    if str(msg.encoding).lower() == "bgra8":
        return cv2.cvtColor(array, cv2.COLOR_BGRA2BGR)
    return array


class OneShotImageSubscriber(Node):
    def __init__(self):
        super().__init__("atr_utm_frame_snapshot")
        self.msg = None
        self.subscription = self.create_subscription(Image, topic, self._callback, sensor_image_qos())

    def _callback(self, msg):
        self.msg = msg


rclpy.init(args=None)
node = OneShotImageSubscriber()
deadline = time.monotonic() + max(timeout_sec, 0.1)
try:
    while node.msg is None and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    if node.msg is None:
        print(json.dumps({
            "ok": False,
            "topic": topic,
            "failure_code": "ROS_IMAGE_TIMEOUT",
            "message": f"No image received on {topic} within {timeout_sec:.2f}s",
        }))
        raise SystemExit(2)
    msg = node.msg
    image = image_to_array(msg)
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        print(json.dumps({
            "ok": False,
            "topic": topic,
            "failure_code": "ROS_IMAGE_ENCODE_FAILED",
        }))
        raise SystemExit(4)
    stamp_sec = float(getattr(msg.header.stamp, "sec", 0) or 0)
    stamp_nsec = float(getattr(msg.header.stamp, "nanosec", 0) or 0)
    stamp = stamp_sec + stamp_nsec / 1_000_000_000.0
    now = time.time()
    frame_age_ms = max((now - stamp) * 1000.0, 0.0) if stamp > 0 else None
    print(json.dumps({
        "ok": True,
        "topic": topic,
        "width": int(msg.width),
        "height": int(msg.height),
        "encoding": str(msg.encoding),
        "format": "jpeg",
        "frame_age_ms": frame_age_ms,
        "data_url": "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii"),
    }))
finally:
    node.destroy_node()
    rclpy.shutdown()
	"""

ROS_IMAGE_MJPEG_STREAM_SCRIPT = r"""
import base64
import sys
import time

topic = sys.argv[1]
fps = max(float(sys.argv[2]), 1.0)
quality = max(min(int(sys.argv[3]), 95), 40)

try:
    import cv2
    import numpy as np
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image
except Exception as exc:
    sys.stderr.write(f"ROS_IMAGE_STREAM_IMPORT_FAILED: {type(exc).__name__}: {exc}\n")
    raise SystemExit(3)

try:
    from cv_bridge import CvBridge
except Exception:
    CvBridge = None


def sensor_image_qos():
    return QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        durability=DurabilityPolicy.VOLATILE,
        depth=1,
    )


def cvt_color(array, code):
    return cv2.cvtColor(array, code)


def image_buffer_array(msg, channels):
    row_bytes = int(getattr(msg, "step", 0) or int(msg.width) * channels)
    needed = int(msg.height) * row_bytes
    data = np.frombuffer(msg.data, dtype=np.uint8)
    if data.size < needed:
        raise ValueError(
            f"image buffer too small for {msg.width}x{msg.height} {msg.encoding}: "
            f"{data.size} < {needed}"
        )
    rows = data[:needed].reshape((int(msg.height), row_bytes))
    rows = rows[:, : int(msg.width) * channels]
    if channels == 1:
        return rows.reshape((int(msg.height), int(msg.width)))
    return rows.reshape((int(msg.height), int(msg.width), channels))


def image_to_array(msg):
    encoding = str(msg.encoding).lower()
    if encoding == "bgr8":
        return image_buffer_array(msg, 3)
    if encoding == "rgb8":
        return cvt_color(image_buffer_array(msg, 3), cv2.COLOR_RGB2BGR)
    if encoding in {"mono8", "8uc1"}:
        return cvt_color(image_buffer_array(msg, 1), cv2.COLOR_GRAY2BGR)
    if encoding == "bgra8":
        return cvt_color(image_buffer_array(msg, 4), cv2.COLOR_BGRA2BGR)
    if encoding == "rgba8":
        return cvt_color(image_buffer_array(msg, 4), cv2.COLOR_RGBA2BGR)
    if encoding in {"yuyv", "yuyv2", "yuv422", "yuv422_yuy2", "yuyv422"}:
        return cvt_color(image_buffer_array(msg, 2), cv2.COLOR_YUV2BGR_YUY2)
    if CvBridge is not None:
        bridge = CvBridge()
        return bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
    channels = {
        "bgr8": 3,
        "rgb8": 3,
        "mono8": 1,
        "bgra8": 4,
        "rgba8": 4,
    }.get(str(msg.encoding).lower())
    if channels is None:
        raise ValueError(f"unsupported image encoding without cv_bridge: {msg.encoding}")
    array = np.frombuffer(msg.data, dtype=np.uint8)
    if channels == 1:
        array = array.reshape((msg.height, msg.width))
        return cvt_color(array, cv2.COLOR_GRAY2BGR)
    array = array.reshape((msg.height, msg.width, channels))
    if str(msg.encoding).lower() == "rgb8":
        return cvt_color(array, cv2.COLOR_RGB2BGR)
    if str(msg.encoding).lower() == "rgba8":
        return cvt_color(array, cv2.COLOR_RGBA2BGR)
    if str(msg.encoding).lower() == "bgra8":
        return cvt_color(array, cv2.COLOR_BGRA2BGR)
    return array


class MjpegStreamSubscriber(Node):
    def __init__(self):
        super().__init__("atr_utm_frame_mjpeg_stream")
        self.subscription = self.create_subscription(Image, topic, self._callback, sensor_image_qos())

    def _callback(self, msg):
        try:
            image = image_to_array(msg)
            ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            if not ok:
                return
            data = encoded.tobytes()
            header = (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
            )
            sys.stdout.buffer.write(header)
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.write(b"\r\n")
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            raise SystemExit(0)
        except Exception as exc:
            sys.stderr.write(f"ROS_IMAGE_STREAM_FRAME_FAILED: {type(exc).__name__}: {exc}\n")


rclpy.init(args=None)
node = MjpegStreamSubscriber()
try:
    rclpy.spin(node)
finally:
    node.destroy_node()
    rclpy.shutdown()
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_command(command: list[str], *, timeout_sec: float = 2.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, "", str(exc)


def _extract_mjpeg_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Extract complete multipart MJPEG frames and keep the incomplete tail."""
    boundary = b"--frame\r\n"
    frames: list[bytes] = []
    while buffer:
        start = buffer.find(boundary)
        if start < 0:
            return frames, buffer[-len(boundary):]
        if start > 0:
            buffer = buffer[start:]
        header_end = buffer.find(b"\r\n\r\n")
        if header_end < 0:
            return frames, buffer
        header = buffer[:header_end].decode("latin1", "replace")
        content_length = None
        for line in header.splitlines():
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    content_length = None
                break
        if content_length is None or content_length < 0:
            buffer = buffer[len(boundary):]
            continue
        frame_end = header_end + 4 + content_length
        total_end = frame_end + 2
        if len(buffer) < frame_end:
            return frames, buffer
        if len(buffer) >= total_end and buffer[frame_end:total_end] == b"\r\n":
            frame = buffer[:total_end]
            buffer = buffer[total_end:]
        else:
            frame = buffer[:frame_end] + b"\r\n"
            buffer = buffer[frame_end:]
        frames.append(frame)
    return frames, buffer


class SharedMjpegTopicStream:
    """One ROS image subscriber process shared by all HTTP MJPEG clients."""

    def __init__(
        self,
        *,
        key: str,
        command: list[str],
        cwd: str,
        topic: str = "/image_utm",
        target_fps: float = 30.0,
        jpeg_quality: int = 82,
        idle_timeout_sec: float = 8.0,
    ) -> None:
        self.key = key
        self.command = command
        self.cwd = cwd
        self.topic = topic
        self.target_fps = max(float(target_fps), 1.0)
        self.jpeg_quality = int(jpeg_quality)
        self.idle_timeout_sec = max(float(idle_timeout_sec), 1.0)
        self._condition = threading.Condition()
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._latest_frame: bytes | None = None
        self._seq = 0
        self._clients = 0
        self._stop_requested = False
        self._last_client_left = time.monotonic()
        self._last_error = ""
        self._frame_times: deque[float] = deque(maxlen=max(120, int(self.target_fps * 5)))
        self._session_frames = 0
        self._first_frame_monotonic = 0.0

    def stats(self) -> dict[str, Any]:
        with self._condition:
            now = time.monotonic()
            process_running = self._process is not None and self._process.poll() is None
            measured_fps = 0.0
            if len(self._frame_times) > 1:
                elapsed = self._frame_times[-1] - self._frame_times[0]
                if elapsed > 0.0:
                    measured_fps = (len(self._frame_times) - 1) / elapsed
            active_elapsed = max(now - self._first_frame_monotonic, 0.0) if self._first_frame_monotonic else 0.0
            expected_frames = round(self.target_fps * active_elapsed) if active_elapsed else 0
            return {
                "ok": True,
                "status": "running" if process_running else "idle",
                "topic": self.topic,
                "requested_fps": round(self.target_fps, 2),
                "measured_fps": round(measured_fps, 2),
                "frames": self._session_frames,
                "estimated_dropped_frames": max(expected_frames - self._session_frames, 0),
                "clients": self._clients,
                "quality": self.jpeg_quality,
                "last_error": self._last_error,
            }

    def _record_frames(self, count: int, *, observed_at: float | None = None) -> None:
        if count <= 0:
            return
        timestamp = time.monotonic() if observed_at is None else float(observed_at)
        with self._condition:
            if not self._first_frame_monotonic:
                self._first_frame_monotonic = timestamp
            self._session_frames += count
            self._frame_times.extend(timestamp for _ in range(count))

    def frames(self) -> Iterator[bytes]:
        self._add_client()
        last_seq = 0
        try:
            while True:
                frame = self._wait_for_next_frame(last_seq)
                if frame is None:
                    break
                last_seq, payload = frame
                yield payload
        finally:
            self._release_client()

    def stop(self) -> None:
        process: subprocess.Popen[bytes] | None
        with self._condition:
            self._stop_requested = True
            process = self._process
            self._condition.notify_all()
        if process is not None and process.poll() is None:
            self._terminate_process_group(process, signal.SIGTERM)
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._terminate_process_group(process, signal.SIGKILL)
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass

    def _add_client(self) -> None:
        with self._condition:
            self._clients += 1
            self._stop_requested = False
            self._ensure_started_locked()

    def _release_client(self) -> None:
        with self._condition:
            self._clients = max(self._clients - 1, 0)
            if self._clients == 0:
                self._last_client_left = time.monotonic()
            self._condition.notify_all()

    def _wait_for_next_frame(self, last_seq: int) -> tuple[int, bytes] | None:
        while True:
            with self._condition:
                if self._seq != last_seq and self._latest_frame is not None:
                    return self._seq, self._latest_frame
                if self._stop_requested:
                    return None
                process_alive = self._process is not None and self._process.poll() is None
                if not process_alive:
                    self._ensure_started_locked()
                self._condition.wait(timeout=2.0)

    def _ensure_started_locked(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._stop_requested = False
        self._latest_frame = None
        self._last_error = ""
        self._frame_times.clear()
        self._session_frames = 0
        self._first_frame_monotonic = 0.0
        self._process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            bufsize=0,
        )
        self._thread = threading.Thread(target=self._reader_loop, name=f"utm-mjpeg-{self.key}", daemon=True)
        self._thread.start()

    def _reader_loop(self) -> None:
        buffer = b""
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while not self._stop_requested:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                buffer += chunk
                frames, buffer = _extract_mjpeg_frames(buffer)
                if frames:
                    self._record_frames(len(frames))
                    with self._condition:
                        for frame in frames:
                            self._latest_frame = frame
                            self._seq += 1
                        self._condition.notify_all()
                if self._should_stop_for_idle():
                    break
        except Exception as exc:
            with self._condition:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._condition.notify_all()
        finally:
            if process.poll() is None:
                self._terminate_process_group(process, signal.SIGTERM)
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._terminate_process_group(process, signal.SIGKILL)
                    try:
                        process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
            with self._condition:
                if self._process is process:
                    self._process = None
                self._condition.notify_all()

    def _should_stop_for_idle(self) -> bool:
        with self._condition:
            return self._clients <= 0 and (time.monotonic() - self._last_client_left) >= self.idle_timeout_sec

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except (ProcessLookupError, PermissionError):
                return


def _stable_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def _coerce_int(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    if minimum is not None:
        coerced = max(coerced, minimum)
    if maximum is not None:
        coerced = min(coerced, maximum)
    return coerced


def _coerce_float(value: Any, default: float, *, minimum: float | None = None) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        coerced = default
    if minimum is not None:
        coerced = max(coerced, minimum)
    return coerced


def _camera_label_from_device_name(name: str) -> str:
    stem = name
    for prefix in ("usb-", "pci-"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    stem = stem.rsplit("-video-index", 1)[0]
    return stem.replace("_", " ").strip() or name


def discover_v4l2_camera_devices(
    *,
    by_id_root: str | Path = "/dev/v4l/by-id",
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Discover V4L2 cameras without opening streams.

    The bridge intentionally treats the device as "Camera" at the user-facing
    layer. Product names appear only as OS-discovered candidate labels.
    """
    runner = command_runner or (lambda command: _run_command(command, timeout_sec=2.0))
    list_code, list_stdout, list_stderr = runner(["v4l2-ctl", "--list-devices"])
    if list_code == 127:
        return {
            "ok": False,
            "tool": "utm.camera.discover",
            "failure_code": "V4L2_CTL_NOT_AVAILABLE",
            "message": "v4l2-ctl is required to discover Camera devices.",
            "stderr": list_stderr,
            "devices": [],
        }

    root = Path(by_id_root)
    devices: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    if root.is_dir():
        for item in sorted(root.iterdir(), key=lambda path: path.name):
            if "-video-index" not in item.name:
                continue
            try:
                resolved = item.resolve(strict=False)
            except OSError:
                resolved = item
            device_path = str(resolved)
            if device_path in seen_paths:
                continue
            seen_paths.add(device_path)
            format_code, formats, format_stderr = runner(["v4l2-ctl", "--list-formats-ext", "-d", device_path])
            ctrl_code, controls, ctrl_stderr = runner(["v4l2-ctl", "--list-ctrls", "-d", device_path])
            label = _camera_label_from_device_name(item.name)
            devices.append(
                {
                    "id": item.name,
                    "label": label,
                    "device_path": device_path,
                    "by_id_path": str(item),
                    "recommended": False,
                    "format_probe_ok": format_code == 0,
                    "control_probe_ok": ctrl_code == 0,
                    "formats": formats,
                    "controls": controls,
                    "probe_errors": {
                        "formats": format_stderr,
                        "controls": ctrl_stderr,
                    },
                }
            )

    return {
        "ok": True,
        "tool": "utm.camera.discover",
        "devices": devices,
        "device_count": len(devices),
        "v4l2_list": list_stdout,
        "v4l2_stderr": list_stderr,
        "generated_at": _now_iso(),
    }


@dataclass
class UTMCameraProfile:
    """Camera profile passed into the cloned UTM ROS launch contract."""

    profile_id: str = "camera_utm_primary"
    label: str = "Camera UTM Primary"
    device_path: str = DEFAULT_UTM_CAMERA_DEVICE
    width: int = 640
    height: int = 480
    fps: int = 60
    pixel_format: str = "mjpeg2rgb"
    brightness: int = 128
    gain: int = -1
    ros_camera_name: str = "camera"
    ros_image_topic: str = "/camera/image_raw"
    ros_rect_topic: str = "/camera/image_rect"
    ros_output_topic: str = "/image_utm"
    checkerboard_size: str = "9x6"
    checkerboard_square_m: float = 0.021
    calibration_file: str = ""
    notes: str = "Default profile follows the cloned UTM camera_rect.launch.py camera settings."

    @property
    def rectified_topic(self) -> str:
        return self.ros_rect_topic

    @property
    def utm_annotated_topic(self) -> str:
        return self.ros_output_topic

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None, *, base: "UTMCameraProfile | None" = None) -> "UTMCameraProfile":
        source = base or cls()
        data = raw if isinstance(raw, dict) else {}
        return cls(
            profile_id=str(data.get("profile_id") or source.profile_id),
            label=str(data.get("label") or source.label),
            device_path=str(data.get("device_path") or source.device_path),
            width=_coerce_int(data.get("width"), source.width, minimum=160, maximum=7680),
            height=_coerce_int(data.get("height"), source.height, minimum=120, maximum=4320),
            fps=_coerce_int(data.get("fps"), source.fps, minimum=1, maximum=240),
            pixel_format=str(data.get("pixel_format") or source.pixel_format),
            brightness=_coerce_int(data.get("brightness"), source.brightness, minimum=-1, maximum=255),
            gain=_coerce_int(data.get("gain"), source.gain, minimum=-1, maximum=255),
            ros_camera_name=str(data.get("ros_camera_name") or source.ros_camera_name),
            ros_image_topic=str(data.get("ros_image_topic") or source.ros_image_topic),
            ros_rect_topic=str(data.get("ros_rect_topic") or source.ros_rect_topic),
            ros_output_topic=str(data.get("ros_output_topic") or source.ros_output_topic),
            checkerboard_size=str(data.get("checkerboard_size") or source.checkerboard_size),
            checkerboard_square_m=_coerce_float(data.get("checkerboard_square_m"), source.checkerboard_square_m, minimum=0.0001),
            calibration_file=str(data.get("calibration_file") or source.calibration_file),
            notes=str(data.get("notes") or source.notes),
        )

    def calibration_path(self, *, repo_root: Path) -> Path:
        if self.calibration_file:
            path = Path(self.calibration_file).expanduser()
            return path if path.is_absolute() else repo_root / path
        return repo_root / DEFAULT_CAMERA_CALIBRATION_RELATIVE

    def ensure_calibration_file(self, *, repo_root: Path) -> Path:
        path = self.calibration_path(repo_root=repo_root)
        if not self.calibration_file and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_CAMERA_CALIBRATION_YAML, encoding="utf-8")
        return path

    def camera_info_url(self, *, repo_root: Path) -> str:
        return f"file://{self.ensure_calibration_file(repo_root=repo_root)}"

    def runtime_device_path(self) -> str:
        raw = str(self.device_path or "").strip()
        if not raw:
            return ""
        path = Path(raw).expanduser()
        try:
            if path.exists():
                return str(path.resolve(strict=True))
        except OSError:
            return raw
        return raw

    def runtime_fps_value(self) -> str:
        # usb_cam declares framerate as double; passing "15" makes ROS reject it
        # as an integer parameter before the camera node can start.
        return f"{float(self.fps):.1f}"

    def to_env(self, *, repo_root: Path) -> dict[str, str]:
        env = {
            "UTM_CAMERA_WIDTH": str(self.width),
            "UTM_CAMERA_HEIGHT": str(self.height),
            "UTM_CAMERA_FPS": self.runtime_fps_value(),
            "UTM_CAMERA_PIXEL_FORMAT": self.pixel_format,
            "UTM_CAMERA_BRIGHTNESS": str(self.brightness),
            "UTM_CAMERA_GAIN": str(self.gain),
            "UTM_CAMERA_NAME": self.ros_camera_name,
            "UTM_CAMERA_IMAGE_TOPIC": self.ros_image_topic,
            "UTM_CAMERA_RECT_TOPIC": self.ros_rect_topic,
            "UTM_CAMERA_OUTPUT_TOPIC": self.ros_output_topic,
            "UTM_CAMERA_INFO_URL": self.camera_info_url(repo_root=repo_root),
        }
        runtime_device = self.runtime_device_path()
        if runtime_device:
            env["UTM_CAMERA_DEVICE"] = runtime_device
        return env

    def to_dict(self, *, repo_root: Path | None = None) -> dict[str, Any]:
        payload = {
            "profile_id": self.profile_id,
            "label": self.label,
            "device_path": self.device_path,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "pixel_format": self.pixel_format,
            "brightness": self.brightness,
            "gain": self.gain,
            "ros_camera_name": self.ros_camera_name,
            "ros_image_topic": self.ros_image_topic,
            "ros_rect_topic": self.ros_rect_topic,
            "ros_output_topic": self.ros_output_topic,
            "checkerboard_size": self.checkerboard_size,
            "checkerboard_square_m": self.checkerboard_square_m,
            "calibration_file": self.calibration_file,
            "notes": self.notes,
        }
        if repo_root is not None:
            payload["camera_info_url"] = self.camera_info_url(repo_root=repo_root)
        return payload


@dataclass
class UTMCameraConfig:
    """Persistent Camera bridge configuration for the UTM Vision runtime."""

    repo_root: Path
    memory_path: Path
    active_profile_id: str
    profiles: dict[str, UTMCameraProfile]
    updated_at: str = ""

    @classmethod
    def load(
        cls,
        *,
        repo_root: str | Path,
        memory_path: str | Path | None = None,
    ) -> "UTMCameraConfig":
        root = Path(repo_root).expanduser()
        path = Path(memory_path).expanduser() if memory_path is not None else root / DEFAULT_CAMERA_CONFIG_RELATIVE
        default_profile = UTMCameraProfile()
        profiles = {default_profile.profile_id: default_profile}
        active_profile_id = default_profile.profile_id
        updated_at = ""
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}
            if isinstance(raw, dict):
                active_profile_id = str(raw.get("active_profile_id") or active_profile_id)
                updated_at = str(raw.get("updated_at") or "")
                raw_profiles = raw.get("profiles", {})
                if isinstance(raw_profiles, dict):
                    for profile_id, raw_profile in raw_profiles.items():
                        base = profiles.get(str(profile_id), default_profile)
                        profile = UTMCameraProfile.from_dict(raw_profile, base=base)
                        profiles[profile.profile_id] = profile
                raw_active = raw.get("active_profile")
                if isinstance(raw_active, dict):
                    profile = UTMCameraProfile.from_dict(raw_active, base=profiles.get(active_profile_id, default_profile))
                    profiles[profile.profile_id] = profile
                    active_profile_id = profile.profile_id
        if active_profile_id not in profiles:
            active_profile_id = default_profile.profile_id
        return cls(
            repo_root=root,
            memory_path=path,
            active_profile_id=active_profile_id,
            profiles=profiles,
            updated_at=updated_at,
        )

    def active_profile(self) -> UTMCameraProfile:
        return self.profiles.get(self.active_profile_id) or next(iter(self.profiles.values()))

    def save_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.active_profile()
        if isinstance(payload.get("active_profile_id"), str) and payload["active_profile_id"] in self.profiles:
            self.active_profile_id = str(payload["active_profile_id"])
            current = self.active_profile()
        nested_profiles = payload.get("profiles")
        if isinstance(nested_profiles, dict):
            requested_id = str(payload.get("active_profile_id") or self.active_profile_id)
            nested_payload = nested_profiles.get(requested_id)
            if not isinstance(nested_payload, dict) and nested_profiles:
                first_key = next(iter(nested_profiles.keys()))
                requested_id = str(first_key)
                nested_payload = nested_profiles[first_key]
            if isinstance(nested_payload, dict):
                profile_seed = dict(nested_payload)
                profile_seed.setdefault("profile_id", requested_id)
                payload = profile_seed
                current = self.profiles.get(requested_id, current)
        profile_payload = dict(current.to_dict(repo_root=self.repo_root))
        profile_payload.update({
            key: value
            for key, value in payload.items()
            if value is not None and key not in {"active_profile_id", "profiles"}
        })
        profile = UTMCameraProfile.from_dict(profile_payload, base=current)
        self.active_profile_id = profile.profile_id
        self.profiles[profile.profile_id] = profile
        self.updated_at = _now_iso()
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "tool": "utm.camera.config.save",
            "memory_path": str(self.memory_path),
            "config": self.to_payload(),
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "schema": "atr.utm.camera.config.v1",
            "memory_path": str(self.memory_path),
            "active_profile_id": self.active_profile_id,
            "active_profile": self.active_profile().to_dict(repo_root=self.repo_root),
            "profiles": {
                profile_id: profile.to_dict(repo_root=self.repo_root)
                for profile_id, profile in sorted(self.profiles.items())
            },
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "atr.utm.camera.config.v1",
            "active_profile_id": self.active_profile_id,
            "profiles": {
                profile_id: profile.to_dict()
                for profile_id, profile in sorted(self.profiles.items())
            },
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class UTMRuntimeConfig:
    """Configuration for the local UTM Vision ROS stack launcher."""

    workspace_root: Path
    script_path: Path
    log_dir: Path
    stop_timeout_sec: float = 5.0
    probe_timeout_sec: float = 2.0
    summary_topic: str = "/compression_tester/summary"
    frame_topic: str = "/image_utm"
    ros_setup_paths: list[str] = field(default_factory=lambda: ["/opt/ros/jazzy/setup.bash"])
    extra_setup_paths: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    allow_virtual_bridge_in_test: bool = True
    camera_config: UTMCameraConfig | None = None

    @classmethod
    def from_devices_config(cls, devices_config: dict[str, Any], *, repo_root: Path) -> "UTMRuntimeConfig":
        devices = devices_config if isinstance(devices_config, dict) else {}
        while isinstance(devices.get("devices"), dict):
            devices = devices["devices"]
        raw = devices.get("utm_vision_runtime", {}) if isinstance(devices, dict) else {}
        workspace_root = Path(str(raw.get("workspace_root") or DEFAULT_UTM_REPO)).expanduser()
        script_path = Path(str(raw.get("script_path") or workspace_root / "scripts" / "start_utm_vision_stack.sh")).expanduser()
        if not script_path.is_absolute():
            script_path = workspace_root / script_path
        log_dir = Path(str(raw.get("log_dir") or repo_root / "artifacts" / "utm_runtime")).expanduser()
        if not log_dir.is_absolute():
            log_dir = repo_root / log_dir
        ros_setup_paths = raw.get("ros_setup_paths", ["/opt/ros/jazzy/setup.bash"])
        if not isinstance(ros_setup_paths, list):
            ros_setup_paths = [str(ros_setup_paths)]
        extra_setup_paths = raw.get("extra_setup_paths", [])
        if not isinstance(extra_setup_paths, list):
            extra_setup_paths = [str(extra_setup_paths)]
        raw_environment = raw.get("environment", {})
        environment = {
            str(key): str(value)
            for key, value in raw_environment.items()
        } if isinstance(raw_environment, dict) else {}
        try:
            stop_timeout_sec = float(raw.get("stop_timeout_sec", 5.0))
        except (TypeError, ValueError):
            stop_timeout_sec = 5.0
        try:
            probe_timeout_sec = float(raw.get("probe_timeout_sec", 2.0))
        except (TypeError, ValueError):
            probe_timeout_sec = 2.0
        return cls(
            workspace_root=workspace_root,
            script_path=script_path,
            log_dir=log_dir,
            stop_timeout_sec=max(stop_timeout_sec, 0.5),
            probe_timeout_sec=max(probe_timeout_sec, 0.2),
            summary_topic=str(raw.get("summary_topic") or "/compression_tester/summary"),
            frame_topic=str(raw.get("frame_topic") or "/image_utm"),
            ros_setup_paths=[str(item) for item in ros_setup_paths],
            extra_setup_paths=[str(item) for item in extra_setup_paths],
            environment=environment,
            allow_virtual_bridge_in_test=bool(raw.get("allow_virtual_bridge_in_test", True)),
            camera_config=UTMCameraConfig.load(repo_root=repo_root),
        )


class UTMGraphSnapshotBuilder:
    """Build expected and actual ROS graph snapshots for the UTM program."""

    def __init__(
        self,
        *,
        workspace_root: str | Path = DEFAULT_UTM_REPO,
        command_runner: Callable[[list[str]], tuple[int, str, str]] | None = None,
        probe_timeout_sec: float = 2.0,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser()
        self.command_runner = command_runner or (lambda command: _run_command(command, timeout_sec=probe_timeout_sec))
        self.probe_timeout_sec = probe_timeout_sec

    def expected_graph(self) -> dict[str, Any]:
        """Return the UTM clone launch topology used as the expected RQT flow."""
        source_files = [str(self.workspace_root / item) for item in EXPECTED_SOURCE_FILES]
        nodes = [
            {"id": "camera/usb_cam", "label": "usb_cam", "kind": "ros_node", "package": "usb_cam"},
            {"id": "camera/rectify_node", "label": "rectify_node", "kind": "ros_node", "package": "image_proc"},
            {"id": "compression_tester_monitor/green_dot_monitor", "label": "green_dot_monitor", "kind": "ros_node", "package": "compression_tester_monitor"},
            {"id": "yolo_bringup/yolov8", "label": "yolov8", "kind": "ros_node", "package": "yolo_bringup"},
            {"id": "/camera/image_raw", "label": "/camera/image_raw", "kind": "ros_topic"},
            {"id": "/camera/image_rect", "label": "/camera/image_rect", "kind": "ros_topic"},
            {"id": "/image_utm", "label": "/image_utm", "kind": "ros_topic"},
            {"id": "/compression_tester/state", "label": "/compression_tester/state", "kind": "ros_topic"},
            {"id": "/compression_tester/summary", "label": "/compression_tester/summary", "kind": "ros_topic"},
            {"id": "/compression_tester/metrics", "label": "/compression_tester/metrics", "kind": "ros_topic"},
            {"id": "/compression_tester/green_points", "label": "/compression_tester/green_points", "kind": "ros_topic"},
            {"id": "/compression_tester/debug_image", "label": "/compression_tester/debug_image", "kind": "ros_topic"},
            {"id": "/yolo/detections", "label": "/yolo/detections", "kind": "ros_topic"},
            {"id": "/yolo/tracking", "label": "/yolo/tracking", "kind": "ros_topic"},
            {"id": "/yolo/dbg_image", "label": "/yolo/dbg_image", "kind": "ros_topic"},
        ]
        edges = [
            {"source": "camera/usb_cam", "target": "/camera/image_raw", "kind": "publishes"},
            {"source": "/camera/image_raw", "target": "camera/rectify_node", "kind": "subscribes"},
            {"source": "camera/rectify_node", "target": "/camera/image_rect", "kind": "publishes"},
            {"source": "/camera/image_rect", "target": "compression_tester_monitor/green_dot_monitor", "kind": "subscribes"},
            {"source": "compression_tester_monitor/green_dot_monitor", "target": "/image_utm", "kind": "publishes"},
            {"source": "compression_tester_monitor/green_dot_monitor", "target": "/compression_tester/state", "kind": "publishes"},
            {"source": "compression_tester_monitor/green_dot_monitor", "target": "/compression_tester/summary", "kind": "publishes"},
            {"source": "compression_tester_monitor/green_dot_monitor", "target": "/compression_tester/metrics", "kind": "publishes"},
            {"source": "compression_tester_monitor/green_dot_monitor", "target": "/compression_tester/green_points", "kind": "publishes"},
            {"source": "compression_tester_monitor/green_dot_monitor", "target": "/compression_tester/debug_image", "kind": "publishes"},
            {"source": "/image_utm", "target": "yolo_bringup/yolov8", "kind": "subscribes"},
            {"source": "yolo_bringup/yolov8", "target": "/yolo/detections", "kind": "publishes"},
            {"source": "yolo_bringup/yolov8", "target": "/yolo/tracking", "kind": "publishes"},
            {"source": "yolo_bringup/yolov8", "target": "/yolo/dbg_image", "kind": "publishes"},
        ]
        return {
            "schema": "atr.utm.rqt_graph.expected.v1",
            "source": "cloned_utm_repository",
            "workspace_root": str(self.workspace_root),
            "source_files": source_files,
            "nodes": nodes,
            "edges": edges,
        }

    def snapshot(self, *, previous_hash: str = "") -> dict[str, Any]:
        expected = self.expected_graph()
        actual = self._actual_graph()
        raw = actual.get("raw", {}) if isinstance(actual.get("raw"), dict) else {}
        node_code = raw.get("node_returncode")
        topic_code = raw.get("topic_returncode")
        ros2_available = shutil.which("ros2") is not None or node_code != 127 or topic_code != 127
        diagnostics = self._diagnostics(expected, actual, ros2_available=ros2_available)
        comparable = {"expected_graph": expected, "actual_graph": actual, "diagnostics": diagnostics}
        graph_hash = _stable_hash(comparable)
        return {
            "ok": True,
            "schema": "atr.utm.rqt_graph.snapshot.v1",
            "generated_at": _now_iso(),
            "changed": graph_hash != str(previous_hash or ""),
            "graph_hash": graph_hash,
            "expected_graph": expected,
            "actual_graph": actual,
            "diagnostics": diagnostics,
        }

    def _diagnostics(self, expected: dict[str, Any], actual: dict[str, Any], *, ros2_available: bool) -> dict[str, Any]:
        expected_topics = {node["id"] for node in expected["nodes"] if node.get("kind") == "ros_topic"}
        expected_nodes = {node["id"] for node in expected["nodes"] if node.get("kind") == "ros_node"}
        actual_topics = {node["id"] for node in actual.get("nodes", []) if node.get("kind") == "ros_topic"}
        actual_nodes = {node["id"].lstrip("/") for node in actual.get("nodes", []) if node.get("kind") == "ros_node"}
        source_file_status = {
            item: Path(item).is_file()
            for item in expected.get("source_files", [])
        }
        return {
            "ros2_available": ros2_available,
            "workspace_found": self.workspace_root.is_dir(),
            "script_found": (self.workspace_root / "scripts" / "start_utm_vision_stack.sh").is_file(),
            "source_files": source_file_status,
            "expected_node_count": len(expected_nodes),
            "expected_topic_count": len(expected_topics),
            "actual_node_count": len(actual_nodes),
            "actual_topic_count": len(actual_topics),
            "missing_expected_nodes": sorted(expected_nodes - actual_nodes) if ros2_available else sorted(expected_nodes),
            "missing_expected_topics": sorted(expected_topics - actual_topics) if ros2_available else sorted(expected_topics),
            "topic_seen": "/compression_tester/summary" in actual_topics,
            "camera_seen": "/camera/image_rect" in actual_topics or "/camera/image_raw" in actual_topics,
        }

    def _actual_graph(self) -> dict[str, Any]:
        node_code, node_stdout, node_stderr = self.command_runner(["ros2", "node", "list"])
        topic_code, topic_stdout, topic_stderr = self.command_runner(["ros2", "topic", "list"])
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        node_info: dict[str, dict[str, Any]] = {}
        if node_code == 0:
            for line in node_stdout.splitlines():
                item = line.strip()
                if item:
                    nodes.append({"id": item, "label": item, "kind": "ros_node"})
                    info_code, info_stdout, info_stderr = self.command_runner(["ros2", "node", "info", item])
                    node_info[item] = {
                        "returncode": info_code,
                        "stderr": info_stderr,
                    }
                    if info_code == 0:
                        parsed_edges = self._parse_node_info_edges(item, info_stdout)
                        edges.extend(parsed_edges)
                        node_info[item]["edge_count"] = len(parsed_edges)
        if topic_code == 0:
            for line in topic_stdout.splitlines():
                item = line.strip()
                if item:
                    nodes.append({"id": item, "label": item, "kind": "ros_topic"})
        return {
            "nodes": nodes,
            "edges": edges,
            "raw": {
                "node_returncode": node_code,
                "topic_returncode": topic_code,
                "node_list": node_stdout,
                "topic_list": topic_stdout,
                "node_error": node_stderr,
                "topic_error": topic_stderr,
                "node_info": node_info,
            },
        }

    @staticmethod
    def _parse_node_info_edges(node_id: str, stdout: str) -> list[dict[str, str]]:
        """Parse `ros2 node info` publishers/subscribers into RQT-like edges."""
        edges: list[dict[str, str]] = []
        section = ""
        for raw_line in stdout.splitlines():
            stripped = raw_line.strip()
            lowered = stripped.lower()
            if not stripped:
                continue
            if lowered == "publishers:":
                section = "publishers"
                continue
            if lowered == "subscribers:":
                section = "subscribers"
                continue
            if stripped.endswith(":") and not stripped.startswith("/"):
                section = ""
                continue
            if section not in {"publishers", "subscribers"} or not stripped.startswith("/"):
                continue
            topic = stripped.split(":", 1)[0].strip()
            if section == "publishers":
                edges.append({"source": node_id, "target": topic, "kind": "publishes"})
            else:
                edges.append({"source": topic, "target": node_id, "kind": "subscribes"})
        return edges


class UTMRuntimeProcessManager:
    """Start, stop, probe, and report the UTM Vision ROS process group."""

    def __init__(self, config: UTMRuntimeConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._calibration_process: subprocess.Popen[bytes] | None = None
        self._calibration_log_path: Path | None = None
        self._calibration_started_at = ""
        self._started_at = ""
        self._started_monotonic = 0.0
        self._last_log_path: Path | None = None
        self._mjpeg_streams: dict[str, SharedMjpegTopicStream] = {}
        self._graph_builder = UTMGraphSnapshotBuilder(
            workspace_root=config.workspace_root,
            command_runner=self._run_ros_command,
            probe_timeout_sec=config.probe_timeout_sec,
        )

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._is_running_locked():
                payload = self._status_locked()
                payload["already_running"] = True
                payload["message"] = "UTM Vision runtime is already running."
                return payload
            self._stop_mjpeg_streams_locked()
            startup_cleanup = self._terminate_stale_runtime_processes()
            if not self.config.script_path.is_file():
                return self._error_payload(
                    "UTM_RUNTIME_SCRIPT_NOT_FOUND",
                    f"UTM runtime script not found: {self.config.script_path}",
                )
            startup_camera_controls = self._apply_camera_runtime_controls()
            self.config.log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            log_path = self.config.log_dir / f"utm_runtime_{stamp}.log"
            command = self._shell_command()
            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            try:
                with log_path.open("ab", buffering=0) as log_file:
                    self._process = subprocess.Popen(
                        command,
                        cwd=str(self.config.workspace_root),
                        env=env,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
            except OSError as exc:
                return self._error_payload("UTM_RUNTIME_START_FAILED", str(exc))
            self._started_at = _now_iso()
            self._started_monotonic = time.monotonic()
            self._last_log_path = log_path
            payload = self._status_locked()
            payload["already_running"] = False
            payload["startup_cleanup"] = startup_cleanup
            payload["startup_camera_controls"] = startup_camera_controls
            payload["message"] = "UTM Vision runtime started."
            return payload

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_mjpeg_streams_locked()
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                external_processes = self._external_runtime_processes()
                if external_processes:
                    cleanup = self._terminate_stale_runtime_processes()
                    payload = self._status_locked()
                    payload["was_running"] = True
                    payload["previous_external_pids"] = [proc["pid"] for proc in external_processes]
                    payload["external_cleanup"] = cleanup
                    payload["message"] = "External UTM Vision runtime processes were stopped."
                    return payload
                payload = self._status_locked()
                payload["was_running"] = False
                payload["message"] = "UTM Vision runtime was not running."
                return payload
            pid = process.pid
            try:
                self._terminate_process_group(process, signal.SIGTERM)
                process.wait(timeout=self.config.stop_timeout_sec)
            except subprocess.TimeoutExpired:
                self._terminate_process_group(process, signal.SIGKILL)
                process.wait(timeout=max(self.config.stop_timeout_sec, 0.5))
            finally:
                self._process = None
            return {
                "ok": True,
                "status": "stopped",
                "pid": None,
                "previous_pid": pid,
                "was_running": True,
                "returncode": process.returncode,
                "started_at": self._started_at,
                "log_path": str(self._last_log_path or ""),
                "command": self._command_preview(),
                "message": "UTM Vision runtime stopped.",
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def probe(self) -> dict[str, Any]:
        snapshot = self.graph()
        diagnostics = dict(snapshot.get("diagnostics", {}))
        payload = self.status()
        payload.update(
            {
                "ok": bool(diagnostics.get("ros2_available") and diagnostics.get("workspace_found") and diagnostics.get("script_found")),
                "tool": "utm.runtime.probe",
                "diagnostics": diagnostics,
                "graph_hash": snapshot.get("graph_hash", ""),
                "failure_code": None,
            }
        )
        if not diagnostics.get("ros2_available"):
            payload["failure_code"] = "ROS2_NOT_INSTALLED"
        elif not diagnostics.get("script_found"):
            payload["failure_code"] = "UTM_RUNTIME_SCRIPT_NOT_FOUND"
        elif not diagnostics.get("topic_seen"):
            payload["failure_code"] = "UTM_TOPIC_NOT_READY"
        return payload

    def graph(self, *, previous_hash: str = "") -> dict[str, Any]:
        return self._graph_builder.snapshot(previous_hash=previous_hash)

    def _capture_ros_frame(self, topics: list[str], *, mode: str) -> dict[str, Any]:
        status = self.status()
        if status.get("status") != "running":
            return {
                "ok": False,
                "mode": mode,
                "topic": topics[0] if topics else self.config.frame_topic,
                "frame_available": False,
                "runtime_status": status.get("status"),
                "runtime_pid": status.get("pid"),
                "failure_code": "UTM_RUNTIME_NOT_RUNNING",
                "message": "UTM Vision runtime is not running; ROS frame capture was skipped.",
                "attempts": [],
                "generated_at": _now_iso(),
            }
        attempts: list[dict[str, Any]] = []
        timeout_sec = max(min(self.config.probe_timeout_sec, 1.25), 0.5)
        for topic in topics:
            code, stdout, stderr = self._run_ros_frame_command([
                "python3",
                "-c",
                ROS_IMAGE_CAPTURE_SCRIPT,
                topic,
                f"{timeout_sec:.2f}",
            ], timeout_sec=timeout_sec + 6.0)
            parsed = self._parse_frame_capture_stdout(stdout)
            attempt = {
                "topic": topic,
                "returncode": code,
                "stderr": stderr[-500:] if stderr else "",
                "stdout_tail": stdout[-500:] if stdout else "",
            }
            if parsed:
                attempt.update({
                    "ok": bool(parsed.get("ok")),
                    "failure_code": parsed.get("failure_code", ""),
                    "message": parsed.get("message", ""),
                })
            attempts.append(attempt)
            if code == 0 and parsed and parsed.get("ok") and parsed.get("data_url"):
                parsed.update({
                    "mode": mode,
                    "frame_available": True,
                    "runtime_status": status.get("status"),
                    "runtime_pid": status.get("pid"),
                    "attempts": attempts,
                    "generated_at": _now_iso(),
                })
                return parsed

        return {
            "ok": False,
            "mode": mode,
            "topic": topics[0] if topics else self.config.frame_topic,
            "frame_available": False,
            "runtime_status": status.get("status"),
            "runtime_pid": status.get("pid"),
            "failure_code": "ROS_IMAGE_FRAME_UNAVAILABLE",
            "message": "No ROS image frame was captured from the configured UTM image topics.",
            "attempts": attempts,
            "generated_at": _now_iso(),
        }

    def frame(self) -> dict[str, Any]:
        """Capture the configured display/overlay frame for GUI presentation."""
        return self._capture_ros_frame(self._frame_topic_candidates(), mode="ros_image_topic")

    def raw_frame(self) -> dict[str, Any]:
        """Capture an unannotated camera frame for specimen-presence decisions."""
        return self._capture_ros_frame(self._raw_frame_topic_candidates(), mode="ros_raw_image_topic")

    def frame_stream(self, *, topic: str = "", fps: float | int | None = None, quality: int = 82) -> Iterator[bytes]:
        """Yield an MJPEG stream from the configured ROS image topic at the requested GUI FPS."""
        status = self.status()
        if status.get("status") != "running":
            return
        profile = self._active_camera_profile()
        selected_topic = self._stream_topic_for_request(topic, profile)
        target_fps = _coerce_float(fps, float(profile.fps or 15), minimum=1.0) if fps is not None else float(profile.fps or 15)
        target_fps = max(min(target_fps, 60.0), 1.0)
        jpeg_quality = _coerce_int(quality, 82, minimum=40, maximum=95)
        stream_key = f"{selected_topic}|{target_fps:.3f}|{jpeg_quality}"
        command = self._ros_command_preview([
            "python3",
            "-c",
            ROS_IMAGE_MJPEG_STREAM_SCRIPT,
            selected_topic,
            f"{target_fps:.3f}",
            str(jpeg_quality),
        ])
        with self._lock:
            stream = self._mjpeg_streams.get(stream_key)
            if stream is None:
                stream = SharedMjpegTopicStream(
                    key=hashlib.sha1(stream_key.encode("utf-8")).hexdigest()[:8],
                    command=command,
                    cwd=str(self.config.workspace_root),
                    topic=selected_topic,
                    target_fps=target_fps,
                    jpeg_quality=jpeg_quality,
                )
                self._mjpeg_streams[stream_key] = stream
        yield from stream.frames()

    def frame_stream_status(
        self,
        *,
        topic: str = "",
        fps: float | int | None = None,
        quality: int = 82,
    ) -> dict[str, Any]:
        """Return rolling statistics for an existing GUI MJPEG worker."""
        profile = self._active_camera_profile()
        selected_topic = self._stream_topic_for_request(topic, profile)
        target_fps = _coerce_float(fps, 30.0, minimum=1.0) if fps is not None else 30.0
        target_fps = max(min(target_fps, 60.0), 1.0)
        jpeg_quality = _coerce_int(quality, 82, minimum=40, maximum=95)
        stream_key = f"{selected_topic}|{target_fps:.3f}|{jpeg_quality}"
        with self._lock:
            stream = self._mjpeg_streams.get(stream_key)
        if stream is None:
            return {
                "ok": True,
                "status": "idle",
                "topic": selected_topic,
                "requested_fps": round(target_fps, 2),
                "measured_fps": 0.0,
                "frames": 0,
                "estimated_dropped_frames": 0,
                "clients": 0,
                "quality": jpeg_quality,
                "last_error": "",
            }
        return stream.stats()

    def _stream_topic_for_request(self, topic: str = "", profile: UTMCameraProfile | None = None) -> str:
        """Normalize UI stream requests to the UTM ROI/overlay output topic."""
        camera_profile = profile or self._active_camera_profile()
        output_topic = str(camera_profile.ros_output_topic or self.config.frame_topic or "/image_utm").strip()
        requested_topic = str(topic or output_topic).strip()
        raw_topics = {
            str(camera_profile.ros_rect_topic or "").strip(),
            str(camera_profile.ros_image_topic or "").strip(),
            "/camera/image_rect",
            "/camera/image_raw",
        }
        if output_topic and requested_topic in raw_topics:
            return output_topic
        return requested_topic or output_topic or "/image_utm"

    def _stop_mjpeg_streams_locked(self) -> None:
        streams = list(self._mjpeg_streams.values())
        self._mjpeg_streams.clear()
        for stream in streams:
            stream.stop()

    def camera_direct_frame(self) -> dict[str, Any]:
        """Capture one frame directly from the selected V4L2 Camera candidate."""
        profile = self._active_camera_profile()
        device_path = str(profile.device_path or "").strip()
        discovery_payload: dict[str, Any] | None = None
        if not device_path:
            discovery_payload = discover_v4l2_camera_devices()
            devices = discovery_payload.get("devices") if isinstance(discovery_payload, dict) else []
            if isinstance(devices, list) and devices:
                first = devices[0] if isinstance(devices[0], dict) else {}
                device_path = str(first.get("by_id_path") or first.get("device_path") or "").strip()
        if not device_path:
            return {
                "ok": False,
                "mode": "direct_v4l2_frame",
                "frame_available": False,
                "failure_code": "CAMERA_DEVICE_NOT_SELECTED",
                "message": "Select and save a Camera device path, or connect a V4L2 camera before Pre Start Check.",
                "discovery": discovery_payload,
                "generated_at": _now_iso(),
            }
        if not Path(device_path).exists():
            return {
                "ok": False,
                "mode": "direct_v4l2_frame",
                "frame_available": False,
                "device_path": device_path,
                "failure_code": "CAMERA_DEVICE_NOT_FOUND",
                "message": f"Camera device path is not present: {device_path}",
                "generated_at": _now_iso(),
            }
        if shutil.which("ffmpeg") is None:
            return {
                "ok": False,
                "mode": "direct_v4l2_frame",
                "frame_available": False,
                "device_path": device_path,
                "failure_code": "FFMPEG_NOT_INSTALLED",
                "message": "ffmpeg is required for direct Camera frame capture.",
                "generated_at": _now_iso(),
            }
        with tempfile.TemporaryDirectory(prefix="atr_utm_camera_") as tmp_dir:
            output_path = Path(tmp_dir) / "frame.jpg"
            commands = [
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "v4l2",
                    "-video_size",
                    f"{profile.width}x{profile.height}",
                    "-framerate",
                    str(profile.fps),
                    "-i",
                    device_path,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(output_path),
                ],
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "v4l2",
                    "-i",
                    device_path,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(output_path),
                ],
            ]
            attempts: list[dict[str, Any]] = []
            for command in commands:
                code, stdout, stderr = _run_command(command, timeout_sec=max(min(self.config.probe_timeout_sec, 3.0), 1.0) + 1.0)
                attempts.append({
                    "command": command,
                    "returncode": code,
                    "stderr": stderr[-800:] if stderr else "",
                    "stdout_tail": stdout[-300:] if stdout else "",
                })
                if code == 0 and output_path.is_file() and output_path.stat().st_size > 0:
                    encoded = base64.b64encode(output_path.read_bytes()).decode("ascii")
                    return {
                        "ok": True,
                        "mode": "direct_v4l2_frame",
                        "frame_available": True,
                        "device_path": device_path,
                        "width": profile.width,
                        "height": profile.height,
                        "fps": profile.fps,
                        "format": "jpeg",
                        "data_url": "data:image/jpeg;base64," + encoded,
                        "attempts": attempts,
                        "generated_at": _now_iso(),
                    }
            return {
                "ok": False,
                "mode": "direct_v4l2_frame",
                "frame_available": False,
                "device_path": device_path,
                "failure_code": "DIRECT_CAMERA_FRAME_CAPTURE_FAILED",
                "message": "ffmpeg could not capture a frame from the selected Camera device.",
                "attempts": attempts,
                "generated_at": _now_iso(),
            }

    def camera_config(self) -> dict[str, Any]:
        camera_config = self.config.camera_config or UTMCameraConfig.load(repo_root=Path.cwd())
        return camera_config.to_payload()

    def update_camera_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        camera_config = self.config.camera_config or UTMCameraConfig.load(repo_root=Path.cwd())
        return camera_config.save_update(payload if isinstance(payload, dict) else {})

    def discover_camera_devices(self) -> dict[str, Any]:
        return discover_v4l2_camera_devices()

    def calibration_command(
        self,
        *,
        checkerboard_size: str | None = None,
        square_m: float | None = None,
    ) -> dict[str, Any]:
        profile = self._active_camera_profile()
        size = str(checkerboard_size or profile.checkerboard_size)
        square = _coerce_float(square_m, profile.checkerboard_square_m, minimum=0.0001) if square_m is not None else profile.checkerboard_square_m
        command = [
            "ros2",
            "run",
            "camera_calibration",
            "cameracalibrator",
            "--size",
            size,
            "--square",
            f"{square:g}",
            f"image:={profile.ros_image_topic}",
            f"camera:=/{profile.ros_camera_name.strip('/') or 'camera'}",
        ]
        return {
            "ok": True,
            "tool": "utm.camera.calibrate.command",
            "command": self._ros_command_preview(command),
            "calibration_file": str(profile.calibration_path(repo_root=self._repo_root())),
            "checkerboard_size": size,
            "checkerboard_square_m": square,
        }

    def start_calibration(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        with self._lock:
            if self._calibration_process is not None and self._calibration_process.poll() is None:
                status = self.calibration_status()
                status["already_running"] = True
                return status
            command_payload = self.calibration_command(
                checkerboard_size=payload.get("checkerboard_size"),
                square_m=payload.get("checkerboard_square_m"),
            )
            self.config.log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            log_path = self.config.log_dir / f"utm_camera_calibration_{stamp}.log"
            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            try:
                with log_path.open("ab", buffering=0) as log_file:
                    self._calibration_process = subprocess.Popen(
                        command_payload["command"],
                        cwd=str(self.config.workspace_root),
                        env=env,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
            except OSError as exc:
                command_payload.update({
                    "ok": False,
                    "status": "error",
                    "failure_code": "UTM_CAMERA_CALIBRATION_START_FAILED",
                    "message": str(exc),
                })
                return command_payload
            self._calibration_log_path = log_path
            self._calibration_started_at = _now_iso()
            status = self.calibration_status()
            status["message"] = "Camera calibration GUI started."
            return status

    def stop_calibration(self) -> dict[str, Any]:
        with self._lock:
            process = self._calibration_process
            if process is None or process.poll() is not None:
                self._calibration_process = None
                return self.calibration_status()
            pid = process.pid
            try:
                self._terminate_process_group(process, signal.SIGTERM)
                process.wait(timeout=self.config.stop_timeout_sec)
            except subprocess.TimeoutExpired:
                self._terminate_process_group(process, signal.SIGKILL)
                process.wait(timeout=max(self.config.stop_timeout_sec, 0.5))
            finally:
                self._calibration_process = None
            payload = self.calibration_status()
            payload.update({
                "previous_pid": pid,
                "was_running": True,
                "message": "Camera calibration GUI stopped.",
            })
            return payload

    def calibration_status(self) -> dict[str, Any]:
        process = self._calibration_process
        profile = self._active_camera_profile()
        if process is None:
            return {
                "ok": True,
                "tool": "utm.camera.calibrate.status",
                "status": "stopped",
                "pid": None,
                "returncode": None,
                "started_at": self._calibration_started_at,
                "log_path": str(self._calibration_log_path or ""),
                "calibration_file": str(profile.calibration_path(repo_root=self._repo_root())),
            }
        returncode = process.poll()
        return {
            "ok": returncode in {None, 0},
            "tool": "utm.camera.calibrate.status",
            "status": "running" if returncode is None else ("stopped" if returncode == 0 else "error"),
            "pid": process.pid if returncode is None else None,
            "returncode": returncode,
            "started_at": self._calibration_started_at,
            "log_path": str(self._calibration_log_path or ""),
            "calibration_file": str(profile.calibration_path(repo_root=self._repo_root())),
            "failure_code": "" if returncode in {None, 0} else "UTM_CAMERA_CALIBRATION_EXITED",
        }

    def shutdown(self) -> dict[str, Any]:
        self.stop_calibration()
        return self.stop()

    def cleanup_ports(self) -> dict[str, Any]:
        """Release Camera/UTM runtime resources without stopping the GUI server."""
        runtime = self.stop()
        calibration = self.stop_calibration()
        before_holders = self._camera_port_holders()
        cleanup = self._terminate_stale_runtime_processes()
        after_holders = self._camera_port_holders()
        remaining_utm = [
            holder for holder in after_holders
            if self._looks_like_utm_runtime_process(str(holder.get("cmd", "")))
        ]
        blocked = bool(after_holders or remaining_utm or cleanup["remaining"])
        return {
            "ok": not blocked,
            "tool": "utm.camera.cleanup",
            "status": "released" if not blocked else "blocked",
            "runtime": runtime,
            "calibration": calibration,
            "device_paths": self._camera_device_paths(),
            "holders_before": before_holders,
            "holders_after": after_holders,
            "terminated": cleanup["terminated"],
            "remaining": cleanup["remaining"],
            "message": (
                "UTM Camera ports were released."
                if not blocked
                else "One or more processes still hold the selected Camera device."
            ),
            "generated_at": _now_iso(),
        }

    def _status_locked(self) -> dict[str, Any]:
        process = self._process
        if process is None:
            external_processes = self._external_runtime_processes()
            if external_processes:
                primary = external_processes[0]
                return {
                    "ok": True,
                    "status": "running",
                    "managed": False,
                    "pid": primary["pid"],
                    "external_pids": [proc["pid"] for proc in external_processes],
                    "returncode": None,
                    "started_at": self._started_at,
                    "log_path": str(self._last_log_path or ""),
                    "command": self._command_preview(),
                    "message": "External UTM Vision runtime processes are running.",
                }
            return {
                "ok": True,
                "status": "stopped",
                "managed": True,
                "pid": None,
                "returncode": None,
                "started_at": self._started_at,
                "log_path": str(self._last_log_path or ""),
                "command": self._command_preview(),
                "message": "UTM Vision runtime is stopped.",
            }
        returncode = process.poll()
        if returncode is None:
            return {
                "ok": True,
                "status": "running",
                "managed": True,
                "pid": process.pid,
                "returncode": None,
                "started_at": self._started_at,
                "uptime_sec": max(time.monotonic() - self._started_monotonic, 0.0) if self._started_monotonic else None,
                "log_path": str(self._last_log_path or ""),
                "command": self._command_preview(),
                "message": "UTM Vision runtime is running.",
            }
        self._stop_mjpeg_streams_locked()
        self._process = None
        ok = returncode == 0
        return {
            "ok": ok,
            "status": "stopped" if ok else "error",
            "managed": True,
            "pid": None,
            "returncode": returncode,
            "started_at": self._started_at,
            "log_path": str(self._last_log_path or ""),
            "command": self._command_preview(),
            "failure_code": "" if ok else "UTM_RUNTIME_EXITED",
            "message": "UTM Vision runtime exited." if ok else "UTM Vision runtime exited with an error.",
        }

    def _is_running_locked(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _shell_command(self) -> list[str]:
        source_parts = self._source_prefix_parts()
        environment = dict(self.config.environment)
        environment.update(self._camera_environment())
        export_parts = [
            f"export {key}={shlex.quote(value)}"
            for key, value in sorted(environment.items())
            if key.replace("_", "").isalnum()
        ]
        source_prefix = "; ".join(source_parts)
        export_prefix = "; ".join(export_parts)
        prefix_parts = [part for part in [source_prefix, export_prefix] if part]
        if prefix_parts:
            script = (
                f"{'; '.join(prefix_parts)}; "
                f"export UTM_VISION_ROOT={shlex.quote(str(self.config.workspace_root))}; "
                f"exec bash {shlex.quote(str(self.config.script_path))}"
            )
            return ["bash", "-lc", script]
        return ["bash", str(self.config.script_path)]

    def _source_prefix_parts(self) -> list[str]:
        source_parts = ['export PATH="$HOME/.local/bin:$PATH"']
        source_parts.extend([
            f"test -f {shlex.quote(path)} && source {shlex.quote(path)} || true"
            for path in self.config.ros_setup_paths
        ])
        for path in self.config.extra_setup_paths:
            source_parts.append(f"test -f {shlex.quote(path)} && source {shlex.quote(path)} || true")
        workspace_setup = self.config.workspace_root / "install" / "setup.bash"
        if workspace_setup.is_file():
            source_parts.append(f"source {shlex.quote(str(workspace_setup))}")
        return source_parts

    def _ros_command_preview(self, command: list[str]) -> list[str]:
        prefix = "; ".join(self._source_prefix_parts())
        command_text = " ".join(shlex.quote(part) for part in command)
        return ["bash", "-lc", f"{prefix}; {command_text}"]

    def _run_ros_command(self, command: list[str]) -> tuple[int, str, str]:
        return _run_command(self._ros_command_preview(command), timeout_sec=self.config.probe_timeout_sec)

    def _run_ros_frame_command(self, command: list[str], *, timeout_sec: float) -> tuple[int, str, str]:
        return _run_command(self._ros_command_preview(command), timeout_sec=timeout_sec)

    def _command_preview(self) -> list[str]:
        return self._shell_command()

    def _repo_root(self) -> Path:
        camera_config = self.config.camera_config
        return camera_config.repo_root if camera_config is not None else Path.cwd()

    def _active_camera_profile(self) -> UTMCameraProfile:
        camera_config = self.config.camera_config
        if camera_config is None:
            return UTMCameraProfile()
        return camera_config.active_profile()

    def _camera_environment(self) -> dict[str, str]:
        camera_config = self.config.camera_config
        if camera_config is None:
            return {}
        return camera_config.active_profile().to_env(repo_root=camera_config.repo_root)

    def _apply_camera_runtime_controls(self) -> dict[str, Any]:
        """Pin UVC controls that otherwise let BRIO drop below the requested FPS."""
        device_paths = self._camera_device_paths()
        device_path = device_paths[0] if device_paths else ""
        if not device_path:
            return {
                "ok": True,
                "status": "skipped",
                "failure_code": "",
                "message": "No Camera device path is configured; V4L2 runtime controls were skipped.",
                "controls": {},
                "attempts": [],
            }
        set_command = [
            "v4l2-ctl",
            f"--device={device_path}",
            "--set-ctrl=exposure_dynamic_framerate=0",
        ]
        get_command = [
            "v4l2-ctl",
            f"--device={device_path}",
            "--get-ctrl=exposure_dynamic_framerate,auto_exposure,exposure_time_absolute,brightness,gain",
        ]
        set_code, set_stdout, set_stderr = _run_command(set_command, timeout_sec=2.0)
        attempts = [
            {
                "command": set_command,
                "returncode": set_code,
                "stdout_tail": set_stdout[-500:] if set_stdout else "",
                "stderr": set_stderr[-500:] if set_stderr else "",
            }
        ]
        get_code, get_stdout, get_stderr = _run_command(get_command, timeout_sec=2.0)
        attempts.append(
            {
                "command": get_command,
                "returncode": get_code,
                "stdout_tail": get_stdout[-500:] if get_stdout else "",
                "stderr": get_stderr[-500:] if get_stderr else "",
            }
        )
        ok = set_code == 0
        failure_code = ""
        if not ok:
            failure_code = "V4L2_CTL_NOT_AVAILABLE" if set_code == 127 else "CAMERA_CONTROL_APPLY_FAILED"
        return {
            "ok": ok,
            "status": "applied" if ok else "warning",
            "failure_code": failure_code,
            "device_path": device_path,
            "controls": {
                "exposure_dynamic_framerate": 0,
            },
            "control_readback": get_stdout.strip(),
            "message": (
                "Camera dynamic framerate was pinned before UTM runtime start."
                if ok
                else "Camera dynamic framerate could not be pinned; UTM runtime start continued."
            ),
            "attempts": attempts,
        }

    def _frame_topic_candidates(self) -> list[str]:
        preferred = [
            self.config.frame_topic,
            "/image_utm",
            "/camera/image_raw",
            "/yolo/dbg_image",
            "/compression_tester/debug_image",
            "/camera/image_rect",
        ]
        seen: set[str] = set()
        topics: list[str] = []
        for topic in preferred:
            clean = str(topic or "").strip()
            if clean and clean not in seen:
                seen.add(clean)
                topics.append(clean)
        return topics

    def _raw_frame_topic_candidates(self) -> list[str]:
        profile = self._active_camera_profile()
        preferred = [
            profile.ros_image_topic,
            "/camera/image_raw",
            profile.ros_rect_topic,
            "/camera/image_rect",
        ]
        seen: set[str] = set()
        topics: list[str] = []
        for topic in preferred:
            clean = str(topic or "").strip()
            if clean and clean not in seen:
                seen.add(clean)
                topics.append(clean)
        return topics

    def _camera_device_paths(self) -> list[str]:
        profile = self._active_camera_profile()
        candidates = [profile.device_path, profile.runtime_device_path()]
        paths: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            raw = str(candidate or "").strip()
            if not raw:
                continue
            path = Path(raw).expanduser()
            variants = [str(path)]
            try:
                if path.exists():
                    variants.append(str(path.resolve(strict=True)))
            except OSError:
                pass
            for variant in variants:
                if variant and variant not in seen:
                    seen.add(variant)
                    paths.append(variant)
        return paths

    def _camera_port_holders(self) -> list[dict[str, Any]]:
        paths = {str(Path(path).resolve()) if Path(path).exists() else path for path in self._camera_device_paths()}
        if not paths:
            return []
        holders: dict[int, dict[str, Any]] = {}
        for proc_dir in Path("/proc").iterdir():
            if not proc_dir.name.isdigit():
                continue
            pid = int(proc_dir.name)
            fd_dir = proc_dir / "fd"
            if not fd_dir.is_dir():
                continue
            held_paths: set[str] = set()
            try:
                fd_entries = list(fd_dir.iterdir())
            except OSError:
                continue
            for fd in fd_entries:
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                try:
                    resolved = str(Path(target).resolve()) if target.startswith("/") else target
                except OSError:
                    resolved = target
                if target in paths or resolved in paths:
                    held_paths.add(resolved)
            if not held_paths:
                continue
            holders[pid] = {
                "pid": pid,
                "cmd": self._process_cmdline(pid),
                "paths": sorted(held_paths),
            }
        return [holders[pid] for pid in sorted(holders)]

    def _external_runtime_processes(self) -> list[dict[str, Any]]:
        """Find a live UTM ROS stack that survived a GUI server restart."""
        targets: list[dict[str, Any]] = []
        for proc in self._iter_process_cmdlines():
            cmd = str(proc.get("cmd", ""))
            if self._looks_like_mjpeg_stream_process(cmd):
                continue
            if self._looks_like_utm_runtime_process(cmd):
                targets.append(proc)
        return targets

    def _terminate_stale_runtime_processes(self) -> dict[str, Any]:
        targets = [
            proc for proc in self._iter_process_cmdlines()
            if self._looks_like_utm_runtime_process(proc["cmd"])
        ]
        terminated: list[dict[str, Any]] = []
        for proc in targets:
            pid = int(proc["pid"])
            if pid in {os.getpid(), os.getppid()}:
                continue
            if not self._pid_exists(pid):
                continue
            terminated.append({"pid": pid, "cmd": proc["cmd"], "signal": "SIGTERM"})
            self._signal_process_or_group(pid, signal.SIGTERM)
        if terminated:
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and any(self._pid_exists(int(item["pid"])) for item in terminated):
                time.sleep(0.05)
        for item in terminated:
            pid = int(item["pid"])
            if self._pid_exists(pid):
                item["signal"] = "SIGKILL"
                self._signal_process_or_group(pid, signal.SIGKILL)
        remaining = [
            proc for proc in self._iter_process_cmdlines()
            if self._looks_like_utm_runtime_process(proc["cmd"])
        ]
        return {
            "ok": not remaining,
            "terminated": terminated,
            "remaining": remaining,
        }

    def _iter_process_cmdlines(self) -> list[dict[str, Any]]:
        processes: list[dict[str, Any]] = []
        for proc_dir in Path("/proc").iterdir():
            if not proc_dir.name.isdigit():
                continue
            pid = int(proc_dir.name)
            if pid in {os.getpid(), os.getppid()}:
                continue
            cmd = self._process_cmdline(pid)
            if cmd:
                processes.append({"pid": pid, "cmd": cmd})
        return processes

    @staticmethod
    def _process_cmdline(pid: int) -> str:
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return ""
        return " ".join(part.decode("utf-8", "replace") for part in raw.split(b"\0") if part)

    def _looks_like_utm_runtime_process(self, cmd: str) -> bool:
        if not cmd:
            return False
        if "rg " in cmd or "grep " in cmd or "pytest" in cmd:
            return False
        if any(pattern in cmd for pattern in (
            " ros2 node list",
            " ros2 node info",
            " ros2 topic list",
            " ros2 topic echo",
            " ros2 topic hz",
        )):
            return False
        if "OneShotImageSubscriber" in cmd or "atr_utm_frame_snapshot" in cmd:
            return False
        if self._looks_like_mjpeg_stream_process(cmd):
            return True
        if (
            "start_utm_vision_stack.sh" in cmd
            or "ros2 launch compression_tester_monitor camera_rect.launch.py" in cmd
            or "ros2 launch compression_tester_monitor green_dot_monitor.launch.py" in cmd
            or "ros2 launch yolo_bringup yolov8.launch.py" in cmd
        ):
            return True
        if "camera_rect.launch.py" in cmd or "green_dot_monitor.launch.py" in cmd or "yolov8.launch.py" in cmd:
            return True
        if "usb_cam_node_exe" in cmd and "__ns:=/camera" in cmd:
            return True
        if "image_proc/rectify_node" in cmd and "__ns:=/camera" in cmd:
            return True
        if "green_dot_monitor" in cmd and "/camera/image_rect" in cmd:
            return True
        if any(name in cmd for name in ("yolo_node", "tracking_node", "debug_node")) and "/image_utm" in cmd:
            return True
        if "cameracalibrator" in cmd and "/camera" in cmd:
            return True
        return False

    @staticmethod
    def _looks_like_mjpeg_stream_process(cmd: str) -> bool:
        return "python3 -c" in cmd and "atr_utm_frame_mjpeg_stream" in cmd and "MjpegStreamSubscriber" in cmd

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        try:
            stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
            if len(stat_fields) > 2 and stat_fields[2] == "Z":
                return False
        except OSError:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _signal_process_or_group(pid: int, sig: signal.Signals) -> None:
        try:
            os.killpg(os.getpgid(pid), sig)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                return

    @staticmethod
    def _parse_frame_capture_stdout(stdout: str) -> dict[str, Any] | None:
        for line in reversed((stdout or "").splitlines()):
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            return payload if isinstance(payload, dict) else None
        return None

    def _error_payload(self, failure_code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "error",
            "pid": None,
            "returncode": None,
            "started_at": self._started_at,
            "log_path": str(self._last_log_path or ""),
            "command": self._command_preview(),
            "failure_code": failure_code,
            "message": message,
        }

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except ProcessLookupError:
            return


_RUNTIME_SINGLETON: UTMRuntimeProcessManager | None = None
_RUNTIME_SINGLETON_KEY: str = ""


def get_utm_runtime_manager(devices_config: dict[str, Any] | None = None, *, repo_root: str | Path = ".") -> UTMRuntimeProcessManager:
    """Return a process-local singleton shared by tool registry and FastAPI routes."""
    global _RUNTIME_SINGLETON, _RUNTIME_SINGLETON_KEY
    config = UTMRuntimeConfig.from_devices_config(devices_config or {}, repo_root=Path(repo_root))
    key = _stable_hash(
        {
            "workspace_root": str(config.workspace_root),
            "script_path": str(config.script_path),
            "log_dir": str(config.log_dir),
            "ros_setup_paths": config.ros_setup_paths,
            "extra_setup_paths": config.extra_setup_paths,
            "environment": config.environment,
            "camera": config.camera_config.to_dict() if config.camera_config is not None else {},
        }
    )
    if _RUNTIME_SINGLETON is None or key != _RUNTIME_SINGLETON_KEY:
        _RUNTIME_SINGLETON = UTMRuntimeProcessManager(config)
        _RUNTIME_SINGLETON_KEY = key
    return _RUNTIME_SINGLETON
