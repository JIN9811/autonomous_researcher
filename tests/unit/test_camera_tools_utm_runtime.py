"""Tests for UTM-backed vision.equipment_cross_check tool behavior."""

from __future__ import annotations

from typing import Any

from mcp_tools.camera_tools import register_camera_tools
from mcp_tools.tool_registry import ToolRegistry


class FakeRuntimeManager:
    def __init__(self, *, probe: dict[str, Any] | None = None) -> None:
        self.start_calls = 0
        self.probe_calls = 0
        self._probe = probe or {"ok": True, "diagnostics": {"ros2_available": True, "topic_seen": True}}

    def start(self) -> dict[str, Any]:
        self.start_calls += 1
        return {"ok": True, "status": "running", "pid": 1234}

    def status(self) -> dict[str, Any]:
        return {"ok": True, "status": "running", "pid": 1234}

    def probe(self) -> dict[str, Any]:
        self.probe_calls += 1
        return dict(self._probe)


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
            "checks": [{"check_id": "utm_motion_confirm", "device": "utm"}],
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
