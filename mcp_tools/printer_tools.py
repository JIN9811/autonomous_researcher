"""
File purpose:
- MCP tool wrapper for printer-related operations.

Key classes/functions:
- register_printer_tools

Inputs/outputs:
- Input: ToolRegistry and devices config
- Output: printer.prepare and device.health handlers registered

Dependencies:
- device_bridges.prusa_bridge
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: payload normalization and health response decoration
- Risky places to edit: tool names consumed by specimen and guardian agents
- Related files: agents/specimen_agent.py, device_bridges/prusa_bridge.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_bridges.bambu_bridge import PrinterDeviceBridgeManager
from device_bridges.prusa_bridge import PrinterAgenticWorkflow, PrusaBridgeConfig
from mcp_tools.tool_registry import ToolRegistry


def register_printer_tools(
    registry: ToolRegistry,
    devices_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> None:
    """Register printer tools using the selected printer device bridge."""
    prusa_config = PrusaBridgeConfig.from_devices_config(devices_config or {}, repo_root=repo_root)
    prusa_workflow = PrinterAgenticWorkflow(prusa_config, repo_root=repo_root)
    bridge_manager = PrinterDeviceBridgeManager.from_devices_config(devices_config or {}, repo_root=repo_root)

    def selected_provider(payload: dict[str, Any]) -> str:
        profile, _reason = bridge_manager._select_profile(payload)  # noqa: SLF001 - local routing boundary.
        return str(profile.provider)

    def printer_prepare(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        if selected_provider(normalized) == "prusa_mk4s":
            result = prusa_workflow.prepare(normalized)
            profile, reason = bridge_manager._select_profile(normalized)  # noqa: SLF001 - local routing boundary.
            result.setdefault("provider", "prusa_mk4s")
            result.setdefault(
                "selected_printer",
                {
                    **profile.redacted(),
                    "locked": True,
                    "selection_reason": reason,
                    "automatic_fallback_allowed": bridge_manager.config.allow_automatic_fallback,
                },
            )
            result.setdefault("automatic_fallback", False)
            return result
        return bridge_manager.prepare(normalized)

    def device_health(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        printer = (
            prusa_workflow.health(normalized)
            if selected_provider(normalized) == "prusa_mk4s"
            else bridge_manager.health(normalized)
        )
        return {
            "ok": bool(printer.get("ok", True)),
            "printer": printer,
            "camera": "ready",
            "robot": "ready",
            "utm": "ready",
            "simulator": "active" if str(printer.get("mode", "test")) != "live" else "mixed",
        }

    registry.register("printer.prepare", printer_prepare, device="printer:fleet")
    registry.register("device.health", device_health)
