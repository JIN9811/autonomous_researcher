"""
File purpose:
- Test-mode camera simulator.

Key classes/functions:
- CameraSimulator

Inputs/outputs:
- Input: capture payload
- Output: simulated frame metadata

Dependencies:
- device_bridges.base_bridge.BaseBridge

Modification guide:
- Safe places to edit: simulated anomaly injection fields
- Risky places to edit: frame key names used by vision agent
- Related files: mcp_tools/mock_tools.py, agents/vision_agent.py
"""

from __future__ import annotations

from typing import Any

from device_bridges.base_bridge import BaseBridge


class CameraSimulator(BaseBridge):
    """Deterministic simulator for camera capture."""

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "bridge": "camera_sim",
            "command": command,
            "frame_id": payload.get("frame_id", "frame-sim"),
            "anomaly": False,
        }
