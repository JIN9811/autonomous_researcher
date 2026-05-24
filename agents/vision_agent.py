"""
File purpose:
- Acquire and summarize visual observations from top/wrist camera feeds.

Key classes/functions:
- VisionAgent

Inputs/outputs:
- Input: state stage metadata and frame request id
- Output: captured frame metadata and anomaly indicator

Dependencies:
- agents.base_agent.BaseAgent
- mcp tool: camera.capture

Modification guide:
- Safe places to edit: frame metadata and anomaly thresholds
- Risky places to edit: output keys consumed by guardian/manipulation agents
- Related files: mcp_tools/camera_tools.py, device_bridges/realsense_bridge.py
"""

from __future__ import annotations

from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState


class VisionAgent(BaseAgent):
    """Captures observations for downstream manipulation and safety checks."""

    name = "vision_agent"

    @staticmethod
    def _specimen_result(state: OrchestratorState) -> dict[str, Any]:
        raw = state.run_metadata.get("specimen_result") if isinstance(state.run_metadata, dict) else {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _as_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _transfer_observation(self, state: OrchestratorState, capture: dict[str, Any]) -> dict[str, Any]:
        specimen = self._specimen_result(state)
        geometry = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        size = geometry.get("size_mm") if isinstance(geometry.get("size_mm"), list) else []
        z_height = self._as_float(size[2], 10.0) if len(size) >= 3 else self._as_float(geometry.get("height_mm"), 10.0)
        specimen_ready = bool(specimen) and not bool(specimen.get("requires_operator_input")) and specimen.get("ok") is not False
        capture_ok = bool(capture.get("ok"))
        anomaly = bool(capture.get("anomaly", False)) or not capture_ok
        pose_confidence = 0.82 if capture_ok and specimen_ready else 0.55 if capture_ok else 0.0
        pose = {
            "x_mm": self._as_float(capture.get("x_mm"), 0.0),
            "y_mm": self._as_float(capture.get("y_mm"), 0.0),
            "z_mm": self._as_float(capture.get("z_mm"), max(1.0, z_height / 2.0)),
            "roll_deg": self._as_float(capture.get("roll_deg"), 0.0),
            "pitch_deg": self._as_float(capture.get("pitch_deg"), 0.0),
            "yaw_deg": self._as_float(capture.get("yaw_deg"), 0.0),
            "confidence": round(pose_confidence, 3),
        }
        return {
            "observation_id": capture.get("observation_id") or capture.get("frame_id") or f"obs-{state.run_id}",
            "frame_id": capture.get("frame_id", f"frame-{state.run_id}"),
            "camera_key": capture.get("camera_key") or capture.get("camera") or "top",
            "source": capture.get("source") or ("live_camera" if state.mode == Mode.LIVE else "simulator"),
            "summary": "3DP output pickup area clear" if not anomaly else "3DP output pickup area requires review",
            "anomaly": anomaly,
            "pose_estimate": pose,
            "pickup_target": {
                "specimen_id": specimen.get("specimen_id", ""),
                "candidate_id": specimen.get("candidate_id", ""),
                "source_location": "3dp_output_area",
                "target_location": "utm_fixture",
                "stl_path": specimen.get("stl_path", ""),
                "sliced_path": specimen.get("sliced_path", ""),
            },
            "transfer_readiness": {
                "ready": bool(capture_ok and specimen_ready and not anomaly),
                "camera_ok": capture_ok,
                "specimen_ready": specimen_ready,
                "pose_confidence": round(pose_confidence, 3),
            },
            "raw_capture": capture,
        }

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        frame_id = f"frame-{state.loop_count}-{state.stage.value}"
        timeout_s = 30.0 if state.mode == Mode.TEST else None
        specimen = self._specimen_result(state)
        try:
            protocol = await ctx.complete(
                "tool_formatting",
                (
                    "Format a concise 3DP output-area vision check before robot transfer. "
                    f"frame_id={frame_id} specimen_id={specimen.get('specimen_id', '')}"
                ),
                timeout_s=timeout_s,
            )
            protocol_note = protocol.text[:220]
        except Exception as exc:
            if state.mode == Mode.TEST:
                protocol_note = f"E2B degraded in test mode: {exc.__class__.__name__}"
            else:
                raise
        response = ctx.tools.call(
            "camera.capture",
            {
                "frame_id": frame_id,
                "camera_key": "top",
                "purpose": "3dp_output_pickup_check",
                "specimen_id": specimen.get("specimen_id", ""),
            },
        )
        observation = self._transfer_observation(state, dict(response))
        return AgentResult(
            success=bool(response.get("ok")) and bool(observation["transfer_readiness"]["ready"]),
            summary="Vision pickup observation complete",
            data={"observation": observation, "protocol_note": protocol_note},
        )
