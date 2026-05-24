"""
File purpose:
- Register LeRobot / ROBOTIS MCP-style tools.

Key classes/functions:
- register_lerobot_tools

Inputs/outputs:
- Input: ToolRegistry, configs/lerobot.yaml data
- Output: registered lerobot.* tool handlers

Dependencies:
- device_bridges.lerobot_bridge
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: additive tool names and payload normalization
- Risky places to edit: response key contracts consumed by GUI/tests
- Related files: app/bootstrap.py, app/main.py, agents/manipulation_agent.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from mcp_tools.tool_registry import ToolRegistry


def register_lerobot_tools(
    registry: ToolRegistry,
    lerobot_config: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> LeRobotBridge:
    """Register LeRobot tools and return the bridge instance."""
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config(lerobot_config or {}, repo_root=repo_root))

    registry.register("lerobot.profiles.list", lambda payload: bridge.profiles_list(dict(payload or {})))
    registry.register("lerobot.profiles.validate", lambda payload: bridge.profiles_validate(dict(payload or {})))
    registry.register("lerobot.find_ports", lambda payload: bridge.find_ports(dict(payload or {})))
    registry.register("lerobot.ports.baseline", lambda payload: bridge.ports_baseline(dict(payload or {})))
    registry.register("lerobot.ports.detect", lambda payload: bridge.ports_detect(dict(payload or {})))
    registry.register("lerobot.ports.save", lambda payload: bridge.ports_save(dict(payload or {})))
    registry.register("lerobot.ports.delete", lambda payload: bridge.ports_delete(dict(payload or {})))
    registry.register("lerobot.camera.test", lambda payload: bridge.camera_test(dict(payload or {})))
    registry.register("lerobot.teleoperate.start", lambda payload: bridge.teleoperate_start(dict(payload or {})))
    registry.register("lerobot.teleoperate.stop", lambda payload: bridge.teleoperate_stop(dict(payload or {})))
    registry.register("lerobot.teleoperate.status", lambda payload: bridge.teleoperate_status(dict(payload or {})))
    registry.register("lerobot.record.start", lambda payload: bridge.record_start(dict(payload or {})))
    registry.register("lerobot.record.control", lambda payload: bridge.record_control(dict(payload or {})))
    registry.register("lerobot.record.status", lambda payload: bridge.record_status(dict(payload or {})))
    registry.register("lerobot.train.start", lambda payload: bridge.train_start(dict(payload or {})))
    registry.register("lerobot.train.cancel", lambda payload: bridge.train_cancel(dict(payload or {})))
    registry.register("lerobot.train.status", lambda payload: bridge.train_status(dict(payload or {})))
    registry.register("lerobot.rollout.start", lambda payload: bridge.rollout_start(dict(payload or {})))
    registry.register("lerobot.rollout.stop", lambda payload: bridge.rollout_stop(dict(payload or {})))
    registry.register("lerobot.rollout.status", lambda payload: bridge.rollout_status(dict(payload or {})))
    registry.register("lerobot.dataset.inspect", lambda payload: bridge.dataset_inspect(dict(payload or {})))
    registry.register("lerobot.dataset.visualize", lambda payload: bridge.visualize_dataset(dict(payload or {})))
    registry.register("lerobot.visualize.start", lambda payload: bridge.visualize_start(dict(payload or {})))
    registry.register("lerobot.visualize.stop", lambda payload: bridge.visualize_stop(dict(payload or {})))
    registry.register("lerobot.visualize.status", lambda payload: bridge.visualize_status(dict(payload or {})))
    registry.register("lerobot.policies.list", lambda payload: bridge.policies_list(dict(payload or {})))
    registry.register("lerobot.policy.download", lambda payload: bridge.policy_download(dict(payload or {})))
    return bridge
