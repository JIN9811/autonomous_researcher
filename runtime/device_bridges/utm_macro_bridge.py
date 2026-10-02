"""
File purpose:
- UTM macro bridge placeholder for live equipment protocol control.

Key classes/functions:
- UTMMacroBridge

Inputs/outputs:
- Input: protocol command payload
- Output: execution result dictionary

Dependencies:
- device_bridges.base_bridge.BaseBridge

Modification guide:
- Safe places to edit: macro engine integration details
- Risky places to edit: output fields used by analysis agent
- Related files: mcp_tools/utm_tools.py, device_bridges/simulator/utm_sim.py
"""

from __future__ import annotations

from typing import Any

from device_bridges.base_bridge import BaseBridge


class UTMMacroBridge(BaseBridge):
    """Live bridge stub for UTM macro control."""

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "bridge": "utm_live_stub", "command": command, "payload": payload}
