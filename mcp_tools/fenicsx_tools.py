"""
File purpose:
- MCP tool wrapper for the optional FEniCSx FEM bridge.

Key classes/functions:
- register_fenicsx_tools

Inputs/outputs:
- Input: ToolRegistry and devices config.
- Output: fenicsx.health, fenicsx.set_runtime_solver, and fenicsx.run_linear_elasticity handlers.

Dependencies:
- device_bridges.fenicsx_bridge
- mcp_tools.tool_registry.ToolRegistry
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_bridges.fenicsx_bridge import FEniCSxBridge, FEniCSxBridgeConfig
from mcp_tools.tool_registry import ToolRegistry


def register_fenicsx_tools(
    registry: ToolRegistry,
    devices_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> FEniCSxBridge:
    """Register FEniCSx FEM bridge tools and return the bridge instance."""
    config = FEniCSxBridgeConfig.from_devices_config(devices_config or {}, repo_root=repo_root)
    bridge = FEniCSxBridge(config)

    registry.register("fenicsx.health", lambda payload: bridge.health(dict(payload or {})))
    registry.register("fenicsx.set_runtime_solver", lambda payload: bridge.set_runtime_solver(dict(payload or {})))
    registry.register(
        "fenicsx.run_linear_elasticity",
        lambda payload: bridge.run_linear_elasticity(dict(payload or {})),
        device="fenicsx:fem",
    )
    registry.register(
        "fenicsx.run_fem",
        lambda payload: bridge.run_linear_elasticity(dict(payload or {})),
        device="fenicsx:fem",
    )
    return bridge
