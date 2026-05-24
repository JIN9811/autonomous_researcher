"""Unit tests for printer tool registration."""

from __future__ import annotations

from pathlib import Path

from mcp_tools.printer_tools import register_printer_tools
from mcp_tools.tool_registry import ToolRegistry


def test_printer_prepare_test_mode_schema(tmp_path: Path) -> None:
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    registry = ToolRegistry()
    register_printer_tools(
        registry,
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "virtual_prusalink_dry_run": True,
                    "connection_memory_path": str(tmp_path / "prusa_connection.json"),
                    "test_printer_live_promotion": {"enabled": True, "transport": "virtual"},
                    "slicer": {"enabled": False, "output_dir": str(tmp_path / "gcode")},
                }
            }
        },
        repo_root=tmp_path,
    )

    result = registry.call("printer.prepare", {"runtime_mode": "test", "specimen_id": "sp-1", "stl_path": str(stl)})

    assert result["ok"] is True
    assert result["tool"] == "printer.prepare"
    assert result["specimen_id"] == "sp-1"
    assert isinstance(result["print_result"], dict)
    assert isinstance(result["ejection_result"], dict)
    assert isinstance(result["step_trace"], list)
    assert result["slicer_settings"]["output_gcode_path"] == result["sliced_path"]
    assert result["prusalink"]["transport"] == "virtual"


def test_device_health_reports_virtual_printer(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_printer_tools(
        registry,
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "virtual_prusalink_dry_run": True,
                    "connection_memory_path": str(tmp_path / "prusa_connection.json"),
                }
            }
        },
        repo_root=tmp_path,
    )

    result = registry.call("device.health", {"runtime_mode": "test"})

    assert result["ok"] is True
    assert result["printer"]["state"] in {"VIRTUAL_PRUSALINK_READY", "SIMULATED_READY"}


def test_device_health_live_missing_connection_info_is_structured(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_printer_tools(
        registry,
        {
            "devices": {
                "printer": {
                    "mode": "live",
                    "virtual_prusalink_dry_run": True,
                    "connection_memory_path": str(tmp_path / "prusa_connection.json"),
                    "live": {"allow_status": True, "auth": {"mode": "api_key"}},
                }
            }
        },
        repo_root=tmp_path,
    )

    result = registry.call("device.health", {"runtime_mode": "live"})

    assert result["ok"] is False
    assert result["printer"]["failure_code"] == "PRINTER_CONNECTION_INFO_REQUIRED"
    assert result["printer"]["requires_connection_info"] is True
