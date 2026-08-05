"""End-to-end unit contract for the active-cam to UTM manipulation loop."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import numpy as np
from PIL import Image

from agents.manipulation_agent import ManipulationAgent
from agents.vision_agent import VisionAgent
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage
from policies.guardian_gate import gate_blocks_execution, guardian_gate
import utils.manipulation_profile as manipulation_profile_module


class _CtxStub:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools
        self.prompts: list[str] = []

    async def complete(self, task_type: str, prompt: str, timeout_s: float | None = None) -> Any:
        self.prompts.append(prompt)
        return SimpleNamespace(text="tool call contract ready", raw={}, model="mock-e4b")


def _loop_state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-active-cam-loop",
        experiment_id="exp-active-cam-loop",
        mode=Mode.TEST,
        stage=Stage.VISION,
        active_goal="Transfer printed specimen to UTM fixture",
        current_experiment_spec={
            "size_mm": [20.0, 20.0, 12.0],
            "active_cam_camera_key": "wrist",
            "utm_camera_key": "utm",
            "lerobot_profile_id": "fake_omx_ai",
            "policy_type": "smolvla",
            "lerobot_policy_path": "fake://smolvla-policy",
            "camera_enabled": True,
            # Legacy D455 flags must not alter the Active Cam inference route.
            "vision_specimen_pose_snapshot_enabled": True,
            "recording_specimen_pose_snapshot_enabled": True,
        },
        run_metadata={
            "specimen_result": {
                "ok": True,
                "specimen_id": "specimen-loop-001",
                "candidate_id": "candidate-loop-001",
                "handoff_status": "ready",
                "stl_path": "runs/specimen-loop-001.stl",
                "sliced_path": "runs/specimen-loop-001.gcode",
            },
            "fabrication_report": {
                "fabrication_outcome": {
                    "location": "a4_workspace",
                    "autoejection_status": "complete",
                },
                "autoejection_gate": {"status": "complete"},
            },
        },
    )


@pytest.mark.asyncio
async def test_active_cam_to_utm_completion_loop_preserves_camera_and_stop_flow(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        manipulation_profile_module,
        "MANIPULATION_AGENT_PROFILE_PATH",
        tmp_path / "memory" / "manipulation_agent_bridge.json",
    )
    tools = ToolRegistry()
    capture_calls: list[dict[str, Any]] = []
    active_cam_calls: list[dict[str, Any]] = []
    rollout_start_calls: list[dict[str, Any]] = []
    rollout_status_calls: list[dict[str, Any]] = []
    rollout_stop_calls: list[dict[str, Any]] = []
    specimen_pose_calls: list[dict[str, Any]] = []
    utm_presence_calls: list[dict[str, Any]] = []
    active_cam_frame = tmp_path / "camera" / "active-cam-ejection.jpg"
    active_cam_frame.parent.mkdir(parents=True)
    active_cam_image = np.full((480, 640, 3), 205, dtype=np.uint8)
    active_cam_image[85:180, 360:440] = [210, 25, 30]
    Image.fromarray(active_cam_image, mode="RGB").save(active_cam_frame)
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))

    def camera_capture(payload: dict[str, Any]) -> dict[str, Any]:
        capture_calls.append(dict(payload))
        return {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload["frame_id"],
            "camera_key": payload["camera_key"],
            "purpose": payload["purpose"],
            "source": "top_camera",
            "frame_path": "/tmp/post-ejection.jpg",
            "confidence": 0.88,
            "pose_confidence": 0.88,
            "stable_for_ms": 1400,
        }

    def utm_specimen_presence(payload: dict[str, Any]) -> dict[str, Any]:
        utm_presence_calls.append(dict(payload))
        frame_path = tmp_path / "utm-placement-confirmed.jpg"
        frame_path.write_bytes(b"utm-placement-confirmed")
        return {
            "ok": True,
            "tool": "vision.utm_specimen_presence.capture",
            "schema": "vision_utm_specimen_presence.v1",
            "status": "confirmed",
            "detected": True,
            "source": "utm_ros_frame",
            "frame_id": payload["frame_id"],
            "annotated_frame_path": str(frame_path),
            "raw_frame_path": str(frame_path),
            "confidence": 0.94,
            "bbox_xyxy": [80, 90, 160, 210],
            "width": 640,
            "height": 480,
            "run_id": payload["run_id"],
            "session_id": payload["session_id"],
            "specimen_id": payload["specimen_id"],
        }

    def active_cam_test(payload: dict[str, Any]) -> dict[str, Any]:
        active_cam_calls.append(dict(payload))
        return {
            "ok": True,
            "tool": "lerobot.active_robot_cam.capture",
            "mode": payload.get("mode", "test"),
            "profile_id": payload.get("profile_id", "fake_omx_ai"),
            "camera_key": payload.get("camera_key", "wrist"),
            "camera_port": "352122273019",
            "port_released": True,
            "camera_returned_to_vla": True,
            "camera_owner_after": "vla_runtime",
            "capture": {
                "ok": True,
                "path": str(active_cam_frame),
                "serve_url": f"/api/lerobot/visualization/file?path={active_cam_frame}",
                "width": 640,
                "height": 480,
                "synthetic": False,
                "port_released": True,
                "camera_returned_to_vla": True,
                "camera_owner_after": "vla_runtime",
            },
        }

    def specimen_pose_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        specimen_pose_calls.append(dict(payload))
        raise AssertionError("D455 specimen pose must not run in the Active Cam inference route")

    def rollout_start(payload: dict[str, Any]) -> dict[str, Any]:
        rollout_start_calls.append(dict(payload))
        return {
            "ok": True,
            "tool": "lerobot.rollout.start",
            "workflow": "rollout",
            "status": "POLICY_ACTIVE",
            "runtime_phase": "ACTION_ACTIVE",
            "action_count": 1,
            "runtime": {"phase": "ACTION_ACTIVE", "action_count": 1},
            "session_id": payload["session_id"],
            "profile_id": payload["profile_id"],
            "command_preview": ["lerobot-record", "--policy.type=smolvla"],
            "step_trace": [{"step": "POLICY_ACTIVE", "status": "active", "detail": "rollout started"}],
        }

    def rollout_stop(payload: dict[str, Any]) -> dict[str, Any]:
        rollout_stop_calls.append(dict(payload))
        return {
            "ok": True,
            "tool": "lerobot.rollout.stop",
            "workflow": "rollout",
            "status": "STOPPED",
            "session_id": payload["session_id"],
            "step_trace": [{"step": "STOPPED", "status": "ok", "detail": "vision completion"}],
        }

    def rollout_status(payload: dict[str, Any]) -> dict[str, Any]:
        rollout_status_calls.append(dict(payload))
        action_count = 30 * len(rollout_status_calls)
        return {
            "ok": True,
            "tool": "lerobot.rollout.status",
            "workflow": "rollout",
            "status": "POLICY_ACTIVE",
            "runtime_phase": "ACTION_ACTIVE",
            "action_count": action_count,
            "runtime": {
                "phase": "ACTION_ACTIVE",
                "action_count": action_count,
                "message": "Robot action stream active",
            },
            "session_id": payload["session_id"],
            "profile_id": payload["profile_id"],
            "post_place_interlock": {
                "schema": "post_place_interlock.v1",
                "session_id": payload["session_id"],
                "ungrasping_seen": True,
                "home_after_ungrasping": True,
                "ready_for_utm_snapshot": True,
            },
        }

    tools.register("camera.capture", camera_capture)
    tools.register("vision.utm_specimen_presence.capture", utm_specimen_presence)
    tools.register("lerobot.active_robot_cam.capture", active_cam_test)
    tools.register("vision.specimen_pose_snapshot", specimen_pose_snapshot)
    tools.register("lerobot.rollout.start", rollout_start)
    tools.register("lerobot.rollout.status", rollout_status)
    tools.register("lerobot.rollout.stop", rollout_stop)
    ctx = _CtxStub(tools)
    state = _loop_state()

    first_vision = await VisionAgent().run(state, ctx)
    assert first_vision.success is True
    assert len(active_cam_calls) == 1
    assert specimen_pose_calls == []
    assert first_vision.data["observation"]["transfer_readiness"]["spc_autoejection_confirmed"] is True
    assert first_vision.data["observation"]["transfer_readiness"]["camera_returned_to_vla"] is True

    state.latest_observations = first_vision.data["observation"]
    state.stage = Stage.MANIPULATION
    first_manipulation = await ManipulationAgent().run(state, ctx)
    assert first_manipulation.success is True
    assert len(rollout_start_calls) == 1
    assert "home_pose" not in first_manipulation.data["manipulation_report"]
    assert first_manipulation.data["requested_next_stage"] == "vision"

    state.run_metadata["manipulation_result"] = first_manipulation.data["manipulation"]
    state.run_metadata["robot_task_result"] = first_manipulation.data["robot_task_result"]
    state.stage = Stage.VISION
    completed_vision = await VisionAgent().run(state, ctx)
    assert completed_vision.success is True
    assert len(active_cam_calls) == 1
    assert specimen_pose_calls == []
    assert capture_calls == []
    assert len(utm_presence_calls) == 1
    completion = completed_vision.data["observation"]["vision_manipulation_completion"]
    assert completion["camera"] == "utm"
    assert completion["detected"] is True
    assert completion["session_id"] == first_manipulation.data["manipulation"]["session_id"]
    assert completion["rollout_stopped"] is True
    assert completed_vision.data["requested_next_stage"] == "equipment"
    assert completed_vision.data["transition_decision"] == "vision_equipment_handoff"
    assert len(rollout_start_calls) == 1
    assert len(rollout_status_calls) == 1
    assert len(rollout_stop_calls) == 1
    assert rollout_stop_calls[0]["reason"] == "vision_utm_placement_verified"
    assert state.run_metadata["manipulation_result"]["handoff_status"] == "ready_for_equipment"
    assert state.run_metadata["robot_task_result"]["handoff_status"] == "ready_for_equipment"


def test_rollout_completion_requires_observed_robot_actions() -> None:
    agent = ManipulationAgent()
    verification = agent._verification_status(
        "transfer_to_utm",
        {
            "manipulation_completion": {
                "schema": "vision_manipulation_completion.v1",
                "detected": True,
                "ready_to_stop_rollout": True,
                "status": "detected",
            },
            "signals": {},
        },
        {
            "ok": True,
            "tool": "lerobot.rollout.status",
            "workflow": "rollout",
            "status": "POLICY_ACTIVE",
            "runtime_phase": "MODEL_LOADING",
            "action_count": 0,
            "runtime": {"phase": "MODEL_LOADING", "action_count": 0},
            "stop_confirmed": False,
            "post_place_interlock": {
                "schema": "post_place_interlock.v1",
                "session_id": "rollout-action-test",
                "ungrasping_seen": True,
                "home_after_ungrasping": True,
                "ready_for_utm_snapshot": True,
            },
        },
    )

    assert verification["verified"] is False
    assert verification["status"] == "executing"
    assert verification["reason"] == "rollout_action_evidence_required"


def test_rollout_start_hands_off_to_vision_without_graph_reentry() -> None:
    """Vision owns the same-session completion gate after a rollout starts."""
    agent = ManipulationAgent()
    response = {
        "ok": True,
        "tool": "lerobot.rollout.start",
        "workflow": "rollout",
        "status": "POLICY_ACTIVE",
        "runtime_phase": "PROCESS_STARTED",
        "action_count": 0,
        "runtime": {"phase": "PROCESS_STARTED", "action_count": 0},
    }
    verification = agent._verification_status("transfer_to_utm", {"signals": {}}, response)
    stage_machine = agent._stage_machine(
        task_id="transfer_to_utm",
        response=response,
        preflight={"status": "pass"},
        verification=verification,
    )
    decision = agent._decision(
        task_id="transfer_to_utm",
        response=response,
        preflight={"status": "pass"},
        verification=verification,
        sarm={"recovery_suggested": False},
    )

    assert stage_machine["current_stage"] == "post_place_verify"
    assert stage_machine["next_expected_stage"] == "vision_verification"
    assert decision["handoff_status"] == "needs_post_place_vision"
    assert decision["completion_status"] == "awaiting_post_place_home"
    assert decision["recommended_next_agent"] == "vision_agent"


def test_physical_utm_verification_rejects_simulator_capture(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(VisionAgent, "_repo_root", staticmethod(lambda: tmp_path))
    state = _loop_state()
    state.current_experiment_spec.update(
        {
            "printer_test_path": "installed_printer",
            "test_printer_transport": "real",
            "allow_test_printer_live": True,
        }
    )
    state.run_metadata["manipulation_result"] = {
        "ok": True,
        "tool": "lerobot.rollout.status",
        "workflow": "rollout",
        "status": "POLICY_ACTIVE",
        "session_id": "rollout-physical-001",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "rollout_active",
        "runtime_phase": "ACTION_ACTIVE",
        "action_count": 12,
        "runtime": {"phase": "ACTION_ACTIVE", "action_count": 12},
    }
    state.run_metadata["robot_task_result"] = {
        "rollout_session_id": "rollout-physical-001",
        "handoff_status": "needs_post_place_vision",
        "completion_status": "rollout_active",
    }

    payload = VisionAgent()._transfer_observation(
        state,
        {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": "frame-simulator",
            "observation_id": "obs-simulator",
            "camera_key": "utm",
            "purpose": "utm_placement_verification",
            "source": "simulator",
            "confidence": 0.99,
            "pose_confidence": 0.99,
            "anomaly": False,
        },
    )

    completion = payload["observation"]["vision_manipulation_completion"]
    assert completion["detected"] is False
    assert completion["ready_to_stop_rollout"] is False
    assert completion["blocking_reason"] == "physical_utm_evidence_required"
