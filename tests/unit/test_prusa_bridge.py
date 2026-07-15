"""Unit tests for PrusaBridge phase1 safety and virtual printer workflow."""

from __future__ import annotations

import json
from pathlib import Path

from device_bridges.prusa_bridge import (
    EjectionConfig,
    GCodeObjectBounds,
    GCodeObjectBoundsExtractor,
    GCodeSafetyValidator,
    PaddleEjectionRoutineBuilder,
    PrinterAgenticWorkflow,
    PrusaBridgeConfig,
    PrusaLinkClient,
    PrusaSlicerRunner,
)


def _config(tmp_path: Path, *, mode: str = "test", ejection: dict | None = None) -> PrusaBridgeConfig:
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
                        "host_env": "PRUSA_HOST_UNSET_FOR_TEST",
                        "scheme": "http",
                        "port": 80,
                        "storage": "usb",
                        "allow_status": True,
                        "allow_upload": False,
                        "allow_start_print": False,
                        "allow_ejection": False,
                        "auth": {"mode": "none"},
                    },
                    "slicer": {"enabled": False, "output_dir": str(tmp_path / "gcode")},
                    "ejection": ejection or {"enabled": False},
                }
            }
        },
        repo_root=tmp_path,
    )


def test_prusa_bridge_config_defaults_are_safe(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    assert cfg.mode == "test"
    assert cfg.virtual_prusalink_dry_run is True
    assert cfg.live_gate("allow_upload") is False
    assert cfg.live_gate("allow_start_print") is False
    assert cfg.live_gate("allow_ejection") is False


def test_prusalink_client_refuses_upload_when_gate_false(tmp_path: Path) -> None:
    cfg = _config(tmp_path, mode="live")
    local = tmp_path / "specimen.gcode"
    local.write_text("M84\n", encoding="utf-8")
    client = PrusaLinkClient(
        config=cfg,
        connection={"host": "127.0.0.1", "scheme": "http", "port": 80, "auth": {"mode": "none"}},
        transport="real",
    )

    result = client.upload_file(local, "usb", "specimen.gcode")

    assert result["ok"] is False
    assert result["failure_code"] == "UPLOAD_DISABLED"


def test_prusalink_client_uses_replayable_bytes_for_digest_upload(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path, mode="live")
    cfg.live["allow_upload"] = True
    cfg.live["timeouts"] = {"connect_sec": 5, "request_sec": 60, "upload_sec": 900}
    local = tmp_path / "specimen.gcode"
    local.write_bytes(b"G28\n")
    captured = {}

    class FakeResponse:
        status_code = 201
        content = b""
        text = ""

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured["auth"] = kwargs.get("auth")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def request(self, method, url, *, headers=None, content=None):
            captured.update({"method": method, "url": url, "headers": headers, "content": content})
            return FakeResponse()

    monkeypatch.setattr("device_bridges.prusa_bridge.httpx.Client", FakeClient)
    client = PrusaLinkClient(
        config=cfg,
        connection={
            "host": "127.0.0.1",
            "scheme": "http",
            "port": 80,
            "auth": {"mode": "digest", "username": "maker", "password": "secret"},
        },
        transport="real",
    )

    result = client.upload_file(local, "usb", "specimen.gcode", overwrite=True)

    assert result["ok"] is True
    assert captured["method"] == "PUT"
    assert captured["content"] == b"G28\n"
    assert result["timeout_kind"] == "upload"
    assert result["timeout_sec"] == 900


def test_prusalink_client_maps_507_to_storage_unavailable(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path, mode="live")
    cfg.live["allow_upload"] = True
    local = tmp_path / "specimen.gcode"
    local.write_bytes(b"G28\n")

    class FakeResponse:
        status_code = 507
        content = b"Failed to write to location"
        text = "507: Insufficient Storage\n\nFailed to write to location\n"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def request(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("device_bridges.prusa_bridge.httpx.Client", FakeClient)
    client = PrusaLinkClient(
        config=cfg,
        connection={"host": "127.0.0.1", "scheme": "http", "port": 80, "auth": {"mode": "none"}},
        transport="real",
    )

    result = client.upload_file(local, "usb", "specimen.gcode")

    assert result["ok"] is False
    assert result["failure_code"] == "PRINTER_STORAGE_UNAVAILABLE"
    assert result["status_code"] == 507


def test_prusalink_client_refuses_start_when_gate_false(tmp_path: Path) -> None:
    cfg = _config(tmp_path, mode="live")
    client = PrusaLinkClient(
        config=cfg,
        connection={"host": "127.0.0.1", "scheme": "http", "port": 80, "auth": {"mode": "none"}},
        transport="real",
    )

    result = client.start_file("usb", "specimen.gcode")

    assert result["ok"] is False
    assert result["failure_code"] == "START_PRINT_DISABLED"


def test_gcode_safety_validator_rejects_out_of_bounds_coordinate() -> None:
    validator = GCodeSafetyValidator(EjectionConfig())

    result = validator.validate_ejection_gcode("G90\nG1 X999 Y10 Z10 F1200\n")

    assert result["ok"] is False
    assert result["failure_code"] == "GCODE_UNSAFE_COORDINATE"


def test_gcode_safety_validator_rejects_heating_in_ejection() -> None:
    validator = GCodeSafetyValidator(EjectionConfig())

    result = validator.validate_ejection_gcode("M104 S200\n")

    assert result["ok"] is False
    assert result["failure_code"] == "GCODE_UNSAFE_HEATING"


def test_gcode_safety_validator_accepts_bed_sweep_cooling_and_progress_codes() -> None:
    ejection = EjectionConfig.from_dict(
        {
            "method": "bed_sweep",
            "max_bed_temp_c": 40.0,
            "max_feedrate_mm_min": 25000,
        }
    )
    validator = GCodeSafetyValidator(ejection)

    result = validator.validate_ejection_gcode(
        "\n".join(
            [
                "M400",
                "M190 R40",
                "G90",
                "G0 Y210 F6000",
                "M73 P99 R0",
                "M73 Q99 S0",
                "G0 X125 F6000",
                "G0 Z1 F3000",
                "G0 Y6 F25000",
                "G28 X Y",
                "M84 X Y E",
                "M104 S0",
                "M140 S0",
                "M400",
                "M73 P100 R0",
                "M73 Q100 S0",
            ]
        )
    )

    assert result["ok"] is True


def test_gcode_safety_validator_rejects_unsupported_ready_command() -> None:
    ejection = EjectionConfig.from_dict(
        {
            "method": "bed_sweep",
            "max_bed_temp_c": 40.0,
            "max_feedrate_mm_min": 25000,
        }
    )
    validator = GCodeSafetyValidator(ejection)

    result = validator.validate_ejection_gcode("M400\nM1200\n")

    assert result["ok"] is False
    assert result["failure_code"] == "GCODE_UNSAFE_COMMAND"


def test_gcode_object_bounds_extractor_uses_extrusion_moves() -> None:
    bounds = GCodeObjectBoundsExtractor.from_text(
        "\n".join(
            [
                "G90",
                "M82",
                "G1 X30 Y40 Z0.2 F1200",
                "G1 X70 Y40 E0.5",
                "G1 X70 Y80 E1.0",
                "G1 X30 Y80 E1.5",
                "G1 E1.0 ; retract",
                "G92 E0",
                "G1 X50 Y90 E0.4",
                "G1 X5 Y5 F3000 ; travel move should not affect object bounds",
            ]
        )
    )

    assert bounds is not None
    assert bounds.to_dict()["x_min_mm"] == 30.0
    assert bounds.to_dict()["x_max_mm"] == 70.0
    assert bounds.to_dict()["center_x_mm"] == 50.0
    assert bounds.to_dict()["y_min_mm"] == 40.0
    assert bounds.to_dict()["y_max_mm"] == 90.0


def test_paddle_ejection_builder_requires_calibration() -> None:
    builder = PaddleEjectionRoutineBuilder(EjectionConfig(enabled=True))

    result = builder.build()

    assert result["ok"] is False
    assert result["failure_code"] == "EJECTION_NOT_CALIBRATED"


def test_paddle_ejection_builder_generates_valid_gcode_from_calibration() -> None:
    ejection = EjectionConfig.from_dict(
        {
            "enabled": True,
            "calibration_id": "cal-1",
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
    )
    builder = PaddleEjectionRoutineBuilder(ejection)

    result = builder.build()

    assert result["ok"] is True
    assert "AUTO-GENERATED PADDLE EJECTION" in result["gcode"]


def test_bed_sweep_ejection_builder_generates_video_style_append_gcode() -> None:
    ejection = EjectionConfig.from_dict(
        {
            "enabled": True,
            "method": "bed_sweep",
            "mode": "append_end_gcode",
            "max_bed_temp_c": 40.0,
            "max_feedrate_mm_min": 25000,
            "calibration_id": "mk4s-bed-sweep-test",
        }
    )
    builder = PaddleEjectionRoutineBuilder(ejection)

    result = builder.build(object_bounds=GCodeObjectBounds(40.0, 80.0, 60.0, 90.0, 0.2, 20.0, 4))

    assert result["ok"] is True
    assert "AUTO-GENERATED BED-SWEEP EJECTION" in result["gcode"]
    assert "M190 R40" in result["gcode"]
    assert "G0 X60 F6000" in result["gcode"]
    assert "G0 Z10 F3000" in result["gcode"]
    assert "G0 Y6 F25000" in result["gcode"]
    assert "G28 X Y" in result["gcode"]
    assert "M73 Q100 S0" in result["gcode"]
    assert result["gcode"].rstrip().endswith("M73 Q100 S0")
    assert result["resolved"]["head_x_source"] == "gcode_object_bounds"
    assert result["resolved"]["head_z_mm"] == 10.0
    assert result["resolved"]["head_z_source"] == "gcode_object_top_minus_offset"


def test_bed_sweep_ejection_builder_clamps_short_object_push_height_to_one_mm() -> None:
    ejection = EjectionConfig.from_dict(
        {
            "enabled": True,
            "method": "bed_sweep",
            "mode": "append_end_gcode",
            "max_bed_temp_c": 40.0,
            "max_feedrate_mm_min": 25000,
        }
    )
    builder = PaddleEjectionRoutineBuilder(ejection)

    result = builder.build(object_bounds=GCodeObjectBounds(40.0, 80.0, 60.0, 90.0, 0.2, 11.0, 4))

    assert result["ok"] is True
    assert "G0 Z1 F3000" in result["gcode"]
    assert result["resolved"]["head_z_mm"] == 1.0


def test_virtual_prusalink_dry_run_reaches_action_boundary(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)

    result = workflow.prepare({"runtime_mode": "test", "specimen_id": "sp-1", "stl_path": str(stl)})

    assert result["ok"] is True
    assert result["mode"] == "test_printer_live_virtual"
    assert result["printer_path"] == "virtual_prusalink"
    assert result["print_result"]["status"] == "virtual_finished"
    assert result["printer"]["status"]["transport"] == "virtual_prusalink"
    assert any(step["step"] == "UPLOAD" for step in result["step_trace"])
    assert result["sliced_path"] and Path(result["sliced_path"]).exists()
    assert result["slicer_settings"]["output_gcode_path"] == result["sliced_path"]
    assert result["slicer_result"]["simulated"] is True
    assert result["gcode_validation"]["ok"] is True
    assert result["prusalink"]["upload_endpoint"].startswith("/api/v1/files/")


def test_prusa_slicer_settings_preserve_final_design_values(tmp_path: Path) -> None:
    runner = PrusaSlicerRunner(_config(tmp_path).slicer, repo_root=tmp_path)

    settings = runner._settings_snapshot(
        source=tmp_path / "specimen.stl",
        output_path=tmp_path / "specimen.gcode",
        simulate=True,
        specimen_id="sp-final",
        printer_profile="prusa_mk4s_pla_0p4_nozzle",
        material="PLA",
        slicer_profile_hint="0p2mm_quality",
        experiment_spec={
            "layer_height_mm": 0.2,
            "first_layer_height_mm": 0.2,
            "nozzle_diameter_mm": 0.4,
            "slow_first_layer_enabled": True,
            "first_layer_speed_mm_s": 9.0,
            "bed_temperature_c": 60.0,
            "first_layer_bed_temperature_c": 65.0,
            "cell_size_mm": 7.5,
            "relative_density": 0.32,
            "expected_mass_g": 6.026,
            "skirt_enabled": False,
            "top_cap_enabled": False,
            "bottom_cap_enabled": False,
            "top_bottom_cap": False,
            "skin_thickness_mm": 0.0,
        },
    )

    assert PrusaSlicerRunner._layer_height_from_hint("0p2mm_quality") == 0.2
    assert PrusaSlicerRunner._layer_height_from_hint("0.2mm_quality") == 0.2
    assert settings["layer_height_mm"] == 0.2
    assert settings["first_layer_height_mm"] == 0.2
    assert settings["nozzle_diameter_mm"] == 0.4
    assert settings["bed_temperature_c"] == 60.0
    assert settings["first_layer_bed_temperature_c"] == 65.0
    assert settings["slow_first_layer_enabled"] is True
    assert settings["first_layer_speed_mm_s"] == 9.0
    assert settings["cell_size_mm"] == 7.5
    assert settings["relative_density"] == 0.32
    assert settings["expected_mass_g"] == 6.026
    assert settings["skirt_enabled"] is False
    assert settings["top_cap_enabled"] is False
    assert settings["bottom_cap_enabled"] is False
    assert settings["top_bottom_cap"] is False
    assert settings["skin_thickness_mm"] == 0.0
    assert "--skirts=0" in settings["resolved_command"]
    assert "--brim-width=0" in settings["resolved_command"]
    assert "--raft-layers=0" in settings["resolved_command"]
    assert "--layer-height=0.2" in settings["resolved_command"]
    assert "--first-layer-height=0.2" in settings["resolved_command"]
    assert "--bed-temperature=60" in settings["resolved_command"]
    assert "--first-layer-bed-temperature=65" in settings["resolved_command"]
    assert "--first-layer-speed=9" in settings["resolved_command"]


def test_prusa_slicer_runner_keeps_auxiliary_adhesion_optional(tmp_path: Path) -> None:
    runner = PrusaSlicerRunner(_config(tmp_path).slicer, repo_root=tmp_path)

    settings = runner._settings_snapshot(
        source=tmp_path / "specimen.stl",
        output_path=tmp_path / "specimen.gcode",
        simulate=False,
        specimen_id="sp-skirt",
        printer_profile="prusa_mk4s_pla_0p4_nozzle",
        material="PLA",
        slicer_profile_hint="0.2mm_quality",
        experiment_spec={"skirt_enabled": True},
    )

    assert settings["skirt_enabled"] is True
    assert "--skirts=0" not in settings["resolved_command"]
    assert "--layer-height=0.2" in settings["resolved_command"]
    assert "--first-layer-height=0.2" in settings["resolved_command"]
    assert "--bed-temperature=60" in settings["resolved_command"]
    assert "--first-layer-bed-temperature=60" in settings["resolved_command"]
    assert "--first-layer-speed=10" in settings["resolved_command"]


def test_prusa_slicer_runner_can_disable_slow_first_layer_option(tmp_path: Path) -> None:
    runner = PrusaSlicerRunner(_config(tmp_path).slicer, repo_root=tmp_path)

    settings = runner._settings_snapshot(
        source=tmp_path / "specimen.stl",
        output_path=tmp_path / "specimen.gcode",
        simulate=False,
        specimen_id="sp-default-first-layer",
        printer_profile="prusa_mk4s_pla_0p4_nozzle",
        material="PLA",
        slicer_profile_hint="0.2mm_quality",
        experiment_spec={"slow_first_layer_enabled": False, "first_layer_speed_mm_s": 9.0},
    )

    assert settings["slow_first_layer_enabled"] is False
    assert settings["first_layer_speed_mm_s"] == 9.0
    assert "--layer-height=0.2" in settings["resolved_command"]
    assert "--first-layer-height=0.2" in settings["resolved_command"]
    assert "--bed-temperature=60" in settings["resolved_command"]
    assert "--first-layer-bed-temperature=60" in settings["resolved_command"]
    assert "--first-layer-speed=9" not in settings["resolved_command"]


def test_prusa_slicer_runner_uses_configured_executable_path(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    wrapper = tmp_path / "install" / "prusaslicer" / "prusa-slicer-docker"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    cfg.slicer.executable_path = "install/prusaslicer/prusa-slicer-docker"
    runner = PrusaSlicerRunner(cfg.slicer, repo_root=tmp_path)

    settings = runner._settings_snapshot(
        source=tmp_path / "specimen.stl",
        output_path=tmp_path / "specimen.gcode",
        simulate=False,
        specimen_id="sp-final",
        printer_profile="prusa_mk4s_pla_0p4_nozzle",
        material="PLA",
        slicer_profile_hint="0p2mm_quality",
        experiment_spec={"layer_height_mm": 0.2},
    )

    assert settings["executable_configured"] is True
    assert settings["resolved_command"][0] == str(wrapper)


def test_live_mode_missing_connection_creates_memory_prompt(tmp_path: Path) -> None:
    cfg = _config(tmp_path, mode="live")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)

    result = workflow.prepare({"runtime_mode": "live", "specimen_id": "sp-1"})

    assert result["ok"] is False
    assert result["requires_connection_info"] is True
    assert result["failure_code"] == "PRINTER_CONNECTION_INFO_REQUIRED"
    assert Path(result["connection_memory_path"]).exists()


def test_test_mode_installed_printer_choice_requires_connection_info(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)

    result = workflow.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "specimen_id": "sp-installed",
            "stl_path": str(stl),
        }
    )

    assert result["ok"] is False
    assert result["mode"] == "test_printer_live"
    assert result["requires_connection_info"] is True
    assert Path(result["connection_memory_path"]).exists()


def test_test_mode_virtual_bridge_choice_runs_real_slicer_before_virtual_prusalink(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config(tmp_path)
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)
    captured = {}

    def fake_slice(self, stl_path, *, specimen_id, simulate, printer_profile="", material="", slicer_profile_hint="", experiment_spec=None):
        captured["simulate"] = simulate
        output = tmp_path / "gcode" / f"{specimen_id}.gcode"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("M84\n", encoding="utf-8")
        return {
            "ok": True,
            "sliced_path": str(output),
            "stdout": "fake slicer",
            "stderr": "",
            "elapsed_sec": 0.01,
            "failure_code": None,
            "simulated": simulate,
            "slicer_settings": {"simulated": simulate, "output_gcode_path": str(output)},
        }

    monkeypatch.setattr(PrusaSlicerRunner, "slice", fake_slice)

    result = workflow.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "virtual_bridge",
            "specimen_id": "sp-virtual-choice",
            "stl_path": str(stl),
        }
    )

    assert result["ok"] is True
    assert result["mode"] == "test_printer_live_virtual"
    assert result["printer_path"] == "virtual_prusalink"
    assert captured["simulate"] is False
    assert result["slicer_result"]["simulated"] is False
    assert result["print_result"]["status"] == "virtual_finished"


def test_test_mode_installed_printer_choice_runs_real_slicer_but_blocks_physical_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config(tmp_path)
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)
    captured = {}

    def fake_slice(self, stl_path, *, specimen_id, simulate, printer_profile="", material="", slicer_profile_hint="", experiment_spec=None):
        captured["simulate"] = simulate
        output = tmp_path / "gcode" / f"{specimen_id}.gcode"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("M84\n", encoding="utf-8")
        return {
            "ok": True,
            "sliced_path": str(output),
            "stdout": "fake slicer",
            "stderr": "",
            "elapsed_sec": 0.01,
            "failure_code": None,
            "simulated": simulate,
            "slicer_settings": {"simulated": simulate, "output_gcode_path": str(output)},
        }

    status_calls: list[int] = []
    job_calls: list[int] = []

    def fake_get_status(self):
        status_calls.append(1)
        if len(status_calls) >= 2:
            return {"ok": True, "payload": {"printer": {"state": "PRINTING"}}}
        return {"ok": True, "payload": {"printer": {"state": "IDLE"}}}

    def fake_get_job(self):
        job_calls.append(1)
        if len(job_calls) >= 2:
            return {"ok": True, "payload": {"id": 201, "state": "PRINTING", "progress": 0.0, "time_remaining": 120}}
        return {"ok": True, "status_code": 204}

    monkeypatch.setattr(PrusaSlicerRunner, "slice", fake_slice)
    monkeypatch.setattr(PrusaLinkClient, "get_status", fake_get_status)
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_storage",
        lambda self: {"ok": True, "payload": {"storage_list": [{"name": "usb", "read_only": False, "available": True}]}},
    )
    monkeypatch.setattr(PrusaLinkClient, "get_job", fake_get_job)
    monkeypatch.setattr(PrusaLinkClient, "get_transfer", lambda self: {"ok": True, "status_code": 204})

    result = workflow.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "specimen_id": "sp-installed-choice",
            "stl_path": str(stl),
            "connection_info": {
                "host": "127.0.0.1",
                "scheme": "http",
                "port": 80,
                "storage": "usb",
                "auth": {"mode": "none"},
            },
        }
    )

    assert result["ok"] is True
    assert result["mode"] == "test_printer_live"
    assert result["printer_path"] == "test_printer_live"
    assert captured["simulate"] is False
    assert result["slicer_result"]["simulated"] is False
    assert result["print_result"]["upload"]["failure_code"] == "PHYSICAL_WRITE_DISABLED_IN_TEST"
    assert result["print_result"]["start"]["failure_code"] == "START_PRINT_DISABLED"


def test_test_mode_physical_print_uploads_and_starts_when_explicitly_selected(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path)
    cfg.live["allow_upload"] = True
    cfg.live["allow_start_print"] = True
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)

    def fake_slice(self, stl_path, *, specimen_id, simulate, printer_profile="", material="", slicer_profile_hint="", experiment_spec=None):
        output = tmp_path / "gcode" / f"{specimen_id}.gcode"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("M84\n", encoding="utf-8")
        return {
            "ok": True,
            "sliced_path": str(output),
            "stdout": "fake slicer",
            "stderr": "",
            "elapsed_sec": 0.01,
            "failure_code": None,
            "simulated": False,
            "slicer_settings": {"simulated": False, "output_gcode_path": str(output)},
        }

    started: list[str] = []

    monkeypatch.setattr(PrusaSlicerRunner, "slice", fake_slice)
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_status",
        lambda self: {"ok": True, "payload": {"printer": {"state": "PRINTING" if started else "IDLE"}}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_storage",
        lambda self: {"ok": True, "payload": {"storage_list": [{"name": "usb", "read_only": False, "available": True}]}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_job",
        lambda self: (
            {"ok": True, "payload": {"id": 202, "state": "PRINTING", "progress": 0.0, "time_remaining": 120}}
            if started
            else {"ok": True, "status_code": 204}
        ),
    )
    monkeypatch.setattr(PrusaLinkClient, "get_transfer", lambda self: {"ok": True, "status_code": 204})
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_file_metadata",
        lambda self, storage, remote_path: {
            "ok": True,
            "payload": {"name": "SP-PHY~1.GCO", "display_name": remote_path, "refs": {"download": "/usb/SP-PHY~1.GCO"}},
        },
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "upload_file",
        lambda self, *args, **kwargs: {"ok": True, "status": "uploaded", "endpoint": "/api/v1/files/usb/sp-physical.gcode"},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "start_file",
        lambda self, storage, remote_path: started.append(remote_path) or {"ok": True, "status": "started", "endpoint": f"/api/v1/files/{storage}/{remote_path}"},
    )

    result = workflow.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "physical_print",
            "specimen_id": "sp-physical",
            "stl_path": str(stl),
            "connection_info": {
                "host": "127.0.0.1",
                "scheme": "http",
                "port": 80,
                "storage": "usb",
                "auth": {"mode": "none"},
            },
            "print": {"start_immediately": True},
        }
    )

    assert result["ok"] is True
    assert result["mode"] == "test_printer_physical_print"
    assert result["printer_path"] == "test_printer_physical_print"
    assert result["slicer_result"]["simulated"] is False
    assert any(step["step"] == "UPLOAD_TRANSFER" and step["status"] == "active" for step in result["step_trace"])
    assert result["print_result"]["upload"]["ok"] is True
    assert result["print_result"]["start"]["ok"] is True
    assert result["print_result"]["start"]["start_remote_path"] == "SP-PHY~1.GCO"
    assert started == ["SP-PHY~1.GCO"]
    assert result["print_result"]["status"] == "started"


def test_physical_print_waits_for_transfer_idle_and_retries_start(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path, mode="live")
    cfg.live["transport"] = "real"
    cfg.live["allow_upload"] = True
    cfg.live["allow_start_print"] = True
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)
    transfer_calls: list[int] = []
    start_calls: list[int] = []

    def fake_slice(self, stl_path, *, specimen_id, simulate, printer_profile="", material="", slicer_profile_hint="", experiment_spec=None):
        output = tmp_path / "gcode" / f"{specimen_id}.gcode"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("G90\nM84\n", encoding="utf-8")
        return {
            "ok": True,
            "sliced_path": str(output),
            "stdout": "fake slicer",
            "stderr": "",
            "elapsed_sec": 0.01,
            "failure_code": None,
            "simulated": False,
            "slicer_settings": {"simulated": False, "output_gcode_path": str(output)},
        }

    def fake_get_transfer(self):
        transfer_calls.append(1)
        if len(transfer_calls) == 1:
            return {"ok": True, "payload": {"progress": 99, "transferred": 99, "size": 100, "path": "/usb/sp-race.gcode"}}
        return {"ok": True, "status_code": 204}

    def fake_start(self, storage, remote_path):
        start_calls.append(1)
        if len(start_calls) == 1:
            return {"ok": False, "status": "retryable", "failure_code": "PRINTER_HTTP_ERROR", "status_code": 409}
        return {"ok": True, "status": "started", "status_code": 204}

    monkeypatch.setattr("device_bridges.prusa_bridge.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(PrusaSlicerRunner, "slice", fake_slice)
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_status",
        lambda self: {"ok": True, "payload": {"printer": {"state": "PRINTING" if len(start_calls) >= 2 else "IDLE"}}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_storage",
        lambda self: {"ok": True, "payload": {"storage_list": [{"name": "usb", "read_only": False, "available": True}]}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_job",
        lambda self: (
            {"ok": True, "payload": {"id": 203, "state": "PRINTING", "progress": 0.0, "time_remaining": 120}}
            if len(start_calls) >= 2
            else {"ok": True, "status_code": 204}
        ),
    )
    monkeypatch.setattr(PrusaLinkClient, "get_transfer", fake_get_transfer)
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_file_metadata",
        lambda self, storage, remote_path: {
            "ok": True,
            "payload": {"name": "SP-RAC~1.GCO", "display_name": remote_path, "refs": {"download": "/usb/SP-RAC~1.GCO"}},
        },
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "upload_file",
        lambda self, *args, **kwargs: {"ok": True, "status": "uploaded", "endpoint": "/api/v1/files/usb/sp-race.gcode"},
    )
    monkeypatch.setattr(PrusaLinkClient, "start_file", fake_start)

    result = workflow.prepare(
        {
            "runtime_mode": "live",
            "specimen_id": "sp-race",
            "stl_path": str(stl),
            "connection_info": {
                "host": "127.0.0.1",
                "scheme": "http",
                "port": 80,
                "storage": "usb",
                "auth": {"mode": "none"},
            },
            "print": {"start_immediately": True},
        }
    )

    assert result["ok"] is True
    assert result["print_result"]["transfer_wait"]["ok"] is True
    assert result["print_result"]["start"]["ok"] is True
    assert result["print_result"]["start"]["attempts"] == 2
    assert result["print_result"]["start"]["start_remote_path"] == "SP-RAC~1.GCO"
    assert len(start_calls) == 2
    assert any(step["step"] == "WAIT_UPLOAD_READY" and step["status"] == "ok" for step in result["step_trace"])


def test_start_retries_every_second_until_printing_is_confirmed(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path, mode="live")
    cfg.live["transport"] = "real"
    cfg.live["allow_start_print"] = True
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)
    client = PrusaLinkClient(
        config=cfg,
        connection={"host": "127.0.0.1", "scheme": "http", "port": 80, "auth": {"mode": "none"}},
        transport="real",
    )
    start_calls: list[int] = []
    sleep_calls: list[float] = []

    def fake_start(self, *args, **kwargs):
        start_calls.append(1)
        return {"ok": True, "status": "accepted", "status_code": 204}

    monkeypatch.setattr("device_bridges.prusa_bridge.time.sleep", lambda seconds: sleep_calls.append(float(seconds)))
    monkeypatch.setattr(PrusaLinkClient, "start_file", fake_start)
    monkeypatch.setattr(PrusaLinkClient, "get_transfer", lambda self: {"ok": True, "status_code": 204})
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_status",
        lambda self: {"ok": True, "payload": {"printer": {"state": "PRINTING" if len(start_calls) >= 2 else "IDLE"}}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_job",
        lambda self: (
            {"ok": True, "payload": {"id": 207, "state": "PRINTING", "progress": 0.0, "time_remaining": 120}}
            if len(start_calls) >= 2
            else {"ok": True, "status_code": 204}
        ),
    )

    result = workflow._start_file_with_retry(client, "usb", "sp-confirm.gcode")

    assert result["ok"] is True
    assert result["status"] == "started"
    assert result["attempts"] == 2
    assert len(start_calls) == 2
    assert sleep_calls == [1.0]
    assert result["retry_history"][0]["confirm_status"] == "not_started"
    assert result["retry_history"][1]["confirm_status"] == "started"


def test_start_uses_prusalink_short_filename_from_metadata(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path, mode="live")
    cfg.live["transport"] = "real"
    cfg.live["allow_start_print"] = True
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)
    client = PrusaLinkClient(
        config=cfg,
        connection={"host": "127.0.0.1", "scheme": "http", "port": 80, "auth": {"mode": "none"}},
        transport="real",
    )
    start_paths: list[str] = []

    monkeypatch.setattr(
        PrusaLinkClient,
        "get_file_metadata",
        lambda self, storage, remote_path: {
            "ok": True,
            "payload": {
                "name": "AUTOEJ~1.GCO",
                "display_name": "autoeject-test-center.gcode",
                "refs": {"download": "/usb/AUTOEJ~1.GCO"},
            },
        },
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "start_file",
        lambda self, storage, remote_path: start_paths.append(remote_path) or {"ok": True, "status": "accepted", "status_code": 204},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_status",
        lambda self: {"ok": True, "payload": {"printer": {"state": "PRINTING"}}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_job",
        lambda self: {"ok": True, "payload": {"id": 210, "state": "PRINTING", "progress": 0.0, "time_remaining": 1}},
    )

    result = workflow._start_file_with_retry(client, "usb", "autoeject-test-center.gcode", attempts=1)

    assert result["ok"] is True
    assert start_paths == ["AUTOEJ~1.GCO"]
    assert result["requested_remote_path"] == "autoeject-test-center.gcode"
    assert result["start_remote_path"] == "AUTOEJ~1.GCO"
    assert result["path_resolution"]["status"] == "resolved"


def test_physical_print_waits_until_100_percent_before_set_ready_and_start(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path, mode="live")
    cfg.live["transport"] = "real"
    cfg.live["allow_upload"] = True
    cfg.live["allow_start_print"] = True
    cfg.live["timeouts"] = {"ready_wait_sec": 60, "request_sec": 60}
    cfg.live["poll_interval_sec"] = 0.01
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)
    jobs = [
        {"ok": True, "payload": {"id": 195, "state": "PRINTING", "progress": 99.0, "time_remaining": 1}},
        {"ok": True, "payload": {"id": 195, "state": "PRINTING", "progress": 100.0, "time_remaining": 0}},
        {"ok": True, "status_code": 204},
        {"ok": True, "payload": {"id": 204, "state": "PRINTING", "progress": 0.0, "time_remaining": 120}},
    ]
    statuses = [
        {"ok": True, "payload": {"printer": {"state": "PRINTING", "target_bed": 0.0, "target_nozzle": 0.0}}},
        {"ok": True, "payload": {"printer": {"state": "PRINTING", "target_bed": 0.0, "target_nozzle": 0.0}}},
        {"ok": True, "payload": {"printer": {"state": "IDLE", "target_bed": 0.0, "target_nozzle": 0.0}}},
        {"ok": True, "payload": {"printer": {"state": "PRINTING", "target_bed": 0.0, "target_nozzle": 0.0}}},
    ]
    uploads: list[str] = []
    starts: list[str] = []

    def fake_slice(self, stl_path, *, specimen_id, simulate, printer_profile="", material="", slicer_profile_hint="", experiment_spec=None):
        output = tmp_path / "gcode" / f"{specimen_id}.gcode"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("G90\nM84\n", encoding="utf-8")
        return {
            "ok": True,
            "sliced_path": str(output),
            "stdout": "fake slicer",
            "stderr": "",
            "elapsed_sec": 0.01,
            "failure_code": None,
            "simulated": False,
            "slicer_settings": {"simulated": False, "output_gcode_path": str(output)},
        }

    def fake_get_job(self):
        if jobs:
            return jobs.pop(0)
        if starts:
            return {"ok": True, "payload": {"id": 204, "state": "PRINTING", "progress": 0.0, "time_remaining": 120}}
        return {"ok": True, "status_code": 204}

    def fake_get_status(self):
        if statuses:
            return statuses.pop(0)
        if starts:
            return {"ok": True, "payload": {"printer": {"state": "PRINTING", "target_bed": 0.0, "target_nozzle": 0.0}}}
        return {"ok": True, "payload": {"printer": {"state": "IDLE", "target_bed": 0.0, "target_nozzle": 0.0}}}

    monkeypatch.setattr("device_bridges.prusa_bridge.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(PrusaSlicerRunner, "slice", fake_slice)
    monkeypatch.setattr(PrusaLinkClient, "get_status", fake_get_status)
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_storage",
        lambda self: {"ok": True, "payload": {"storage_list": [{"name": "usb", "read_only": False, "available": True}]}},
    )
    monkeypatch.setattr(PrusaLinkClient, "get_job", fake_get_job)
    monkeypatch.setattr(PrusaLinkClient, "get_transfer", lambda self: {"ok": True, "status_code": 204})
    monkeypatch.setattr(
        PrusaLinkClient,
        "upload_file",
        lambda self, *args, **kwargs: uploads.append("upload") or {"ok": True, "status": "uploaded", "endpoint": "/api/v1/files/usb/sp-ready.gcode"},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_file_metadata",
        lambda self, storage, remote_path: {
            "ok": True,
            "payload": {"name": "SP-REA~1.GCO", "display_name": remote_path, "refs": {"download": "/usb/SP-REA~1.GCO"}},
        },
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "start_file",
        lambda self, storage, remote_path: starts.append(remote_path) or {"ok": True, "status": "started", "status_code": 204},
    )

    result = workflow.prepare(
        {
            "runtime_mode": "live",
            "specimen_id": "sp-ready",
            "stl_path": str(stl),
            "connection_info": {
                "host": "127.0.0.1",
                "scheme": "http",
                "port": 80,
                "storage": "usb",
                "auth": {"mode": "none"},
            },
            "print": {"start_immediately": True},
        }
    )

    assert result["ok"] is True
    assert uploads == ["upload"]
    assert starts == ["SP-REA~1.GCO"]
    assert result["print_result"]["set_ready"]["status"] == "ready"
    assert result["print_result"]["start"]["start_remote_path"] == "SP-REA~1.GCO"
    assert any(step["step"] == "READY_FOR_START" and step["status"] == "ok" for step in result["step_trace"])


def test_physical_print_does_not_set_ready_or_upload_when_job_never_reaches_100_percent(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path, mode="live")
    cfg.live["transport"] = "real"
    cfg.live["allow_upload"] = True
    cfg.live["allow_start_print"] = True
    cfg.live["timeouts"] = {"ready_wait_sec": 0.1, "request_sec": 60}
    cfg.live["poll_interval_sec"] = 0.01
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)
    uploads: list[str] = []
    monotonic_values = iter([0.0, 0.0, 1.0])

    def fake_slice(self, stl_path, *, specimen_id, simulate, printer_profile="", material="", slicer_profile_hint="", experiment_spec=None):
        output = tmp_path / "gcode" / f"{specimen_id}.gcode"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("G90\nM84\n", encoding="utf-8")
        return {
            "ok": True,
            "sliced_path": str(output),
            "stdout": "fake slicer",
            "stderr": "",
            "elapsed_sec": 0.01,
            "failure_code": None,
            "simulated": False,
            "slicer_settings": {"simulated": False, "output_gcode_path": str(output)},
        }

    monkeypatch.setattr("device_bridges.prusa_bridge.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("device_bridges.prusa_bridge.time.monotonic", lambda: next(monotonic_values, 1.0))
    monkeypatch.setattr(PrusaSlicerRunner, "slice", fake_slice)
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_status",
        lambda self: {"ok": True, "payload": {"printer": {"state": "PRINTING", "target_bed": 0.0, "target_nozzle": 0.0}}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_storage",
        lambda self: {"ok": True, "payload": {"storage_list": [{"name": "usb", "read_only": False, "available": True}]}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_job",
        lambda self: {"ok": True, "payload": {"id": 195, "state": "PRINTING", "progress": 99.0, "time_remaining": 1}},
    )
    monkeypatch.setattr(PrusaLinkClient, "get_transfer", lambda self: {"ok": True, "status_code": 204})
    monkeypatch.setattr(PrusaLinkClient, "upload_file", lambda self, *args, **kwargs: uploads.append("upload") or {"ok": True})

    result = workflow.prepare(
        {
            "runtime_mode": "live",
            "specimen_id": "sp-timeout",
            "stl_path": str(stl),
            "connection_info": {
                "host": "127.0.0.1",
                "scheme": "http",
                "port": 80,
                "storage": "usb",
                "auth": {"mode": "none"},
            },
            "print": {"start_immediately": True},
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "PRINTER_JOB_NOT_COMPLETE_TIMEOUT"
    assert uploads == []


def test_append_end_gcode_ejection_uploads_autoeject_gcode(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(
        tmp_path,
        mode="live",
        ejection={
            "enabled": False,
            "method": "bed_sweep",
            "mode": "append_end_gcode",
            "max_bed_temp_c": 40.0,
            "max_feedrate_mm_min": 25000,
            "calibration_id": "mk4s-bed-sweep-test",
        },
    )
    cfg.live["transport"] = "real"
    cfg.live["allow_upload"] = True
    cfg.live["allow_start_print"] = True
    cfg.live["allow_ejection"] = False
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)
    uploaded = {}

    def fake_slice(self, stl_path, *, specimen_id, simulate, printer_profile="", material="", slicer_profile_hint="", experiment_spec=None):
        output = tmp_path / "gcode" / f"{specimen_id}.gcode"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "\n".join(
                [
                    "; sliced body",
                    "G90",
                    "M82",
                    "G1 X80 Y90 Z0.2 F1200",
                    "G1 X120 Y90 E0.5",
                    "G1 X120 Y130 E1.0",
                    "G1 X80 Y130 E1.5",
                    "M84",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "sliced_path": str(output),
            "stdout": "fake slicer",
            "stderr": "",
            "elapsed_sec": 0.01,
            "failure_code": None,
            "simulated": simulate,
            "slicer_settings": {"simulated": simulate, "output_gcode_path": str(output)},
        }

    def fake_upload(self, local_path, storage, remote_path, **kwargs):
        uploaded["local_path"] = str(local_path)
        return {"ok": True, "status": "uploaded", "local_path": str(local_path)}

    started: list[str] = []

    monkeypatch.setattr(PrusaSlicerRunner, "slice", fake_slice)
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_status",
        lambda self: {"ok": True, "payload": {"printer": {"state": "PRINTING" if started else "IDLE"}}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_storage",
        lambda self: {"ok": True, "payload": {"storage_list": [{"name": "usb", "read_only": False, "available": True}]}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_job",
        lambda self: (
            {"ok": True, "payload": {"id": 205, "state": "PRINTING", "progress": 0.0, "time_remaining": 120}}
            if started
            else {"ok": True, "status_code": 204}
        ),
    )
    monkeypatch.setattr(PrusaLinkClient, "get_transfer", lambda self: {"ok": True, "status_code": 204})
    monkeypatch.setattr(PrusaLinkClient, "upload_file", fake_upload)
    monkeypatch.setattr(PrusaLinkClient, "start_file", lambda self, *args, **kwargs: started.append("start") or {"ok": True, "status": "started"})

    result = workflow.prepare(
        {
            "runtime_mode": "live",
            "specimen_id": "sp-autoeject",
            "stl_path": str(stl),
            "connection_info": {
                "host": "127.0.0.1",
                "scheme": "http",
                "port": 80,
                "storage": "usb",
                "auth": {"mode": "none"},
            },
            "print": {"start_immediately": True},
            "ejection": {"enabled": True},
        }
    )

    appended_path = Path(result["ejection_result"]["appended_gcode_path"])
    assert result["ok"] is True
    assert result["ejection_result"]["status"] == "appended_to_print_gcode"
    assert result["sliced_path"] == str(appended_path)
    assert uploaded["local_path"] == str(appended_path)
    assert "M190 R40" in appended_path.read_text(encoding="utf-8")
    assert "G0 X100 F6000" in appended_path.read_text(encoding="utf-8")
    assert "G0 Z1 F3000" in appended_path.read_text(encoding="utf-8")
    assert "G0 Y6 F25000" in appended_path.read_text(encoding="utf-8")
    assert result["ejection_result"]["resolved"]["head_x_source"] == "gcode_object_bounds"
    assert result["ejection_result"]["object_bounds"]["center_x_mm"] == 100.0
    assert any(step["step"] == "APPEND_EJECTION_GCODE" for step in result["step_trace"])


def test_standalone_autoejection_test_uses_same_builder_without_printing(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(
        tmp_path,
        mode="live",
        ejection={
            "enabled": False,
            "method": "bed_sweep",
            "mode": "append_end_gcode",
            "max_bed_temp_c": 40.0,
            "max_feedrate_mm_min": 25000,
            "require_cooldown": False,
        },
    )
    cfg.live["transport"] = "real"
    cfg.live["allow_upload"] = True
    cfg.live["allow_start_print"] = True
    cfg.live["allow_ejection"] = False
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)
    uploaded = {}

    def fake_upload(self, local_path, storage, remote_path, **kwargs):
        uploaded["local_path"] = str(local_path)
        uploaded["remote_path"] = remote_path
        return {"ok": True, "status": "uploaded", "local_path": str(local_path), "remote_path": remote_path}

    started: list[str] = []

    monkeypatch.setattr(
        PrusaLinkClient,
        "get_status",
        lambda self: {"ok": True, "payload": {"printer": {"state": "PRINTING" if started else "IDLE"}}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_storage",
        lambda self: {"ok": True, "payload": {"storage_list": [{"name": "usb", "read_only": False, "available": True}]}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_job",
        lambda self: (
            {"ok": True, "payload": {"id": 206, "state": "PRINTING", "progress": 0.0, "time_remaining": 120}}
            if started
            else {"ok": True, "status_code": 204}
        ),
    )
    monkeypatch.setattr(PrusaLinkClient, "upload_file", fake_upload)
    monkeypatch.setattr(PrusaLinkClient, "get_transfer", lambda self: {"ok": True, "status_code": 204})
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_file_metadata",
        lambda self, storage, remote_path: {
            "ok": True,
            "payload": {"name": "AUTOEJ~3.GCO", "display_name": remote_path, "refs": {"download": "/usb/AUTOEJ~3.GCO"}},
        },
    )
    monkeypatch.setattr(PrusaLinkClient, "start_file", lambda self, *args, **kwargs: started.append("start") or {"ok": True, "status": "started"})

    result = workflow.run_autoejection_test(
        {
            "runtime_mode": "live",
            "position": "right",
            "object_size_mm": [30.0, 30.0, 20.0],
            "storage": "usb",
            "connection_info": {
                "host": "127.0.0.1",
                "scheme": "http",
                "port": 80,
                "storage": "usb",
                "auth": {"mode": "none"},
            },
        }
    )

    ejection_path = Path(result["ejection_gcode_path"])
    text = ejection_path.read_text(encoding="utf-8")
    assert result["ok"] is True
    assert result["status"] == "started"
    assert result["program_mode"] == "standalone_same_bed_sweep_builder"
    assert result["resolved"]["head_x_source"] == "gcode_object_bounds"
    assert result["resolved"]["temperature_commands_included"] is True
    assert result["object_bounds"]["center_x_mm"] == 210.0
    assert "G0 X210 F6000" in text
    assert "G0 Z10 F3000" in text
    assert "M190 R40" in text
    assert "M104 S0" in text
    assert "M140 S0" in text
    assert "M73 Q100 S0" in text
    assert text.rstrip().endswith("M73 Q100 S0")
    assert uploaded["local_path"] == str(ejection_path)
    assert not any(" E" in line and line.startswith("G1") for line in text.splitlines())


def test_live_workflow_blocks_when_prusalink_usb_storage_unavailable(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path, mode="live")
    cfg.live["allow_upload"] = True
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)

    monkeypatch.setattr(
        PrusaLinkClient,
        "get_status",
        lambda self: {"ok": True, "payload": {"printer": {"state": "IDLE"}}},
    )
    monkeypatch.setattr(
        PrusaLinkClient,
        "get_storage",
        lambda self: {"ok": True, "payload": {"storage_list": [{"name": "usb", "read_only": False, "available": False}]}},
    )
    monkeypatch.setattr(PrusaLinkClient, "get_job", lambda self: {"ok": True, "status_code": 204})
    monkeypatch.setattr(PrusaLinkClient, "get_transfer", lambda self: {"ok": True, "status_code": 204})
    monkeypatch.setattr(
        PrusaLinkClient,
        "upload_file",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(AssertionError("upload must not run without writable storage")),
    )

    result = workflow.prepare(
        {
            "runtime_mode": "live",
            "specimen_id": "sp-storage",
            "stl_path": str(stl),
            "connection_info": {
                "host": "127.0.0.1",
                "scheme": "http",
                "port": 80,
                "storage": "usb",
                "auth": {"mode": "none"},
            },
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "PRINTER_STORAGE_UNAVAILABLE"
    assert any(step["step"] == "PRUSALINK_STORAGE" and step["status"] == "blocked" for step in result["step_trace"])


def test_live_mode_stores_connection_info_for_reuse(tmp_path: Path) -> None:
    cfg = _config(tmp_path, mode="live")
    cfg.live["transport"] = "virtual"
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    workflow = PrinterAgenticWorkflow(cfg, repo_root=tmp_path)

    first = workflow.prepare(
        {
            "runtime_mode": "live",
            "specimen_id": "sp-memory",
            "stl_path": str(stl),
            "connection_info": {
                "host": "printer.local",
                "scheme": "http",
                "port": 80,
                "storage": "usb",
                "auth": {"mode": "none"},
            },
        }
    )
    stored = json.loads((tmp_path / "prusa_connection.json").read_text(encoding="utf-8"))

    second = PrinterAgenticWorkflow(cfg, repo_root=tmp_path).prepare(
        {"runtime_mode": "live", "specimen_id": "sp-memory-2", "stl_path": str(stl)}
    )

    assert first["ok"] is True
    assert stored["host"] == "printer.local"
    assert second["ok"] is True
    assert "requires_connection_info" not in second
