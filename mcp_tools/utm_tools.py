"""
File purpose:
- MCP tool wrapper for UTM/equipment protocol operations.

Key classes/functions:
- register_utm_tools

Inputs/outputs:
- Input: ToolRegistry
- Output: UTM tool handlers registered

Dependencies:
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: protocol argument fields
- Risky places to edit: tool names consumed by equipment agent
- Related files: agents/equipment_agent.py, device_bridges/utm_macro_bridge.py
"""

from __future__ import annotations

from mcp_tools.tool_registry import ToolRegistry


def register_utm_tools(registry: ToolRegistry) -> None:
    """Register UTM macro run tool."""
    registry.register(
        "utm.run_protocol",
        lambda payload: {"ok": True, "tool": "utm.run_protocol", "profile": payload.get("profile", "default")},
    )
