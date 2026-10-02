"""Describe the installed Windows/PyAutoGUI bridge without constructing it."""
import json

from device_bridges.module_contract import BridgeModule


MODULE = BridgeModule("windows_pyautogui", "1.0.0", json.dumps({
    "label": "Windows PyAutoGUI / UTM",
    "root": "device_bridges/windows_pyautogui",
    "requirements": "device_bridges/windows_pyautogui/requirements.txt",
    "registration": "device_bridges.windows_pyautogui.tools.register_equipment_tools",
    "runtime_bridge_ids": ["windows_pyautogui_bridge"],
    "tools": [
        "equipment.pyautogui.capture_locator",
        "equipment.pyautogui.connection_status",
        "equipment.pyautogui.delete_candidate",
        "equipment.pyautogui.delete_program",
        "equipment.pyautogui.health",
        "equipment.pyautogui.list_locators",
        "equipment.pyautogui.list_programs",
        "equipment.pyautogui.register_program",
        "equipment.pyautogui.request_log",
        "equipment.pyautogui.run",
        "equipment.pyautogui.save_connection",
        "equipment.pyautogui.save_utm_profile",
        "equipment.pyautogui.screenshot",
        "equipment.pyautogui.select_candidate",
        "equipment.pyautogui.utm_profile",
        "equipment.runtime.current",
        "equipment.runtime.get",
        "equipment.runtime.list",
    ],
    "providers": [
        {"id": "selected_worker", "label": "Selected Windows or local worker",
         "implementation": "device_bridges.windows_pyautogui.bridge.WindowsPyAutoGUIBridge"},
        {"id": "bundled_worker", "label": "Bundled Windows bridge server",
         "implementation": "Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py"},
        {"id": "local_worker", "label": "Local PyAutoGUI supervisor",
         "implementation": "utils.local_pyautogui_bridge.LocalPyAutoGUIBridgeSupervisor"},
    ],
    "ui": {
        "workspace": "/equipment/windows",
        "api": "/api/equipment/windows/readiness",
        "assets": "web/static/equipment_agent_manager.js",
    },
    "apis": [
        "/api/equipment/windows/readiness",
        "/api/equipment/windows/live-preflight",
        "/api/equipment/windows/discover",
        "/api/equipment/runtime",
    ],
    "configuration": "configs/devices.yaml",
    "storage": {
        "connection": "memory/windows_pyautogui_connection.json",
        "utm_profile": "memory/equipment_utm_profile.json",
        "runtime": "memory/equipment_runtime/",
        "skills": "memory/equipment_skills/",
        "run_artifacts": "runs",
    },
    "owned_references": {
        "installed_server": "install/windows_pyautogui_bridge_server.py",
        "windows_server": "Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py",
        "local_worker": "utils/local_pyautogui_bridge.py",
        "workspace_templates": [
            "web/templates/windows_equipment.html",
            "web/templates/equipment_agent_manager.html",
        ],
        "workspace_assets": [
            "web/static/windows_equipment.js",
            "web/static/windows_equipment_selection.js",
            "web/static/equipment_agent_manager.js",
        ],
        "profiles_skills_runtime": [
            "utils/equipment_profiles.py",
            "utils/equipment_skill_runtime.py",
            "utils/equipment_runtime_service.py",
            "utils/utm_csv.py",
        ],
    },
    "binding_requirements": [
        {"id": "windows_pyautogui_connection", "kind": "device",
         "owner_id": "windows_pyautogui", "required": True},
    ],
    "documentation": "device_bridges/windows_pyautogui/README.md",
}, allow_nan=False))
