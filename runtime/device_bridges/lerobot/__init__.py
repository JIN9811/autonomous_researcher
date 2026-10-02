"""Installed LeRobot bridge package with lazy, compatibility-safe exports."""

__all__ = ["LeRobotBridge", "LeRobotBridgeConfig", "register_lerobot_tools"]


def __getattr__(name: str):
    if name in {"LeRobotBridge", "LeRobotBridgeConfig"}:
        from device_bridges.lerobot import bridge

        return getattr(bridge, name)
    if name == "register_lerobot_tools":
        from device_bridges.lerobot.tools import register_lerobot_tools

        return register_lerobot_tools
    raise AttributeError(name)
