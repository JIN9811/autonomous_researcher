"""
File purpose:
- Test-mode robot simulator.

Key classes/functions:
- RobotSimulator

Inputs/outputs:
- Input: manipulation payload
- Output: simulated grasp and task response

Dependencies:
- device_bridges.base_bridge.BaseBridge

Modification guide:
- Safe places to edit: mock grasp scoring
- Risky places to edit: fields used by SARM calculations
- Related files: mcp_tools/mock_tools.py, agents/manipulation_agent.py
"""

from __future__ import annotations

from typing import Any

from device_bridges.base_bridge import BaseBridge


class RobotSimulator(BaseBridge):
    """Deterministic simulator for manipulation tasks."""

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "bridge": "robot_sim",
            "command": command,
            "task": payload.get("task", "pick_place"),
            "grasp_score": 0.9,
        }
