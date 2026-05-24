"""
File purpose:
- MCP tool wrapper for camera operations.

Key classes/functions:
- register_camera_tools

Inputs/outputs:
- Input: ToolRegistry
- Output: camera tool handlers registered

Dependencies:
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: payload schema and response fields
- Risky places to edit: tool names consumed by vision agent
- Related files: agents/vision_agent.py, device_bridges/realsense_bridge.py
"""

from __future__ import annotations

from mcp_tools.tool_registry import ToolRegistry


def register_camera_tools(registry: ToolRegistry) -> None:
    """Register camera capture tool."""
    registry.register(
        "camera.capture",
        lambda payload: {"ok": True, "tool": "camera.capture", "frame_id": payload.get("frame_id", "mock")},
    )
