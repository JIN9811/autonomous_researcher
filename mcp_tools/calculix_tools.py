"""
File purpose:
- MCP tool wrapper for Improvement 15 CalculiX bridge operations.

Key classes/functions:
- register_calculix_tools

Inputs/outputs:
- Input: ToolRegistry and devices config.
- Output: calculix.health, calculix.prepare_input, calculix.solve, calculix.postprocess,
  and calculix.run_job handlers registered.

Dependencies:
- device_bridges.calculix_bridge
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: additional CalculiX endpoints and payload normalization.
- Risky places to edit: tool names and failure codes consumed by Analysis/Guardian/GUI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_bridges.calculix_bridge import CalculiXBridge, CalculiXBridgeConfig
from mcp_tools.tool_registry import ToolRegistry


def register_calculix_tools(
    registry: ToolRegistry,
    devices_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> CalculiXBridge:
    """Register CalculiX bridge tools and return the bridge instance."""
    config = CalculiXBridgeConfig.from_devices_config(devices_config or {}, repo_root=repo_root)
    bridge = CalculiXBridge(config)

    registry.register("calculix.health", lambda payload: bridge.health())
    registry.register("calculix.prepare_input", lambda payload: bridge.prepare_input(dict(payload or {})), device="cae:calculix")
    registry.register("calculix.solve", lambda payload: bridge.solve(dict(payload or {})), device="cae:calculix")
    registry.register("calculix.postprocess", lambda payload: bridge.postprocess(dict(payload or {})), device="cae:calculix")
    registry.register("calculix.run_job", lambda payload: bridge.run_job(dict(payload or {})), device="cae:calculix")
    registry.register_resource("calculix_bridge", bridge)
    return bridge
