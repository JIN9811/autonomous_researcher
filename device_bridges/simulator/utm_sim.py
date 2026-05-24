"""
File purpose:
- Test-mode UTM simulator.

Key classes/functions:
- UTMSimulator

Inputs/outputs:
- Input: protocol payload
- Output: simulated protocol result file metadata

Dependencies:
- device_bridges.base_bridge.BaseBridge

Modification guide:
- Safe places to edit: result summary fields
- Risky places to edit: keys used by analysis pipeline
- Related files: mcp_tools/mock_tools.py, agents/equipment_agent.py
"""

from __future__ import annotations

from typing import Any

from device_bridges.base_bridge import BaseBridge


class UTMSimulator(BaseBridge):
    """Deterministic simulator for equipment test runs."""

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "bridge": "utm_sim",
            "command": command,
            "profile": payload.get("profile", "default"),
            "result_file": "runs/mock/utm_result.csv",
        }
