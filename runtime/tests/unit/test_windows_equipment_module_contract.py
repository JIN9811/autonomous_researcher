"""Consumer contract for the installed Windows/PyAutoGUI equipment bridge."""
from __future__ import annotations

import importlib
from pathlib import Path


TOOL_IDS = {
    "equipment.pyautogui.health",
    "equipment.pyautogui.list_programs",
    "equipment.pyautogui.register_program",
    "equipment.pyautogui.delete_program",
    "equipment.pyautogui.run",
    "equipment.pyautogui.screenshot",
    "equipment.pyautogui.list_locators",
    "equipment.pyautogui.request_log",
    "equipment.pyautogui.capture_locator",
    "equipment.pyautogui.utm_profile",
    "equipment.pyautogui.save_utm_profile",
    "equipment.pyautogui.connection_status",
    "equipment.pyautogui.save_connection",
    "equipment.pyautogui.select_candidate",
    "equipment.pyautogui.delete_candidate",
    "equipment.runtime.current",
    "equipment.runtime.list",
    "equipment.runtime.get",
}


def test_windows_equipment_bridge_discovery_identity_and_repository_sources():
    from device_bridges.module_discovery import discover_bridge_modules

    modules = {module.module_id: module.describe() for module in discover_bridge_modules()}
    descriptor = modules["windows_pyautogui"]
    assert descriptor["version"] == "1.0.0"
    assert descriptor["runtime_bridge_ids"] == ["windows_pyautogui_bridge"]
    assert descriptor["registration"] == "device_bridges.windows_pyautogui.tools.register_equipment_tools"
    assert descriptor["root"] == "device_bridges/windows_pyautogui"
    assert descriptor["tools"] == sorted(TOOL_IDS)
    assert descriptor["ui"] == {
        "workspace": "/equipment/windows",
        "api": "/api/equipment/windows/readiness",
        "assets": "web/static/equipment_agent_manager.js",
    }
    root = Path(__file__).resolve().parents[2]
    for key in ("requirements", "documentation"):
        assert (root / descriptor[key]).is_file()
    for path in descriptor["owned_references"].values():
        for item in path if isinstance(path, list) else [path]:
            assert (root / item).exists(), item


def test_windows_equipment_legacy_imports_share_canonical_module_identity(monkeypatch):
    bridge = importlib.import_module("device_bridges.windows_pyautogui.bridge")
    tools = importlib.import_module("device_bridges.windows_pyautogui.tools")
    assert importlib.import_module("device_bridges.windows_pyautogui_bridge") is bridge
    assert importlib.import_module("mcp_tools.equipment_tools") is tools
    monkeypatch.setattr(bridge, "_identity_probe", "bridge", raising=False)
    monkeypatch.setattr(tools, "_identity_probe", "tools", raising=False)
    assert importlib.import_module("device_bridges.windows_pyautogui_bridge")._identity_probe == "bridge"
    assert importlib.import_module("mcp_tools.equipment_tools")._identity_probe == "tools"


def test_windows_equipment_tool_ids_queue_names_and_resources_are_unchanged(tmp_path):
    from device_bridges.windows_pyautogui.tools import register_equipment_tools
    from mcp_tools.tool_registry import ToolRegistry

    class Queue:
        def __init__(self):
            self.calls = []

        def submit_sync(self, *, device, tool_name, handler, payload):
            self.calls.append((device, tool_name))
            return handler(payload)

        def status(self):
            return {"calls": list(self.calls)}

    queue = Queue()
    registry = ToolRegistry(job_queue=queue)
    bridge = register_equipment_tools(
        registry,
        {"devices": {"equipment": {"mode": "simulator", "windows_pyautogui": {
            "connection_memory_path": str(tmp_path / "connection.json"),
        }}}},
        repo_root=tmp_path,
    )
    assert set(registry.list_tools()) == TOOL_IDS
    assert registry.resource("equipment.bridge") is bridge
    assert registry.resource("equipment_runtime") is not None
    assert registry.call("equipment.pyautogui.run", {
        "runtime_mode": "test", "program_id": "program1", "sequence_id": "queue-contract"
    })["ok"] is True
    registry.call("equipment.pyautogui.capture_locator", {"runtime_mode": "test"})
    assert queue.calls == [
        ("equipment:windows_pyautogui", "equipment.pyautogui.run"),
        ("equipment:windows_pyautogui", "equipment.pyautogui.capture_locator"),
    ]


def test_equipment_package_resolves_one_installed_windows_bridge_without_activation(monkeypatch):
    from agents.equipment.module import MODULE as equipment
    from device_bridges.module_discovery import discover_bridge_modules
    from device_bridges.windows_pyautogui.bridge import WindowsPyAutoGUIBridge
    from packages.service import PackageService, installed_agent_packages

    monkeypatch.setattr(
        WindowsPyAutoGUIBridge,
        "__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("catalog activated equipment bridge")),
    )
    packages = installed_agent_packages([equipment.describe()])
    bridges = [module.describe() for module in discover_bridge_modules()]
    service = PackageService(
        agent_packages=packages,
        bridge_modules=bridges,
        installed_handlers=["agent.equipment_agent"],
        installed_module_ids=["equipment"],
        validate_graph=lambda _raw: [],
        validate_module=lambda _ident, _raw: [],
    )
    catalog = service.catalog()
    assert catalog["ok"], catalog
    package = catalog["agent_packages"][0]
    assert package["bridge_modules"] == [{"id": "windows_pyautogui", "version": "1.0.0"}]
    bridge = next(item for item in catalog["bridge_modules"] if item["id"] == "windows_pyautogui")
    assert bridge["package_owners"] == [{"id": "equipment", "version": "1.0.0"}]
