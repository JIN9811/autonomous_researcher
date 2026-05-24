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

from device_bridges.prusa_bridge import PrinterAgenticWorkflow, PrusaBridgeConfig
from mcp_tools.tool_registry import ToolRegistry


def register_printer_tools(
    registry: ToolRegistry,
    devices_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> None:
    """Register printer tools using the safe PrusaBridge phase1 workflow."""
    config = PrusaBridgeConfig.from_devices_config(devices_config or {}, repo_root=repo_root)
    workflow = PrinterAgenticWorkflow(config, repo_root=repo_root)

    def printer_prepare(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        return workflow.prepare(normalized)

    def device_health(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        printer = workflow.health(normalized)
        return {
            "ok": bool(printer.get("ok", True)),
            "printer": printer,
            "camera": "ready",
            "robot": "ready",
            "utm": "ready",
            "simulator": "active" if str(printer.get("mode", "test")) != "live" else "mixed",
        }

    registry.register("printer.prepare", printer_prepare, device="printer:prusa_mk4s")
    registry.register("device.health", device_health)
