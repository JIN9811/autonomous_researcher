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
                    "provider": "prusa_mk4s",
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


def test_printer_prepare_defaults_to_bambu_when_no_profile_is_selected(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_printer_tools(
        registry,
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "bambu": {
                        "slicer": {"enabled": False, "output_dir": str(tmp_path / "bambu_sliced")},
                        "mqtt": {"timeout_sec": 0.1},
                    },
                }
            }
        },
        repo_root=tmp_path,
    )

    result = registry.call("printer.prepare", {"runtime_mode": "test", "run_id": "run-1", "specimen_id": "sp-1"})

    assert result["ok"] is True
    assert result["provider"] == "bambulab_x2d"
    assert result["selected_printer"]["profile_id"] == "bambulab_x2d_lab_01"
    assert result["automatic_fallback"] is False
    assert result["device_screen"]["schema"] == "printer_device_screen.v1"
    assert result["device_screen"]["job"]["progress_percent"] is None


def test_printer_prepare_prusa_path_requires_explicit_profile_selection(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_printer_tools(
        registry,
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "profiles": {
                        "bambulab_x2d_lab_01": {"provider": "bambulab_x2d", "enabled": True},
                        "prusa_mk4s_lab_01": {"provider": "prusa_mk4s", "enabled": True},
                    },
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "virtual_prusalink_dry_run": True,
                    "test_printer_live_promotion": {"enabled": True, "transport": "virtual"},
                    "slicer": {"enabled": False, "output_dir": str(tmp_path / "gcode")},
                }
            }
        },
        repo_root=tmp_path,
    )

    result = registry.call(
        "printer.prepare",
        {
            "runtime_mode": "test",
            "specimen_id": "sp-1",
            "stl_path": str(tmp_path / "specimen.stl"),
            "printer_profile_id": "prusa_mk4s_lab_01",
        },
    )

    assert result["provider"] == "prusa_mk4s"
    assert result["selected_printer"]["selection_reason"] == "explicit_profile_id"


def test_device_health_reports_virtual_printer(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_printer_tools(
        registry,
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "provider": "prusa_mk4s",
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
                    "provider": "prusa_mk4s",
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
