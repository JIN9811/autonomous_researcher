"""
File purpose:
- MCP tool wrapper for robot manipulation operations.

Key classes/functions:
- register_robot_tools

Inputs/outputs:
- Input: ToolRegistry
- Output: robot tool handlers registered

Dependencies:
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: command payload and score fields
- Risky places to edit: tool names consumed by manipulation agent
- Related files: agents/manipulation_agent.py, device_bridges/robot_bridge.py
"""

from __future__ import annotations

from mcp_tools.tool_registry import ToolRegistry


def register_robot_tools(registry: ToolRegistry) -> None:
    """Register robot manipulation tool."""
    registry.register(
        "robot.pick_place",
        lambda payload: {"ok": True, "tool": "robot.pick_place", "task": payload.get("task", "pick_place")},
    )
