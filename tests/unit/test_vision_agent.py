"""Unit tests for VisionAgent pickup observation contract."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agents.vision_agent import VisionAgent
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage
from policies.guardian_gate import gate_blocks_execution, guardian_gate


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


def test_active_cam_capture_is_copied_into_current_vision_run_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    source = tmp_path / "camera-runtime" / "frame.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"active-cam-frame")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))

    artifact = VisionAgent()._persist_active_cam_run_artifact(
        state=state,
        observation_id="frame-1-vision",
        active_check={
            "status": "confirmed",
            "spc_autoejection_confirmed": True,
            "capture_path": str(source),
            "camera_key": "wrist",
            "frame_width": 640,
            "frame_height": 480,
            "specimen_id": "specimen-1",
        },
    )

    stored = Path(artifact["path"])
    assert artifact["status"] == "stored"
    assert stored.is_file()
    assert stored.parent == tmp_path / "runs" / state.run_id / "vision" / "frame-1-vision"
    assert stored.read_bytes() == b"active-cam-frame"
    assert artifact["url"].startswith(f"/api/runs/{state.run_id}/artifact-file/vision/")


def test_active_cam_missing_source_returns_failed_update_without_deleting_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    prior = tmp_path / "runs" / state.run_id / "vision" / "frame-1-vision" / "active_cam_capture_prior.jpg"
    prior.parent.mkdir(parents=True)
    prior.write_bytes(b"prior")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))

    artifact = VisionAgent()._persist_active_cam_run_artifact(
        state=state,
        observation_id="frame-2-vision",
        active_check={
            "status": "confirmed",
            "spc_autoejection_confirmed": True,
            "capture_path": str(tmp_path / "missing.jpg"),
        },
    )

    assert artifact["status"] == "failed"
    assert artifact.get("path", "") == ""
    assert prior.read_bytes() == b"prior"


def test_blocked_active_cam_attempt_never_becomes_current_run_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    source = tmp_path / "camera-runtime" / "blocked.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"blocked-frame")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))

    artifact = VisionAgent()._persist_active_cam_run_artifact(
        state=state,
        observation_id="frame-2-vision",
        active_check={
            "status": "blocked",
            "spc_autoejection_confirmed": False,
            "capture_path": str(source),
        },
    )

    assert artifact["status"] == "failed"
    assert artifact["failure_code"] == "ACTIVE_CAM_ATTEMPT_FAILED"
    assert artifact.get("path", "") == ""


def test_transfer_observation_publishes_active_cam_run_artifact_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    source = tmp_path / "camera-runtime" / "confirmed.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"confirmed-frame")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))

    payload = VisionAgent()._transfer_observation(
        state,
        {
            "ok": True,
            "frame_id": "frame-confirmed",
            "camera_key": "top",
            "confidence": 0.9,
            "spc_autoejection_confirmation": {"confirmed": True},
            "active_cam_ejection_check": {
                "status": "confirmed",
                "spc_autoejection_confirmed": True,
                "specimen_detected": True,
                "capture_path": str(source),
                "capture_url": "/transient/frame.png",
                "camera_key": "wrist",
                "frame_width": 640,
                "frame_height": 480,
                "port_released": True,
                "camera_returned_to_vla": True,
            },
        },
    )

    update = payload["active_cam_artifact_update"]
    active = payload["vision_agent_report"]["active_cam_ejection_check"]
    artifacts = payload["vision_report"]["artifacts"]
    assert update["status"] == "stored"
    assert active["capture_path"] == update["path"]
    assert active["capture_url"] == update["url"]
    assert active["run_artifact"] == update
    assert artifacts["active_cam_run_artifact"] == update
    assert {ref["type"] for ref in payload["evidence_refs"]} >= {"active_cam_capture", "active_cam_run_artifact"}
    assert payload["observation"]["spc_autoejection_confirmation"]["capture_path"] == update["path"]
    assert payload["observation"]["spc_autoejection_confirmation"]["capture_url"] == update["url"]


def test_transfer_observation_failed_active_cam_attempt_clears_display_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    source = tmp_path / "camera-runtime" / "blocked.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"blocked-frame")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))

    payload = VisionAgent()._transfer_observation(
        state,
        {
            "ok": True,
            "frame_id": "frame-blocked",
            "camera_key": "top",
            "confidence": 0.9,
            "active_cam_ejection_check": {
                "status": "blocked",
                "spc_autoejection_confirmed": False,
                "specimen_detected": True,
                "capture_path": str(source),
                "capture_url": "/transient/blocked.png",
                "camera_key": "wrist",
                "port_released": True,
                "camera_returned_to_vla": True,
            },
        },
    )

    update = payload["active_cam_artifact_update"]
    active = payload["vision_agent_report"]["active_cam_ejection_check"]
    assert update["status"] == "failed"
    assert active["capture_path"] == ""
    assert active["capture_url"] == ""
    assert payload["observation"]["spc_autoejection_confirmation"]["confirmed"] is False
    assert payload["observation"]["spc_autoejection_confirmation"]["status"] == "blocked"


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
        "agentic_progress",
    }
    assert screen_report["schema"] == "vision_agent_report.v1"
    assert screen_report["source_report_id"] == observation["vision_report"]["report_id"]
    assert expected_sections.issubset(screen_report)
    assert screen_report["camera_health"]["status"] == "ready"
    assert screen_report["confidence_distribution"]["histogram"]
    assert screen_report["segmentation"]["panels"]
    assert screen_report["pose_estimation"]["ready"] is True
    assert screen_report["handoff_recommendations"]["status"] == "ready"
    progress = screen_report["agentic_progress"]
    assert progress["schema"] == "vision_agentic_progress.v1"
    assert [step["id"] for step in progress["steps"]] == ["capture", "specimen_pose", "camera_release", "active_cam", "handoff"]
    assert {step["status"] for step in progress["steps"]} == {"complete"}
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
async def test_post_disposal_vision_keeps_existing_generic_observation_path() -> None:
    tools = ToolRegistry()
    capture_calls: list[dict[str, Any]] = []
    utm_calls: list[dict[str, Any]] = []
    tools.register(
        "camera.capture",
        lambda payload: capture_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": payload["camera_key"],
            "purpose": payload["purpose"],
            "source": "generic_post_disposal_observation",
            "confidence": 0.9,
            "pose_confidence": 0.9,
        },
    )
    tools.register(
        "vision.utm_specimen_presence.capture",
        lambda payload: utm_calls.append(dict(payload or {})) or {
            "ok": True,
            "detected": True,
        },
    )
    state = _state()
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "session_id": "lr-rollout-disposal-001",
        "handoff_status": "needs_post_disposal_vision",
        "completion_status": "reported_complete",
    }
    state.run_metadata["robot_task_result"] = {
        "schema": "robot_task_result.v1",
        "rollout_session_id": "lr-rollout-disposal-001",
        "handoff_status": "needs_post_disposal_vision",
        "completion_status": "reported_complete",
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert result.success is True
    assert len(capture_calls) == 1
    assert capture_calls[0]["purpose"] == "3dp_output_pickup_check"
    assert utm_calls == []
    assert result.data["observation"]["vision_report"]["task"] != "post_manipulation_utm_verification"


@pytest.mark.asyncio
async def test_vision_agent_verifies_utm_placement_after_manipulation(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    tools = ToolRegistry()
    capture_calls: list[dict[str, Any]] = []
    utm_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    annotated_frame = tmp_path / "incoming" / "utm-confirmed.png"
    annotated_frame.parent.mkdir(parents=True)
    annotated_frame.write_bytes(b"utm-confirmed")
    tools.register(
        "camera.capture",
        lambda payload: capture_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": payload["camera_key"],
            "purpose": payload["purpose"],
            "source": "utm_camera",
            "confidence": 0.91,
            "pose_confidence": 0.91,
        },
    )
    tools.register(
        "vision.utm_specimen_presence.capture",
        lambda payload: utm_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "vision.utm_specimen_presence.capture",
            "schema": "vision_utm_specimen_presence.v1",
            "status": "confirmed",
            "detected": True,
            "source": "utm_ros_frame",
            "frame_id": payload["frame_id"],
            "confidence": 0.91,
            "bbox_xyxy": [20, 30, 90, 110],
            "annotated_frame_path": str(annotated_frame),
            "raw_frame_path": str(annotated_frame),
            "width": 160,
            "height": 120,
            "session_id": payload["session_id"],
            "specimen_id": payload["specimen_id"],
        },
    )
    state = _state()
    interlock = {
        "schema": "post_place_interlock.v1",
        "session_id": "lr-rollout-utm-001",
        "ungrasping_seen": True,
        "home_after_ungrasping": True,
        "ready_for_utm_snapshot": True,
    }
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "session_id": "lr-rollout-utm-001",
        "workflow": "rollout",
        "runtime_phase": "ACTION_ACTIVE",
        "action_count": 30,
        "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete",
        "post_place_interlock": interlock,
    }
    state.run_metadata["robot_task_result"] = {
        "schema": "robot_task_result.v1",
        "rollout_session_id": "lr-rollout-utm-001",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete",
        "post_place_interlock": interlock,
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert result.success is True
    assert capture_calls == []
    assert len(utm_calls) == 1
    assert utm_calls[0]["session_id"] == "lr-rollout-utm-001"
    observation = result.data["observation"]
    assert observation["vision_report"]["task"] == "post_manipulation_utm_verification"
    assert observation["vision_report"]["zones"]["utm_platen"]["specimen_present"] is True
    assert observation["vision_report"]["zones"]["utm_platen"]["aligned"] is True
    completion = observation["vision_manipulation_completion"]
    assert completion["schema"] == "vision_manipulation_completion.v1"
    assert completion["detected"] is True
    assert completion["ready_to_stop_rollout"] is True
    assert completion["session_id"] == "lr-rollout-utm-001"
    artifact = result.data["utm_completion_artifact_update"]
    assert artifact["schema"] == "utm_completion_run_artifact.v1"
    assert artifact["status"] == "stored"
    assert artifact["run_id"] == state.run_id
    assert artifact["session_id"] == "lr-rollout-utm-001"
    assert artifact["specimen_id"] == state.run_metadata["specimen_result"]["specimen_id"]
    assert Path(artifact["path"]).read_bytes() == b"utm-confirmed"
    assert completion["evidence_path"] == artifact["path"]
    screen_report = result.data["vision_agent_report"]
    assert screen_report["utm_completion_confirmation"]["detected"] is True
    assert screen_report["utm_completion_confirmation"]["run_artifact"]["path"] == artifact["path"]
    utm_step = next(
        step
        for step in screen_report["agentic_progress"]["steps"]
        if step["id"] == "utm_confirmation"
    )
    assert utm_step["status"] == "complete"
    assert result.data["requested_next_stage"] == "manipulation"
    assert result.data["transition_decision"] == "vision_manipulation_completion"
    gate = guardian_gate(state=state, stage="vision", phase="post", agent="vision_agent", payload=result.data)
    assert gate_blocks_execution(gate) is False
    signal = next(item for item in observation["agent_signals"] if item["signal"] == "vision_manipulation_completion")
    assert signal["status"] == "detected"
    assert signal["target_agent"] == "manipulation_agent"


@pytest.mark.asyncio
async def test_vision_agent_utm_not_detected_emits_failed_attempt_and_keeps_rollout_active(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    tools = ToolRegistry()
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    annotated_frame = tmp_path / "incoming" / "utm-empty.png"
    annotated_frame.parent.mkdir(parents=True)
    annotated_frame.write_bytes(b"utm-empty")
    tools.register(
        "vision.utm_specimen_presence.capture",
        lambda payload: {
            "ok": True,
            "tool": "vision.utm_specimen_presence.capture",
            "schema": "vision_utm_specimen_presence.v1",
            "status": "not_detected",
            "detected": False,
            "source": "utm_ros_frame",
            "frame_id": payload["frame_id"],
            "annotated_frame_path": str(annotated_frame),
            "raw_frame_path": str(annotated_frame),
            "confidence": 0.0,
            "width": 160,
            "height": 120,
            "session_id": payload["session_id"],
            "specimen_id": payload["specimen_id"],
        },
    )
    state = _state()
    interlock = {
        "schema": "post_place_interlock.v1",
        "session_id": "lr-rollout-utm-empty",
        "ungrasping_seen": True,
        "home_after_ungrasping": True,
        "ready_for_utm_snapshot": True,
    }
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "session_id": "lr-rollout-utm-empty",
        "workflow": "rollout",
        "runtime_phase": "ACTION_ACTIVE",
        "action_count": 30,
        "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete",
        "post_place_interlock": interlock,
    }
    state.run_metadata["robot_task_result"] = {
        "schema": "robot_task_result.v1",
        "rollout_session_id": "lr-rollout-utm-empty",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete",
        "post_place_interlock": interlock,
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert result.success is True
    completion = result.data["observation"]["vision_manipulation_completion"]
    assert completion["detected"] is False
    assert completion["ready_to_stop_rollout"] is False
    assert completion["blocking_reason"] == "specimen_not_detected_on_utm"
    assert result.data["requested_next_stage"] == "manipulation"
    assert result.data["transition_decision"] == "vision_manipulation_monitoring"
    artifact = result.data["utm_completion_artifact_update"]
    assert artifact["status"] == "not_detected"
    assert artifact["session_id"] == "lr-rollout-utm-empty"
    assert artifact["specimen_id"] == state.run_metadata["specimen_result"]["specimen_id"]
    screen_report = result.data["vision_agent_report"]
    assert screen_report["utm_completion_confirmation"]["detected"] is False
    utm_step = next(
        step
        for step in screen_report["agentic_progress"]["steps"]
        if step["id"] == "utm_confirmation"
    )
    assert utm_step["status"] == "waiting"


@pytest.mark.asyncio
async def test_vision_agent_does_not_capture_utm_before_measured_post_place_gate() -> None:
    tools = ToolRegistry()
    capture_calls: list[dict[str, Any]] = []
    tools.register(
        "camera.capture",
        lambda payload: capture_calls.append(dict(payload))
        or (_ for _ in ()).throw(AssertionError("generic camera capture must not run while the post-place gate is closed")),
    )
    state = _state()
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "workflow": "rollout",
        "session_id": "lr-rollout-gate-waiting",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "awaiting_post_place_home",
        "post_place_interlock": {
            "schema": "post_place_interlock.v1",
            "session_id": "lr-rollout-gate-waiting",
            "ungrasping_seen": True,
            "home_after_ungrasping": False,
            "ready_for_utm_snapshot": False,
        },
    }
    state.run_metadata["robot_task_result"] = {
        "schema": "robot_task_result.v1",
        "rollout_session_id": "lr-rollout-gate-waiting",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "awaiting_post_place_home",
        "post_place_interlock": state.run_metadata["manipulation_result"]["post_place_interlock"],
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert result.success is True
    assert capture_calls == []
    assert result.data["observation"]["vision_manipulation_completion"]["detected"] is False
    assert result.data["observation"]["vision_manipulation_completion"]["blocking_reason"] == "post_place_interlock_waiting"
    assert result.data["requested_next_stage"] == "manipulation"


@pytest.mark.asyncio
async def test_vision_agent_captures_one_utm_frame_after_measured_post_place_gate(tmp_path: Path) -> None:
    tools = ToolRegistry()
    utm_calls: list[dict[str, Any]] = []
    evidence = tmp_path / "utm-confirmed.png"
    evidence.write_bytes(b"utm-confirmed")
    tools.register(
        "camera.capture",
        lambda _payload: (_ for _ in ()).throw(AssertionError("generic simulator capture must not verify UTM completion")),
    )
    tools.register(
        "vision.utm_specimen_presence.capture",
        lambda payload: utm_calls.append(dict(payload)) or {
            "ok": True,
            "tool": "vision.utm_specimen_presence.capture",
            "schema": "vision_utm_specimen_presence.v1",
            "status": "confirmed",
            "detected": True,
            "source": "utm_ros_frame",
            "frame_id": "utm-completion-1",
            "topic": "/image_utm",
            "confidence": 0.94,
            "bbox_xyxy": [20, 30, 90, 110],
            "annotated_frame_path": str(evidence),
            "raw_frame_path": str(evidence),
            "width": 160,
            "height": 120,
            "run_id": "run-vision",
            "session_id": "lr-rollout-gate-ready",
            "specimen_id": "specimen-001",
        },
    )
    state = _state()
    gate = {
        "schema": "post_place_interlock.v1",
        "session_id": "lr-rollout-gate-ready",
        "ungrasping_seen": True,
        "home_after_ungrasping": True,
        "ready_for_utm_snapshot": True,
    }
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "workflow": "rollout",
        "runtime_phase": "ACTION_ACTIVE",
        "action_count": 30,
        "session_id": "lr-rollout-gate-ready",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete",
        "post_place_interlock": gate,
    }
    state.run_metadata["robot_task_result"] = {
        "schema": "robot_task_result.v1",
        "rollout_session_id": "lr-rollout-gate-ready",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "reported_complete",
        "post_place_interlock": gate,
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert len(utm_calls) == 1
    assert utm_calls[0]["session_id"] == "lr-rollout-gate-ready"
    completion = result.data["observation"]["vision_manipulation_completion"]
    assert completion["detected"] is True
    assert completion["ready_to_stop_rollout"] is True
    assert completion["run_id"] == "run-vision"
    assert completion["session_id"] == "lr-rollout-gate-ready"
    assert completion["specimen_id"] == "specimen-001"


@pytest.mark.asyncio
async def test_vision_agent_uses_lerobot_active_robot_cam_routine_for_ejection_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_frame = tmp_path / "camera-runtime" / "active-robot-cam-ejection.jpg"
    active_frame.parent.mkdir(parents=True)
    active_frame.write_bytes(b"active-robot-cam-ejection")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    tools = ToolRegistry()
    camera_test_calls: list[dict[str, Any]] = []
    active_robot_cam_calls: list[dict[str, Any]] = []
    tools.register(
        "camera.capture",
        lambda payload: {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": "top",
            "source": "live_camera",
            "confidence": 0.87,
        },
    )
    tools.register(
        "lerobot.camera.test",
        lambda payload: camera_test_calls.append(dict(payload or {})) or {
            "ok": False,
            "failure_code": "SHOULD_NOT_USE_CAMERA_TEST_FOR_ACTIVE_CAM",
        },
    )
    tools.register(
        "lerobot.active_robot_cam.capture",
        lambda payload: active_robot_cam_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": "live",
            "profile_id": payload.get("profile_id", "robotis_omx_ai"),
            "camera_key": payload.get("camera_key", "wrist"),
            "camera_port": "352122273019",
            "port_released": True,
            "camera_returned_to_vla": True,
            "camera_owner_after": "vla_runtime",
            "robot_pose_included": True,
            "capture_pose": {"status": "reached"},
            "resume_pose": {"status": "reached"},
            "capture": {
                "ok": True,
                "path": str(active_frame),
                "serve_url": f"/api/lerobot/visualization/file?path={active_frame}",
                "width": 640,
                "height": 480,
                "synthetic": False,
                "port_released": True,
                "camera_returned_to_vla": True,
                "camera_owner_after": "vla_runtime",
            },
        },
    )
    state = _state()
    state.mode = Mode.TEST
    state.current_experiment_spec = {
        **state.current_experiment_spec,
        "active_cam_camera_key": "wrist",
        "robot_profile_id": "robotis_omx_ai",
        "printer_test_path": "installed_printer",
    }
    state.run_metadata["specimen_result"]["printer_path"] = "installed_printer"
    state.run_metadata["fabrication_report"] = {
        "fabrication_intent": {"printer_path": "installed_printer", "physical_intent": True},
        "fabrication_outcome": {"location": "a4_workspace", "autoejection_status": "complete"},
        "autoejection_gate": {"status": "complete", "method": "bambu_gcode"},
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert active_robot_cam_calls
    assert active_robot_cam_calls[0]["camera_key"] == "wrist"
    assert active_robot_cam_calls[0]["mode"] == "live"
    assert active_robot_cam_calls[0]["confirm_live_execute"] is True
    assert camera_test_calls == []
    active = result.data["vision_agent_report"]["active_cam_ejection_check"]
    assert active["source"] == "lerobot.active_robot_cam.capture"
    assert active["spc_autoejection_confirmed"] is True
    assert active["robot_pose_included"] is True


@pytest.mark.asyncio
async def test_vision_agent_confirms_spc_autoejection_with_active_cam_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_frame = tmp_path / "camera-runtime" / "active_cam_ejection.jpg"
    active_frame.parent.mkdir(parents=True)
    active_frame.write_bytes(b"active-cam")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    tools = ToolRegistry()
    active_cam_calls: list[dict[str, Any]] = []
    tools.register(
        "camera.capture",
        lambda payload: {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": "top",
            "source": "simulator",
            "confidence": 0.84,
        },
    )
    tools.register(
        "lerobot.active_robot_cam.capture",
        lambda payload: active_cam_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": payload.get("mode", "test"),
            "profile_id": payload.get("profile_id", "robotis_omx_ai"),
            "camera_key": payload.get("camera_key", "wrist"),
            "camera_port": "352122273019",
            "port_released": True,
            "camera_returned_to_vla": True,
            "camera_owner_after": "vla_runtime",
            "capture": {
                "ok": True,
                "path": str(active_frame),
                "serve_url": f"/api/lerobot/visualization/file?path={active_frame}",
                "width": 640,
                "height": 480,
                "synthetic": False,
                "port_released": True,
                "camera_returned_to_vla": True,
                "camera_owner_after": "vla_runtime",
            },
        },
    )
    state = _state()
    state.current_experiment_spec = {
        **state.current_experiment_spec,
        "active_cam_camera_key": "wrist",
        "robot_profile_id": "robotis_omx_ai",
    }
    state.run_metadata["fabrication_report"] = {
        "fabrication_outcome": {"location": "a4_workspace", "autoejection_status": "complete"},
        "autoejection_gate": {"status": "complete", "method": "bambu_gcode"},
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert active_cam_calls
    assert active_cam_calls[0]["camera_key"] == "wrist"
    observation = result.data["observation"]
    screen_report = result.data["vision_agent_report"]
    active = screen_report["active_cam_ejection_check"]
    assert active["status"] == "confirmed"
    assert active["specimen_detected"] is True
    assert active["spc_autoejection_confirmed"] is True
    assert Path(active["capture_path"]).is_file()
    assert active["capture_path"] != str(active_frame)
    assert active["capture_url"].startswith(f"/api/runs/{state.run_id}/artifact-file/vision/")
    assert active["port_released"] is True
    assert active["camera_returned_to_vla"] is True
    assert active["camera_owner_after"] == "vla_runtime"
    assert observation["transfer_readiness"]["camera_returned_to_vla"] is True
    assert observation["transfer_readiness"]["spc_autoejection_confirmed"] is True
    assert observation["spc_autoejection_confirmation"]["signal"] == "SPC_AUTOEJECTION_CONFIRMED_BY_ACTIVE_CAM"
    assert observation["vision_report"]["artifacts"]["active_cam_capture_path"] == active["capture_path"]
    signal = next(item for item in observation["vision_report"]["signal_board"] if item["signal"] == "spc_autoejection_confirmed")
    assert signal["target_agent"] == "specimen_agent"
    progress_ids = [step["id"] for step in screen_report["agentic_progress"]["steps"]]
    assert "active_cam" in progress_ids


@pytest.mark.asyncio
async def test_test_mode_installed_printer_uses_live_active_cam_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_frame = tmp_path / "camera-runtime" / "installed-printer-active-cam.jpg"
    active_frame.parent.mkdir(parents=True)
    active_frame.write_bytes(b"installed-printer-active-cam")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    tools = ToolRegistry()
    active_cam_calls: list[dict[str, Any]] = []
    generic_camera_calls: list[dict[str, Any]] = []
    tools.register(
        "camera.capture",
        lambda payload: generic_camera_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": "top",
            "source": "live_camera",
            "confidence": 0.84,
        },
    )
    tools.register(
        "lerobot.active_robot_cam.capture",
        lambda payload: active_cam_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": payload.get("mode", "test"),
            "runtime_mode": payload.get("runtime_mode", "test"),
            "profile_id": payload.get("profile_id", "robotis_omx_ai"),
            "camera_key": payload.get("camera_key", "wrist"),
            "camera_port": "352122273019",
            "port_released": True,
            "camera_returned_to_vla": True,
            "camera_owner_after": "vla_runtime",
            "capture": {
                "ok": True,
                "path": str(active_frame),
                "serve_url": f"/api/lerobot/visualization/file?path={active_frame}",
                "width": 640,
                "height": 480,
                "synthetic": False,
                "port_released": True,
                "camera_returned_to_vla": True,
                "camera_owner_after": "vla_runtime",
            },
        },
    )
    state = _state()
    state.mode = Mode.TEST
    state.current_experiment_spec = {
        **state.current_experiment_spec,
        "active_cam_camera_key": "wrist",
        "robot_profile_id": "robotis_omx_ai",
        "printer_test_path": "installed_printer",
    }
    state.run_metadata["specimen_result"]["printer_path"] = "installed_printer"
    state.run_metadata["fabrication_report"] = {
        "fabrication_intent": {"printer_path": "installed_printer", "physical_intent": True},
        "fabrication_outcome": {"location": "a4_workspace", "autoejection_status": "complete"},
        "autoejection_gate": {"status": "complete", "method": "bambu_gcode"},
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert active_cam_calls
    assert active_cam_calls[0]["mode"] == "live"
    assert active_cam_calls[0]["runtime_mode"] == "live"
    assert active_cam_calls[0]["confirm_live_execute"] is True
    assert active_cam_calls[0]["active_robot_cam_camera_priority"] == "d405"
    assert active_cam_calls[0]["active_robot_cam_d455f_fallback_enabled"] is False
    assert generic_camera_calls == []
    assert result.data["observation"]["source"] == "lerobot_active_robot_cam"
    assert result.data["vision_agent_report"]["active_cam_ejection_check"]["synthetic_frame"] is False


@pytest.mark.asyncio
async def test_test_mode_installed_printer_active_cam_failure_has_no_simulator_observation() -> None:
    tools = ToolRegistry()
    generic_camera_calls: list[dict[str, Any]] = []
    tools.register(
        "camera.capture",
        lambda payload: generic_camera_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": "top",
            "source": "simulator",
            "confidence": 0.86,
        },
    )
    tools.register(
        "lerobot.active_robot_cam.capture",
        lambda payload: {
            "ok": False,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": "live",
            "runtime_mode": "live",
            "camera_key": payload.get("camera_key", "wrist"),
            "camera_port": "352122273019",
            "failure_code": "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED",
            "message": "SPECIMEN_NOT_DETECTED",
            "active_robot_cam_result": {
                "ok": False,
                "failure_code": "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED",
                "capture": {
                    "ok": True,
                    "path": "/tmp/active-cam-no-specimen.png",
                    "width": 640,
                    "height": 480,
                    "synthetic": False,
                    "port_released": True,
                    "camera_returned_to_vla": True,
                    "camera_owner_after": "vla_runtime",
                },
            },
        },
    )
    state = _state()
    state.mode = Mode.TEST
    state.current_experiment_spec = {
        **state.current_experiment_spec,
        "active_cam_camera_key": "wrist",
        "robot_profile_id": "robotis_omx_ai",
        "printer_test_path": "installed_printer",
        "allow_test_printer_live": True,
    }
    state.run_metadata["specimen_result"]["printer_path"] = "installed_printer"
    state.run_metadata["fabrication_report"] = {
        "fabrication_intent": {"printer_path": "installed_printer", "physical_intent": True},
        "fabrication_outcome": {"location": "a4_workspace", "autoejection_status": "complete"},
        "autoejection_gate": {"status": "complete", "method": "bambu_project_file"},
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    observation = result.data["observation"]
    assert generic_camera_calls == []
    assert result.success is False
    assert observation["source"] == "lerobot_active_robot_cam"
    assert observation["camera_key"] == "wrist"
    assert observation["vision_report"]["detections"] == []
    assert observation["transfer_readiness"]["ready"] is False
    assert observation["raw_capture"]["source"] == "lerobot_active_robot_cam"
    assert observation["raw_capture"]["failure_code"] == "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED"
    assert result.data["failure_code"] == "ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED"
    assert result.data["safe_stop_recommended"] is True


@pytest.mark.asyncio
async def test_test_mode_installed_printer_uses_specimen_fabrication_report_alias_for_active_cam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_frame = tmp_path / "camera-runtime" / "alias-active-cam.jpg"
    active_frame.parent.mkdir(parents=True)
    active_frame.write_bytes(b"alias-active-cam")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    tools = ToolRegistry()
    active_cam_calls: list[dict[str, Any]] = []
    tools.register(
        "camera.capture",
        lambda payload: {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": "top",
            "source": "live_camera",
            "confidence": 0.86,
        },
    )
    tools.register(
        "lerobot.active_robot_cam.capture",
        lambda payload: active_cam_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": payload.get("mode", "test"),
            "runtime_mode": payload.get("runtime_mode", "test"),
            "camera_key": payload.get("camera_key", "wrist"),
            "port_released": True,
            "camera_returned_to_vla": True,
            "camera_owner_after": "vla_runtime",
            "capture": {
                "ok": True,
                "path": str(active_frame),
                "serve_url": f"/api/lerobot/visualization/file?path={active_frame}",
                "width": 640,
                "height": 480,
                "synthetic": False,
                "port_released": True,
                "camera_returned_to_vla": True,
                "camera_owner_after": "vla_runtime",
            },
        },
    )
    state = _state()
    state.mode = Mode.TEST
    state.current_experiment_spec = {
        **state.current_experiment_spec,
        "active_cam_camera_key": "wrist",
        "printer_test_path": "installed_printer",
        "allow_test_printer_live": True,
    }
    state.run_metadata["specimen_result"]["printer_path"] = "installed_printer"
    state.run_metadata["specimen_fabrication_report"] = {
        "fabrication_intent": {"printer_path": "installed_printer", "physical_intent": True},
        "fabrication_outcome": {"location": "a4_workspace", "autoejection_status": "complete"},
        "autoejection_gate": {"status": "complete", "method": "bambu_project_file"},
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert active_cam_calls
    assert active_cam_calls[0]["mode"] == "live"
    assert active_cam_calls[0]["runtime_mode"] == "live"
    assert result.data["observation"]["transfer_readiness"]["spc_autoejection_confirmed"] is True


@pytest.mark.asyncio
async def test_live_vision_agent_allows_active_cam_after_autoejection_handoff_without_manual_confirm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_frame = tmp_path / "camera-runtime" / "live-active-cam.jpg"
    active_frame.parent.mkdir(parents=True)
    active_frame.write_bytes(b"live-active-cam")
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    tools = ToolRegistry()
    active_cam_calls: list[dict[str, Any]] = []
    tools.register(
        "camera.capture",
        lambda payload: {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": "top",
            "source": "live_camera",
            "confidence": 0.82,
        },
    )
    tools.register(
        "lerobot.active_robot_cam.capture",
        lambda payload: active_cam_calls.append(dict(payload or {})) or {
            "ok": True,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": "live",
            "camera_key": payload.get("camera_key", "wrist"),
            "port_released": True,
            "camera_returned_to_vla": True,
            "camera_owner_after": "vla_runtime",
            "capture": {
                "ok": True,
                "path": str(active_frame),
                "serve_url": f"/api/lerobot/visualization/file?path={active_frame}",
                "width": 640,
                "height": 480,
                "synthetic": False,
                "port_released": True,
                "camera_returned_to_vla": True,
                "camera_owner_after": "vla_runtime",
            },
        },
    )
    state = _state()
    state.mode = Mode.LIVE
    state.current_experiment_spec = {**state.current_experiment_spec, "active_cam_camera_key": "wrist"}
    state.run_metadata["fabrication_report"] = {
        "fabrication_outcome": {"location": "a4_workspace", "autoejection_status": "complete"},
        "autoejection_gate": {"status": "complete"},
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    assert active_cam_calls
    assert active_cam_calls[0]["mode"] == "live"
    assert active_cam_calls[0]["confirm_live_execute"] is True
    assert result.data["vision_agent_report"]["active_cam_ejection_check"]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_vision_agent_blocks_handoff_when_active_cam_does_not_return_to_vla() -> None:
    tools = ToolRegistry()
    tools.register(
        "camera.capture",
        lambda payload: {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": "top",
            "source": "live_camera",
            "confidence": 0.86,
        },
    )
    tools.register(
        "lerobot.active_robot_cam.capture",
        lambda payload: {
            "ok": True,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": "live",
            "camera_key": payload.get("camera_key", "wrist"),
            "port_released": False,
            "camera_returned_to_vla": False,
            "camera_owner_after": "vision_agent",
            "capture": {
                "ok": True,
                "path": "/tmp/active-cam-not-returned.jpg",
                "serve_url": "/api/lerobot/visualization/file?path=/tmp/active-cam-not-returned.jpg",
                "width": 640,
                "height": 480,
                "synthetic": False,
                "port_released": False,
                "camera_returned_to_vla": False,
                "camera_owner_after": "vision_agent",
            },
        },
    )
    state = _state()
    state.mode = Mode.LIVE
    state.current_experiment_spec = {**state.current_experiment_spec, "active_cam_camera_key": "wrist"}
    state.run_metadata["fabrication_report"] = {
        "fabrication_outcome": {"location": "a4_workspace", "autoejection_status": "complete"},
        "autoejection_gate": {"status": "complete"},
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    observation = result.data["observation"]
    active = result.data["vision_agent_report"]["active_cam_ejection_check"]
    assert active["status"] == "blocked"
    assert active["spc_autoejection_confirmed"] is False
    assert active["camera_returned_to_vla"] is False
    assert observation["transfer_readiness"]["ready"] is False
    assert observation["transfer_readiness"]["camera_returned_to_vla"] is False


@pytest.mark.asyncio
async def test_vision_agent_clears_active_cam_display_on_resume_timeout() -> None:
    tools = ToolRegistry()
    tools.register(
        "camera.capture",
        lambda payload: {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": "top",
            "source": "live_camera",
            "confidence": 0.86,
        },
    )
    tools.register(
        "lerobot.active_robot_cam.capture",
        lambda payload: {
            "ok": False,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": "live",
            "camera_key": payload.get("camera_key", "wrist"),
            "failure_code": "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED",
            "message": "resume timeout after frame capture",
            "active_robot_cam_result": {
                "ok": False,
                "status": "applied",
                "failure_code": "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED",
                "capture": {
                    "ok": True,
                    "path": "/tmp/active-cam-resume-timeout.jpg",
                    "serve_url": "/api/lerobot/visualization/file?path=/tmp/active-cam-resume-timeout.jpg",
                    "width": 640,
                    "height": 480,
                    "synthetic": False,
                    "port_released": True,
                    "camera_returned_to_vla": True,
                    "camera_owner_after": "vla_runtime",
                },
                "capture_pose": {"ok": True, "status": "reached"},
                "resume_pose": {"ok": False, "status": "timeout", "failure_code": "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED"},
            },
        },
    )
    state = _state()
    state.mode = Mode.LIVE
    state.current_experiment_spec = {**state.current_experiment_spec, "active_cam_camera_key": "wrist"}
    state.run_metadata["fabrication_report"] = {
        "fabrication_outcome": {"location": "a4_workspace", "autoejection_status": "complete"},
        "autoejection_gate": {"status": "complete"},
    }

    result = await VisionAgent().run(state, _CtxStub(tools))

    active = result.data["vision_agent_report"]["active_cam_ejection_check"]
    assert active["status"] == "blocked"
    assert active["specimen_detected"] is True
    assert active["spc_autoejection_confirmed"] is False
    assert active["capture_path"] == ""
    assert active["capture_url"] == ""
    assert result.data["active_cam_artifact_update"]["status"] == "failed"
    assert active["blocking_reason"] == "ACTIVE_ROBOT_CAM_RESUME_NOT_REACHED"


@pytest.mark.asyncio
async def test_vision_agent_auto_starts_utm_runtime_when_tool_is_registered() -> None:
    tools = ToolRegistry()
    start_payloads: list[dict[str, Any]] = []

    tools.register(
        "vision.utm_runtime.start",
        lambda payload: start_payloads.append(dict(payload or {})) or {
            "ok": True,
            "tool": "vision.utm_runtime.start",
            "status": "running",
            "pid": 1234,
        },
    )
    tools.register(
        "camera.capture",
        lambda payload: {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "source": "live_camera",
            "confidence": 0.86,
        },
    )

    result = await VisionAgent().run(_state(), _CtxStub(tools))

    assert start_payloads == [{"mode": "test", "source": "vision_agent.preflight", "agent": "vision_agent"}]
    runtime = result.data["observation"]["utm_runtime_status"]
    assert runtime["status"] == "running"
    assert result.data["vision_agent_report"]["camera_health"]["utm_runtime_status"]["status"] == "running"



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
    progress = result.data["vision_agent_report"]["agentic_progress"]
    assert progress["schema"] == "vision_agentic_progress.v1"
    assert progress["steps"][0]["status"] == "blocked"
    assert progress["current_step"] == "capture"
    assert result.data["vision_report"]["safety_anomaly"]["anomaly"] is True
    assert any(signal["signal"] == "anomaly_detected" for signal in result.data["vision_report"]["signal_board"])
