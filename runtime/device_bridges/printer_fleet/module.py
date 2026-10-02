"""Describe the installed fleet without importing providers or reading their memory."""
import json
from device_bridges.module_contract import BridgeModule

MODULE = BridgeModule("printer_fleet", "1.0.0", json.dumps({
    "tools": ["printer.prepare", "device.health"],
    "registration": "mcp_tools.printer_tools.register_printer_tools",
    "label": "Printer Fleet",
    "runtime_bridge_ids": ["prusa_bridge"],
    "root": "device_bridges/printer_fleet",
    "requirements": "device_bridges/printer_fleet/requirements.txt",
    "manager": "device_bridges.printer_fleet.bridge.PrinterDeviceBridgeManager",
    "providers": [
        {"id": "bambu", "label": "Bambu", "version": "1.0.0", "component": "device_bridges.printer_fleet.providers.bambu",
         "requirements": "device_bridges/printer_fleet/providers/bambu-requirements.txt"},
        {"id": "prusa", "label": "Prusa", "version": "1.0.0", "component": "device_bridges.printer_fleet.providers.prusa",
         "requirements": "device_bridges/printer_fleet/providers/prusa-requirements.txt"}],
    "ui": {"workspace": "/printer", "api": "/api/printer", "assets": "web/static/printer.js"},
    "storage": {"fleet": "memory/printer_fleet.json", "bambu": "memory/bambu_connection.json",
                "prusa": "memory/prusa_connection.json", "artifacts": "artifacts/gcode"},
    "binding_requirements": [{"id": "printer_fleet_connection", "kind": "device",
                              "owner_id": "printer_fleet", "required": True}],
}, allow_nan=False))
