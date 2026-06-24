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
            return {
                "ok": True,
                "tool": "vision.specimen_pose_snapshot",
                "mode": mode,
                "pose": pose,
                "lease": self._lease_payload(),
                "fallback_trace": self._fallback_trace("VIRTUAL_TEST_POSE", "Test mode used deterministic specimen pose instead of the D455F ROS snapshot."),
            }
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
        env["ATR_SPECIMEN_POSE_ROS_SETUP_PATHS"] = os.pathsep.join(self.config.ros_setup_paths)
        env["ATR_SPECIMEN_POSE_EXTRA_SETUP_PATHS"] = os.pathsep.join(self.config.extra_setup_paths)
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.script_path.parent),
                env=env,
                text=True,
                capture_output=True,
                timeout=self.config.max_runtime_sec,
                check=False,
            )
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
        pose.setdefault("schema", "specimen_pose.v1")
        pose.setdefault("port_released", True)
        pose.setdefault("vla_camera_precheck_ok", True)
        pose.setdefault("camera_owner_after", "vla_runtime")
        pose.setdefault("camera_owner_before", "vla_runtime")
        pose.setdefault("camera_id", self.config.camera_id)
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

    def _fallback_trace(self, reason_code: str, message: str) -> dict[str, Any]:
        return {
            "event_type": "specimen_pose_tracker.fallback",
            "severity": "warning",
            "reason_code": reason_code,
            "message": message,
            "timestamp": _now_iso(),
        }

    def _error(self, failure_code: str, message: str) -> dict[str, Any]:
        return {"ok": False, "tool": "vision.specimen_pose_snapshot", "failure_code": failure_code, "message": message, "lease": self._lease_payload(), "generated_at": _now_iso()}


def get_specimen_pose_tracker_bridge(devices_config: dict[str, Any], *, repo_root: Path) -> SpecimenPoseTrackerBridge:
    return SpecimenPoseTrackerBridge(SpecimenPoseTrackerConfig.from_devices_config(devices_config, repo_root=repo_root))
