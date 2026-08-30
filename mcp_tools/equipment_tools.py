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
from utils.equipment_runtime_service import EquipmentRuntimeContractError, EquipmentRuntimeService


def register_equipment_tools(
    registry: ToolRegistry,
    devices_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> None:
    """Register Windows PyAutoGUI equipment bridge tools."""
    config = WindowsPyAutoGUIBridgeConfig.from_devices_config(devices_config or {}, repo_root=repo_root)
    bridge = WindowsPyAutoGUIBridge(config)
    runtime = EquipmentRuntimeService((repo_root or Path.cwd()) / "memory" / "equipment_runtime")

    def runtime_current(_payload: dict[str, Any]) -> dict[str, Any]:
        execution = runtime.latest()
        return {
            "ok": True,
            "execution": execution,
            "projection": EquipmentRuntimeService.project(execution) if execution else None,
        }

    def runtime_list(payload: dict[str, Any]) -> dict[str, Any]:
        executions = runtime.list(limit=int(payload.get("limit") or 100))
        return {
            "ok": True,
            "executions": executions,
            "projections": [EquipmentRuntimeService.project(item) for item in executions],
        }

    def runtime_get(payload: dict[str, Any]) -> dict[str, Any]:
        execution_id = str(payload.get("execution_id") or "").strip()
        try:
            execution = runtime.get(execution_id)
        except EquipmentRuntimeContractError as exc:
            return {"ok": False, "failure_code": "EQUIPMENT_EXECUTION_NOT_FOUND", "message": str(exc)}
        return {"ok": True, "execution": execution, "projection": EquipmentRuntimeService.project(execution)}

    registry.register("equipment.pyautogui.health", lambda payload: bridge.health(dict(payload or {})))
    registry.register("equipment.pyautogui.list_programs", lambda payload: bridge.list_programs(dict(payload or {})))
    registry.register("equipment.pyautogui.register_program", lambda payload: bridge.register_program(dict(payload or {})))
    registry.register("equipment.pyautogui.delete_program", lambda payload: bridge.delete_program(dict(payload or {})))
    registry.register("equipment.pyautogui.run", lambda payload: bridge.run(dict(payload or {})), device="equipment:windows_pyautogui")
    registry.register("equipment.pyautogui.screenshot", lambda payload: bridge.screenshot(dict(payload or {})))
    registry.register("equipment.pyautogui.list_locators", lambda payload: bridge.list_locators(dict(payload or {})))
    registry.register("equipment.pyautogui.request_log", lambda payload: bridge.request_log(dict(payload or {})))
    registry.register("equipment.pyautogui.capture_locator", lambda payload: bridge.capture_locator(dict(payload or {})), device="equipment:windows_pyautogui")
    registry.register("equipment.pyautogui.utm_profile", lambda payload: bridge.utm_profile_status())
    registry.register("equipment.pyautogui.save_utm_profile", lambda payload: bridge.save_utm_profile(dict(payload or {})))
    registry.register("equipment.pyautogui.connection_status", lambda payload: bridge.connection_status())
    registry.register("equipment.pyautogui.save_connection", lambda payload: bridge.save_connection(dict(payload or {})))
    registry.register("equipment.pyautogui.select_candidate", lambda payload: bridge.select_candidate(dict(payload or {})))
    registry.register("equipment.pyautogui.delete_candidate", lambda payload: bridge.delete_candidate(dict(payload or {})))
    registry.register("equipment.runtime.current", runtime_current)
    registry.register("equipment.runtime.list", runtime_list)
    registry.register("equipment.runtime.get", runtime_get)
    registry.register_resource("equipment_runtime", runtime)
