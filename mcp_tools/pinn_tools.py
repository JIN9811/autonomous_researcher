"""
File purpose:
- MCP tool wrapper for Improvement 15 PINN bridge operations.

Key classes/functions:
- register_pinn_tools

Inputs/outputs:
- Input: ToolRegistry and devices config.
- Output: pinn.health, pinn.dataset.build, pinn.train, pinn.predict, and pinn.registry
  handlers registered.

Dependencies:
- device_bridges.pinn_bridge
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: model registry metadata and optional training/prediction adapters.
- Risky places to edit: unavailable semantics consumed by Analysis/GUI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_bridges.pinn_bridge import PINNBridge, PINNBridgeConfig
from mcp_tools.tool_registry import ToolRegistry


def register_pinn_tools(
    registry: ToolRegistry,
    devices_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> PINNBridge:
    """Register PINN bridge tools and return the bridge instance."""
    config = PINNBridgeConfig.from_devices_config(devices_config or {}, repo_root=repo_root)
    bridge = PINNBridge(config)

    registry.register("pinn.health", lambda payload: bridge.health())
    registry.register("pinn.dataset.build", lambda payload: bridge.build_dataset(dict(payload or {})), device="analysis:pinn")
    registry.register("pinn.train", lambda payload: bridge.train(dict(payload or {})), device="analysis:pinn")
    registry.register("pinn.predict", lambda payload: bridge.predict(dict(payload or {})), device="analysis:pinn")
    registry.register("pinn.registry", lambda payload: bridge.registry(dict(payload or {})))
    registry.register_resource("pinn_bridge", bridge)
    return bridge
