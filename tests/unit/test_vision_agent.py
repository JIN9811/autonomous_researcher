"""Unit tests for VisionAgent pickup observation contract."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agents.vision_agent import VisionAgent
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


class _CtxStub:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    async def complete(self, task_type: str, prompt: str, timeout_s: float | None = None) -> Any:
        return SimpleNamespace(text="capture top camera and estimate pickup readiness", raw={}, model="mock-e4b")


def _state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-vision",
        experiment_id="exp-vision",
        mode=Mode.TEST,
        stage=Stage.VISION,
        current_experiment_spec={"size_mm": [20.0, 20.0, 10.0]},
        run_metadata={
            "specimen_result": {
                "ok": True,
                "specimen_id": "specimen-001",
                "candidate_id": "candidate-001",
                "handoff_status": "ready",
                "stl_path": "runs/specimen-001.stl",
                "sliced_path": "runs/specimen-001.gcode",
            }
        },
    )


@pytest.mark.asyncio
async def test_vision_agent_returns_pickup_observation() -> None:
    tools = ToolRegistry()
    register_mock_tools(tools)
    result = await VisionAgent().run(_state(), _CtxStub(tools))

    observation = result.data["observation"]
    assert result.success is True
    assert observation["transfer_readiness"]["ready"] is True
    assert observation["pickup_target"]["specimen_id"] == "specimen-001"
    assert observation["pickup_target"]["source_location"] == "3dp_output_area"
    assert observation["pickup_target"]["target_location"] == "utm_fixture"
    assert observation["pose_estimate"]["confidence"] >= 0.8
    assert observation["vision_report"]["schema"] == "vision_report.v1"
    assert observation["vision_report"]["task"] == "post_ejection_basket_check"
    assert observation["vision_report"]["zones"]["ejection_basket"]["specimen_present"] is True
    assert observation["vision_report"]["signal_board"]
    pickup_signal = next(item for item in observation["vision_report"]["signal_board"] if item["signal"] == "pickup_ready")
    assert pickup_signal["status"] == "ready"
    assert pickup_signal["expires_at"]
    assert all(item["run_id"] == "run-vision" for item in observation["vision_report"]["signal_board"])
    assert all(item["experiment_id"] == "exp-vision" for item in observation["vision_report"]["signal_board"])
    assert all(item["specimen_id"] == "specimen-001" for item in observation["vision_report"]["signal_board"])
    assert result.data["vision_signal"]["schema"] == "vision_signal.v1"
    assert result.data["vision_signal"]["signal_id"] == pickup_signal["signal_id"]
    screen_report = result.data["vision_agent_report"]
    expected_sections = {
        "camera_health",
        "calibration_summary",
        "confidence_distribution",
        "inspection_feed",
        "segmentation",
        "defect_summary",
        "pose_estimation",
        "confusion_matrix",
        "quality_metrics",
        "evidence_review",
        "handoff_recommendations",
    }
    assert screen_report["schema"] == "vision_agent_report.v1"
    assert screen_report["source_report_id"] == observation["vision_report"]["report_id"]
    assert expected_sections.issubset(screen_report)
    assert screen_report["camera_health"]["status"] == "ready"
    assert screen_report["confidence_distribution"]["histogram"]
    assert screen_report["segmentation"]["panels"]
    assert screen_report["pose_estimation"]["ready"] is True
    assert screen_report["handoff_recommendations"]["status"] == "ready"
    assert observation["vision_agent_report"] == screen_report
    assert {item["type"] for item in screen_report["visualization_manifest"]} >= {
        "image_overlays",
        "histogram",
        "calibration_line_chart",
        "segmentation_panels",
        "confusion_matrix",
    }
    assert result.data["vision_signal"]["consumer_agents"] == [
        "equipment_agent",
        "guardian_agent",
        "knowledge_agent",
        "manipulation_agent",
        "specimen_agent",
    ]
    signal_names = {item["signal"] for item in observation["vision_report"]["signal_board"]}
    assert {
        "printer_output_visible",
        "specimen_ejected_to_basket",
        "basket_contains_specimen",
        "pickup_ready",
        "basket_empty_after_pick",
        "gripper_holding_specimen",
        "specimen_on_utm_platen",
        "fixture_alignment_ok",
        "utm_motion_observed",
        "utm_home_restored",
        "equipment_screen_state",
        "visual_test_evidence_ready",
        "data_quality_low",
        "anomaly_detected",
    }.issubset(signal_names)
    event_names = {item["event_type"] for item in observation["vision_report"]["events"]}
    assert {"printer_bed_clear", "specimen_ejected_to_basket", "basket_contains_specimen"}.issubset(event_names)
    assert result.data["handoff_packet"]["schema"] == "vision_signal.v1"
    assert result.data["metrics"]["signal_count"] >= 14
    assert result.data["decisions"]
    assert any(ref["type"] == "detection_json" for ref in result.data["evidence_refs"])
    assert observation["vision_report"]["artifacts"]["detection_json_path"]



@pytest.mark.asyncio
async def test_vision_agent_blocks_stale_risk_when_camera_fails() -> None:
    class _FailingTools(ToolRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.register("camera.capture", lambda payload: {
                "ok": False,
                "tool": "camera.capture",
                "frame_id": payload.get("frame_id", "frame-fail"),
                "camera_key": "top",
                "source": "simulator",
                "anomaly": True,
                "confidence": 0.0,
            })

    tools = _FailingTools()
    result = await VisionAgent().run(_state(), _CtxStub(tools))

    observation = result.data["observation"]
    assert result.success is False
    assert observation["transfer_readiness"]["ready"] is False
    assert observation["transfer_readiness"]["blocking_reason"] in {"camera_capture_failed", "anomaly_detected", "specimen_or_pose_not_ready"}
    assert result.data["vision_signal"]["status"] in {"warning", "blocked"}
    assert result.data["vision_agent_report"]["schema"] == "vision_agent_report.v1"
    assert result.data["vision_agent_report"]["camera_health"]["status"] == "review_required"
    assert result.data["vision_agent_report"]["defect_summary"]["anomaly"] is True
    assert result.data["vision_agent_report"]["handoff_recommendations"]["status"] in {"warning", "blocked"}
    assert result.data["vision_report"]["safety_anomaly"]["anomaly"] is True
    assert any(signal["signal"] == "anomaly_detected" for signal in result.data["vision_report"]["signal_board"])
