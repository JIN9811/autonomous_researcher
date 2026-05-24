"""Integration-style tests for printer workflow mode selection."""

from __future__ import annotations

from pathlib import Path

from device_bridges.prusa_bridge import PrinterAgenticWorkflow, PrusaBridgeConfig


def _ejection_cfg() -> dict:
    return {
        "enabled": True,
        "calibration_id": "cal-test",
        "paddle": {
            "safe_z_mm": 20,
            "sweep_z_mm": 5,
            "sweep_start_x_mm": 10,
            "sweep_start_y_mm": 10,
            "sweep_end_x_mm": 120,
            "sweep_end_y_mm": 10,
            "sweep_feedrate_mm_min": 1000,
            "park_x_mm": 5,
            "park_y_mm": 5,
        },
    }


def _config(tmp_path: Path, *, mode: str, live_transport: str = "virtual") -> PrusaBridgeConfig:
    return PrusaBridgeConfig.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": mode,
                    "provider": "prusa_mk4s",
                    "virtual_prusalink_dry_run": True,
                    "connection_memory_path": str(tmp_path / "prusa_connection.json"),
                    "test_printer_live_promotion": {"enabled": True, "transport": "virtual"},
                    "live": {
                        "transport": live_transport,
                        "host_env": "PRUSA_HOST_UNSET_FOR_TEST",
                        "scheme": "http",
                        "port": 80,
                        "storage": "usb",
                        "allow_status": True,
                        "allow_upload": True,
                        "allow_start_print": True,
                        "allow_ejection": True,
                        "auth": {"mode": "none"},
                    },
                    "slicer": {"enabled": False, "output_dir": str(tmp_path / "gcode")},
                    "ejection": _ejection_cfg(),
                }
            }
        },
        repo_root=tmp_path,
    )


def test_live_mode_armed_workflow_over_test_communication_bridge(tmp_path: Path) -> None:
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(_config(tmp_path, mode="live", live_transport="virtual"), repo_root=tmp_path)

    result = workflow.prepare(
        {
            "runtime_mode": "live",
            "specimen_id": "sp-live",
            "stl_path": str(stl),
            "print": {"start_immediately": True, "storage": "usb"},
            "ejection": {"enabled": True},
        }
    )

    assert result["ok"] is True
    assert result["mode"] == "live"
    assert result["printer_path"] == "virtual_prusalink"
    assert result["print_result"]["status"] == "virtual_finished"
    assert result["ejection_result"]["status"] == "virtual_ack"
    assert result["status"] == "simulated_printed_and_ejected"


def test_test_mode_printer_live_promotion_is_printer_only_over_virtual_bridge(tmp_path: Path) -> None:
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(_config(tmp_path, mode="test"), repo_root=tmp_path)

    result = workflow.prepare({"runtime_mode": "test", "specimen_id": "sp-test", "stl_path": str(stl)})

    assert result["ok"] is True
    assert result["mode"] == "test_printer_live_virtual"
    assert result["printer_path"] == "virtual_prusalink"
    assert result["operator_messages"]
    assert result["print_result"]["status"] == "virtual_finished"
