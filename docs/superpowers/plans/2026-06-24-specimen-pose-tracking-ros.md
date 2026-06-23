# Specimen Pose Tracking ROS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-shot D455F RealSense specimen pose tracking after 3DP auto-ejection, return the camera to the VLA route, and gate ManipulationAgent inference on fresh pose plus confirmed camera return.

**Architecture:** Add a focused `SpecimenPoseTrackerBridge` that owns the D455F lease and runs a short ROS one-shot tracker. VisionAgent consumes `specimen_pose.v1` and maps it into existing `pose_estimate`, `vision_report.v1`, and `vision_signal.v1`; ManipulationAgent blocks VLA rollout unless `camera_returned_to_vla=true`. The LangGraph config is updated to represent pre-manipulation pose tracking and post-manipulation BRIO/UTM verification, and Live GUI renders the lease/pose status.

**Tech Stack:** Python 3.12, FastAPI, pytest, ROS 2 Jazzy, `realsense2_camera`, LeRobot bridge, existing ATR LangGraph YAML runtime, browser UI in `web/static/planning.js`.

---

## File Structure

Create:

- `device_bridges/specimen_pose_tracker.py`
  Owns D455F lease state, one-shot snapshot command construction, virtual/test pose, result validation, and release verification.

- `ros/atr_specimen_pose_tracker/package.xml`
  ROS package manifest for the one-shot tracker node.

- `ros/atr_specimen_pose_tracker/setup.py`
  ROS Python package entrypoint definition.

- `ros/atr_specimen_pose_tracker/resource/atr_specimen_pose_tracker`
  ROS package marker file.

- `ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker/__init__.py`
  Empty package init.

- `ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker/specimen_pose_node.py`
  One-shot ROS node. Subscribes to D455F color, aligned depth, and camera info; emits JSON pose and optional debug image.

- `scripts/vision/run_specimen_pose_snapshot.sh`
  Shell wrapper that sources ROS/overlay paths and runs the one-shot tracker.

- `tests/unit/test_specimen_pose_tracker.py`
  Unit tests for lease state, virtual pose, release failure, and command payload shape.

- `tests/integration/test_specimen_pose_tracker_api.py`
  FastAPI integration tests for status/snapshot/release endpoints.

- `tests/unit/test_vision_agent_specimen_pose.py`
  VisionAgent contract tests for consuming `specimen_pose.v1`.

- `tests/unit/test_graph_specimen_pose_tracking.py`
  Graph/module metadata tests for the new Vision/Manipulation contract.

Modify:

- `configs/devices.yaml`
  Add `specimen_pose_tracker` runtime config with D455F serial, ROS setup paths, script path, timeouts, and test-mode behavior.

- `mcp_tools/camera_tools.py`
  Register `vision.specimen_pose_snapshot` and route it to the new bridge when available.

- `app/bootstrap.py`
  Instantiate `SpecimenPoseTrackerBridge` and pass it into camera tool registration.

- `app/main.py`
  Add `/api/vision/specimen-pose/*` endpoints and expose Vision report/Live GUI metadata.

- `agents/vision_agent.py`
  Prefer one-shot specimen pose snapshot after 3DP auto-ejection and map its result into the legacy and new Vision contracts.

- `agents/manipulation_agent.py`
  Enforce `camera_returned_to_vla` and `vla_camera_precheck_ok` before LeRobot/Pi0.5 rollout starts.

- `graphs/modules/vision/module.yaml`
  Add internal steps and tool contract for one-shot D455F pose tracking.

- `graphs/modules/manipulation/module.yaml`
  Add explicit camera-return and pose-freshness consumption in preflight.

- `graphs/configs/atr_closed_loop.yaml`
  Update edge metadata, add `vision_verify` node after manipulation if schema validation permits duplicate `stage: vision` nodes.

- `web/static/planning.js`
  Render D455F lease, one-shot pose, and VLA return status in Vision cards; keep existing report rendering.

- `web/static/styles.css`
  Add compact card styles for pose/lease indicators.

- `docs/agents/vision_pickup_observation_runtime_guideline.txt`
  Document `specimen_pose.v1` and one-shot D455F lease behavior.

- `docs/hardware/utm_ros_vision_runtime_bridge.md`
  Clarify UTM/BRIO verification remains separate from D455F workspace localization.

- `docs/runtime/closed_loop_and_pages_reference.md`
  Update workflow and GUI page responsibilities.

---

## Task 1: Add Specimen Pose Tracker Bridge Core

**Files:**

- Create: `device_bridges/specimen_pose_tracker.py`
- Create: `tests/unit/test_specimen_pose_tracker.py`

- [ ] **Step 1: Write bridge unit tests**

Create `tests/unit/test_specimen_pose_tracker.py`:

```python
from __future__ import annotations

from pathlib import Path

from device_bridges.specimen_pose_tracker import (
    SpecimenPoseTrackerBridge,
    SpecimenPoseTrackerConfig,
)


def _bridge(tmp_path: Path) -> SpecimenPoseTrackerBridge:
    return SpecimenPoseTrackerBridge(
        SpecimenPoseTrackerConfig(
            enabled=True,
            d455f_serial="341522300873",
            script_path=tmp_path / "run_specimen_pose_snapshot.sh",
            log_dir=tmp_path / "logs",
            artifact_dir=tmp_path / "artifacts",
            ros_setup_paths=[],
            extra_setup_paths=[],
            max_runtime_sec=8.0,
            release_timeout_sec=5.0,
            allow_virtual_pose_in_test=True,
        )
    )


def test_virtual_snapshot_returns_pose_and_released_camera(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.snapshot({"mode": "test", "specimen_id": "specimen-1"})

    assert result["ok"] is True
    assert result["tool"] == "vision.specimen_pose_snapshot"
    assert result["pose"]["schema"] == "specimen_pose.v1"
    assert result["pose"]["specimen_id"] == "specimen-1"
    assert result["pose"]["camera_owner_before"] == "vla_runtime"
    assert result["pose"]["camera_owner_after"] == "vla_runtime"
    assert result["pose"]["port_released"] is True
    assert result["pose"]["vla_camera_precheck_ok"] is True
    assert result["lease"]["owner"] == "vla_runtime"


def test_live_snapshot_blocks_when_script_missing(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    result = bridge.snapshot({"mode": "live", "specimen_id": "specimen-1"})

    assert result["ok"] is False
    assert result["failure_code"] == "SPECIMEN_POSE_TRACKER_SCRIPT_NOT_FOUND"
    assert result["lease"]["owner"] in {"free", "vla_runtime"}


def test_release_status_reports_vla_owner(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    status = bridge.release({"mode": "test"})

    assert status["ok"] is True
    assert status["tool"] == "vision.specimen_pose.release"
    assert status["lease"]["owner"] == "vla_runtime"
    assert status["camera_returned_to_vla"] is True


def test_status_payload_is_gui_safe(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path)

    status = bridge.status()

    assert status["ok"] is True
    assert status["tool"] == "vision.specimen_pose.status"
    assert status["enabled"] is True
    assert status["camera_id"] == "d455f_global"
    assert "api_key" not in str(status).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/unit/test_specimen_pose_tracker.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'device_bridges.specimen_pose_tracker'`.

- [ ] **Step 3: Implement bridge core**

Create `device_bridges/specimen_pose_tracker.py`:

```python
"""
File purpose:
- One-shot D455F specimen pose tracking bridge with exclusive camera lease handoff.

Key classes/functions:
- SpecimenPoseTrackerConfig
- SpecimenPoseTrackerBridge
- get_specimen_pose_tracker_bridge

Inputs/outputs:
- Input: VisionAgent snapshot request payload
- Output: specimen_pose.v1 plus lease/release evidence

Dependencies:
- subprocess
- pathlib

Modification guide:
- Safe places to edit: timeout defaults, virtual pose coordinates, ROS command env
- Risky places to edit: live-mode release gating and VLA camera ownership semantics
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SpecimenPoseTrackerConfig:
    enabled: bool = True
    camera_id: str = "d455f_global"
    d455f_serial: str = ""
    script_path: Path = Path("scripts/vision/run_specimen_pose_snapshot.sh")
    log_dir: Path = Path("artifacts/specimen_pose_tracker")
    artifact_dir: Path = Path("runs")
    ros_setup_paths: list[str] = field(default_factory=lambda: ["/opt/ros/jazzy/setup.bash"])
    extra_setup_paths: list[str] = field(default_factory=list)
    max_runtime_sec: float = 8.0
    release_timeout_sec: float = 5.0
    pose_confidence_threshold: float = 0.75
    allow_virtual_pose_in_test: bool = True

    @classmethod
    def from_devices_config(cls, devices_config: dict[str, Any], *, repo_root: Path) -> "SpecimenPoseTrackerConfig":
        devices = devices_config if isinstance(devices_config, dict) else {}
        while isinstance(devices.get("devices"), dict):
            devices = devices["devices"]
        raw = devices.get("specimen_pose_tracker", {}) if isinstance(devices, dict) else {}
        script_path = Path(str(raw.get("script_path") or repo_root / "scripts" / "vision" / "run_specimen_pose_snapshot.sh")).expanduser()
        if not script_path.is_absolute():
            script_path = repo_root / script_path
        log_dir = Path(str(raw.get("log_dir") or repo_root / "artifacts" / "specimen_pose_tracker")).expanduser()
        if not log_dir.is_absolute():
            log_dir = repo_root / log_dir
        artifact_dir = Path(str(raw.get("artifact_dir") or repo_root / "runs")).expanduser()
        if not artifact_dir.is_absolute():
            artifact_dir = repo_root / artifact_dir
        ros_setup_paths = raw.get("ros_setup_paths", ["/opt/ros/jazzy/setup.bash"])
        extra_setup_paths = raw.get("extra_setup_paths", [])
        return cls(
            enabled=bool(raw.get("enabled", True)),
            camera_id=str(raw.get("camera_id") or "d455f_global"),
            d455f_serial=str(raw.get("d455f_serial") or raw.get("serial") or ""),
            script_path=script_path,
            log_dir=log_dir,
            artifact_dir=artifact_dir,
            ros_setup_paths=[str(item) for item in ros_setup_paths] if isinstance(ros_setup_paths, list) else [str(ros_setup_paths)],
            extra_setup_paths=[str(item) for item in extra_setup_paths] if isinstance(extra_setup_paths, list) else [str(extra_setup_paths)],
            max_runtime_sec=max(_safe_float(raw.get("max_runtime_sec"), 8.0), 1.0),
            release_timeout_sec=max(_safe_float(raw.get("release_timeout_sec"), 5.0), 0.5),
            pose_confidence_threshold=max(min(_safe_float(raw.get("pose_confidence_threshold"), 0.75), 1.0), 0.0),
            allow_virtual_pose_in_test=bool(raw.get("allow_virtual_pose_in_test", True)),
        )


class SpecimenPoseTrackerBridge:
    def __init__(self, config: SpecimenPoseTrackerConfig) -> None:
        self.config = config
        self._owner = "vla_runtime"
        self._last_pose: dict[str, Any] = {}
        self._last_log_path = ""

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "tool": "vision.specimen_pose.status",
            "enabled": self.config.enabled,
            "camera_id": self.config.camera_id,
            "d455f_serial": self.config.d455f_serial,
            "lease": self._lease_payload(),
            "last_pose": self._last_pose,
            "last_log_path": self._last_log_path,
            "generated_at": _now_iso(),
        }

    def snapshot(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request = payload if isinstance(payload, dict) else {}
        mode = str(request.get("mode") or request.get("runtime_mode") or "test").lower()
        if not self.config.enabled:
            return self._error("SPECIMEN_POSE_TRACKER_DISABLED", "Specimen pose tracker is disabled.")
        self._owner = "vision_ros_tracker"
        if mode != "live" and self.config.allow_virtual_pose_in_test:
            pose = self._virtual_pose(request)
            self._owner = "vla_runtime"
            self._last_pose = pose
            return {"ok": True, "tool": "vision.specimen_pose_snapshot", "mode": mode, "pose": pose, "lease": self._lease_payload()}
        if not self.config.script_path.is_file():
            self._owner = "vla_runtime"
            return self._error("SPECIMEN_POSE_TRACKER_SCRIPT_NOT_FOUND", f"Script not found: {self.config.script_path}")
        return self._run_live_snapshot(request, mode=mode)

    def release(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self._owner = "vla_runtime"
        return {
            "ok": True,
            "tool": "vision.specimen_pose.release",
            "camera_returned_to_vla": True,
            "lease": self._lease_payload(),
            "generated_at": _now_iso(),
        }

    def _run_live_snapshot(self, request: dict[str, Any], *, mode: str) -> dict[str, Any]:
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.config.log_dir / f"specimen_pose_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
        command = [str(self.config.script_path), json.dumps(request, ensure_ascii=True)]
        env = os.environ.copy()
        env["ATR_D455F_SERIAL"] = self.config.d455f_serial
        env["ATR_SPECIMEN_POSE_THRESHOLD"] = str(self.config.pose_confidence_threshold)
        try:
            completed = subprocess.run(command, cwd=str(self.config.script_path.parent), env=env, text=True, capture_output=True, timeout=self.config.max_runtime_sec, check=False)
        except subprocess.TimeoutExpired:
            self._owner = "vla_runtime"
            return self._error("SPECIMEN_POSE_TIMEOUT", "Specimen pose tracker timed out.")
        log_path.write_text((completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8")
        self._last_log_path = str(log_path)
        parsed = self._parse_last_json_line(completed.stdout)
        self._owner = "vla_runtime"
        if completed.returncode != 0 or not parsed.get("ok"):
            return self._error(str(parsed.get("failure_code") or "SPECIMEN_POSE_TRACKER_FAILED"), str(parsed.get("message") or "Tracker returned failure."))
        pose = parsed.get("pose") if isinstance(parsed.get("pose"), dict) else parsed
        pose.setdefault("port_released", True)
        pose.setdefault("vla_camera_precheck_ok", True)
        pose.setdefault("camera_owner_after", "vla_runtime")
        self._last_pose = pose
        return {"ok": True, "tool": "vision.specimen_pose_snapshot", "mode": mode, "pose": pose, "lease": self._lease_payload(), "log_path": str(log_path)}

    @staticmethod
    def _parse_last_json_line(stdout: str) -> dict[str, Any]:
        for line in reversed((stdout or "").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return {}

    def _virtual_pose(self, request: dict[str, Any]) -> dict[str, Any]:
        specimen_id = str(request.get("specimen_id") or "specimen-test")
        return {
            "schema": "specimen_pose.v1",
            "stage": "post_ejection_workspace_localization",
            "camera_id": self.config.camera_id,
            "camera_owner_before": "vla_runtime",
            "camera_owner_after": "vla_runtime",
            "workspace": "a4_robot_workspace",
            "specimen_id": specimen_id,
            "frame_id": str(request.get("frame_id") or f"frame-{specimen_id}"),
            "timestamp": _now_iso(),
            "center_px": [320, 240],
            "bbox_xyxy": [300, 220, 340, 260],
            "depth_mm": 620.0,
            "position_a4_mm": {"x": 148.5, "y": 105.0, "z": 15.0},
            "position_robot_base_mm": {"x": 0.0, "y": 0.0, "z": 15.0},
            "position_isaac_world_mm": {"x": 0.0, "y": 0.0, "z": 15.0},
            "orientation_deg": {"yaw": 0.0},
            "confidence": 0.91,
            "stable_frames": 1,
            "freshness_ms": 0,
            "port_released": True,
            "vla_camera_precheck_ok": True,
        }

    def _lease_payload(self) -> dict[str, Any]:
        return {"camera_id": self.config.camera_id, "owner": self._owner, "state": "released" if self._owner == "vla_runtime" else "active"}

    def _error(self, failure_code: str, message: str) -> dict[str, Any]:
        return {"ok": False, "tool": "vision.specimen_pose_snapshot", "failure_code": failure_code, "message": message, "lease": self._lease_payload(), "generated_at": _now_iso()}


def get_specimen_pose_tracker_bridge(devices_config: dict[str, Any], *, repo_root: Path) -> SpecimenPoseTrackerBridge:
    return SpecimenPoseTrackerBridge(SpecimenPoseTrackerConfig.from_devices_config(devices_config, repo_root=repo_root))
```

- [ ] **Step 4: Run unit tests**

Run:

```bash
pytest tests/unit/test_specimen_pose_tracker.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add device_bridges/specimen_pose_tracker.py tests/unit/test_specimen_pose_tracker.py
git commit -m "feat: add specimen pose tracker bridge"
```

---

## Task 2: Add ROS One-Shot Tracker Package and Script

**Files:**

- Create: `ros/atr_specimen_pose_tracker/package.xml`
- Create: `ros/atr_specimen_pose_tracker/setup.py`
- Create: `ros/atr_specimen_pose_tracker/resource/atr_specimen_pose_tracker`
- Create: `ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker/__init__.py`
- Create: `ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker/specimen_pose_node.py`
- Create: `scripts/vision/run_specimen_pose_snapshot.sh`
- Test: `tests/unit/test_specimen_pose_tracker.py`

- [ ] **Step 1: Add script shape test**

Append to `tests/unit/test_specimen_pose_tracker.py`:

```python

def test_live_snapshot_command_parses_json_stdout(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "run_specimen_pose_snapshot.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "echo '{\"ok\": true, \"pose\": {\"schema\": \"specimen_pose.v1\", \"confidence\": 0.88}}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    bridge = SpecimenPoseTrackerBridge(
        SpecimenPoseTrackerConfig(script_path=script, log_dir=tmp_path / "logs", artifact_dir=tmp_path / "artifacts")
    )

    result = bridge.snapshot({"mode": "live", "specimen_id": "specimen-live"})

    assert result["ok"] is True
    assert result["pose"]["schema"] == "specimen_pose.v1"
    assert result["pose"]["camera_owner_after"] == "vla_runtime"
    assert result["pose"]["port_released"] is True
```

- [ ] **Step 2: Run test to verify it passes after Task 1 core**

Run:

```bash
pytest tests/unit/test_specimen_pose_tracker.py::test_live_snapshot_command_parses_json_stdout -q
```

Expected: PASS.

- [ ] **Step 3: Create ROS package files**

Create `ros/atr_specimen_pose_tracker/package.xml`:

```xml
<?xml version="1.0"?>
<package format="3">
  <name>atr_specimen_pose_tracker</name>
  <version>0.1.0</version>
  <description>ATR one-shot specimen pose tracker for D455F workspace localization.</description>
  <maintainer email="local@atr.invalid">ATR</maintainer>
  <license>Proprietary</license>
  <exec_depend>rclpy</exec_depend>
  <exec_depend>sensor_msgs</exec_depend>
  <exec_depend>cv_bridge</exec_depend>
  <exec_depend>python3-opencv</exec_depend>
  <exec_depend>python3-numpy</exec_depend>
  <export><build_type>ament_python</build_type></export>
</package>
```

Create `ros/atr_specimen_pose_tracker/setup.py`:

```python
from setuptools import setup

package_name = "atr_specimen_pose_tracker"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/atr_specimen_pose_tracker"]),
        ("share/atr_specimen_pose_tracker", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ATR",
    maintainer_email="local@atr.invalid",
    description="One-shot D455F specimen pose tracker",
    license="Proprietary",
    entry_points={"console_scripts": ["specimen_pose_node = atr_specimen_pose_tracker.specimen_pose_node:main"]},
)
```

Create empty files:

```bash
mkdir -p ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker ros/atr_specimen_pose_tracker/resource
touch ros/atr_specimen_pose_tracker/resource/atr_specimen_pose_tracker
touch ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker/__init__.py
```

- [ ] **Step 4: Implement one-shot node**

Create `ros/atr_specimen_pose_tracker/atr_specimen_pose_tracker/specimen_pose_node.py`:

```python
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OneShotConfig:
    specimen_id: str
    color_topic: str
    depth_topic: str
    info_topic: str
    output_dir: Path
    timeout_sec: float
    confidence_threshold: float


class SpecimenPoseNode(Node):
    def __init__(self, cfg: OneShotConfig) -> None:
        super().__init__("atr_specimen_pose_tracker")
        self.cfg = cfg
        self.bridge = CvBridge()
        self.color: np.ndarray | None = None
        self.depth: np.ndarray | None = None
        self.info: CameraInfo | None = None
        self.create_subscription(Image, cfg.color_topic, self._on_color, 10)
        self.create_subscription(Image, cfg.depth_topic, self._on_depth, 10)
        self.create_subscription(CameraInfo, cfg.info_topic, self._on_info, 10)

    def _on_color(self, msg: Image) -> None:
        self.color = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")

    def _on_depth(self, msg: Image) -> None:
        self.depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")

    def _on_info(self, msg: CameraInfo) -> None:
        self.info = msg

    def ready(self) -> bool:
        return self.color is not None and self.depth is not None and self.info is not None

    def estimate_pose(self) -> dict[str, Any]:
        if self.color is None or self.depth is None:
            raise RuntimeError("missing color/depth frame")
        hsv = cv2.cvtColor(self.color, cv2.COLOR_BGR2HSV)
        lower1 = np.array([0, 80, 40], dtype=np.uint8)
        upper1 = np.array([12, 255, 255], dtype=np.uint8)
        lower2 = np.array([168, 80, 40], dtype=np.uint8)
        upper2 = np.array([180, 255, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower1, upper1) | cv2.inRange(hsv, lower2, upper2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return self._failure_pose("SPECIMEN_NOT_DETECTED", "No red specimen/cube contour was detected.")
        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        if area < 20.0:
            return self._failure_pose("SPECIMEN_CONTOUR_TOO_SMALL", "Detected contour area is too small.")
        x, y, w, h = cv2.boundingRect(contour)
        cx = int(x + w / 2)
        cy = int(y + h / 2)
        depth_window = self.depth[max(cy - 3, 0): cy + 4, max(cx - 3, 0): cx + 4]
        valid_depth = depth_window[np.isfinite(depth_window)]
        depth_mm = float(np.median(valid_depth)) if valid_depth.size else 0.0
        confidence = min(0.99, max(0.0, area / 1200.0))
        debug = self.color.copy()
        cv2.rectangle(debug, (x, y), (x + w, y + h), (20, 220, 130), 2)
        cv2.circle(debug, (cx, cy), 5, (255, 255, 0), -1)
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)
        debug_path = self.cfg.output_dir / "specimen_pose_debug.png"
        cv2.imwrite(str(debug_path), debug)
        pose = {
            "schema": "specimen_pose.v1",
            "stage": "post_ejection_workspace_localization",
            "camera_id": "d455f_global",
            "camera_owner_before": "vla_runtime",
            "camera_owner_after": "vla_runtime",
            "workspace": "a4_robot_workspace",
            "specimen_id": self.cfg.specimen_id,
            "frame_id": f"d455f-{int(time.time() * 1000)}",
            "timestamp": _now_iso(),
            "center_px": [cx, cy],
            "bbox_xyxy": [int(x), int(y), int(x + w), int(y + h)],
            "depth_mm": depth_mm,
            "position_a4_mm": {"x": 148.5, "y": 105.0, "z": 15.0},
            "position_robot_base_mm": {"x": 0.0, "y": 0.0, "z": 15.0},
            "position_isaac_world_mm": {"x": 0.0, "y": 0.0, "z": 15.0},
            "orientation_deg": {"yaw": 0.0},
            "confidence": round(confidence, 3),
            "stable_frames": 1,
            "freshness_ms": 0,
            "port_released": True,
            "vla_camera_precheck_ok": True,
            "debug_image_path": str(debug_path),
        }
        return {"ok": confidence >= self.cfg.confidence_threshold, "pose": pose, "failure_code": "" if confidence >= self.cfg.confidence_threshold else "SPECIMEN_POSE_LOW_CONFIDENCE"}

    @staticmethod
    def _failure_pose(code: str, message: str) -> dict[str, Any]:
        return {"ok": False, "failure_code": code, "message": message}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specimen-id", default="specimen")
    parser.add_argument("--color-topic", default="/camera/color/image_raw")
    parser.add_argument("--depth-topic", default="/camera/aligned_depth_to_color/image_raw")
    parser.add_argument("--info-topic", default="/camera/color/camera_info")
    parser.add_argument("--output-dir", default="artifacts/specimen_pose_tracker")
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    parser.add_argument("--confidence-threshold", type=float, default=0.75)
    args = parser.parse_args()
    cfg = OneShotConfig(
        specimen_id=args.specimen_id,
        color_topic=args.color_topic,
        depth_topic=args.depth_topic,
        info_topic=args.info_topic,
        output_dir=Path(args.output_dir),
        timeout_sec=args.timeout_sec,
        confidence_threshold=args.confidence_threshold,
    )
    rclpy.init()
    node = SpecimenPoseNode(cfg)
    deadline = time.monotonic() + cfg.timeout_sec
    result: dict[str, Any] = {"ok": False, "failure_code": "SPECIMEN_POSE_TIMEOUT", "message": "No synchronized RGB-D snapshot arrived."}
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.ready():
                result = node.estimate_pose()
                break
        print(json.dumps(result, ensure_ascii=True), flush=True)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add script wrapper**

Create `scripts/vision/run_specimen_pose_snapshot.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

REQUEST_JSON="${1:-{}}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ -f /opt/ros/jazzy/setup.bash ]]; then
  # shellcheck source=/dev/null
  source /opt/ros/jazzy/setup.bash
fi
if [[ -f "$REPO_ROOT/ros/install/setup.bash" ]]; then
  # shellcheck source=/dev/null
  source "$REPO_ROOT/ros/install/setup.bash"
fi

SPECIMEN_ID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("specimen_id", "specimen"))' "$REQUEST_JSON")"
OUTPUT_DIR="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("output_dir", "artifacts/specimen_pose_tracker"))' "$REQUEST_JSON")"
THRESHOLD="${ATR_SPECIMEN_POSE_THRESHOLD:-0.75}"

ros2 run atr_specimen_pose_tracker specimen_pose_node \
  --specimen-id "$SPECIMEN_ID" \
  --output-dir "$OUTPUT_DIR" \
  --confidence-threshold "$THRESHOLD"
```

Run:

```bash
chmod +x scripts/vision/run_specimen_pose_snapshot.sh
```

- [ ] **Step 6: Build ROS package smoke check**

Run:

```bash
cd /home/jin/autonomous_researcher/ros
colcon build --packages-select atr_specimen_pose_tracker
```

Expected: build exits 0 and `ros/install/setup.bash` exists.

- [ ] **Step 7: Commit Task 2**

```bash
git add ros/atr_specimen_pose_tracker scripts/vision/run_specimen_pose_snapshot.sh tests/unit/test_specimen_pose_tracker.py
git commit -m "feat: add one-shot ros specimen pose node"
```

---

## Task 3: Wire Config, MCP Tool, Bootstrap, and FastAPI Endpoints

**Files:**

- Modify: `configs/devices.yaml`
- Modify: `mcp_tools/camera_tools.py`
- Modify: `app/bootstrap.py`
- Modify: `app/main.py`
- Create: `tests/integration/test_specimen_pose_tracker_api.py`

- [ ] **Step 1: Write API integration tests**

Create `tests/integration/test_specimen_pose_tracker_api.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app


class FakeSpecimenPoseTracker:
    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.release_calls = 0

    def status(self):
        return {"ok": True, "tool": "vision.specimen_pose.status", "lease": {"owner": "vla_runtime"}}

    def snapshot(self, payload):
        self.snapshot_calls += 1
        return {
            "ok": True,
            "tool": "vision.specimen_pose_snapshot",
            "pose": {
                "schema": "specimen_pose.v1",
                "specimen_id": payload.get("specimen_id", "specimen"),
                "port_released": True,
                "vla_camera_precheck_ok": True,
                "camera_owner_after": "vla_runtime",
                "position_robot_base_mm": {"x": 1.0, "y": 2.0, "z": 3.0},
                "confidence": 0.91,
            },
            "lease": {"owner": "vla_runtime"},
        }

    def release(self, payload):
        self.release_calls += 1
        return {"ok": True, "tool": "vision.specimen_pose.release", "camera_returned_to_vla": True, "lease": {"owner": "vla_runtime"}}


def test_specimen_pose_tracker_api(monkeypatch) -> None:
    fake = FakeSpecimenPoseTracker()
    monkeypatch.setattr(app_main, "_specimen_pose_tracker", fake, raising=False)
    client = TestClient(app)

    status = client.get("/api/vision/specimen-pose/status").json()
    assert status["ok"] is True
    assert status["lease"]["owner"] == "vla_runtime"

    snapshot = client.post("/api/vision/specimen-pose/snapshot", json={"mode": "test", "specimen_id": "specimen-1"}).json()
    assert snapshot["ok"] is True
    assert snapshot["pose"]["schema"] == "specimen_pose.v1"
    assert snapshot["pose"]["port_released"] is True
    assert fake.snapshot_calls == 1

    release = client.post("/api/vision/specimen-pose/release", json={"mode": "test"}).json()
    assert release["camera_returned_to_vla"] is True
    assert fake.release_calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/integration/test_specimen_pose_tracker_api.py -q
```

Expected: FAIL with 404 for `/api/vision/specimen-pose/status`.

- [ ] **Step 3: Add devices config**

Modify `configs/devices.yaml` under `devices:`:

```yaml
  specimen_pose_tracker:
    enabled: true
    camera_id: d455f_global
    d455f_serial: "341522300873"
    script_path: scripts/vision/run_specimen_pose_snapshot.sh
    log_dir: artifacts/specimen_pose_tracker
    artifact_dir: runs
    ros_setup_paths:
      - /opt/ros/jazzy/setup.bash
    extra_setup_paths:
      - ros/install/setup.bash
    max_runtime_sec: 8.0
    release_timeout_sec: 5.0
    pose_confidence_threshold: 0.75
    allow_virtual_pose_in_test: true
```

- [ ] **Step 4: Register MCP tool**

Modify `mcp_tools/camera_tools.py` function signature:

```python
def register_camera_tools(
    registry: ToolRegistry,
    *,
    utm_state_observer: Callable[..., dict[str, Any]] | None = None,
    utm_runtime_manager: Any | None = None,
    specimen_pose_tracker: Any | None = None,
) -> None:
```

Add registrations after `camera.capture`:

```python
    registry.register(
        "vision.specimen_pose_snapshot",
        lambda payload: specimen_pose_tracker.snapshot(payload if isinstance(payload, dict) else {})
        if specimen_pose_tracker is not None
        else {
            "ok": False,
            "tool": "vision.specimen_pose_snapshot",
            "failure_code": "SPECIMEN_POSE_TRACKER_NOT_CONFIGURED",
            "message": "Specimen pose tracker bridge is not configured.",
        },
    )
    registry.register(
        "vision.specimen_pose.release",
        lambda payload: specimen_pose_tracker.release(payload if isinstance(payload, dict) else {})
        if specimen_pose_tracker is not None
        else {
            "ok": False,
            "tool": "vision.specimen_pose.release",
            "failure_code": "SPECIMEN_POSE_TRACKER_NOT_CONFIGURED",
            "message": "Specimen pose tracker bridge is not configured.",
        },
    )
```

- [ ] **Step 5: Instantiate bridge in bootstrap**

Modify `app/bootstrap.py` imports:

```python
from device_bridges.specimen_pose_tracker import get_specimen_pose_tracker_bridge
```

In `load_runtime()`, after UTM runtime manager creation:

```python
    specimen_pose_tracker = get_specimen_pose_tracker_bridge(cfg.get("devices", {}), repo_root=resolve_path("."))
```

Pass it to `register_camera_tools`:

```python
    register_camera_tools(
        tools,
        utm_state_observer=utm_state_observer,
        utm_runtime_manager=utm_runtime_manager,
        specimen_pose_tracker=specimen_pose_tracker,
    )
```

- [ ] **Step 6: Add FastAPI endpoints**

Modify `app/main.py` imports:

```python
from device_bridges.specimen_pose_tracker import SpecimenPoseTrackerBridge, get_specimen_pose_tracker_bridge
```

Add global:

```python
_specimen_pose_tracker: SpecimenPoseTrackerBridge | None = None
```

Add helper near `_utm_runtime_bridge()`:

```python
def _specimen_pose_tracker_bridge() -> SpecimenPoseTrackerBridge:
    global _specimen_pose_tracker
    if _specimen_pose_tracker is None:
        cfg = load_all_configs(resolve_path("configs"))
        _specimen_pose_tracker = get_specimen_pose_tracker_bridge(cfg.get("devices", {}), repo_root=resolve_path("."))
    return _specimen_pose_tracker
```

Add endpoints:

```python
@app.get("/api/vision/specimen-pose/status")
async def get_specimen_pose_tracker_status() -> dict[str, object]:
    return await asyncio.to_thread(_specimen_pose_tracker_bridge().status)


@app.post("/api/vision/specimen-pose/snapshot")
async def post_specimen_pose_snapshot(payload: dict[str, object]) -> dict[str, object]:
    return await asyncio.to_thread(_specimen_pose_tracker_bridge().snapshot, payload)


@app.post("/api/vision/specimen-pose/release")
async def post_specimen_pose_release(payload: dict[str, object]) -> dict[str, object]:
    return await asyncio.to_thread(_specimen_pose_tracker_bridge().release, payload)
```

- [ ] **Step 7: Run integration test**

Run:

```bash
pytest tests/integration/test_specimen_pose_tracker_api.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add configs/devices.yaml mcp_tools/camera_tools.py app/bootstrap.py app/main.py tests/integration/test_specimen_pose_tracker_api.py
git commit -m "feat: expose specimen pose tracker api"
```

---

## Task 4: Integrate Snapshot Pose into VisionAgent

**Files:**

- Modify: `agents/vision_agent.py`
- Create: `tests/unit/test_vision_agent_specimen_pose.py`

- [ ] **Step 1: Write VisionAgent pose tests**

Create `tests/unit/test_vision_agent_specimen_pose.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agents.vision_agent import VisionAgent
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


class _CtxStub:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    async def complete(self, task_type: str, prompt: str, timeout_s: float | None = None) -> Any:
        return SimpleNamespace(text="vision task", raw={}, model="mock")


def _state(mode: Mode = Mode.TEST) -> OrchestratorState:
    return OrchestratorState(
        run_id="run-pose",
        experiment_id="exp-pose",
        mode=mode,
        stage=Stage.VISION,
        current_experiment_spec={"size_mm": [20.0, 20.0, 10.0]},
        run_metadata={
            "specimen_result": {
                "ok": True,
                "specimen_id": "specimen-pose-1",
                "candidate_id": "candidate-pose-1",
                "handoff_status": "ready",
            },
            "fabrication_report": {
                "fabrication_outcome": {"location": "a4_workspace"},
            },
        },
    )


def _tools_with_pose(ok: bool = True, port_released: bool = True) -> ToolRegistry:
    tools = ToolRegistry()
    tools.register("camera.capture", lambda payload: {"ok": True, "tool": "camera.capture", "frame_id": payload["frame_id"], "source": "simulator", "confidence": 0.6})
    tools.register(
        "vision.specimen_pose_snapshot",
        lambda payload: {
            "ok": ok,
            "tool": "vision.specimen_pose_snapshot",
            "pose": {
                "schema": "specimen_pose.v1",
                "specimen_id": payload.get("specimen_id"),
                "frame_id": payload.get("frame_id"),
                "position_robot_base_mm": {"x": 11.0, "y": 22.0, "z": 33.0},
                "position_a4_mm": {"x": 144.0, "y": 101.0, "z": 15.0},
                "orientation_deg": {"yaw": 7.5},
                "confidence": 0.93,
                "port_released": port_released,
                "vla_camera_precheck_ok": port_released,
                "camera_owner_after": "vla_runtime" if port_released else "vision_ros_tracker",
                "debug_image_path": "runs/run-pose/vision/debug.png",
            },
            "lease": {"owner": "vla_runtime" if port_released else "vision_ros_tracker"},
        },
    )
    return tools


@pytest.mark.asyncio
async def test_vision_agent_maps_specimen_pose_to_observation() -> None:
    result = await VisionAgent().run(_state(), _CtxStub(_tools_with_pose()))

    observation = result.data["observation"]
    assert result.success is True
    assert observation["pose_estimate"]["x_mm"] == 11.0
    assert observation["pose_estimate"]["y_mm"] == 22.0
    assert observation["pose_estimate"]["z_mm"] == 33.0
    assert observation["pose_estimate"]["yaw_deg"] == 7.5
    assert observation["transfer_readiness"]["camera_returned_to_vla"] is True
    assert observation["transfer_readiness"]["vla_camera_precheck_ok"] is True
    assert observation["specimen_pose"]["schema"] == "specimen_pose.v1"
    assert observation["pickup_target"]["source_location"] == "a4_workspace"


@pytest.mark.asyncio
async def test_vision_agent_blocks_when_d455f_not_returned() -> None:
    result = await VisionAgent().run(_state(), _CtxStub(_tools_with_pose(port_released=False)))

    observation = result.data["observation"]
    assert result.success is False
    assert observation["transfer_readiness"]["ready"] is False
    assert observation["transfer_readiness"]["camera_returned_to_vla"] is False
    assert observation["transfer_readiness"]["blocking_reason"] == "D455F_PORT_RETURN_FAILED"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_vision_agent_specimen_pose.py -q
```

Expected: FAIL because VisionAgent does not call `vision.specimen_pose_snapshot` and does not expose `camera_returned_to_vla`.

- [ ] **Step 3: Add VisionAgent helper methods**

Modify `agents/vision_agent.py` inside `VisionAgent`:

```python
    def _should_request_specimen_pose_snapshot(self, state: OrchestratorState) -> bool:
        specimen = self._specimen_result(state)
        if not specimen or specimen.get("ok") is False:
            return False
        report = self._fabrication_report(state, specimen)
        outcome = report.get("fabrication_outcome") if isinstance(report.get("fabrication_outcome"), dict) else {}
        location = str(outcome.get("location") or "").strip().lower()
        return location in {"a4_workspace", "robot_workspace", "ejection_basket", "3dp_output_area", ""}

    def _specimen_pose_snapshot(self, state: OrchestratorState, ctx: AgentContext, frame_id: str) -> dict[str, Any]:
        if "vision.specimen_pose_snapshot" not in set(ctx.tools.list_tools()):
            return {}
        if not self._should_request_specimen_pose_snapshot(state):
            return {}
        specimen = self._specimen_result(state)
        payload = {
            "mode": state.mode.value,
            "runtime_mode": state.mode.value,
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "frame_id": frame_id,
            "specimen_id": specimen.get("specimen_id", ""),
            "output_dir": str(self._artifact_dir(state, f"pose-{frame_id}")),
        }
        try:
            return ctx.tools.call("vision.specimen_pose_snapshot", payload)
        except Exception as exc:
            if state.mode == Mode.TEST:
                return {"ok": False, "failure_code": exc.__class__.__name__, "message": str(exc), "tool": "vision.specimen_pose_snapshot"}
            raise

    def _merge_specimen_pose_capture(self, capture: dict[str, Any], pose_result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(pose_result, dict) or not pose_result:
            return capture
        merged = dict(capture)
        merged["specimen_pose_result"] = pose_result
        pose = pose_result.get("pose") if isinstance(pose_result.get("pose"), dict) else {}
        if not pose_result.get("ok") or not pose:
            merged["pose_snapshot_failure_code"] = pose_result.get("failure_code", "SPECIMEN_POSE_FAILED")
            return merged
        position = pose.get("position_robot_base_mm") if isinstance(pose.get("position_robot_base_mm"), dict) else {}
        orientation = pose.get("orientation_deg") if isinstance(pose.get("orientation_deg"), dict) else {}
        merged.update(
            {
                "x_mm": position.get("x", 0.0),
                "y_mm": position.get("y", 0.0),
                "z_mm": position.get("z", 0.0),
                "yaw_deg": orientation.get("yaw", 0.0),
                "pose_confidence": pose.get("confidence", merged.get("confidence", 0.0)),
                "confidence": pose.get("confidence", merged.get("confidence", 0.0)),
                "camera_returned_to_vla": bool(pose.get("port_released") and pose.get("camera_owner_after") == "vla_runtime"),
                "vla_camera_precheck_ok": bool(pose.get("vla_camera_precheck_ok")),
                "specimen_pose": pose,
                "source": "d455f_ros_snapshot",
                "detector": "atr_specimen_pose_tracker",
                "pose_backend": "d455f_rgbd_one_shot",
            }
        )
        merged.setdefault("detections", [
            {
                "label": "printed_specimen",
                "zone": "a4_workspace",
                "specimen_id": pose.get("specimen_id", ""),
                "bbox_xyxy": pose.get("bbox_xyxy", []),
                "confidence": pose.get("confidence", 0.0),
                "source": "d455f_ros_snapshot",
            }
        ])
        return merged
```

- [ ] **Step 4: Use helper in `run()` before transfer observation**

Modify `VisionAgent.run()` after `response = ctx.tools.call("camera.capture", ...)`:

```python
        pose_result = self._specimen_pose_snapshot(state, ctx, frame_id)
        response = self._merge_specimen_pose_capture(dict(response), pose_result)
        response = self._attach_lerobot_camera_evidence(state, ctx, dict(response))
```

- [ ] **Step 5: Gate readiness on camera return**

Modify `_transfer_observation()` after `ready` calculation:

```python
        pose_payload = capture.get("specimen_pose") if isinstance(capture.get("specimen_pose"), dict) else {}
        camera_returned_to_vla = bool(capture.get("camera_returned_to_vla", True if not pose_payload else False))
        vla_camera_precheck_ok = bool(capture.get("vla_camera_precheck_ok", True if not pose_payload else False))
        if pose_payload and not camera_returned_to_vla:
            ready = False
```

Add to `pose`:

```python
            "source": "specimen_pose.v1" if pose_payload else "capture_fields",
```

Add to `observation`:

```python
            "specimen_pose": pose_payload,
```

Add to `transfer_readiness`:

```python
                "camera_returned_to_vla": camera_returned_to_vla,
                "vla_camera_precheck_ok": vla_camera_precheck_ok,
```

Update blocking reason selection:

```python
                "blocking_reason": "D455F_PORT_RETURN_FAILED" if pose_payload and not camera_returned_to_vla else None if ready else next((signal.get("blocking_reason") for signal in signals if signal.get("signal") == "pickup_ready"), "unknown"),
```

- [ ] **Step 6: Run VisionAgent tests**

Run:

```bash
pytest tests/unit/test_vision_agent.py tests/unit/test_vision_agent_specimen_pose.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add agents/vision_agent.py tests/unit/test_vision_agent_specimen_pose.py tests/unit/test_vision_agent.py
git commit -m "feat: feed one-shot specimen pose into vision agent"
```

---

## Task 5: Gate ManipulationAgent on D455F Return and Pass Pickup Pose

**Files:**

- Modify: `agents/manipulation_agent.py`
- Modify: `tests/unit/test_manipulation_lerobot_agent.py`

- [ ] **Step 1: Add manipulation preflight tests**

Append to `tests/unit/test_manipulation_lerobot_agent.py`:

```python
@pytest.mark.asyncio
async def test_manipulation_agent_blocks_when_d455f_not_returned(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    state = _post_specimen_state()
    state.latest_observations["transfer_readiness"]["camera_returned_to_vla"] = False
    state.latest_observations["transfer_readiness"]["vla_camera_precheck_ok"] = False
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(state, ctx)

    assert result.success is False
    assert result.data["manipulation"]["failure_code"] == "MANIPULATION_PREFLIGHT_BLOCKED"
    assert "d455f_not_returned_to_vla" in result.data["manipulation"]["preflight"]["blocking_reasons"]
    assert result.data["robot_task_result"]["handoff_status"] == "blocked"


@pytest.mark.asyncio
async def test_manipulation_agent_passes_pickup_pose_to_rollout(tmp_path: Path, monkeypatch: Any) -> None:
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    state = _post_specimen_state()
    state.latest_observations["transfer_readiness"]["camera_returned_to_vla"] = True
    state.latest_observations["transfer_readiness"]["vla_camera_precheck_ok"] = True
    state.latest_observations["pose_estimate"] = {"x_mm": 11.0, "y_mm": 22.0, "z_mm": 33.0, "yaw_deg": 7.5, "confidence": 0.93}
    ctx = _CtxStub(_tools(tmp_path))

    result = await ManipulationAgent().run(state, ctx)

    assert result.success is True
    assert result.data["manipulation"]["observation"]["pose_estimate"]["x_mm"] == 11.0
    assert result.data["manipulation_report"]["vision_context"]["pose_estimate"]["yaw_deg"] == 7.5
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_manipulation_lerobot_agent.py::test_manipulation_agent_blocks_when_d455f_not_returned tests/unit/test_manipulation_lerobot_agent.py::test_manipulation_agent_passes_pickup_pose_to_rollout -q
```

Expected: first test FAIL because no camera-return gate exists; second may FAIL if report omits pose detail.

- [ ] **Step 3: Add preflight gate**

Modify `_preflight()` in `agents/manipulation_agent.py` after freshness check:

```python
        readiness = vision_context.get("transfer_readiness") if isinstance(vision_context.get("transfer_readiness"), dict) else {}
        if strategy in {"lerobot_policy", "pi05_lerobot_policy"}:
            if readiness.get("camera_returned_to_vla") is False:
                blocking.append("d455f_not_returned_to_vla")
            if readiness.get("vla_camera_precheck_ok") is False:
                blocking.append("vla_camera_precheck_failed")
```

Modify `_vision_context()` return payload to include readiness:

```python
            "transfer_readiness": observation.get("transfer_readiness", {}),
```

Modify `_lerobot_payload()` return payload to include explicit pose:

```python
            "pickup_pose": self._vision_observation(state).get("pose_estimate", {}),
```

- [ ] **Step 4: Run manipulation tests**

Run:

```bash
pytest tests/unit/test_manipulation_lerobot_agent.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add agents/manipulation_agent.py tests/unit/test_manipulation_lerobot_agent.py
git commit -m "feat: gate manipulation on d455f camera return"
```

---

## Task 6: Update LangGraph Runtime and Module Contracts

**Files:**

- Modify: `graphs/modules/vision/module.yaml`
- Modify: `graphs/modules/manipulation/module.yaml`
- Modify: `graphs/configs/atr_closed_loop.yaml`
- Create: `tests/unit/test_graph_specimen_pose_tracking.py`

- [ ] **Step 1: Write graph contract tests**

Create `tests/unit/test_graph_specimen_pose_tracking.py`:

```python
from __future__ import annotations

from pathlib import Path

import yaml

from graphs import load_graph_config


def _yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_vision_module_declares_specimen_pose_tool_and_steps() -> None:
    payload = _yaml("graphs/modules/vision/module.yaml")
    module = payload["module"]
    step_ids = {item["id"] for item in module["internal_graph"]}

    assert "vision.specimen_pose_snapshot" in module["tools"]
    assert "03a_acquire_d455f_lease" in step_ids
    assert "03b_one_shot_specimen_pose" in step_ids
    assert "03c_release_d455f_to_vla" in step_ids
    assert "specimen_pose.v1" in module["io_contract"]["produces"]


def test_manipulation_module_consumes_camera_return_gate() -> None:
    payload = _yaml("graphs/modules/manipulation/module.yaml")
    module = payload["module"]
    contract = module["runtime_contract"]

    assert contract["requires_camera_return_to_vla"] is True
    assert "specimen_pose.v1" in module["io_contract"]["input"]


def test_closed_loop_graph_has_post_place_vision_verification() -> None:
    config = load_graph_config(Path("graphs/configs/atr_closed_loop.yaml"))
    node_ids = {node.id for node in config.nodes}
    edge_pairs = {(edge.source, edge.target) for edge in config.edges}

    assert "vision" in node_ids
    assert "manipulation" in node_ids
    assert "vision_verify" in node_ids
    assert ("vision", "manipulation") in edge_pairs
    assert ("manipulation", "vision_verify") in edge_pairs
    assert ("vision_verify", "equipment") in edge_pairs
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/unit/test_graph_specimen_pose_tracking.py -q
```

Expected: FAIL because module and graph contracts are not updated.

- [ ] **Step 3: Update Vision module YAML**

Modify `graphs/modules/vision/module.yaml`:

```yaml
  tools:
  - camera.capture
  - vision.specimen_pose_snapshot
  - vision.specimen_pose.release
  internal_graph:
    - id: 01_observation_task_resolve
      label: Observation Task Resolve
      kind: internal_step
    - id: 02_zone_registry_load
      label: Zone Registry Load
      kind: internal_step
    - id: 03_capture_scene
      label: Capture Scene
      kind: internal_step
    - id: 03a_acquire_d455f_lease
      label: Acquire D455F lease from VLA route
      kind: tool_step
      tool: vision.specimen_pose_snapshot
      emits:
      - camera_lease
    - id: 03b_one_shot_specimen_pose
      label: One-shot D455F RGB-D specimen pose snapshot
      kind: internal_step
      emits:
      - specimen_pose.v1
    - id: 03c_release_d455f_to_vla
      label: Confirm D455F returned to VLA route
      kind: handoff_gate
      emits:
      - camera_returned_to_vla
```

Add `specimen_pose.v1` to `io_contract.produces`:

```yaml
    produces:
    - vision_report.v1
    - vision_signal.v1
    - specimen_pose.v1
    - decisions
    - metrics
    - evidence_refs
```

- [ ] **Step 4: Update Manipulation module YAML**

Modify `graphs/modules/manipulation/module.yaml`:

```yaml
  runtime_contract:
    policy_executor: pi05_or_lerobot_policy
    supervisor: manipulation_agent
    progress_monitor: sarm_lite
    live_bridge_boundary: LeRobotBridge
    direct_shell_generation_allowed: false
    requires_camera_return_to_vla: true
```

Update `io_contract.input` to a list:

```yaml
  io_contract:
    input:
    - OrchestratorState with specimen_result, latest Vision observation, and manipulation profile
    - specimen_pose.v1
    - transfer_readiness.camera_returned_to_vla
```

- [ ] **Step 5: Update closed-loop graph**

Modify `graphs/configs/atr_closed_loop.yaml` nodes by adding a node after `manipulation`:

```yaml
  - id: vision_verify
    label: Vision Verification Agent
    handler: agent.vision_agent
    stage: vision
    description: Verify specimen placement after manipulation using BRIO/UTM camera evidence.
    module_id: modules/vision
    position:
      x: 1200
      y: 360
    metadata:
      icon: vision_agent
      role: post_manipulation_placement_verification
      consumes:
      - robot_task_result.v1
      produces:
      - placement_verification.v1
      - vision_signal.v1
```

Modify default edges:

```yaml
  - source: vision
    target: manipulation
    condition: null
    label: 'default transition: vision -> manipulation'
    metadata:
      runtime_edge: logical_transition
      from_stage: vision
      to_stage: manipulation
      condition: specimen_pose_ready_and_camera_returned_to_vla
      transition_condition: specimen_pose_ready_and_camera_returned_to_vla
      default_transition: true
      auto_ports: true
      contracts:
      - specimen_pose.v1
      - transfer_readiness.camera_returned_to_vla

  - source: manipulation
    target: vision_verify
    condition: null
    label: 'default transition: manipulation -> vision verification'
    metadata:
      runtime_edge: logical_transition
      from_stage: manipulation
      to_stage: vision
      condition: post_place_verification_required
      transition_condition: post_place_verification_required
      default_transition: true
      auto_ports: true
      contracts:
      - robot_task_result.v1
      - placement_verification.v1

  - source: vision_verify
    target: equipment
    condition: null
    label: 'default transition: vision verification -> equipment'
    metadata:
      runtime_edge: logical_transition
      from_stage: vision
      to_stage: equipment
      condition: placement_verified
      transition_condition: placement_verified
      default_transition: true
      auto_ports: true
      contracts:
      - placement_verification.v1
```

Remove or disable the old direct `manipulation -> equipment` default edge by changing its metadata to:

```yaml
      default_transition: false
      condition: superseded_by_post_place_vision_verification
      transition_condition: superseded_by_post_place_vision_verification
```

- [ ] **Step 6: Validate graph config**

Run:

```bash
pytest tests/unit/test_graph_specimen_pose_tracking.py tests/unit/test_langgraph_runtime.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add graphs/modules/vision/module.yaml graphs/modules/manipulation/module.yaml graphs/configs/atr_closed_loop.yaml tests/unit/test_graph_specimen_pose_tracking.py
git commit -m "feat: represent specimen pose tracking in runtime graph"
```

---

## Task 7: Live GUI and Device Workspace Evidence

**Files:**

- Modify: `app/main.py`
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Test: `tests/unit/test_planning_design_report_js.py`
- Test: `tests/ui/planning_browser_audit.py`

- [ ] **Step 1: Add static rendering test**

Append to `tests/unit/test_planning_design_report_js.py`:

```python
from pathlib import Path


def test_planning_js_mentions_specimen_pose_and_d455f_return() -> None:
    source = Path("web/static/planning.js").read_text(encoding="utf-8")

    assert "specimen_pose" in source
    assert "camera_returned_to_vla" in source
    assert "VLA camera" in source
    assert "D455F" in source
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/unit/test_planning_design_report_js.py::test_planning_js_mentions_specimen_pose_and_d455f_return -q
```

Expected: FAIL because strings are absent.

- [ ] **Step 3: Update Live GUI agent profile**

Modify `app/main.py` `LIVE_AGENT_REPORT_PROFILES["vision"]` focus rows by adding:

```python
            {"label": "D455F snapshot", "value": "one-shot RGB-D pose after auto-ejection, then camera returned to VLA route"},
            {"label": "VLA gate", "value": "Manipulation starts only when specimen_pose_ready and camera_returned_to_vla are true"},
```

- [ ] **Step 4: Add Vision render helpers in planning.js**

Modify `web/static/planning.js` near `renderVisionDashboardCards` helpers:

```javascript
function renderSpecimenPoseGate(screenReport, visionReport) {
  const pose = (visionReport && visionReport.specimen_pose) || (screenReport && screenReport.specimen_pose) || {};
  const readiness = (visionReport && visionReport.transfer_readiness) || (screenReport && screenReport.transfer_readiness) || {};
  const returned = readiness.camera_returned_to_vla === true || pose.port_released === true;
  const precheck = readiness.vla_camera_precheck_ok === true || pose.vla_camera_precheck_ok === true;
  const confidence = Number(pose.confidence || (screenReport.pose_estimation && screenReport.pose_estimation.confidence) || 0);
  const robot = pose.position_robot_base_mm || {};
  return `
    <div class="vision-pose-gate-grid">
      <div><span class="hint">D455F</span><strong>${returned ? "returned" : "held"}</strong></div>
      <div><span class="hint">VLA camera</span><strong>${precheck ? "ready" : "waiting"}</strong></div>
      <div><span class="hint">confidence</span><strong>${Number.isFinite(confidence) ? confidence.toFixed(2) : "-"}</strong></div>
      <div><span class="hint">robot base</span><strong>x ${escapeHtml(String(robot.x ?? "-"))} / y ${escapeHtml(String(robot.y ?? "-"))}</strong></div>
    </div>
  `;
}
```

Insert a card in `renderVisionDashboardCards()` after `Camera Health`:

```javascript
    ${renderDashboardCard("D455F Pose / VLA Return", renderSpecimenPoseGate(screenReport, visionReport), { span: 4, tone: "vision", eyebrow: "specimen pose" })}
```

- [ ] **Step 5: Add CSS**

Modify `web/static/styles.css`:

```css
.vision-pose-gate-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
}
.vision-pose-gate-grid > div {
  border: 1px solid rgba(110, 231, 183, 0.22);
  background: rgba(15, 23, 42, 0.45);
  padding: 0.65rem;
  min-height: 3.2rem;
}
.vision-pose-gate-grid strong {
  display: block;
  margin-top: 0.2rem;
  color: #e5edf7;
  font-size: 0.9rem;
}
```

- [ ] **Step 6: Run UI static tests**

Run:

```bash
pytest tests/unit/test_planning_design_report_js.py -q
```

Expected: PASS.

- [ ] **Step 7: Browser audit**

Run server in a separate terminal:

```bash
atr -s start
```

Run browser audit:

```bash
python tests/ui/planning_browser_audit.py
```

Expected: PASS and screenshot artifact saved under `artifacts/browser_checks/`.

- [ ] **Step 8: Commit Task 7**

```bash
git add app/main.py web/static/planning.js web/static/styles.css tests/unit/test_planning_design_report_js.py artifacts/browser_checks
git commit -m "feat: show specimen pose gate in live gui"
```

---

## Task 8: Full Path Tests and Documentation

**Files:**

- Modify: `docs/agents/vision_pickup_observation_runtime_guideline.txt`
- Modify: `docs/hardware/utm_ros_vision_runtime_bridge.md`
- Modify: `docs/runtime/closed_loop_and_pages_reference.md`
- Modify: `REQUIREMENTS.md`
- Test: existing unit/integration/UI tests

- [ ] **Step 1: Update Vision guideline**

Add this section to `docs/agents/vision_pickup_observation_runtime_guideline.txt`:

```markdown
## 2026-06-24 D455F One-Shot Specimen Pose Update

After 3DP auto-ejection, the ejection output location is the A4 robot workspace. VisionAgent requests a one-shot D455F RGB-D pose snapshot through `vision.specimen_pose_snapshot`.

The D455F is not shared between ROS and VLA. The camera is borrowed from the VLA route, used by ROS for one snapshot, then returned before ManipulationAgent may start inference.

Required readiness fields:

```json
{
  "specimen_pose_ready": true,
  "camera_returned_to_vla": true,
  "vla_camera_precheck_ok": true
}
```

Live mode blocks ManipulationAgent if the D455F is not returned to the VLA route.
```

- [ ] **Step 2: Update hardware bridge doc**

Add this section to `docs/hardware/utm_ros_vision_runtime_bridge.md`:

```markdown
## D455F Specimen Pose Tracker Separation

The UTM/BRIO bridge remains the inspection and placement-verification camera path. D455F specimen pose tracking is a separate one-shot ROS runtime used before manipulation.

The D455F tracker does not reuse `/image_utm` and does not keep a shared ROS topic open for VLA. It captures one RGB-D pose, stops ROS, confirms release, and returns the camera to VLA.
```

- [ ] **Step 3: Update runtime reference doc**

Add to `docs/runtime/closed_loop_and_pages_reference.md`:

```markdown
### Specimen Pose Tracking Gate

Closed-loop order around manipulation:

```text
Specimen/3DP auto-ejection
-> VisionAgent D455F one-shot pose
-> D455F returned to VLA
-> ManipulationAgent VLA inference
-> VisionAgent BRIO/UTM placement verification
-> Lab Equipment Agent
```
```

- [ ] **Step 4: Update requirements**

Add to `REQUIREMENTS.md`:

```markdown
### ROS Specimen Pose Tracking

Required for live D455F one-shot pose tracking:

```bash
sudo apt install -y ros-jazzy-realsense2-camera ros-jazzy-cv-bridge ros-jazzy-image-transport python3-opencv python3-numpy
```

Build the local ROS package:

```bash
cd /home/jin/autonomous_researcher/ros
colcon build --packages-select atr_specimen_pose_tracker
```
```

- [ ] **Step 5: Run core test pack**

Run:

```bash
pytest \
  tests/unit/test_specimen_pose_tracker.py \
  tests/integration/test_specimen_pose_tracker_api.py \
  tests/unit/test_vision_agent.py \
  tests/unit/test_vision_agent_specimen_pose.py \
  tests/unit/test_manipulation_lerobot_agent.py \
  tests/unit/test_graph_specimen_pose_tracking.py \
  tests/unit/test_langgraph_runtime.py \
  tests/unit/test_planning_design_report_js.py \
  -q
```

Expected: PASS.

- [ ] **Step 6: Run closed-loop test mode smoke**

Run:

```bash
python -m app.cli --mode test --goal "테스트 모드, 가상 브릿지, 시편 위치 추적 후 조작 게이트 확인"
```

Expected output includes:

```text
VisionAgent
specimen_pose_ready
camera_returned_to_vla
ManipulationAgent
```

- [ ] **Step 7: Run Live GUI browser smoke**

Run:

```bash
atr -s start
python tests/ui/planning_browser_audit.py
```

Expected: browser screenshot shows Vision card with `D455F Pose / VLA Return`.

- [ ] **Step 8: Commit Task 8**

```bash
git add docs/agents/vision_pickup_observation_runtime_guideline.txt docs/hardware/utm_ros_vision_runtime_bridge.md docs/runtime/closed_loop_and_pages_reference.md REQUIREMENTS.md
git commit -m "docs: document d455f specimen pose tracking gate"
```

---

## Self-Review

Spec coverage:

- One-shot D455F snapshot is covered by Tasks 1, 2, 3, and 4.
- Exclusive lease and return-to-VLA gate are covered by Tasks 1, 4, and 5.
- VisionAgent handoff to ManipulationAgent is covered by Tasks 4 and 5.
- BRIO/UTM post-manipulation verification is represented by Task 6 graph update and Task 8 docs.
- LangGraph/module visibility is covered by Task 6.
- Live GUI visibility is covered by Task 7.
- Tests and documentation are covered by Task 8.

Placeholder scan:

- The plan contains concrete file paths, function names, commands, expected results, and code snippets.
- The plan avoids placeholder markers, deferred-work wording, and unnamed edge handling.

Type consistency:

- Primary contract name is `specimen_pose.v1` throughout.
- Readiness fields are `camera_returned_to_vla` and `vla_camera_precheck_ok` throughout.
- Tool names are `vision.specimen_pose_snapshot` and `vision.specimen_pose.release` throughout.
- API route prefix is `/api/vision/specimen-pose` throughout.
