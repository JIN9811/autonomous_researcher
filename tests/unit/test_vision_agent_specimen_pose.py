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


def _state_with_runtime_handoff_only() -> OrchestratorState:
    state = _state()
    state.run_metadata.pop("fabrication_report", None)
    state.run_metadata["specimen_fabricated"] = {
        "schema": "specimen_fabricated.v1",
        "status": "ready",
        "specimen_id": "specimen-pose-1",
        "candidate_id": "candidate-pose-1",
    }
    return state


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
async def test_vision_agent_requests_pose_from_runtime_specimen_handoff() -> None:
    result = await VisionAgent().run(_state_with_runtime_handoff_only(), _CtxStub(_tools_with_pose()))

    observation = result.data["observation"]
    assert result.success is True
    assert observation["specimen_pose"]["schema"] == "specimen_pose.v1"
    assert observation["transfer_readiness"]["camera_returned_to_vla"] is True
    assert observation["pose_estimate"]["source"] == "specimen_pose.v1"


@pytest.mark.asyncio
async def test_vision_agent_blocks_when_d455f_not_returned() -> None:
    result = await VisionAgent().run(_state(), _CtxStub(_tools_with_pose(port_released=False)))

    observation = result.data["observation"]
    assert result.success is False
    assert observation["transfer_readiness"]["ready"] is False
    assert observation["transfer_readiness"]["camera_returned_to_vla"] is False
    assert observation["transfer_readiness"]["blocking_reason"] == "D455F_PORT_RETURN_FAILED"
