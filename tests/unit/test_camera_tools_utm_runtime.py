"""Tests for UTM-backed vision.equipment_cross_check tool behavior."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from mcp_tools.camera_tools import register_camera_tools
from mcp_tools.tool_registry import ToolRegistry


class FakeRuntimeManager:
    def __init__(self, *, probe: dict[str, Any] | None = None, frame: dict[str, Any] | None = None) -> None:
        self.start_calls = 0
        self.probe_calls = 0
        self.frame_calls = 0
        self.raw_frame_calls = 0
        self._probe = probe or {"ok": True, "diagnostics": {"ros2_available": True, "topic_seen": True}}
        self._frame = frame or {
            "ok": False,
            "frame_available": False,
            "failure_code": "ROS_IMAGE_FRAME_UNAVAILABLE",
        }

    def start(self) -> dict[str, Any]:
        self.start_calls += 1
        return {"ok": True, "status": "running", "pid": 1234}

    def status(self) -> dict[str, Any]:
        return {"ok": True, "status": "running", "pid": 1234}

    def stop(self) -> dict[str, Any]:
        return {"ok": True, "status": "stopped", "was_running": True}

    def probe(self) -> dict[str, Any]:
        self.probe_calls += 1
        return dict(self._probe)

    def frame(self) -> dict[str, Any]:
        self.frame_calls += 1
        return dict(self._frame)

    def raw_frame(self) -> dict[str, Any]:
        self.raw_frame_calls += 1
        return dict(self._frame)


def _red_specimen_frame(*, topic: str = "/camera/image_raw") -> dict[str, Any]:
    image = np.full((120, 180, 3), 215, dtype=np.uint8)
    image[30:100, 65:130] = [230, 20, 25]
    buffer = BytesIO()
    Image.fromarray(image, mode="RGB").save(buffer, format="JPEG", quality=95)
    return {
        "ok": True,
        "frame_available": True,
        "frame_id": "utm-frame-tool-1",
        "topic": topic,
        "width": 180,
        "height": 120,
        "data_url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
    }


def test_live_utm_motion_check_uses_observer_and_runtime_manager() -> None:
    calls = []

    def fake_observer(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "ok": True,
            "duration_sec": 5.0,
            "sample_count": 20,
            "valid_sample_count": 20,
            "working_count": 16,
            "not_working_count": 4,
            "initial_state": "NOT_WORKING",
            "final_state": "WORKING",
            "transition": "NOT_WORKING_TO_WORKING",
            "stable_state": "",
            "span_y_delta": 95.0,
        }

    manager = FakeRuntimeManager()
    registry = ToolRegistry()
    register_camera_tools(registry, utm_state_observer=fake_observer, utm_runtime_manager=manager)

    result = registry.call(
        "vision.equipment_cross_check",
        {
            "runtime_mode": "live",
            "checks": [
                {
                    "task_id": "utm_motion_confirm",
                    "check_id": "utm_motion_confirm",
                    "device": "utm",
                    "run_id": "run-identity",
                    "loop_id": 4,
                    "specimen_id": "specimen-identity",
                    "producer_agent": "equipment_agent",
                    "consumer_agent": "vision_agent",
                }
            ],
            "duration_sec": 5.0,
            "sample_interval_sec": 0.2,
            "minimum_samples": 8,
        },
    )

    assert manager.start_calls == 1
    assert manager.probe_calls == 1
    assert calls == [{"duration_sec": 5.0, "sample_interval_sec": 0.2, "minimum_samples": 8}]
    assert result["ok"] is True
    assert result["observer_mode"] == "ros_topic"
    assert result["runtime_status"]["status"] == "running"
    assert result["results"][0]["status"] == "verified"
    assert result["results"][0]["evidence"]["transition"] == "NOT_WORKING_TO_WORKING"
    assert result["results"][0]["task_id"] == "utm_motion_confirm"
    assert result["results"][0]["run_id"] == "run-identity"
    assert result["results"][0]["loop_id"] == 4
    assert result["results"][0]["specimen_id"] == "specimen-identity"
    assert result["results"][0]["producer_agent"] == "vision_agent"
    assert result["results"][0]["consumer_agent"] == "equipment_agent"


def test_live_utm_passive_verification_matches_state_and_motion_direction() -> None:
    observations = iter(
        [
            {
                "ok": True,
                "sample_count": 8,
                "valid_sample_count": 8,
                "final_state": "WORKING",
                "stable_state": "WORKING",
                "transition": "STABLE_WORKING",
                "motion_direction": "STABLE",
            },
            {
                "ok": True,
                "sample_count": 8,
                "valid_sample_count": 8,
                "final_state": "NOT_WORKING",
                "stable_state": "",
                "transition": "WORKING_TO_NOT_WORKING",
                "motion_direction": "DOWN",
            },
        ]
    )
    registry = ToolRegistry()
    register_camera_tools(
        registry,
        utm_state_observer=lambda **_kwargs: next(observations),
        utm_runtime_manager=FakeRuntimeManager(),
    )

    working = registry.call(
        "vision.equipment_cross_check",
        {"runtime_mode": "live", "checks": [{"task_id": "utm_state_working", "check_id": "utm_state_working", "device": "utm"}]},
    )
    down = registry.call(
        "vision.equipment_cross_check",
        {"runtime_mode": "live", "checks": [{"task_id": "utm_motion_down", "check_id": "utm_motion_down", "device": "utm"}]},
    )

    assert working["ok"] is True
    assert working["results"][0]["verification_label"] == "WORKING"
    assert down["ok"] is True
    assert down["results"][0]["verification_label"] == "DOWN"


def test_live_utm_passive_verification_reports_mismatch_without_relabeling_it() -> None:
    registry = ToolRegistry()
    register_camera_tools(
        registry,
        utm_state_observer=lambda **_kwargs: {
            "ok": True,
            "sample_count": 8,
            "valid_sample_count": 8,
            "final_state": "NOT_WORKING",
            "transition": "WORKING_TO_NOT_WORKING",
            "motion_direction": "UP",
        },
        utm_runtime_manager=FakeRuntimeManager(),
    )

    result = registry.call(
        "vision.equipment_cross_check",
        {"runtime_mode": "live", "checks": [{"task_id": "utm_motion_down", "check_id": "utm_motion_down", "device": "utm"}]},
    )

    assert result["ok"] is False
    assert result["results"][0]["verification_label"] == "DOWN"
    assert result["results"][0]["failure_code"] == "UTM_EXPECTED_VISION_RESULT_MISMATCH"


def test_camera_tools_register_vision_utm_runtime_controls() -> None:
    manager = FakeRuntimeManager()
    registry = ToolRegistry()
    register_camera_tools(registry, utm_runtime_manager=manager)

    assert "vision.utm_runtime.start" in registry.list_tools()
    assert "vision.utm_runtime.status" in registry.list_tools()
    assert "vision.utm_runtime.stop" in registry.list_tools()

    start = registry.call("vision.utm_runtime.start", {"source": "test"})
    status = registry.call("vision.utm_runtime.status", {})
    stop = registry.call("vision.utm_runtime.stop", {})

    assert manager.start_calls == 1
    assert start["status"] == "running"
    assert status["status"] == "running"
    assert stop["status"] == "stopped"


def test_utm_specimen_presence_captures_exactly_one_runtime_frame(tmp_path: Path) -> None:
    manager = FakeRuntimeManager(frame=_red_specimen_frame())
    registry = ToolRegistry()
    register_camera_tools(registry, utm_runtime_manager=manager)

    result = registry.call(
        "vision.utm_specimen_presence.capture",
        {
            "runtime_mode": "live",
            "auto_start_runtime": True,
            "run_id": "run-1",
            "session_id": "rollout-1",
            "specimen_id": "specimen-1",
            "output_dir": str(tmp_path / "evidence"),
            "min_area_px": 300,
        },
    )

    assert manager.start_calls == 1
    assert manager.raw_frame_calls == 1
    assert manager.frame_calls == 0
    assert result["ok"] is True
    assert result["detected"] is True
    assert result["source"] == "utm_ros_raw_frame"
    assert result["run_id"] == "run-1"
    assert result["session_id"] == "rollout-1"
    assert Path(result["annotated_frame_path"]).is_file()


def test_utm_specimen_presence_retries_transient_ros_frame_failure(tmp_path: Path) -> None:
    class SequencedRuntimeManager(FakeRuntimeManager):
        def __init__(self) -> None:
            super().__init__()
            self._frames = [
                {
                    "ok": False,
                    "frame_available": False,
                    "failure_code": "ROS_IMAGE_FRAME_UNAVAILABLE",
                },
                _red_specimen_frame(),
            ]

        def raw_frame(self) -> dict[str, Any]:
            self.raw_frame_calls += 1
            return dict(self._frames[min(self.raw_frame_calls - 1, len(self._frames) - 1)])

    manager = SequencedRuntimeManager()
    registry = ToolRegistry()
    register_camera_tools(registry, utm_runtime_manager=manager)

    result = registry.call(
        "vision.utm_specimen_presence.capture",
        {
            "runtime_mode": "live",
            "output_dir": str(tmp_path),
            "frame_attempts": 3,
            "frame_retry_delay_sec": 0,
        },
    )

    assert manager.raw_frame_calls == 2
    assert manager.frame_calls == 0
    assert result["ok"] is True
    assert result["detected"] is True
    assert result["frame_attempt_count"] == 2


def test_live_utm_specimen_presence_fails_closed_without_frame(tmp_path: Path) -> None:
    manager = FakeRuntimeManager()
    registry = ToolRegistry()
    register_camera_tools(registry, utm_runtime_manager=manager)

    result = registry.call(
        "vision.utm_specimen_presence.capture",
        {
            "runtime_mode": "live",
            "output_dir": str(tmp_path),
            "allow_virtual_bridge_in_test": True,
        },
    )

    assert manager.raw_frame_calls == 1
    assert manager.frame_calls == 0
    assert result["ok"] is False
    assert result["detected"] is False
    assert result["virtualized"] is False
    assert result["failure_code"] == "ROS_IMAGE_FRAME_UNAVAILABLE"


def test_test_utm_specimen_presence_virtualizes_only_when_explicitly_allowed(tmp_path: Path) -> None:
    manager = FakeRuntimeManager()
    registry = ToolRegistry()
    register_camera_tools(registry, utm_runtime_manager=manager)

    result = registry.call(
        "vision.utm_specimen_presence.capture",
        {
            "runtime_mode": "test",
            "output_dir": str(tmp_path),
            "run_id": "virtual-run",
            "session_id": "virtual-rollout",
            "specimen_id": "virtual-specimen",
            "allow_virtual_bridge_in_test": True,
        },
    )

    assert manager.raw_frame_calls == 1
    assert manager.frame_calls == 0
    assert result["ok"] is True
    assert result["detected"] is True
    assert result["virtualized"] is True
    assert result["source"] == "virtual_utm_bridge"


def test_test_utm_specimen_presence_prefers_virtual_bridge_when_explicitly_requested(tmp_path: Path) -> None:
    manager = FakeRuntimeManager(frame=_red_specimen_frame())
    registry = ToolRegistry()
    register_camera_tools(registry, utm_runtime_manager=manager)

    result = registry.call(
        "vision.utm_specimen_presence.capture",
        {
            "runtime_mode": "test",
            "output_dir": str(tmp_path),
            "allow_virtual_bridge_in_test": True,
            "prefer_virtual_bridge_in_test": True,
        },
    )

    assert manager.raw_frame_calls == 0
    assert result["ok"] is True
    assert result["detected"] is True
    assert result["virtualized"] is True
    assert result["source"] == "virtual_utm_bridge"


def test_test_mode_falls_back_to_virtual_utm_bridge_with_visible_trace() -> None:
    def unavailable_observer(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("ROS topic timeout")

    manager = FakeRuntimeManager(probe={"ok": False, "failure_code": "ROS2_NOT_INSTALLED", "diagnostics": {"ros2_available": False}})
    registry = ToolRegistry()
    register_camera_tools(registry, utm_state_observer=unavailable_observer, utm_runtime_manager=manager)

    result = registry.call(
        "vision.equipment_cross_check",
        {
            "runtime_mode": "test",
            "checks": [{"check_id": "utm_motion_confirm", "device": "utm"}],
            "allow_virtual_bridge_in_test": True,
        },
    )

    assert result["ok"] is True
    assert result["observer_mode"] == "virtual_utm_bridge"
    assert result["virtualized"] is True
    assert result["fallback_trace"]["event_type"] == "utm.runtime.fallback"
    assert result["fallback_trace"]["reason_code"] in {"ROS2_NOT_INSTALLED", "TOPIC_TIMEOUT"}
    assert "virtual UTM bridge" in result["fallback_trace"]["message"]
    assert result["results"][0]["status"] == "verified"
    assert result["results"][0]["source"] == "virtual_utm_bridge"


def test_live_mode_does_not_virtualize_missing_utm_evidence() -> None:
    def insufficient_observer(**kwargs: Any) -> dict[str, Any]:
        return {
            "ok": False,
            "failure_code": "UTM_INSUFFICIENT_TEMPORAL_EVIDENCE",
            "sample_count": 1,
            "valid_sample_count": 1,
            "transition": "INSUFFICIENT_EVIDENCE",
        }

    registry = ToolRegistry()
    register_camera_tools(registry, utm_state_observer=insufficient_observer, utm_runtime_manager=FakeRuntimeManager())

    result = registry.call(
        "vision.equipment_cross_check",
        {"runtime_mode": "live", "checks": [{"check_id": "utm_motion_confirm", "device": "utm"}]},
    )

    assert result["ok"] is False
    assert result["observer_mode"] == "ros_topic"
    assert result["virtualized"] is False
    assert result["failure_code"] == "UTM_INSUFFICIENT_TEMPORAL_EVIDENCE"
    assert result["operator_attention"]["status"] == "attention_required"
    assert result["results"][0]["status"] == "attention_required"


def test_non_utm_check_keeps_existing_simulator_behavior() -> None:
    calls = []

    def fake_observer(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"ok": True}

    registry = ToolRegistry()
    register_camera_tools(registry, utm_state_observer=fake_observer)

    result = registry.call(
        "vision.equipment_cross_check",
        {"runtime_mode": "test", "checks": [{"check_id": "robot_clear", "device": "robot"}]},
    )

    assert calls == []
    assert result["ok"] is True
    assert result["observer_mode"] == "simulator"
    assert result["results"][0]["source"] == "simulator"
