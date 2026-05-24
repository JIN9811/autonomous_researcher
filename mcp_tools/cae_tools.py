"""
File purpose:
- MCP tool wrapper for open-source CAE analysis bridge operations.

Key classes/functions:
- register_cae_tools

Inputs/outputs:
- Input: ToolRegistry and devices config.
- Output: cae.health and cae.run_static_analysis handlers registered.

Dependencies:
- device_bridges.cae_bridge
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: payload normalization and additional CAE endpoints.
- Risky places to edit: tool names consumed by AnalysisAgent and GUI.
- Related files: agents/analysis_agent.py, app/bootstrap.py, app/main.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_bridges.cae_bridge import CAEBridge, CAEBridgeConfig
from mcp_tools.tool_registry import ToolRegistry


def register_cae_tools(
    registry: ToolRegistry,
    devices_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> CAEBridge:
    """Register CAE bridge tools and return the bridge instance."""
    config = CAEBridgeConfig.from_devices_config(devices_config or {}, repo_root=repo_root)
    bridge = CAEBridge(config)

    registry.register("cae.health", lambda payload: bridge.solver_status())
    registry.register(
        "cae.run_static_analysis",
        lambda payload: bridge.run_static_analysis(dict(payload or {})),
        device="cae:calculix",
    )
    return bridge
