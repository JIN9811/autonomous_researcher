"""Tests for UTM-backed vision.equipment_cross_check tool behavior."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from mcp_tools.camera_tools import register_camera_tools
from mcp_tools.tool_registry import ToolRegistry


@pytest.mark.parametrize("check_id,expected_duration,expected_ok", [
    ("utm_motion_down", 10.0, True), ("utm_state_not_working", 10.0, False),
    ("utm_state_working", 3.0, True),
])
def test_quasistatic_check_duration_preserves_state_requirements(check_id, expected_duration, expected_ok):
    from device_bridges.camera_vision.utm_state_observer import summarize_utm_state_sequence
    calls = []

    def observer(**kwargs):
        calls.append(kwargs)
        samples = [{"state": "WORKING", "point_count": 4,
                    "span_y": 95 - 0.4 * (i + 0.5) / 100} for i in range(100)]
        result = summarize_utm_state_sequence(samples)
        result["duration_sec"] = kwargs["duration_sec"]
        return result

    registry = ToolRegistry()
    register_camera_tools(registry, utm_state_observer=observer)
    result = registry.call("vision.equipment_cross_check", {
        "runtime_mode": "live", "duration_sec": 3.0,
        "checks": [{"check_id": check_id, "device": "utm"}],
    })
    assert calls[0]["duration_sec"] == expected_duration
    assert result["ok"] is expected_ok


@pytest.mark.parametrize("state,drift,expected_ok,direction", [
    ("WORKING", 0.4, False, "UP"),
    ("NOT_WORKING", 0.4, True, "UP"),
    ("NOT_WORKING", 0.0, True, "STABLE"),
])
def test_return_motion_is_not_a_substitute_for_final_clearance_state(state, drift, expected_ok, direction):
    from device_bridges.camera_vision.utm_state_observer import summarize_utm_state_sequence

    def observer(**kwargs):
        assert kwargs["duration_sec"] == 10.0
        result = summarize_utm_state_sequence([
            {"state": state, "point_count": 4, "span_y": 280 + drift * (i + 0.5) / 100}
            for i in range(100)])
        result["duration_sec"] = kwargs["duration_sec"]
        return result

    registry = ToolRegistry()
    register_camera_tools(registry, utm_state_observer=observer)
    result = registry.call("vision.equipment_cross_check", {
        "runtime_mode": "live", "checks": [{"check_id": "utm_state_not_working", "device": "utm"}],
    })
    assert result["ok"] is expected_ok
    assert result["results"][0]["evidence"]["motion_direction"] == direction


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

    def _run_ros_frame_command(self, command, *, timeout_sec):
        import json
        # The ROS observation publishes already-resolved pixel bounds.
        return 0, json.dumps({"enabled": True, "x_min": 50, "y_min": 0,
            "x_max": 115, "y_max": 120}), ""


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
    assert calls == [{"duration_sec": 10.0, "sample_interval_sec": 0.2, "minimum_samples": 8}]
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


def test_placement_uses_live_observation_roi_and_ignores_larger_red_outside(tmp_path):
    from mcp_tools.camera_tools import _utm_specimen_presence_capture
    arr = np.full((120, 180, 3), 160, dtype=np.uint8)
    arr[10:115, 5:45] = [230, 20, 25]
    arr[50:80, 70:95] = [230, 20, 25]
    stream = BytesIO()
    Image.fromarray(arr).save(stream, format="PNG")
    frame = {**_red_specimen_frame(), "data_url": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()}
    manager = FakeRuntimeManager(frame=frame)
    payload = {"runtime_mode": "live", "output_dir": str(tmp_path), "roi_normalized": [0, 0, 1, 1]}
    result = _utm_specimen_presence_capture(payload, utm_runtime_manager=manager)
    assert result["roi_xyxy"] == [50, 0, 115, 120]
    assert result["bbox_xyxy"] == [70, 50, 95, 80]
    manager._run_ros_frame_command = lambda *args, **kwargs: (1, "", "unavailable")
    result = _utm_specimen_presence_capture(payload, utm_runtime_manager=manager)
    assert result["ok"] is False and result["detected"] is False
    assert result["failure_code"] == "UTM_OBSERVATION_ROI_UNAVAILABLE"


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


def test_live_utm_check_stamps_evidence_at_last_fresh_sample_not_request_start() -> None:
    import time as _time
    from datetime import datetime, timedelta, timezone

    started = datetime.now(timezone.utc)
    sample_times: list[datetime] = []

    def slow_observer(**_kwargs: Any) -> dict[str, Any]:
        # Runtime start/probe already happened; the sampling window itself
        # runs now, so fresh samples are stamped after the request arrived.
        for _ in range(3):
            _time.sleep(0.02)
            sample_times.append(datetime.now(timezone.utc))
        return {
            "ok": True,
            "duration_sec": 3.0,
            "sample_count": 3,
            "valid_sample_count": 3,
            "working_count": 0,
            "not_working_count": 3,
            "initial_state": "NOT_WORKING",
            "final_state": "NOT_WORKING",
            "transition": "STABLE_NOT_WORKING",
            "stable_state": "NOT_WORKING",
            "motion_direction": "STABLE",
            "samples": [
                {"state": "NOT_WORKING", "timestamp": stamp.isoformat(), "summary_fresh": True}
                for stamp in sample_times
            ]
            # A stale/future or non-fresh sample must never move the stamp.
            + [{"state": "UNKNOWN", "timestamp": (started + timedelta(seconds=30)).isoformat(), "summary_fresh": True}]
            + [{"state": "UNKNOWN", "timestamp": (started + timedelta(seconds=1)).isoformat(), "summary_fresh": False}],
        }

    registry = ToolRegistry()
    register_camera_tools(registry, utm_state_observer=slow_observer, utm_runtime_manager=FakeRuntimeManager())
    result = registry.call(
        "vision.equipment_cross_check",
        {
            "runtime_mode": "live",
            "checks": [{"task_id": "utm_state_not_working", "check_id": "utm_state_not_working", "device": "utm"}],
            "duration_sec": 3.0,
            "freshness_ttl_ms": 5000,
        },
    )

    item = result["results"][0]
    assert item["ok"] is True
    assert item["status"] == "verified"
    assert item["freshness_ttl_ms"] == 5000
    # Stamped at the last fresh sample, not at request start.
    assert datetime.fromisoformat(item["timestamp"]) == sample_times[-1]
    assert datetime.fromisoformat(item["expires_at"]) == sample_times[-1] + timedelta(milliseconds=5000)
    request_started_at = datetime.fromisoformat(item["request_started_at"])
    assert started <= request_started_at < sample_times[0]


def test_live_utm_check_without_sample_timestamps_stamps_after_observation() -> None:
    from datetime import datetime, timezone

    def observer(**_kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "sample_count": 20,
            "valid_sample_count": 20,
            "working_count": 20,
            "not_working_count": 0,
            "initial_state": "WORKING",
            "final_state": "WORKING",
            "transition": "STABLE_WORKING",
            "stable_state": "WORKING",
            "motion_direction": "STABLE",
        }

    registry = ToolRegistry()
    register_camera_tools(registry, utm_state_observer=observer, utm_runtime_manager=FakeRuntimeManager())
    before = datetime.now(timezone.utc)
    result = registry.call(
        "vision.equipment_cross_check",
        {"runtime_mode": "live", "checks": [{"task_id": "utm_state_working", "check_id": "utm_state_working", "device": "utm"}]},
    )
    item = result["results"][0]
    assert item["ok"] is True
    assert item["freshness_ttl_ms"] == 5000
    assert datetime.fromisoformat(item["timestamp"]) >= before
    assert datetime.fromisoformat(item["request_started_at"]) <= datetime.fromisoformat(item["timestamp"])
