"""Installed Windows/PyAutoGUI bridge package with lazy compatibility exports."""

__all__ = [
    "WindowsPyAutoGUIBridge",
    "WindowsPyAutoGUIBridgeConfig",
    "discover_windows_pyautogui_bridges",
    "local_ipv4_scan_targets",
    "register_equipment_tools",
]


def __getattr__(name: str):
    if name in {
        "WindowsPyAutoGUIBridge",
        "WindowsPyAutoGUIBridgeConfig",
        "discover_windows_pyautogui_bridges",
        "local_ipv4_scan_targets",
    }:
        from device_bridges.windows_pyautogui import bridge

        return getattr(bridge, name)
    if name == "register_equipment_tools":
        from device_bridges.windows_pyautogui.tools import register_equipment_tools

        return register_equipment_tools
    raise AttributeError(name)
