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

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState


class VisionAgent(BaseAgent):
    """Captures observations for downstream manipulation and safety checks."""

    name = "vision_agent"

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        frame_id = f"frame-{state.loop_count}-{state.stage.value}"
        timeout_s = 30.0 if state.mode == Mode.TEST else None
        try:
            protocol = await ctx.complete(
                "tool_formatting",
                f"Format camera capture command for frame_id={frame_id}. Return concise capture plan.",
                timeout_s=timeout_s,
            )
            protocol_note = protocol.text[:220]
        except Exception as exc:
            if state.mode == Mode.TEST:
                protocol_note = f"E2B degraded in test mode: {exc.__class__.__name__}"
            else:
                raise
        response = ctx.tools.call("camera.capture", {"frame_id": frame_id})
        return AgentResult(
            success=bool(response.get("ok")),
            summary="Vision capture complete",
            data={"observation": response, "protocol_note": protocol_note},
        )
