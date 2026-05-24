"""
File purpose:
- MCP tool wrapper for Windows PyAutoGUI equipment bridge operations.

Key classes/functions:
- register_equipment_tools

Inputs/outputs:
- Input: ToolRegistry and devices config.
- Output: equipment.pyautogui.* handlers registered.

Dependencies:
- device_bridges.windows_pyautogui_bridge
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: tool names and payload normalization additions.
- Risky places to edit: live execution gates inside the bridge client.
- Related files: agents/equipment_agent.py, app/bootstrap.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_bridges.windows_pyautogui_bridge import (
    WindowsPyAutoGUIBridge,
    WindowsPyAutoGUIBridgeConfig,
)
from mcp_tools.tool_registry import ToolRegistry


def register_equipment_tools(
    registry: ToolRegistry,
    devices_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> None:
    """Register Windows PyAutoGUI equipment bridge tools."""
    config = WindowsPyAutoGUIBridgeConfig.from_devices_config(devices_config or {}, repo_root=repo_root)
    bridge = WindowsPyAutoGUIBridge(config)

    registry.register("equipment.pyautogui.health", lambda payload: bridge.health(dict(payload or {})))
    registry.register("equipment.pyautogui.list_programs", lambda payload: bridge.list_programs(dict(payload or {})))
    registry.register("equipment.pyautogui.run", lambda payload: bridge.run(dict(payload or {})), device="equipment:windows_pyautogui")
    registry.register("equipment.pyautogui.connection_status", lambda payload: bridge.connection_status())
    registry.register("equipment.pyautogui.save_connection", lambda payload: bridge.save_connection(dict(payload or {})))
    registry.register("equipment.pyautogui.select_candidate", lambda payload: bridge.select_candidate(dict(payload or {})))
    registry.register("equipment.pyautogui.delete_candidate", lambda payload: bridge.delete_candidate(dict(payload or {})))
