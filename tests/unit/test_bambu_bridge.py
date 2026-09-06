"""Unit tests for Bambu Lab printer fleet/device bridge contracts."""

from __future__ import annotations

import socket
import ssl
import json
import hashlib
import zipfile
from ftplib import FTP
from pathlib import Path

import yaml

from device_bridges.bambu_bridge import (
    AutoEjectionConfig,
    BambuAutoejectionMemory,
    BambuBridgeConfig,
    BambuConnectionMemory,
    BambuLiveProbe,
    BambuMqttReportClient,
    BambuSlicerConfig,
    BambuStudioSlicerRunner,
    BambuVideoStreamClient,
    PrinterDeviceBridgeManager,
    _ImplicitFTP_TLS,
    build_bambu_project_file_command_draft,
    normalize_bambu_report,
)


def _write_minimal_bambu_gcode_3mf(path: Path, *, plate_id: int = 1, gcode: str = "G90\nG1 X10 Y10 Z10 F1200\nM84\n") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"Metadata/plate_{int(plate_id)}.gcode", gcode)
        archive.writestr("3D/3dmodel.model", "<model />")


def test_bambu_slicer_resolves_path_binary_when_configured_wrapper_is_missing(tmp_path: Path, monkeypatch) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_executable = fake_bin / "bambu-studio"
    fake_executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_executable.chmod(0o755)
    monkeypatch.delenv("BAMBU_STUDIO_EXECUTABLE", raising=False)
    monkeypatch.setenv("PATH", str(fake_bin))
    config = BambuSlicerConfig(
        enabled=True,
        executable_env="BAMBU_STUDIO_EXECUTABLE",
        executable_path="install/bambustudio/bambu-studio-wrapper",
        output_dir="artifacts/bambu_sliced",
    )

    resolved = config.resolved_payload(repo_root=tmp_path)

    assert resolved["enabled"] is True
    assert resolved["available"] is True
    assert resolved["source"] == "path"
    assert resolved["resolved_executable_path"] == str(fake_executable)
    assert resolved["configured_executable_path"] == "install/bambustudio/bambu-studio-wrapper"
    assert resolved["output_dir"] == str(tmp_path / "artifacts/bambu_sliced")


def test_bambu_studio_slicer_runner_exports_real_artifact_with_fake_cli(tmp_path: Path) -> None:
    fake_cli = tmp_path / "bambu-studio"
    fake_cli.write_text(
        """#!/bin/sh
set -eu
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--outputdir" ]; then
    out="$arg"
  fi
  prev="$arg"
done
mkdir -p "$out"
printf 'real sliced payload' > "$out/specimen.gcode.3mf"
echo "fake slice complete"
""",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    source = tmp_path / "specimen.stl"
    source.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    config = BambuSlicerConfig(
        enabled=True,
        executable_path=str(fake_cli),
        output_dir=str(tmp_path / "bambu_sliced"),
        timeout_sec=5,
    )
    runner = BambuStudioSlicerRunner(config, repo_root=tmp_path)

    result = runner.slice(source_path=source, specimen_id="specimen")

    sliced_path = Path(result["sliced_artifact_path"])
    assert result["ok"] is True
    assert result["tool"] == "printer.bambu.slice_artifact"
    assert sliced_path.exists()
    assert sliced_path.name == "specimen.gcode.3mf"
    assert result["size_bytes"] == len(b"real sliced payload")
    assert result["sha256"]
    assert "--slice" in result["command"]
    assert "--arrange" in result["command"]
    assert "--ensure-on-bed" in result["command"]
    assert "--outputdir" in result["command"]
    assert "--export-3mf" in result["command"]
    assert "--debug" in result["command"]
    assert result["command"][result["command"].index("--debug") + 1] == "2"
    export_arg = result["command"][result["command"].index("--export-3mf") + 1]
    assert export_arg == "specimen.gcode.3mf"
    assert result["will_publish"] is False


def test_bambu_studio_slicer_runner_preserves_defaults_and_removes_front_test_line_only(tmp_path: Path) -> None:
    fake_cli = tmp_path / "bambu-studio"
    fake_cli.write_text(
        '''#!/usr/bin/env python3
import pathlib
import sys
import zipfile

out = ""
export_name = "specimen.gcode.3mf"
for idx, arg in enumerate(sys.argv):
    if arg == "--outputdir" and idx + 1 < len(sys.argv):
        out = sys.argv[idx + 1]
    if arg == "--export-3mf" and idx + 1 < len(sys.argv):
        export_name = sys.argv[idx + 1]
output_dir = pathlib.Path(out)
output_dir.mkdir(parents=True, exist_ok=True)
gcode = """; filament start gcode
M104 S220 ; keep Bambu purge/temperature defaults
;===== nozzle load line ===============================
G1 X18 Y1 Z0.3 F18000
G1 X200 Y1 E20 F1500 ; front build-plate test line to remove
;===== nozzle load line end ===========================
;===== wipe nozzle ===============================
G1 X70 Y265 F12000 ; keep Bambu cleaning/wipe defaults
; printing object
G1 X50 Y50 E1
"""
with zipfile.ZipFile(output_dir / export_name, "w") as archive:
    archive.writestr("Metadata/plate_1.gcode", gcode)
    archive.writestr("3D/3dmodel.model", "<model />")
''',
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    source = tmp_path / "specimen.stl"
    source.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    config = BambuSlicerConfig(
        enabled=True,
        executable_path=str(fake_cli),
        output_dir=str(tmp_path / "bambu_sliced"),
        timeout_sec=5,
    )
    runner = BambuStudioSlicerRunner(config, repo_root=tmp_path)

    result = runner.slice(source_path=source, specimen_id="specimen")

    assert result["ok"] is True
    assert "--load-settings" in result["command"]
    assert "--load-filaments" in result["command"]
    profile = result["slicer_profile"]
    assert profile["preserve_bambu_defaults"] is True
    assert profile["auto_no_skirt_profile"] is True
    assert result["front_test_line_removal"]["removed"] is True
    with zipfile.ZipFile(result["sliced_artifact_path"]) as archive:
        plate_gcode = archive.read("Metadata/plate_1.gcode").decode("utf-8")
        plate_md5 = archive.read("Metadata/plate_1.gcode.md5").decode("utf-8")
    assert "nozzle load line" not in plate_gcode
    assert "front build-plate test line to remove" not in plate_gcode
    assert "keep Bambu purge/temperature defaults" in plate_gcode
    assert "keep Bambu cleaning/wipe defaults" in plate_gcode
    assert "; printing object" in plate_gcode
    assert plate_md5 == hashlib.md5(plate_gcode.encode("utf-8")).hexdigest()


def test_bambu_studio_slicer_runner_packages_plate_gcode_when_cli_export_crashes(tmp_path: Path) -> None:
    fake_cli = tmp_path / "bambu-studio"
    fake_cli.write_text(
        '''#!/usr/bin/env python3
import pathlib
import sys

out = ""
for idx, arg in enumerate(sys.argv):
    if arg == "--outputdir" and idx + 1 < len(sys.argv):
        out = sys.argv[idx + 1]
output_dir = pathlib.Path(out)
output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / "plate_1.gcode").write_text("""; HEADER_BLOCK_START
; BambuStudio fallback path
; HEADER_BLOCK_END
;===== nozzle load line ===============================
G1 X18 Y1 Z0.3 F18000
G1 X200 Y1 E20 F1500
;===== nozzle load line end ===========================
G1 X50 Y50 E1
""", encoding="utf-8")
print("Wayland: Failed to connect to display")
sys.exit(139)
''',
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    source = tmp_path / "specimen.stl"
    source.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    config = BambuSlicerConfig(
        enabled=True,
        executable_path=str(fake_cli),
        output_dir=str(tmp_path / "bambu_sliced"),
        timeout_sec=5,
    )
    runner = BambuStudioSlicerRunner(config, repo_root=tmp_path)

    result = runner.slice(source_path=source, specimen_id="specimen")

    assert result["ok"] is True
    assert result["returncode"] == 139
    assert result["slicer_profile"]["fallback_packaged_plate_gcode"] is True
    sliced_path = Path(result["sliced_artifact_path"])
    assert sliced_path.name == "specimen.gcode.3mf"
    with zipfile.ZipFile(sliced_path) as archive:
        plate_gcode = archive.read("Metadata/plate_1.gcode").decode("utf-8")
        plate_md5 = archive.read("Metadata/plate_1.gcode.md5").decode("utf-8")
        names = set(archive.namelist())
        assert "3D/3dmodel.model" in names
        assert "3D/_rels/3dmodel.model.rels" in names
        assert "3D/Objects/object_1.model" in names
        assert "Metadata/_rels/model_settings.config.rels" in names
    assert "nozzle load line" not in plate_gcode
    assert "G1 X50 Y50 E1" in plate_gcode
    assert plate_md5 == hashlib.md5(plate_gcode.encode("utf-8")).hexdigest()


def test_bambu_studio_slicer_runner_accepts_overwritten_existing_artifact(tmp_path: Path) -> None:
    fake_cli = tmp_path / "bambu-studio"
    fake_cli.write_text(
        """#!/bin/sh
set -eu
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--outputdir" ]; then
    out="$arg"
  fi
  prev="$arg"
done
mkdir -p "$out"
count_file="$out/count.txt"
count=0
if [ -f "$count_file" ]; then
  count="$(cat "$count_file")"
fi
count=$((count + 1))
printf '%s' "$count" > "$count_file"
printf 'real sliced payload %s' "$count" > "$out/specimen.gcode.3mf"
""",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    source = tmp_path / "specimen.stl"
    source.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    config = BambuSlicerConfig(
        enabled=True,
        executable_path=str(fake_cli),
        output_dir=str(tmp_path / "bambu_sliced"),
        timeout_sec=5,
    )
    runner = BambuStudioSlicerRunner(config, repo_root=tmp_path)

    first = runner.slice(source_path=source, specimen_id="specimen")
    second = runner.slice(source_path=source, specimen_id="specimen")

    assert first["ok"] is True
    assert second["ok"] is True
    assert Path(second["sliced_artifact_path"]).read_text(encoding="utf-8") == "real sliced payload 2"


def test_bambu_studio_slicer_runner_blocks_when_source_missing(tmp_path: Path) -> None:
    config = BambuSlicerConfig(enabled=True, executable_path="/bin/true", output_dir=str(tmp_path / "out"))
    runner = BambuStudioSlicerRunner(config, repo_root=tmp_path)

    result = runner.slice(source_path=tmp_path / "missing.stl", specimen_id="missing")

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_SLICER_SOURCE_FILE_NOT_FOUND"
    assert result["will_publish"] is False


def test_bambu_autoejection_requires_verified_routine_and_vision_evidence() -> None:
    config = AutoEjectionConfig.from_dict(
        {
            "enabled": True,
            "provider": "external_robot_pickoff",
            "require_verified_routine": True,
            "require_pre_eject_vision": True,
            "require_post_eject_vision": True,
        }
    )

    status = config.status_payload()

    assert status["requested"] is True
    assert status["enabled"] is False
    assert status["status"] == "blocked"
    assert status["can_run_test"] is False
    assert "BAMBU_AUTOEJECTION_ROUTINE_NOT_VERIFIED" in status["blockers"]
    assert "BAMBU_PRE_EJECT_VISION_PROFILE_REQUIRED" in status["blockers"]
    assert "BAMBU_POST_EJECT_VISION_PROFILE_REQUIRED" in status["blockers"]


def test_bambu_autoejection_can_be_configured_with_verified_external_provider() -> None:
    config = AutoEjectionConfig.from_dict(
        {
            "enabled": True,
            "provider": "external_robot_pickoff",
            "verified_routine_id": "robot-pickoff-v1",
            "pre_eject_vision_profile": "bambu-bed-occupied-check",
            "post_eject_vision_profile": "bambu-bed-clear-check",
        }
    )

    status = config.status_payload()

    assert status["enabled"] is True
    assert status["status"] == "configured"
    assert status["can_run_test"] is True
    assert status["blockers"] == []


def test_bambu_native_gcode_patch_autoejection_does_not_require_external_routine_or_vision() -> None:
    config = AutoEjectionConfig.from_dict(
        {
            "enabled": True,
            "provider": "bambu_gcode_patch",
            "require_verified_routine": True,
            "require_pre_eject_vision": True,
            "require_post_eject_vision": True,
        }
    )

    status = config.status_payload()

    assert status["enabled"] is True
    assert status["status"] == "configured"
    assert status["can_run_test"] is True
    assert status["provider"] == "bambu_gcode_patch"
    assert status["blockers"] == []
    assert status["native_gcode_patch"] is True


def test_bambu_native_autoejection_memory_preserves_gcode_patch_parameters(tmp_path: Path) -> None:
    memory = BambuAutoejectionMemory(tmp_path / "bambu_autoejection.json")
    defaults = AutoEjectionConfig.from_dict({"enabled": False, "provider": "none"})

    saved = memory.save_from_payload(
        {
            "enabled": True,
            "provider": "bambu_gcode_patch",
            "push_direction": "right",
            "z_push_offset_mm": 22.5,
            "push_lane_offset_mm": 18.0,
            "push_speed_mm_min": 420,
            "enable_full_bed_sweep": True,
            "sweep_z_mm": 1.5,
            "sweep_speed_mm_min": 260,
        },
        defaults,
    )

    status = saved.status_payload()
    native = status["native_gcode_parameters"]
    assert native["push_direction"] == "right"
    assert native["z_push_offset_mm"] == 22.5
    assert native["push_lane_offset_mm"] == 18.0
    assert native["push_speed_mm_min"] == 420
    assert native["enable_full_bed_sweep"] is True
    assert native["sweep_z_mm"] == 1.5
    assert native["sweep_speed_mm_min"] == 260
    assert memory.config_with_defaults(defaults).to_dict()["push_direction"] == "right"
    assert memory.load()["push_speed_mm_min"] == 420


def test_bambu_native_autoejection_memory_caps_motion_parameters_to_safe_bounds(tmp_path: Path) -> None:
    memory = BambuAutoejectionMemory(tmp_path / "bambu_autoejection.json")
    defaults = AutoEjectionConfig.from_dict({"enabled": False, "provider": "none"})

    saved = memory.save_from_payload(
        {
            "enabled": True,
            "provider": "bambu_gcode_patch",
            "z_push_offset_mm": 9999,
            "push_lane_offset_mm": 9999,
            "push_speed_mm_min": 99999,
            "sweep_z_mm": 9999,
            "sweep_speed_mm_min": 99999,
        },
        defaults,
    )

    native = saved.status_payload()["native_gcode_parameters"]
    assert native["z_push_offset_mm"] == 200.0
    assert native["push_lane_offset_mm"] == 120.0
    assert native["push_speed_mm_min"] == 12000
    assert native["sweep_z_mm"] == 50.0
    assert native["sweep_speed_mm_min"] == 12000
    persisted = memory.load()
    assert persisted["z_push_offset_mm"] == 200.0
    assert persisted["push_lane_offset_mm"] == 120.0


def test_bambu_autoejection_memory_overlays_safe_defaults(tmp_path: Path) -> None:
    memory = BambuAutoejectionMemory(tmp_path / "bambu_autoejection.json")
    defaults = AutoEjectionConfig.from_dict({"enabled": False, "provider": "none"})

    before = memory.config_with_defaults(defaults).status_payload()
    assert before["requested"] is False
    assert "BAMBU_AUTOEJECTION_NOT_REQUESTED" in before["blockers"]

    saved = memory.save_from_payload(
        {
            "enabled": True,
            "provider": "external_robot_pickoff",
            "verified_routine_id": "robot-pickoff-v1",
            "pre_eject_vision_profile": "bambu-bed-occupied-check",
            "post_eject_vision_profile": "bambu-bed-clear-check",
        },
        defaults,
    )

    status = saved.status_payload()
    assert status["enabled"] is True
    assert status["can_run_test"] is True
    assert memory.config_with_defaults(defaults).verified_routine_id == "robot-pickoff-v1"
    assert memory.path.exists()


def test_bambu_manager_patches_autoejection_artifact_without_provider_handoff(tmp_path: Path) -> None:
    source = tmp_path / "specimen.gcode"
    source.write_text(
        "G90\nG1 X20 Y30 Z0.2 E0.02\nG1 X50 Y70 Z12.0 E1.50\nM104 S0\nM140 S0\nM84\n",
        encoding="utf-8",
    )
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})

    result = manager.patch_bambu_autoejection_artifact(
        source_path=source,
        specimen_id="specimen-cand-1",
        position="center",
        plate_id=1,
    )

    patched_path = Path(result["patched_artifact_path"])
    assert result["ok"] is True
    assert result["provider"] == "bambulab_x2d"
    assert result["autoejection"]["provider"] == "bambu_gcode_patch"
    assert result["autoejection"]["native_gcode_patch"] is True
    assert result["handoff_required"] is False
    assert patched_path.exists()
    assert "atr.bambu.autoejection.v1" in patched_path.read_text(encoding="utf-8")


def test_bambu_manager_applies_saved_native_autoejection_motion_parameters(tmp_path: Path) -> None:
    source = tmp_path / "specimen.gcode"
    source.write_text(
        "G90\nG1 X30 Y40 Z0.2 E0.02\nG1 X70 Y90 Z40.0 E2.00\nM104 S0\nM140 S0\nM84\n",
        encoding="utf-8",
    )
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    manager.save_autoejection_config(
        {
            "enabled": True,
            "provider": "bambu_gcode_patch",
            "push_direction": "right",
            "z_push_offset_mm": 22.5,
            "push_lane_offset_mm": 18.0,
            "push_speed_mm_min": 420,
            "enable_full_bed_sweep": True,
            "sweep_z_mm": 1.5,
            "sweep_speed_mm_min": 260,
        }
    )

    result = manager.patch_bambu_autoejection_artifact(source_path=source, specimen_id="specimen-cand-1")

    patched_text = Path(result["patched_artifact_path"]).read_text(encoding="utf-8")
    assert result["ok"] is True
    assert result["autoejection"]["native_gcode_parameters"]["push_direction"] == "right"
    assert result["position"] == "right"
    assert "; atr_push_lane_offset_mm=18.0" in patched_text
    assert "; atr_z_push_offset_mm=22.5" in patched_text
    assert "; atr_full_bed_sweep_enabled=true" in patched_text
    assert "G0 X50.000" in patched_text
    assert "F420" in patched_text
    assert "G0 Z17.500" in patched_text
    assert "G0 Z1.500" in patched_text
    assert "F260" in patched_text


def test_bambu_manager_blocks_a1_family_from_corexy_autoejection_tail(tmp_path: Path) -> None:
    source = tmp_path / "specimen.gcode"
    source.write_text(
        "G90\nG1 X30 Y40 Z0.2 E0.02\nG1 X70 Y90 Z40.0 E2.00\nM104 S0\nM140 S0\nM84\n",
        encoding="utf-8",
    )
    cfg = _devices_config(tmp_path)
    printer_cfg = cfg["devices"]["printer"]
    printer_cfg["default_profile_id"] = "bambulab_a1_mini_lab_01"
    printer_cfg["profiles"]["bambulab_a1_mini_lab_01"] = {
        "provider": "bambulab_x2d",
        "label": "Bambu Lab A1 Mini - Lab 01",
        "enabled": True,
        "connection_memory_path": str(tmp_path / "bambu_a1_connection.json"),
        "capabilities": {
            "model_family": "a1_mini",
            "slicer": "bambu_studio_cli",
            "transfer": ["ftps"],
            "telemetry": "mqtt",
            "live_view": "lan_video_stream",
        },
    }
    manager = PrinterDeviceBridgeManager.from_devices_config(cfg, repo_root=tmp_path)
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})

    result = manager.patch_bambu_autoejection_artifact(source_path=source, specimen_id="specimen-cand-1")

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_AUTOEJECTION_MODEL_FAMILY_UNSUPPORTED"
    assert "BAMBU_AUTOEJECTION_MODEL_FAMILY_UNSUPPORTED" in result["blockers"]
    assert "bed-slinger" in result["message"]
    assert result["selected_printer"]["profile_id"] == "bambulab_a1_mini_lab_01"


def test_bambu_ftps_upload_file_deletes_probe_file(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    uploaded: dict[str, bytes | str | bool] = {}

    class FakeFtps:
        def __init__(self, context=None) -> None:
            self.context = context

        def connect(self, host: str, port: int, timeout: float) -> None:
            uploaded["connect"] = f"{host}:{port}:{timeout}"

        def login(self, username: str, password: str) -> None:
            uploaded["login"] = username

        def prot_p(self) -> None:
            uploaded["prot_p"] = True

        def storbinary(self, command: str, fp) -> None:
            uploaded["command"] = command
            uploaded["content"] = fp.read()

        def delete(self, remote_path: str) -> None:
            uploaded["deleted"] = remote_path

        def quit(self) -> None:
            uploaded["quit"] = True

    monkeypatch.setattr(bambu_bridge, "_ImplicitFTP_TLS", FakeFtps)
    local = tmp_path / "artifact.gcode.3mf"
    local.write_bytes(b"bambu artifact bytes")
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    result = manager.ftps_client.upload_file(
        local_path=local,
        remote_path="atr-upload-probe.gcode.3mf",
        host="192.0.2.42",
        username="bblp",
        access_code="secret",
        timeout_sec=0.1,
        delete_after=True,
    )

    assert result["ok"] is True
    assert result["remote_path"] == "atr-upload-probe.gcode.3mf"
    assert result["size_bytes"] == len(b"bambu artifact bytes")
    assert result["sha256"]
    assert uploaded["command"] == "STOR atr-upload-probe.gcode.3mf"
    assert uploaded["content"] == b"bambu artifact bytes"
    assert uploaded["deleted"] == "atr-upload-probe.gcode.3mf"


def test_bambu_ftps_probe_reports_read_only_storage_when_write_probe_fails(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    class FakeFtps:
        def __init__(self, context=None) -> None:
            pass

        def connect(self, host: str, port: int, timeout: float) -> None:
            pass

        def login(self, username: str, password: str) -> None:
            pass

        def prot_p(self) -> None:
            pass

        def nlst(self) -> list[str]:
            return []

        def storbinary(self, command: str, fp) -> None:
            raise RuntimeError("553 Could not create file.")

        def quit(self) -> None:
            pass

    monkeypatch.setattr(bambu_bridge, "_ImplicitFTP_TLS", FakeFtps)
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    result = manager.ftps_client.probe_storage(
        host="192.0.2.42",
        username="bblp",
        access_code="secret",
        timeout_sec=0.1,
        write_probe=True,
    )

    assert result["ok"] is False
    assert result["read_ok"] is True
    assert result["failure_code"] == "BAMBU_FTPS_WRITE_FAILED"
    assert "553" in result["error"]


def test_bambu_ftps_probe_classifies_plaintext_421_too_many_connections(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    class FakeFtps:
        def __init__(self, context=None) -> None:
            pass

        def connect(self, host: str, port: int, timeout: float) -> None:
            raise ssl.SSLError("[SSL: WRONG_VERSION_NUMBER] wrong version number")

        def quit(self) -> None:
            pass

    class FakeSocket:
        def settimeout(self, timeout: float) -> None:
            pass

        def recv(self, size: int) -> bytes:
            return b"421 There are too many connections from your internet address.\r\n"

        def close(self) -> None:
            pass

    monkeypatch.setattr(bambu_bridge, "_ImplicitFTP_TLS", FakeFtps)
    monkeypatch.setattr(bambu_bridge.socket, "create_connection", lambda *args, **kwargs: FakeSocket())
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    result = manager.ftps_client.probe_storage(
        host="192.0.2.42",
        username="bblp",
        access_code="secret",
        timeout_sec=0.1,
        write_probe=True,
    )

    assert result["ok"] is False
    assert result["storage"] == "ftps"
    assert result["failure_code"] == "BAMBU_FTPS_TOO_MANY_CONNECTIONS"
    assert "too many connections" in result["error"].lower()


def test_bambu_ftps_upload_path_probe_reports_each_candidate_and_deletes_success(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    attempted: list[tuple[str, str]] = []
    cwd_calls: list[str] = []
    deleted: list[str] = []

    class FakeFtps:
        def __init__(self, context=None) -> None:
            self.cwd_path = "/"

        def pwd(self) -> str:
            return self.cwd_path

        def cwd(self, path: str) -> None:
            cwd_calls.append(path)
            if path == "/":
                self.cwd_path = "/"
            elif path in {"/cache", "cache"}:
                self.cwd_path = "/cache"
            elif path in {"/sdcard", "sdcard"}:
                self.cwd_path = "/sdcard"
            else:
                raise RuntimeError(f"550 Directory not found: {path}")

        def mkd(self, path: str) -> None:
            pass

        def connect(self, host: str, port: int, timeout: float) -> None:
            pass

        def login(self, username: str, password: str) -> None:
            pass

        def prot_p(self) -> None:
            pass

        def nlst(self) -> list[str]:
            return []

        def storbinary(self, command: str, fp) -> None:
            remote = command.removeprefix("STOR ")
            attempted.append((self.cwd_path, remote))
            fp.read()
            if self.cwd_path == "/cache" and remote == "atr-ftps-path-probe.txt":
                return
            raise RuntimeError("553 Could not create file.")

        def delete(self, remote_path: str) -> None:
            deleted.append(f"{self.cwd_path}/{remote_path}".replace("//", "/"))

        def quit(self) -> None:
            pass

    monkeypatch.setattr(bambu_bridge, "_ImplicitFTP_TLS", FakeFtps)
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    result = manager.ftps_client.probe_upload_paths(
        host="192.0.2.42",
        username="bblp",
        access_code="secret",
        timeout_sec=0.1,
        candidate_dirs=["", "cache", "sdcard"],
    )

    assert result["ok"] is True
    assert result["write_ok"] is True
    assert result["selected_remote_dir"] == "cache"
    assert attempted == [
        ("/", "atr-ftps-path-probe.txt"),
        ("/cache", "atr-ftps-path-probe.txt"),
        ("/sdcard", "atr-ftps-path-probe.txt"),
    ]
    assert deleted == ["/cache/atr-ftps-path-probe.txt"]
    assert cwd_calls == ["/", "/cache", "/", "/sdcard", "/"]
    assert [item["ok"] for item in result["candidates"]] == [False, True, False]
    assert "access_code" not in str(result)


def test_bambu_ftps_upload_file_uses_directory_cwd_and_basename_for_cache(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    actions: list[tuple[str, str]] = []

    class FakeFtps:
        def __init__(self, context=None) -> None:
            self.cwd_path = "/"

        def connect(self, host: str, port: int, timeout: float) -> None:
            actions.append(("connect", f"{host}:{port}:{timeout}"))

        def login(self, username: str, password: str) -> None:
            actions.append(("login", username))

        def prot_p(self) -> None:
            actions.append(("prot_p", "true"))

        def pwd(self) -> str:
            return self.cwd_path

        def cwd(self, path: str) -> None:
            actions.append(("cwd", path))
            if path == "/":
                self.cwd_path = "/"
            elif path in {"/cache", "cache"}:
                self.cwd_path = "/cache"
            else:
                raise RuntimeError(f"550 Directory not found: {path}")

        def mkd(self, path: str) -> None:
            actions.append(("mkd", path))

        def storbinary(self, command: str, fp) -> None:
            actions.append(("stor", f"{self.cwd_path}:{command}:{fp.read().decode()}"))

        def delete(self, remote_path: str) -> None:
            actions.append(("delete", f"{self.cwd_path}:{remote_path}"))

        def quit(self) -> None:
            actions.append(("quit", "true"))

    monkeypatch.setattr(bambu_bridge, "_ImplicitFTP_TLS", FakeFtps)
    local = tmp_path / "artifact.gcode.3mf"
    local.write_text("payload", encoding="utf-8")
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    result = manager.ftps_client.upload_file(
        local_path=local,
        remote_path="cache/specimen.gcode.3mf",
        host="192.0.2.42",
        username="bblp",
        access_code="secret",
        timeout_sec=0.1,
        delete_after=True,
    )

    assert result["ok"] is True
    assert result["remote_path"] == "cache/specimen.gcode.3mf"
    assert ("cwd", "/cache") in actions
    assert ("stor", "/cache:STOR specimen.gcode.3mf:payload") in actions
    assert ("delete", "/cache:specimen.gcode.3mf") in actions
    assert ("cwd", "/") in actions


def test_bambu_video_probe_reports_reachable_rtsps_without_leaking_access_code(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    calls: list[tuple[str, int, float]] = []

    class FakeSocket:
        def close(self) -> None:
            pass

    def fake_create_connection(address, timeout):  # noqa: ANN001
        host, port = address
        calls.append((host, port, timeout))
        if port == 322:
            return FakeSocket()
        raise OSError("closed")

    monkeypatch.setattr(bambu_bridge.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(bambu_bridge.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    result = BambuVideoStreamClient(manager.config).probe_live_view(
        host="192.0.2.42",
        access_code="secret-code",
        reported_rtsp_url="",
        timeout_sec=0.1,
    )

    assert result["ok"] is True
    assert result["status"] == "streaming_candidate"
    assert result["stream_kind"] == "rtsps"
    assert result["port"] == 322
    assert result["proxy_ready"] is True
    assert result["proxy_url"] == "/api/printer/video-stream.mjpeg"
    assert result["stream_url"] == "rtsps://192.0.2.42:322/streaming/live/1"
    assert calls[0] == ("192.0.2.42", 322, 0.1)
    assert "secret-code" not in str(result)


def _devices_config(tmp_path: Path) -> dict:
    return {
        "devices": {
            "printer": {
                "mode": "test",
                "default_profile_id": "bambulab_x2d_lab_01",
                "allow_automatic_fallback": False,
                "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                "profiles": {
                    "bambulab_x2d_lab_01": {
                        "provider": "bambulab_x2d",
                        "label": "Bambu Lab X2D - Lab 01",
                        "enabled": True,
                        "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                        "capabilities": {
                            "slicer": "bambu_studio_cli",
                            "transfer": ["ftps", "bambu_connect"],
                            "telemetry": "mqtt",
                            "live_view": "lan_video_stream",
                        },
                    },
                    "prusa_mk4s_lab_01": {
                        "provider": "prusa_mk4s",
                        "label": "Prusa MK4S - Lab 01",
                        "enabled": True,
                        "capabilities": {
                            "slicer": "prusa_slicer",
                            "transfer": "prusalink_http",
                            "telemetry": "prusalink_rest",
                            "live_view": "none",
                        },
                    },
                },
                "bambu": {
                    "mqtt": {"port": 8883, "timeout_sec": 0.1},
                    "video": {"enabled": True, "rtsps_port": 322, "jpeg_stream_port": 6000},
                    "slicer": {"enabled": False, "output_dir": str(tmp_path / "bambu_sliced")},
                },
            }
        }
    }


def test_fleet_config_defaults_to_bambu_and_disables_automatic_fallback(tmp_path: Path) -> None:
    config = BambuBridgeConfig.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    assert config.default_profile_id == "bambulab_x2d_lab_01"
    assert config.allow_automatic_fallback is False
    assert config.default_profile.provider == "bambulab_x2d"
    assert config.profile("prusa_mk4s_lab_01").provider == "prusa_mk4s"


def test_repository_devices_config_defaults_to_native_bambu_autoejection_without_robot_recovery_handoff() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    raw = yaml.safe_load((repo_root / "configs" / "devices.yaml").read_text(encoding="utf-8"))

    config = BambuBridgeConfig.from_devices_config(raw, repo_root=repo_root)

    assert config.autoejection.enabled is False
    assert config.autoejection.provider == "bambu_gcode_patch"
    assert config.autoejection.recovery_to_robot_pickoff is False
    status = config.autoejection.status_payload()
    assert status["native_gcode_patch"] is True
    assert "BAMBU_AUTOEJECTION_PROVIDER_NOT_CONFIGURED" not in status["blockers"]


def test_bambu_mqtt_publish_timeout_defaults_to_180_independent_from_status_timeout(tmp_path: Path) -> None:
    config = BambuBridgeConfig.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    assert config.mqtt.timeout_sec == 0.1
    assert config.mqtt.publish_timeout_sec == 180.0


def test_bambu_mqtt_publish_timeout_clamps_below_60_seconds(tmp_path: Path) -> None:
    raw_config = _devices_config(tmp_path)
    raw_config["devices"]["printer"]["bambu"]["mqtt"]["publish_timeout_sec"] = 15

    config = BambuBridgeConfig.from_devices_config(raw_config, repo_root=tmp_path)

    assert config.mqtt.publish_timeout_sec == 60.0


def test_prepare_uses_default_bambu_profile_and_locks_selected_profile(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    result = manager.prepare({"runtime_mode": "test", "run_id": "run-1", "specimen_id": "sp-1"})

    assert result["ok"] is True
    assert result["tool"] == "printer.prepare"
    assert result["provider"] == "bambulab_x2d"
    assert result["selected_printer"]["profile_id"] == "bambulab_x2d_lab_01"
    assert result["selected_printer"]["locked"] is True
    assert result["automatic_fallback"] is False
    assert result["device_screen"]["schema"] == "printer_device_screen.v1"
    assert result["device_screen"]["connection"]["mqtt"] == "virtual"
    assert result["device_screen"]["connection"]["video"] == "virtual"
    assert result["autoejection"]["enabled"] is False
    assert result["autoejection"]["status"] == "not_configured"


def test_prusa_profile_selection_is_explicit_not_fallback(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "run_id": "run-1",
            "specimen_id": "sp-1",
            "printer_profile_id": "prusa_mk4s_lab_01",
        }
    )

    assert result["provider"] == "prusa_mk4s"
    assert result["selected_printer"]["profile_id"] == "prusa_mk4s_lab_01"
    assert result["selected_printer"]["selection_reason"] == "explicit_profile_id"
    assert result["automatic_fallback"] is False


def test_fleet_memory_selection_is_used_when_no_explicit_profile_is_requested(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    saved = manager.save_fleet_selection("prusa_mk4s_lab_01")
    result = manager.prepare({"runtime_mode": "test", "run_id": "run-1", "specimen_id": "sp-1"})

    assert saved["active_profile_id"] == "prusa_mk4s_lab_01"
    assert saved["available_printers"][0]["profile_id"] == "bambulab_x2d_lab_01"
    assert result["provider"] == "prusa_mk4s"
    assert result["selected_printer"]["profile_id"] == "prusa_mk4s_lab_01"
    assert result["selected_printer"]["selection_reason"] == "fleet_memory_profile_id"
    assert result["automatic_fallback"] is False


def test_live_bambu_without_connection_info_blocks_without_fake_ready_state(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    result = manager.prepare({"runtime_mode": "live", "run_id": "run-1", "specimen_id": "sp-1"})

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_CONNECTION_INFO_REQUIRED"
    assert result["requires_connection_info"] is True
    assert result["device_screen"]["connection"]["mqtt"] == "unknown"
    assert result["device_screen"]["connection"]["video"] == "unknown"
    assert result["device_screen"]["job"]["progress_percent"] is None
    assert result["device_screen"]["actions"]["can_start_print"] is False


def test_live_probe_accepts_bambu_lan_self_signed_tls(monkeypatch, tmp_path: Path) -> None:
    """Bambu LAN MQTT exposes TLS with a local certificate, not a public CA cert."""
    config = BambuBridgeConfig.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    probe = BambuLiveProbe(config)

    class DummySocket:
        def close(self) -> None:
            pass

    class VerifiedContext:
        def wrap_socket(self, sock, server_hostname=None):
            raise ssl.SSLError("certificate verify failed")

    class WrappedSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class LanContext:
        def wrap_socket(self, sock, server_hostname=None):
            return WrappedSocket()

    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: DummySocket())
    monkeypatch.setattr(ssl, "create_default_context", lambda: VerifiedContext())
    monkeypatch.setattr(ssl, "_create_unverified_context", lambda: LanContext())

    result = probe.probe_tls_port("192.0.2.42", 8883, 0.1)

    assert result["ok"] is True
    assert result["port"] == 8883


def test_implicit_ftps_reuses_control_tls_session_for_data_channel(monkeypatch) -> None:
    class RawDataSocket:
        pass

    class WrappedDataSocket:
        pass

    class ControlSocket:
        session = "control-session"

    class Context:
        def __init__(self) -> None:
            self.last_session = None

        def wrap_socket(self, conn, server_hostname=None, session=None):
            self.last_session = session
            return WrappedDataSocket()

    def fake_transfer(self, cmd, rest=None):
        return RawDataSocket(), 123

    monkeypatch.setattr(FTP, "ntransfercmd", fake_transfer)
    client = object.__new__(_ImplicitFTP_TLS)
    client.sock = ControlSocket()
    client.context = Context()
    client.host = "192.0.2.42"
    client._prot_p = True

    data_socket, size = client.ntransfercmd("NLST")

    assert isinstance(data_socket, WrappedDataSocket)
    assert size == 123
    assert client.context.last_session == "control-session"


def test_normalize_bambu_report_maps_real_device_fields() -> None:
    report = {
        "print": {
            "gcode_state": "IDLE",
            "mc_percent": 84,
            "layer_num": 108,
            "total_layer_num": 108,
            "nozzle_temper": 31.2,
            "nozzle_target_temper": 0,
            "bed_temper": 29.4,
            "bed_target_temper": 0,
            "fan_gear": 30,
            "subtask_name": "specimen_job.gcode.3mf",
        }
    }

    normalized = normalize_bambu_report(report, received_at="2026-06-14T01:00:00+09:00")

    assert normalized["state"] == "IDLE"
    assert normalized["job"]["progress_percent"] == 84
    assert normalized["job"]["layer"] == 108
    assert normalized["job"]["total_layers"] == 108
    assert normalized["job"]["file_name"] == "specimen_job.gcode.3mf"
    assert normalized["temperatures"]["nozzle_c"] == 31.2
    assert normalized["temperatures"]["bed_c"] == 29.4
    assert normalized["fans"]["part_percent"] == 30
    assert normalized["received_at"] == "2026-06-14T01:00:00+09:00"


def test_normalize_bambu_report_preserves_x2d_device_screen_fields() -> None:
    report = {
        "print": {
            "gcode_state": "FINISH",
            "percent": 100,
            "sdcard": False,
            "3D": {"layer_num": 12, "total_layer_num": 12},
            "hms": [{"code": 131184, "attr": 83887616}],
            "ipcam": {"liveview_preview": True, "resolution": "1080p", "ipcam_record": "enable"},
            "upload": {"status": "idle", "progress": 0, "message": "Good"},
            "lights_report": [{"node": "chamber_light", "mode": "on"}],
            "ams": {
                "ams": [
                    {
                        "id": "0",
                        "humidity": "3",
                        "temp": "21.7",
                        "tray": [
                            {
                                "id": "0",
                                "tray_type": "PLA",
                                "tray_sub_brands": "PLA Basic",
                                "tray_color": "545454FF",
                                "remain": 40,
                            }
                        ],
                    }
                ]
            },
        }
    }

    normalized = normalize_bambu_report(report, received_at="2026-06-14T01:00:00+09:00")

    assert normalized["job"]["progress_percent"] == 100
    assert normalized["job"]["layer"] == 12
    assert normalized["job"]["total_layers"] == 12
    assert normalized["health"]["hms_count"] == 1
    assert normalized["camera"]["liveview_preview"] is True
    assert normalized["camera"]["resolution"] == "1080p"
    assert normalized["upload"]["status"] == "idle"
    assert normalized["storage"]["sdcard_available"] is False
    assert normalized["lights"] == [{"node": "chamber_light", "mode": "on"}]
    assert normalized["materials"]["slots"][0]["tray_type"] == "PLA"
    assert normalized["materials"]["slots"][0]["remain_percent"] == 40


def test_normalize_bambu_report_preserves_x2d_video_and_storage_paths() -> None:
    report = {
        "print": {
            "gcode_state": "FINISH",
            "sdcard": False,
            "gcode_file": "/data/Metadata/plate_1.gcode",
            "ipcam": {
                "liveview_preview": True,
                "resolution": "1080p",
                "rtsp_url": "rtsps://192.0.2.42:322/streaming/live/1",
                "tl_internal_free_kb": 950032,
                "tl_internal_total_kb": 962560,
                "tl_external_free_kb": 0,
                "tl_external_total_kb": 0,
            },
        }
    }

    normalized = normalize_bambu_report(report, received_at="2026-06-14T01:00:00+09:00")

    assert normalized["camera"]["rtsp_url"] == "rtsps://192.0.2.42:322/streaming/live/1"
    assert normalized["storage"]["sdcard_available"] is False
    assert normalized["storage"]["internal_free_kb"] == 950032
    assert normalized["storage"]["internal_total_kb"] == 962560
    assert normalized["storage"]["external_free_kb"] == 0
    assert normalized["storage"]["gcode_file"] == "/data/Metadata/plate_1.gcode"


def test_normalize_bambu_report_preserves_x2d_diagnostics_and_tooling_fields() -> None:
    report = {
        "print": {
            "gcode_state": "FINISH",
            "wifi_signal": "-69dBm",
            "care": [{"id": "ss", "info": "641864"}, {"id": "ls", "info": "103190C"}],
            "hms": [{"code": 131184, "attr": 83887616, "ts_unix": "20260426022410"}],
            "xcam": {
                "spaghetti_detector": True,
                "first_layer_inspector": True,
                "printing_monitor": True,
                "print_halt": True,
            },
            "job": {
                "job_state": 8,
                "cur_stage": {"idx": 0, "state": 0},
                "stage": [{"idx": 0, "type": 2, "tool": ["HS01", "HS01"], "diameter": [0.4, 0.4]}],
            },
            "3D": {"layer_num": 12, "total_layer_num": 12, "ventobox": {"enable": False, "speed": 50}},
            "2D": {"makeable": False, "cond": 15, "material": {"state": 0}},
            "device": {
                "bed": {"info": {"temp": 24}, "state": 0},
                "ctc": {"info": {"temp": 23}, "state": 0},
                "extruder": {"state": 274, "info": [{"id": 0, "temp": 24}, {"id": 1, "temp": 25}]},
                "nozzle": {
                    "exist": 3,
                    "src_id": 0,
                    "tar_id": 0,
                    "info": [
                        {"id": 0, "diameter": 0.4, "type": "HS01", "wear": 0.0},
                        {"id": 1, "diameter": 0.4, "type": "HS01", "wear": 0.0},
                    ],
                },
                "plate": {"cur_id": "P0101", "base": 4, "mat": 1},
            },
            "ams": {
                "ams": [
                    {
                        "id": "0",
                        "humidity": "3",
                        "humidity_raw": "31",
                        "temp": "21.7",
                        "tray": [{"id": "0", "tray_type": "PLA", "remain": 40}],
                    }
                ],
                "ams_exist_bits": "3",
                "tray_exist_bits": "ff",
            },
        }
    }

    normalized = normalize_bambu_report(report, received_at="2026-06-14T01:00:00+09:00")

    assert normalized["health"]["hms_count"] == 1
    assert normalized["health"]["care"][0]["id"] == "ss"
    assert normalized["diagnostics"]["wifi_signal"] == "-69dBm"
    assert normalized["monitoring"]["xcam"]["spaghetti_detector"] is True
    assert normalized["monitoring"]["xcam"]["first_layer_inspector"] is True
    assert normalized["job"]["job_state"] == 8
    assert normalized["job"]["stage_count"] == 1
    assert normalized["modes"]["print_2d"]["makeable"] is False
    assert normalized["modes"]["print_3d"]["ventobox"]["speed"] == 50
    assert normalized["device"]["plate"]["cur_id"] == "P0101"
    assert normalized["device"]["nozzles"][1]["type"] == "HS01"
    assert normalized["device"]["extruders"][1]["temp_c"] == 25
    assert normalized["materials"]["ams_units"][0]["humidity_raw"] == "31"
    assert normalized["materials"]["slots"][0]["ams_temp_c"] == 21.7


def test_normalize_bambu_report_preserves_x2d_runtime_control_and_network_fields() -> None:
    report = {
        "print": {
            "gcode_state": "FINISH",
            "gcode_file_prepare_percent": "100",
            "prepare_per": 99,
            "queue": 0,
            "queue_sts": 1,
            "queue_number": 2,
            "queue_total": 4,
            "queue_est": 120,
            "mc_action": 255,
            "mc_stage": 1,
            "mc_print_stage": "1",
            "mc_print_sub_stage": 0,
            "print_real_action": 0,
            "print_gcode_action": 255,
            "print_error": 0,
            "mc_print_error_code": "0",
            "spd_lvl": 2,
            "spd_mag": 100,
            "cooling_fan_speed": "15",
            "big_fan1_speed": "30",
            "big_fan2_speed": "45",
            "heatbreak_fan_speed": "60",
            "aux_part_fan": True,
            "ams_status": 7,
            "ams_rfid_status": 3,
            "ipcam": {
                "tl_store_path_type": 2,
                "tl_store_hpd_type": 2,
            },
            "net": {
                "conf": 16,
                "info": [{"ip": 1611376832, "mask": 16711679}, {"ip": 0, "mask": 0}],
            },
        }
    }

    normalized = normalize_bambu_report(report, received_at="2026-06-14T01:00:00+09:00")

    assert normalized["job"]["prepare_percent"] == 100
    assert normalized["queue"] == {"enabled": 0, "status": 1, "number": 2, "total": 4, "estimated_sec": 120}
    assert normalized["control"]["mc_action"] == 255
    assert normalized["control"]["mc_stage"] == 1
    assert normalized["control"]["print_real_action"] == 0
    assert normalized["control"]["print_gcode_action"] == 255
    assert normalized["speed"] == {"level": 2, "magnitude_percent": 100}
    assert normalized["fans"]["cooling_percent"] == 15
    assert normalized["fans"]["big_fan1_percent"] == 30
    assert normalized["fans"]["big_fan2_percent"] == 45
    assert normalized["fans"]["heatbreak_percent"] == 60
    assert normalized["fans"]["aux_part_fan_on"] is True
    assert normalized["materials"]["ams_status"] == 7
    assert normalized["materials"]["ams_rfid_status"] == 3
    assert normalized["storage"]["timelapse_store_path_type"] == 2
    assert normalized["network"]["interfaces"][0]["ip"] == "192.168.11.96"
    assert normalized["network"]["interfaces"][0]["raw_ip"] == 1611376832


def test_build_bambu_project_file_command_draft_never_publishes_or_leaks_secrets() -> None:
    draft = build_bambu_project_file_command_draft(
        serial="20PTEST000001",
        remote_path="cache/specimen.gcode.3mf",
        subtask_name="specimen-loop-1",
        plate_id=1,
        use_ams=True,
        ams_mapping=[-1, -1, -1, -1, 0],
    )

    assert draft["ok"] is True
    assert draft["will_publish"] is False
    assert draft["start_enabled"] is False
    assert draft["requires_guardian"] is True
    assert draft["topic"] == "device/20PTEST000001/request"
    assert draft["payload"]["print"]["command"] == "project_file"
    assert draft["payload"]["print"]["url"] == "file:///cache/specimen.gcode.3mf"
    assert draft["payload"]["print"]["param"] == "Metadata/plate_1.gcode"
    assert draft["payload"]["print"]["use_ams"] is True
    assert draft["payload"]["print"]["ams_mapping"] == [-1, -1, -1, -1, 0]
    assert "access_code" not in str(draft).lower()


def test_build_bambu_project_file_command_draft_blocks_missing_ams_mapping() -> None:
    draft = build_bambu_project_file_command_draft(
        serial="20PTEST000001",
        remote_path="cache/specimen.gcode.3mf",
        subtask_name="specimen-loop-1",
        plate_id=1,
        use_ams=True,
        ams_mapping=None,
    )

    assert draft["ok"] is False
    assert draft["failure_code"] == "BAMBU_AMS_MAPPING_REQUIRED"
    assert draft["will_publish"] is False
    assert draft["start_enabled"] is False


def test_build_bambu_project_file_command_draft_blocks_invalid_ams_mapping_length() -> None:
    draft = build_bambu_project_file_command_draft(
        serial="20PTEST000001",
        remote_path="cache/specimen.gcode.3mf",
        subtask_name="specimen-loop-1",
        plate_id=1,
        use_ams=True,
        ams_mapping=[],
    )

    assert draft["ok"] is False
    assert draft["failure_code"] == "BAMBU_AMS_MAPPING_INVALID"


def test_build_bambu_project_file_command_draft_accepts_http_artifact_url() -> None:
    draft = build_bambu_project_file_command_draft(
        serial="20PTEST000001",
        remote_path="http://192.168.50.10:8080/artifacts/specimen.gcode.3mf",
        subtask_name="specimen-http",
        plate_id=2,
        bed_leveling=True,
    )

    assert draft["ok"] is True
    assert draft["payload"]["print"]["url"] == "http://192.168.50.10:8080/artifacts/specimen.gcode.3mf"
    assert draft["payload"]["print"]["param"] == "Metadata/plate_2.gcode"
    assert draft["payload"]["print"]["bed_leveling"] is True
    assert draft["will_publish"] is False


def test_build_bambu_project_file_command_draft_blocks_loopback_http_artifact_url() -> None:
    draft = build_bambu_project_file_command_draft(
        serial="20PTEST000001",
        remote_path="http://127.0.0.1:8080/artifacts/specimen.gcode.3mf",
    )

    assert draft["ok"] is False
    assert draft["failure_code"] == "BAMBU_PROJECT_FILE_HTTP_URL_NOT_PRINTER_REACHABLE"
    assert draft["will_publish"] is False


def test_build_bambu_project_file_command_draft_blocks_missing_artifact_path() -> None:
    draft = build_bambu_project_file_command_draft(serial="20PTEST000001", remote_path="")

    assert draft["ok"] is False
    assert draft["failure_code"] == "BAMBU_PROJECT_FILE_REMOTE_PATH_REQUIRED"
    assert draft["will_publish"] is False


def test_build_bambu_project_file_command_draft_blocks_plain_gcode_param_mismatch() -> None:
    draft = build_bambu_project_file_command_draft(
        serial="20PTEST000001",
        remote_path="cache/specimen.autoeject.gcode",
        subtask_name="plain-gcode-should-not-use-project-file",
        plate_id=1,
    )

    assert draft["ok"] is False
    assert draft["failure_code"] == "BAMBU_PROJECT_FILE_PARAM_MISMATCH"
    assert draft["will_publish"] is False
    assert draft["start_enabled"] is False


def test_build_bambu_project_file_command_draft_blocks_invalid_plate_id() -> None:
    draft = build_bambu_project_file_command_draft(
        serial="20PTEST000001",
        remote_path="cache/specimen.gcode.3mf",
        subtask_name="invalid-plate",
        plate_id=0,
    )

    assert draft["ok"] is False
    assert draft["failure_code"] == "BAMBU_PROJECT_FILE_PARAM_MISMATCH"
    assert draft["will_publish"] is False
    assert draft["start_enabled"] is False


def test_build_bambu_project_file_command_draft_blocks_unsafe_subtask_name() -> None:
    draft = build_bambu_project_file_command_draft(
        serial="20PTEST000001",
        remote_path="cache/specimen.gcode.3mf",
        subtask_name="../unsafe\nname",
        plate_id=1,
    )

    assert draft["ok"] is False
    assert draft["failure_code"] == "BAMBU_PROJECT_FILE_SUBTASK_NAME_INVALID"
    assert draft["will_publish"] is False
    assert draft["start_enabled"] is False


def test_bambu_mqtt_client_publishes_project_file_command_without_leaking_secret(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    published: list[dict[str, object]] = []
    gcode_lines: list[dict[str, object]] = []

    class FakePublishInfo:
        rc = 0

        def wait_for_publish(self, timeout: float | None = None) -> bool:
            published.append({"wait_timeout": timeout})
            return True

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.on_connect = None

        def username_pw_set(self, username: str, password: str) -> None:
            published.append({"username": username, "password_seen": bool(password)})

        def tls_set(self, **kwargs) -> None:
            published.append({"tls": kwargs})

        def tls_insecure_set(self, value: bool) -> None:
            published.append({"tls_insecure": value})

        def connect(self, host: str, port: int, keepalive: int = 30) -> None:
            published.append({"connect": f"{host}:{port}:{keepalive}"})
            if self.on_connect:
                self.on_connect(self, None, None, 0, None)

        def loop_start(self) -> None:
            published.append({"loop_start": True})

        def loop_stop(self) -> None:
            published.append({"loop_stop": True})

        def disconnect(self) -> None:
            published.append({"disconnect": True})

        def publish(self, topic: str, payload: str, qos: int = 0) -> FakePublishInfo:
            published.append({"topic": topic, "payload": payload, "qos": qos})
            return FakePublishInfo()

    class FakeMqtt:
        class CallbackAPIVersion:
            VERSION2 = object()

        Client = FakeClient

    monkeypatch.setattr(bambu_bridge, "mqtt", FakeMqtt)
    config = BambuBridgeConfig.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    client = BambuMqttReportClient(config)
    draft = build_bambu_project_file_command_draft(
        serial="20PTEST000001",
        remote_path="http://192.168.50.10:18080/printer-artifacts/bambu/t/specimen.gcode.3mf",
        subtask_name="specimen-publish",
    )

    result = client.publish_project_file_command(
        host="192.0.2.42",
        serial="20PTEST000001",
        username="bblp",
        access_code="secret-code",
        topic=draft["topic"],
        payload=draft["payload"],
        timeout_sec=0.1,
    )

    publish_event = next(item for item in published if item.get("topic") == "device/20PTEST000001/request")
    assert result["ok"] is True
    assert result["status"] == "published"
    assert result["will_publish"] is True
    assert publish_event["qos"] == 1
    assert '"command": "project_file"' in str(publish_event["payload"])
    assert "secret-code" not in str(result)
    assert "secret-code" not in str(publish_event)


def test_bambu_mqtt_client_rejects_direct_gcode_line_motion(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    class FakeMqtt:
        class CallbackAPIVersion:
            VERSION2 = object()

        class Client:
            def __init__(self, *args, **kwargs) -> None:
                raise AssertionError("unsupported direct-motion command must not instantiate MQTT client")

    monkeypatch.setattr(bambu_bridge, "mqtt", FakeMqtt)
    config = BambuBridgeConfig.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    client = BambuMqttReportClient(config)

    result = client.publish_project_file_command(
        host="192.0.2.42",
        serial="20PTEST000001",
        username="bblp",
        access_code="secret-code",
        topic="device/20PTEST000001/request",
        payload={"print": {"command": "gcode_line", "param": "G0 X0 Y0 F300"}},
        timeout_sec=0.1,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_MQTT_UNSUPPORTED_COMMAND"
    assert result["will_publish"] is False
    assert result["published"] is False


def test_bambu_mqtt_client_publishes_guarded_gcode_line_command(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    published: list[dict[str, object]] = []

    class FakePublishInfo:
        rc = 0
        mid = 42

        def wait_for_publish(self, timeout: float | None = None) -> bool:
            raise AssertionError("gcode_line publish must not block inside the MQTT on_connect callback")

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.on_connect = None
            self.on_publish = None

        def username_pw_set(self, username: str, password: str) -> None:
            published.append({"username": username, "password_seen": bool(password)})

        def tls_set(self, **kwargs) -> None:
            published.append({"tls": kwargs})

        def tls_insecure_set(self, value: bool) -> None:
            published.append({"tls_insecure": value})

        def connect(self, host: str, port: int, keepalive: int = 30) -> None:
            published.append({"connect": f"{host}:{port}:{keepalive}"})
            if self.on_connect:
                self.on_connect(self, None, None, 0, None)

        def loop_start(self) -> None:
            published.append({"loop_start": True})

        def loop_stop(self) -> None:
            published.append({"loop_stop": True})

        def disconnect(self) -> None:
            published.append({"disconnect": True})

        def publish(self, topic: str, payload: str, qos: int = 0) -> FakePublishInfo:
            published.append({"topic": topic, "payload": payload, "qos": qos})
            if self.on_publish:
                self.on_publish(self, None, 42, None, None)
            return FakePublishInfo()

    class FakeMqtt:
        class CallbackAPIVersion:
            VERSION2 = object()

        Client = FakeClient

    monkeypatch.setattr(bambu_bridge, "mqtt", FakeMqtt)
    config = BambuBridgeConfig.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    client = BambuMqttReportClient(config)

    result = client.publish_gcode_line_command(
        host="192.0.2.42",
        serial="20PTEST000001",
        username="bblp",
        access_code="secret-code",
        topic="device/20PTEST000001/request",
        gcode="G90\nG0 X128 Y245 F150",
        timeout_sec=0.1,
    )

    publish_event = next(item for item in published if item.get("topic") == "device/20PTEST000001/request")
    payload = json.loads(str(publish_event["payload"]))
    assert result["ok"] is True
    assert result["status"] == "published"
    assert result["command"] == "gcode_line"
    assert publish_event["qos"] == 1
    assert payload["print"]["command"] == "gcode_line"
    assert payload["print"]["param"].endswith("\n")
    assert "G0 X128 Y245 F150" in payload["print"]["param"]
    assert "secret-code" not in str(result)
    assert published[-2:] == [{"disconnect": True}, {"loop_stop": True}]


def test_bambu_mqtt_client_waits_for_gcode_line_puback_before_success(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    events: list[dict[str, object]] = []

    class FakePublishInfo:
        rc = 0
        mid = 77

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.on_connect = None
            self.on_publish = None

        def username_pw_set(self, username: str, password: str) -> None:
            events.append({"username": username, "password_seen": bool(password)})

        def tls_set(self, **kwargs) -> None:
            events.append({"tls": kwargs})

        def tls_insecure_set(self, value: bool) -> None:
            events.append({"tls_insecure": value})

        def connect(self, host: str, port: int, keepalive: int = 30) -> None:
            events.append({"connect": f"{host}:{port}:{keepalive}"})
            if self.on_connect:
                self.on_connect(self, None, None, 0, None)

        def loop_start(self) -> None:
            events.append({"loop_start": True})

        def disconnect(self) -> None:
            events.append({"disconnect": True})

        def loop_stop(self) -> None:
            events.append({"loop_stop": True})

        def publish(self, topic: str, payload: str, qos: int = 0) -> FakePublishInfo:
            events.append({"topic": topic, "payload": payload, "qos": qos})
            return FakePublishInfo()

    class FakeMqtt:
        class CallbackAPIVersion:
            VERSION2 = object()

        Client = FakeClient

    monkeypatch.setattr(bambu_bridge, "mqtt", FakeMqtt)
    config = BambuBridgeConfig.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    client = BambuMqttReportClient(config)

    result = client.publish_gcode_line_command(
        host="192.0.2.42",
        serial="20PTEST000001",
        username="bblp",
        access_code="secret-code",
        topic="device/20PTEST000001/request",
        gcode="G90\nG0 X128 Y245 F150",
        timeout_sec=0.001,
    )

    assert result["ok"] is False
    assert result["status"] == "timeout"
    assert result["failure_code"] == "BAMBU_MQTT_PUBLISH_TIMEOUT"
    assert result["published"] is False
    assert events[-2:] == [{"disconnect": True}, {"loop_stop": True}]


def test_bambu_mqtt_snapshot_reuses_recent_report_without_reconnecting_or_pushall(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    events: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            events.append({"client_created": kwargs.get("client_id") or (args[1] if len(args) > 1 else "")})
            self.on_connect = None
            self.on_message = None

        def username_pw_set(self, username: str, password: str) -> None:
            events.append({"username": username, "password_seen": bool(password)})

        def tls_set(self, **kwargs) -> None:
            events.append({"tls": kwargs})

        def tls_insecure_set(self, value: bool) -> None:
            events.append({"tls_insecure": value})

        def connect(self, host: str, port: int, keepalive: int = 30) -> None:
            events.append({"connect": f"{host}:{port}:{keepalive}"})
            if self.on_connect:
                self.on_connect(self, None, None, 0, None)

        def loop_start(self) -> None:
            events.append({"loop_start": True})

        def loop_stop(self) -> None:
            events.append({"loop_stop": True})

        def disconnect(self) -> None:
            events.append({"disconnect": True})

        def subscribe(self, topic: str, qos: int = 0) -> None:
            events.append({"subscribe": topic, "qos": qos})

        def publish(self, topic: str, payload: str, qos: int = 0):
            events.append({"topic": topic, "payload": payload, "qos": qos})
            if self.on_message:
                report = {"print": {"gcode_state": "IDLE", "mc_percent": 7}}
                msg = type("Message", (), {"topic": topic.replace("/request", "/report"), "payload": json.dumps(report).encode("utf-8")})
                self.on_message(self, None, msg)
            return type("Info", (), {"rc": 0})()

    class FakeMqtt:
        class CallbackAPIVersion:
            VERSION2 = object()

        Client = FakeClient

    monkeypatch.setattr(bambu_bridge, "mqtt", FakeMqtt)
    config = BambuBridgeConfig.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    client = BambuMqttReportClient(config)

    first = client.read_snapshot(
        host="192.0.2.42",
        serial="20PTEST000001",
        username="bblp",
        access_code="secret-code",
        timeout_sec=0.1,
    )
    second = client.read_snapshot(
        host="192.0.2.42",
        serial="20PTEST000001",
        username="bblp",
        access_code="secret-code",
        timeout_sec=0.1,
    )

    pushall_events = [event for event in events if "pushall" in str(event.get("payload", ""))]
    assert first["ok"] is True
    assert second["ok"] is True
    assert second["cache_status"] == "cache_hit"
    assert len([event for event in events if "client_created" in event]) == 1
    assert len(pushall_events) == 1
    assert "secret-code" not in str(second)


def test_bambu_mqtt_snapshot_force_refresh_bypasses_recent_cache(monkeypatch, tmp_path: Path) -> None:
    from device_bridges import bambu_bridge

    created: list[int] = []

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            created.append(len(created) + 1)
            self.on_connect = None
            self.on_message = None

        def username_pw_set(self, username: str, password: str) -> None:
            pass

        def tls_set(self, **kwargs) -> None:
            pass

        def tls_insecure_set(self, value: bool) -> None:
            pass

        def connect(self, host: str, port: int, keepalive: int = 30) -> None:
            if self.on_connect:
                self.on_connect(self, None, None, 0, None)

        def loop_start(self) -> None:
            pass

        def loop_stop(self) -> None:
            pass

        def disconnect(self) -> None:
            pass

        def subscribe(self, topic: str, qos: int = 0) -> None:
            pass

        def publish(self, topic: str, payload: str, qos: int = 0):
            if self.on_message:
                report = {"print": {"gcode_state": "IDLE", "mc_percent": created[-1]}}
                msg = type("Message", (), {"topic": topic.replace("/request", "/report"), "payload": json.dumps(report).encode("utf-8")})
                self.on_message(self, None, msg)
            return type("Info", (), {"rc": 0})()

    class FakeMqtt:
        class CallbackAPIVersion:
            VERSION2 = object()

        Client = FakeClient

    monkeypatch.setattr(bambu_bridge, "mqtt", FakeMqtt)
    config = BambuBridgeConfig.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    client = BambuMqttReportClient(config)

    first = client.read_snapshot(
        host="192.0.2.42",
        serial="20PTEST000001",
        username="bblp",
        access_code="secret-code",
        timeout_sec=0.1,
    )
    second = client.read_snapshot(
        host="192.0.2.42",
        serial="20PTEST000001",
        username="bblp",
        access_code="secret-code",
        timeout_sec=0.1,
        force_refresh=True,
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["cache_status"] == "refreshed"
    assert second["report"]["print"]["mc_percent"] == 2
    assert len(created) == 2


def test_live_bambu_uses_mqtt_report_for_device_screen_and_preprint_gate(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port, "checked_at": "2026-06-14T01:00:00+09:00"}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            assert host == "192.0.2.42"
            assert serial == "20PTEST000001"
            assert username == "bblp"
            assert access_code == "secret"
            return {
                "ok": True,
                "topic": "device/20PTEST000001/report",
                "received_at": "2026-06-14T01:00:02+09:00",
                "report": {
                    "print": {
                        "gcode_state": "IDLE",
                        "mc_percent": 100,
                        "gcode_file_prepare_percent": "88",
                        "spd_mag": 100,
                        "queue_number": 1,
                        "queue_total": 3,
                        "mc_action": 255,
                        "net": {"info": [{"ip": 1611376832, "mask": 16711679}]},
                        "bed_temper": 31,
                        "nozzle_temper": 30,
                        "ipcam": {"liveview_preview": True, "resolution": "1080p"},
                        "upload": {"status": "idle", "progress": 0},
                        "ams": {"ams": [{"id": "0", "tray": [{"id": "0", "tray_type": "PLA", "remain": 40}]}]},
                    }
                },
            }

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            assert host == "192.0.2.42"
            assert username == "bblp"
            assert access_code == "secret"
            assert write_probe is True
            return {"ok": True, "storage": "sdcard", "entries_sample": ["cache", "timelapse"]}

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare({"runtime_mode": "live", "run_id": "run-1", "specimen_id": "sp-1"})

    assert result["ok"] is True
    assert result["status"] == "READY_TO_UPLOAD"
    assert result["device_screen"]["connection"]["mqtt"] == "connected"
    assert result["device_screen"]["connection"]["transfer"] == "connected"
    assert result["device_screen"]["job"]["progress_percent"] == 100
    assert result["device_screen"]["job"]["prepare_percent"] == 88
    assert result["device_screen"]["motion"]["speed"]["magnitude_percent"] == 100
    assert result["device_screen"]["motion"]["queue"]["number"] == 1
    assert result["device_screen"]["motion"]["control"]["mc_action"] == 255
    assert result["device_screen"]["network"]["interfaces"][0]["ip"] == "192.168.11.96"
    assert result["device_screen"]["temperatures"]["bed_c"] == 31
    assert result["device_screen"]["camera"]["liveview_preview"] is True
    assert result["device_screen"]["upload"]["status"] == "idle"
    assert result["device_screen"]["materials"]["slots"][0]["tray_type"] == "PLA"
    assert result["device_screen"]["actions"]["can_upload"] is True
    assert result["device_screen"]["actions"]["can_start_print"] is False
    assert result["preprint_gate"]["checks"]["latest_report_fresh"] is True
    assert result["preprint_gate"]["checks"]["storage_transfer_path_verified"] is True
    assert result["preprint_gate"]["checks"]["printer_safe_state_verified"] is True
    assert result["device_screen"]["progress_panel"] == {
        "state": "IDLE",
        "job_name": "",
        "progress_percent": 100,
        "prepare_percent": 88,
        "current_layer": None,
        "total_layers": None,
        "remaining_min": None,
        "source": "mqtt_report",
    }
    assert result["device_screen"]["camera_panel"]["status"] == "preview_available"
    assert result["device_screen"]["camera_panel"]["stream_kind"] == "liveview_preview"
    assert result["device_screen"]["control_panel"]["state"] == "IDLE"
    assert result["device_screen"]["control_panel"]["queue_label"] == "1/3"
    assert result["device_screen"]["material_panel"]["slot_count"] == 1
    assert result["device_screen"]["material_panel"]["slots"][0]["tray_type"] == "PLA"
    evidence = {card["id"]: card for card in result["device_screen"]["evidence_cards"]}
    assert evidence["mqtt"]["status"] == "connected"
    assert evidence["transfer"]["status"] == "connected"
    assert evidence["video"]["status"] == "unknown"
    assert evidence["safe_state"]["status"] == "ready"


def test_live_bambu_post_publish_observation_forces_mqtt_refresh(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    force_refresh_calls: list[bool] = []

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(
            self,
            *,
            host: str,
            serial: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            force_refresh: bool = False,
        ) -> dict:
            force_refresh_calls.append(force_refresh)
            return {
                "ok": True,
                "received_at": "2026-06-14T01:00:02+09:00",
                "report": {"print": {"gcode_state": "RUNNING", "mc_percent": 1}},
            }

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {"ok": True, "storage": "sdcard"}

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-1",
            "post_publish_observation": True,
        }
    )

    assert result["ok"] is True
    assert force_refresh_calls == [True]
    assert result["device_screen"]["progress_panel"]["state"] == "RUNNING"


def test_bambu_post_publish_running_snapshot_carries_progress_evidence(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    running = manager._classify_bambu_post_publish_snapshot(
        {
            "ok": True,
            "received_at": "2026-07-10T09:00:00+09:00",
            "report": {
                "print": {
                    "gcode_state": "RUNNING",
                    "mc_percent": 1,
                    "subtask_name": "specimen-cand-1",
                    "task_id": "task-123",
                }
            },
        }
    )
    idle = manager._classify_bambu_post_publish_snapshot(
        {
            "ok": True,
            "received_at": "2026-07-10T09:00:01+09:00",
            "report": {"print": {"gcode_state": "IDLE", "mc_percent": 0}},
        }
    )

    assert running["status"] == "running"
    assert running["progress_observed"] is True
    assert running["progress_percent"] == 1
    assert running["file_name"] == "specimen-cand-1"
    assert running["task_id"] == "task-123"
    assert idle["status"] == "idle"
    assert idle["failure_code"] == "BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED"


def test_bambu_post_publish_fast_ejection_done_snapshot_is_completed(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)

    completed = manager._classify_bambu_post_publish_snapshot(
        {
            "ok": True,
            "received_at": "2026-07-10T09:00:02+09:00",
            "report": {
                "print": {
                    "gcode_state": "FINISH",
                    "mc_percent": 100,
                    "stg_cur": 1,
                    "stg": [1],
                    "subtask_name": "specimen-cand-1.ejection-test",
                    "task_id": "task-456",
                }
            },
        },
        expected_subtask_name="specimen-cand-1.ejection-test",
    )

    assert completed["status"] == "completed"
    assert completed["failure_code"] == ""
    assert completed["progress_observed"] is True
    assert completed["progress_percent"] == 100
    assert completed["file_name"] == "specimen-cand-1.ejection-test"


def test_live_bambu_marks_ftps_read_only_as_transfer_read_only(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {
                "ok": False,
                "read_ok": True,
                "failure_code": "BAMBU_FTPS_WRITE_FAILED",
                "error": "553 Could not create file.",
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare({"runtime_mode": "live", "run_id": "run-1", "specimen_id": "sp-1"})

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_FTPS_WRITE_FAILED"
    assert result["device_screen"]["connection"]["transfer"] == "read_only"
    assert result["preprint_gate"]["checks"]["mqtt_authenticated_or_virtual"] is True
    assert result["device_screen"]["actions"]["can_upload"] is False
    assert result["preprint_gate"]["checks"]["developer_mode_confirmed"] is False
    assert any(action["code"] == "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED" for action in result["operator_actions"])


def test_live_bambu_recovers_writable_cache_path_after_root_marker_write_fails(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    path_probe_called: list[bool] = []

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {
                "ok": False,
                "read_ok": True,
                "failure_code": "BAMBU_FTPS_WRITE_FAILED",
                "error": "553 Could not create file at root.",
            }

        def probe_upload_paths(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, candidate_dirs=None
        ) -> dict:
            path_probe_called.append(True)
            return {
                "ok": True,
                "write_ok": True,
                "storage": "ftps",
                "selected_remote_dir": "cache",
                "selected_remote_path": "cache/atr-ftps-path-probe.txt",
                "candidates": [
                    {"remote_dir": "", "remote_path": "atr-ftps-path-probe.txt", "ok": False},
                    {"remote_dir": "cache", "remote_path": "cache/atr-ftps-path-probe.txt", "ok": True},
                ],
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare({"runtime_mode": "live", "run_id": "run-1", "specimen_id": "sp-1"})

    assert path_probe_called == [True]
    assert result["ok"] is True
    assert result["status"] == "READY_TO_UPLOAD"
    assert result["failure_code"] == ""
    assert result["ftps_probe"]["ok"] is True
    assert result["ftps_probe"]["selected_remote_dir"] == "cache"
    assert result["device_screen"]["connection"]["transfer"] == "connected"
    assert result["preprint_gate"]["checks"]["storage_transfer_path_verified"] is True
    assert all(action["code"] != "BAMBU_FTPS_WRITE_FAILED" for action in result["operator_actions"])


def test_live_bambu_uploads_explicit_sliced_artifact_without_starting_print(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    sliced = tmp_path / "sp-1.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(sliced)
    uploaded: dict[str, str | bool] = {}

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {
                "ok": True,
                "received_at": "2026-06-14T01:00:02+09:00",
                "report": {"print": {"gcode_state": "IDLE", "upload": {"status": "idle", "progress": 0}}},
            }

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            assert write_probe is True
            return {"ok": True, "storage": "ftps", "entries_sample": []}

        def upload_file(
            self,
            *,
            local_path,
            remote_path: str,
            host: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            delete_after: bool = False,
        ) -> dict:
            uploaded["local_path"] = str(local_path)
            uploaded["remote_path"] = remote_path
            uploaded["delete_after"] = delete_after
            return {
                "ok": True,
                "status": "uploaded",
                "remote_path": remote_path,
                "size_bytes": 20,
                "sha256": "abc123",
                "delete_after": False,
                "deleted": False,
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-1",
            "bambu_artifact_path": str(sliced),
        }
    )

    assert result["ok"] is True
    assert result["status"] == "UPLOADED_NOT_STARTED"
    assert uploaded["local_path"] == str(sliced)
    assert uploaded["remote_path"] == "sp-1.gcode.3mf"
    assert uploaded["delete_after"] is False
    assert result["upload"]["remote_path"] == "sp-1.gcode.3mf"
    assert result["project_file_draft"]["ok"] is True
    assert result["project_file_draft"]["payload"]["print"]["url"] == "file:///sp-1.gcode.3mf"
    assert result["project_file_draft"]["will_publish"] is False
    assert result["preprint_gate"]["checks"]["slicer_artifact_hash_recorded"] is True
    assert result["preprint_gate"]["checks"]["start_command_draft_prepared"] is True
    assert result["device_screen"]["upload"]["artifact"]["sha256"] == "abc123"
    assert result["device_screen"]["upload"]["start_command_draft"]["payload"]["print"]["command"] == "project_file"
    assert result["device_screen"]["actions"]["can_start_print"] is True
    assert result["device_screen"]["actions"]["requires_guardian"] is True


def test_live_bambu_prepare_physical_stl_uses_http_artifact_and_publishes_when_ftps_is_busy(
    tmp_path: Path,
) -> None:
    fake_cli = tmp_path / "bambu-studio"
    fake_cli.write_text(
        """#!/bin/sh
set -eu
out=""
name="specimen.gcode.3mf"
prev=""
for arg in "$@"; do
  if [ "$prev" = "--outputdir" ]; then
    out="$arg"
  fi
  if [ "$prev" = "--export-3mf" ]; then
    name="$arg"
  fi
  prev="$arg"
done
mkdir -p "$out"
python3 - "$out/$name" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w") as archive:
    archive.writestr("Metadata/plate_1.gcode", "G90\\nG1 X10 Y10 Z10 F1200\\nM84\\n")
    archive.writestr("3D/3dmodel.model", "<model />")
PY
""",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    raw = _devices_config(tmp_path)
    raw["devices"]["printer"]["bambu"]["slicer"] = {
        "enabled": True,
        "executable_path": str(fake_cli),
        "output_dir": str(tmp_path / "bambu_sliced"),
        "timeout_sec": 5,
    }
    manager = PrinterDeviceBridgeManager.from_devices_config(raw, repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    stl = tmp_path / "specimen.stl"
    stl.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    published: dict[str, object] = {}
    snapshots: list[bool] = []

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(
            self,
            *,
            host: str,
            serial: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            force_refresh: bool = False,
        ) -> dict:
            snapshots.append(force_refresh)
            state = "RUNNING" if force_refresh else "FINISH"
            return {
                "ok": True,
                "received_at": "2026-06-14T01:00:02+09:00",
                "report": {"print": {"gcode_state": state, "mc_percent": 100}},
            }

        def publish_project_file_command(self, **kwargs) -> dict:
            published.update(kwargs)
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-test",
                "topic": kwargs.get("topic"),
            }

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {
                "ok": False,
                "storage": "ftps",
                "failure_code": "BAMBU_FTPS_TOO_MANY_CONNECTIONS",
                "error": "421 There are too many connections from your internet address.",
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-physical",
            "stl_path": str(stl),
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
                "public_base_url": "http://192.0.2.10:7860",
            },
        }
    )

    assert result["ok"] is True
    assert result["status"] == "PRINT_STARTED"
    assert result["slicer_result"]["ok"] is True
    assert result["http_artifact_route"]["ok"] is True
    assert result["upload"]["route"] == "http_artifact"
    assert result["device_screen"]["connection"]["transfer"] == "connected"
    assert result["device_screen"]["actions"]["can_start_print"] is True
    assert result["print_result"]["published"] is True
    assert result["print_result"]["post_publish_status"]["status"] == "running"
    assert published["payload"]["print"]["command"] == "project_file"
    assert str(published["payload"]["print"]["url"]).startswith("http://192.0.2.10:7860/printer-artifacts/bambu/")
    assert snapshots == [False, True]


def test_test_mode_installed_printer_uploads_starts_then_stops_before_autoejection(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    sliced = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(
        sliced,
        gcode="\n".join(
            [
                "G90",
                "M82",
                "G92 E0",
                "G1 X110 Y110 Z0.2 E0.1 F1200",
                "G1 X146 Y110 Z0.2 E0.2 F1200",
                "G1 X146 Y143 Z12.0 E0.3 F1200",
                "G1 X110 Y143 Z20.0 E0.4 F1200",
                "M84",
            ]
        ),
    )
    published: dict[str, object] = {}
    controls: list[dict[str, object]] = []
    uploaded: dict[str, object] = {}
    snapshots: list[bool] = []

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(
            self,
            *,
            host: str,
            serial: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            force_refresh: bool = False,
        ) -> dict:
            snapshots.append(force_refresh)
            state = "RUNNING" if force_refresh else "IDLE"
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": state, "mc_percent": 1}}}

        def publish_project_file_command(self, **kwargs) -> dict:
            published.update(kwargs)
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-start",
                "topic": kwargs.get("topic"),
            }

        def publish_print_control_command(self, **kwargs) -> dict:
            controls.append(kwargs)
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-stop",
                "command": kwargs.get("command"),
                "topic": kwargs.get("topic"),
            }

        def publish_gcode_line_command(self, **kwargs) -> dict:
            gcode_lines.append(kwargs)
            return {
                "ok": True,
                "tool": "printer.bambu.mqtt_gcode_line",
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-gcode-line",
                "command": "gcode_line",
                "gcode_line_count": len(str(kwargs.get("gcode") or "").splitlines()),
                "topic": kwargs.get("topic"),
            }

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            assert write_probe is True
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(
            self,
            *,
            local_path: Path,
            remote_path: str,
            host: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            delete_after: bool = False,
        ) -> dict:
            uploaded.update({"local_path": str(local_path), "remote_path": remote_path, "delete_after": delete_after})
            return {
                "ok": True,
                "status": "uploaded",
                "storage": "ftps",
                "remote_path": remote_path,
                "sha256": hashlib.sha256(Path(local_path).read_bytes()).hexdigest(),
                "delete_after": delete_after,
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
                "stop_after_start": True,
            },
        }
    )

    assert result["ok"] is True
    assert result["status"] == "TEST_PRINTER_STARTED_THEN_STOPPED"
    assert result["mode"] == "test"
    assert result["physical_transport"] is True
    assert result["device_screen"]["connection"]["mqtt"] == "connected"
    assert result["device_screen"]["connection"]["transfer"] == "connected"
    assert result["preprint_gate"]["checks"]["storage_transfer_path_verified"] is True
    assert result["step_trace"][1]["step"] == "BAMBU_MQTT_TLS_PREFLIGHT"
    assert uploaded["remote_path"].endswith(".gcode.3mf")
    assert published["payload"]["print"]["command"] == "project_file"
    assert controls and controls[0]["command"] == "stop"
    assert result["print_result"]["published"] is True
    assert result["print_result"]["stop_after_start"] is True
    assert result["print_result"]["stop"]["published"] is True
    assert snapshots == [False, True]


def test_test_mode_installed_printer_uploads_ejection_only_project_file_from_actual_slice(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    manager.save_autoejection_config(
        {
            "enabled": True,
            "provider": "bambu_gcode_patch",
            "push_direction": "center",
            "object_size_mm": [30.0, 30.0, 20.0],
        }
    )
    sliced = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(
        sliced,
        gcode="\n".join(
            [
                "G90",
                "M82",
                "G92 E0",
                "G1 X110 Y110 Z0.2 E0.1 F1200",
                "G1 X146 Y110 Z0.2 E0.2 F1200",
                "G1 X146 Y143 Z12.0 E0.3 F1200",
                "G1 X110 Y143 Z20.0 E0.4 F1200",
                "M84",
            ]
        ),
    )
    published: list[dict[str, object]] = []
    controls: list[dict[str, object]] = []
    uploads: list[dict[str, object]] = []
    gcode_lines: list[dict[str, object]] = []

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(
            self,
            *,
            host: str,
            serial: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            force_refresh: bool = False,
        ) -> dict:
            state = "RUNNING" if force_refresh else "IDLE"
            return {
                "ok": True,
                "received_at": "now",
                "report": {"print": {"gcode_state": state, "mc_percent": 1, "bed_temper": 29}},
            }

        def publish_project_file_command(self, **kwargs) -> dict:
            published.append(kwargs)
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": f"seq-start-{len(published)}",
                "topic": kwargs.get("topic"),
            }

        def publish_print_control_command(self, **kwargs) -> dict:
            controls.append(kwargs)
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-stop",
                "command": kwargs.get("command"),
                "topic": kwargs.get("topic"),
            }

        def publish_gcode_line_command(self, **kwargs) -> dict:
            gcode_lines.append(kwargs)
            return {
                "ok": True,
                "tool": "printer.bambu.mqtt_gcode_line",
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-gcode-line",
                "command": "gcode_line",
                "gcode_line_count": len(str(kwargs.get("gcode") or "").splitlines()),
                "topic": kwargs.get("topic"),
            }

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            assert write_probe is True
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(
            self,
            *,
            local_path: Path,
            remote_path: str,
            host: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            delete_after: bool = False,
        ) -> dict:
            uploads.append({"local_path": str(local_path), "remote_path": remote_path, "delete_after": delete_after})
            return {
                "ok": True,
                "status": "uploaded",
                "storage": "ftps",
                "remote_path": remote_path,
                "sha256": hashlib.sha256(Path(local_path).read_bytes()).hexdigest(),
                "delete_after": delete_after,
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
                "stop_after_start": True,
            },
            "ejection": {
                "enabled": True,
                "allow_ejection": True,
                "standalone_after_start_stop": True,
                "use_ejection_only_project_file": True,
                "position": "center",
                "object_size_mm": [30.0, 30.0, 20.0],
            },
        }
    )

    assert result["ok"] is True
    assert result["status"] == "TEST_PRINTER_EJECTION_PROJECT_STARTED"
    assert controls == []
    assert len(published) == 1
    assert len(uploads) == 1
    assert len(gcode_lines) == 0
    assert str(uploads[0]["local_path"]).endswith(".ejection-test.gcode.3mf")
    assert str(uploads[0]["remote_path"]).endswith(".ejection-test.gcode.3mf")
    assert result["ejection_only_project_file"] is True
    assert result["autoejection_patch"]["ok"] is True
    assert result["autoejection_patch"]["patched_artifact_path"] == uploads[0]["local_path"]
    with zipfile.ZipFile(uploads[0]["local_path"]) as archive:
        patched_gcode = archive.read("Metadata/plate_1.gcode").decode("utf-8")
    assert "G0 X128.000 Y245.000" in patched_gcode
    assert "E0.1" not in patched_gcode
    assert "; atr_print_body_omitted=true" in patched_gcode
    assert "; atr_cooldown_wait_policy=not_required_no_print_body" in patched_gcode
    assert "M190 R40" not in patched_gcode
    assert "G28 ; atr_autoejection_home_all_axes" not in patched_gcode
    assert result["ejection_result"] == {}
    assert any(item["step"] == "BAMBU_NATIVE_AUTOEJECTION_PATCH" and item["status"] == "ok" for item in result["step_trace"])


def test_test_mode_installed_printer_autoejection_uses_actual_sliced_artifact_bounds(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch", "push_direction": "center"})
    sliced = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(
        sliced,
        gcode="\n".join(
            [
                "G90",
                "M82",
                "G92 E0",
                "G1 X30 Y40 Z0.2 E0.1 F1200",
                "G1 X70 Y40 Z0.2 E0.2 F1200",
                "G1 X70 Y80 Z6.0 E0.3 F1200",
                "G1 X30 Y80 Z12.0 E0.4 F1200",
                "M84",
            ]
        ),
    )
    gcode_lines: list[dict[str, object]] = []
    uploads: list[dict[str, object]] = []
    published: list[dict[str, object]] = []
    controls: list[dict[str, object]] = []

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, **kwargs) -> dict:
            state = "RUNNING" if kwargs.get("force_refresh") else "IDLE"
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": state, "mc_percent": 1, "bed_temper": 29}}}

        def publish_project_file_command(self, **kwargs) -> dict:
            published.append(kwargs)
            return {"ok": True, "status": "published", "will_publish": True, "published": True, "sequence_id": "seq-start", "topic": kwargs.get("topic")}

        def publish_print_control_command(self, **kwargs) -> dict:
            controls.append(kwargs)
            return {"ok": True, "status": "published", "will_publish": True, "published": True, "sequence_id": "seq-stop", "command": kwargs.get("command"), "topic": kwargs.get("topic")}

        def publish_gcode_line_command(self, **kwargs) -> dict:
            gcode_lines.append(kwargs)
            return {"ok": True, "tool": "printer.bambu.mqtt_gcode_line", "status": "published", "will_publish": True, "published": True, "sequence_id": "seq-gcode-line", "command": "gcode_line", "topic": kwargs.get("topic")}

    class FakeFtpsClient:
        def probe_storage(self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False) -> dict:
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(self, *, local_path: Path, remote_path: str, host: str, username: str, access_code: str, timeout_sec: float, delete_after: bool = False) -> dict:
            uploads.append({"local_path": str(local_path), "remote_path": remote_path, "delete_after": delete_after})
            return {
                "ok": True,
                "status": "uploaded",
                "storage": "ftps",
                "local_path": str(local_path),
                "remote_path": remote_path,
                "sha256": hashlib.sha256(Path(local_path).read_bytes()).hexdigest(),
                "delete_after": delete_after,
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
                "stop_after_start": False,
                "use_ejection_only_project_file": True,
            },
            "ejection": {
                "enabled": True,
                "allow_ejection": True,
                "standalone_after_start_stop": True,
                "use_ejection_only_project_file": True,
                "position": "center",
                "object_size_mm": [30.0, 30.0, 30.0],
            },
        }
    )

    assert result["ok"] is True
    assert len(gcode_lines) == 0
    assert len(uploads) == 1
    assert len(published) == 1
    assert controls == []
    assert result["status"] == "TEST_PRINTER_EJECTION_PROJECT_STARTED"
    assert result["ejection_only_project_file"] is True
    assert result["upload"]["remote_path"].endswith(".ejection-test.gcode.3mf")
    assert result["print_result"].get("stop_after_start") is not True
    assert result["ejection_result"] == {}
    assert result["autoejection_patch"]["source_object_bounds_mm"]["source"] == "extrusion_moves"
    assert result["autoejection_patch"]["source_object_bounds_mm"]["center_x_mm"] == 50.0
    assert result["autoejection_patch"]["source_object_bounds_mm"]["center_y_mm"] == 60.0
    assert result["autoejection_patch"]["source_object_bounds_mm"]["max_z"] == 12.0
    assert uploads[0]["local_path"].endswith(".ejection-test.gcode.3mf")
    with zipfile.ZipFile(uploads[0]["local_path"]) as archive:
        gcode = archive.read("Metadata/plate_1.gcode").decode("utf-8")
    assert "E0.1" not in gcode
    assert "E0.4" not in gcode
    assert "; atr_print_body_omitted=true" in gcode
    assert "; atr_assumed_object_bounds_mm=" in gcode
    assert "G0 Z10.000 F3000" in gcode
    assert gcode.index("G0 Z20.000 F3000") < gcode.index("G0 X50.000 Y245.000")
    assert gcode.index("G0 X50.000 Y245.000") < gcode.index("G0 Z10.000 F3000")
    assert "G0 Z2.000 F3000" not in gcode
    assert "G0 Z22.000 F3000" not in gcode
    assert "G0 X50.000 Y245.000" in gcode
    assert "G0 X128.000 Y245.000" not in gcode


def test_printer_preflight_builds_position_aware_actual_print_artifact_without_network(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch", "push_direction": "center"})
    sliced = tmp_path / "candidate-7.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(
        sliced,
        gcode="\n".join(
            [
                "G90",
                "M82",
                "G92 E0",
                "G1 X30 Y40 Z0.2 E0.1 F1200",
                "G1 X70 Y40 Z0.2 E0.2 F1200",
                "G1 X70 Y80 Z6.0 E0.3 F1200",
                "G1 X30 Y80 Z12.0 E0.4 F1200",
                "M84",
            ]
        ),
    )

    class Tripwire:
        def __getattr__(self, name):
            raise AssertionError(f"printer preflight must not call network method: {name}")

    manager.live_probe = Tripwire()
    manager.mqtt_client = Tripwire()
    manager.ftps_client = Tripwire()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "execution_policy_mode": "preflight_only",
            "test_printer_path": "physical_print",
            "bambu_artifact_path": str(sliced),
            "specimen_id": "candidate-7",
            "run_id": "run-safe",
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
            },
            "ejection": {"enabled": True, "allow_ejection": True, "position": "center"},
        }
    )

    preflight = result["printer_preflight"]
    patched = Path(preflight["immutable_artifact_path"])
    assert result["ok"] is True
    assert result["status"] == "execution_ready_pending_approval"
    assert preflight["actuation_performed"] is False
    assert preflight["upload_performed"] is False
    assert preflight["start_command_published"] is False
    assert preflight["specimen_id"] == "candidate-7"
    assert preflight["plate_id"] == 1
    assert preflight["source_object_bounds_mm"]["source"] == "extrusion_moves"
    assert preflight["source_object_bounds_mm"]["center_x_mm"] == 50.0
    assert preflight["source_object_bounds_mm"]["center_y_mm"] == 60.0
    assert preflight["artifact_sha256"] == hashlib.sha256(patched.read_bytes()).hexdigest()
    assert preflight["artifact_plate_validation"]["ok"] is True
    with zipfile.ZipFile(patched) as archive:
        gcode = archive.read("Metadata/plate_1.gcode").decode("utf-8")
    assert "G1 X30 Y40 Z0.2 E0.1 F1200" in gcode
    assert "; atr.bambu.autoejection.v1" in gcode
    assert "G0 X50.000 Y245.000" in gcode


def test_test_mode_physical_print_keeps_actual_print_body_when_autoejection_is_enabled(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch", "push_direction": "center"})
    sliced = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(
        sliced,
        gcode="\n".join(
            [
                "G90",
                "M82",
                "G92 E0",
                "G1 X30 Y40 Z0.2 E0.1 F1200",
                "G1 X70 Y40 Z0.2 E0.2 F1200",
                "G1 X70 Y80 Z6.0 E0.3 F1200",
                "G1 X30 Y80 Z30.0 E0.4 F1200",
                "M84",
                "M73 P100 R0",
            ]
        ),
    )

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, **kwargs) -> dict:
            state = "RUNNING" if kwargs.get("force_refresh") else "IDLE"
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": state, "mc_percent": 1, "bed_temper": 29}}}

        def publish_project_file_command(self, **kwargs) -> dict:
            return {"ok": True, "status": "published", "will_publish": True, "published": True, "sequence_id": "seq-start", "topic": kwargs.get("topic")}

        def publish_print_control_command(self, **kwargs) -> dict:
            return {"ok": True, "status": "published", "will_publish": True, "published": True, "sequence_id": "seq-stop", "command": kwargs.get("command"), "topic": kwargs.get("topic")}

        def publish_gcode_line_command(self, **kwargs) -> dict:
            raise AssertionError("physical print must not use direct gcode_line autoejection")

    class FakeFtpsClient:
        def probe_storage(self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False) -> dict:
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(self, **kwargs) -> dict:
            raise AssertionError("physical_print must use the printer-fetchable HTTP artifact route")

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "physical_print",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "prefer_http_artifact": True,
            "public_base_url": "http://192.0.2.100:7860",
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
                "stop_after_start": False,
                "prefer_http_artifact": True,
            },
            "ejection": {
                "enabled": True,
                "allow_ejection": True,
                "position": "center",
            },
        }
    )

    assert result["ok"] is True
    assert result["ejection_only_project_file"] is False
    assert result["upload"]["route"] == "http_artifact"
    assert result["project_file_draft"]["payload"]["print"]["url"].startswith(
        "http://192.0.2.100:7860/printer-artifacts/bambu/"
    )
    exported_path = result["upload"]["artifact"]["export_path"]
    assert exported_path.endswith(".autoeject.gcode.3mf")
    assert not exported_path.endswith(".ejection-test.gcode.3mf")
    with zipfile.ZipFile(exported_path) as archive:
        gcode = archive.read("Metadata/plate_1.gcode").decode("utf-8")
    assert "E0.1" in gcode
    assert "E0.4" in gcode
    assert "; atr_print_body_omitted=true" not in gcode
    assert "; atr.bambu.autoejection.v1" in gcode
    assert "M190 R40" in gcode
    assert "; atr_z_push_offset_mm=15.0" in gcode
    assert "G0 Z15.000 F3000" in gcode
    assert "G0 Z10.000 F3000" not in gcode
    assert "M73 P100 R0" in gcode
    assert gcode.index("; atr.bambu.autoejection.end") < gcode.index("M73 P100 R0")


def test_physical_print_blocks_upload_if_patched_artifact_sha_changes_before_transfer(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})
    sliced = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(
        sliced,
        gcode="G90\nM82\nG92 E0\nG1 X30 Y40 Z0.2 E0.1\nG1 X70 Y80 Z30 E0.4\nM84\n",
    )

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, **kwargs) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class UploadTripwire:
        def probe_storage(self, **kwargs) -> dict:
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(self, **kwargs) -> dict:
            raise AssertionError("SHA-mismatched artifact must be blocked before FTPS upload")

    real_patch = manager._patch_bambu_native_autoejection_for_prepare

    def tampering_patch(**kwargs) -> dict:
        result = real_patch(**kwargs)
        Path(result["patched_artifact_path"]).write_bytes(
            Path(result["patched_artifact_path"]).read_bytes() + b"tampered-after-patch"
        )
        return result

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = UploadTripwire()
    manager._patch_bambu_native_autoejection_for_prepare = tampering_patch  # type: ignore[method-assign]

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "physical_print",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "print": {"start_immediately": True, "physical_intent": True, "confirm_physical_print": True},
            "ejection": {"enabled": True, "allow_ejection": True, "position": "center"},
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_ARTIFACT_SHA256_MISMATCH"


def test_physical_print_blocks_start_if_local_artifact_sha_changes_after_upload(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    artifact = tmp_path / "immutable.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(artifact)
    expected_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    artifact.write_bytes(artifact.read_bytes() + b"tampered-after-upload")

    class PublishTripwire:
        def publish_project_file_command(self, **kwargs) -> dict:
            raise AssertionError("SHA-mismatched artifact must be blocked before MQTT start")

    manager.mqtt_client = PublishTripwire()
    result = manager._publish_bambu_project_file_start(
        connection={"serial": "20PTEST000001", "username": "bblp"},
        raw_connection={"host": "192.0.2.42"},
        raw_auth={"access_code": "secret"},
        payload={"runtime_mode": "test", "test_printer_path": "physical_print"},
        project_file_draft={"ok": True, "topic": "device/20PTEST000001/request", "payload": {"print": {}}},
        upload_result={"ok": True, "remote_path": "cache/immutable.gcode.3mf", "sha256": expected_sha},
        gate_ready=True,
        normalized_report={"state": "IDLE"},
        local_artifact_path=artifact,
        expected_artifact_sha256=expected_sha,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_ARTIFACT_SHA256_MISMATCH"
    assert result["published"] is False


def test_prefer_http_artifact_skips_ftps_upload_for_installed_printer_ejection_project(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch", "push_direction": "center"})
    sliced = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(
        sliced,
        gcode="\n".join(
            [
                "G90",
                "M82",
                "G92 E0",
                "G1 X30 Y40 Z0.2 E0.1 F1200",
                "G1 X70 Y40 Z0.2 E0.2 F1200",
                "G1 X70 Y80 Z6.0 E0.3 F1200",
                "G1 X30 Y80 Z12.0 E0.4 F1200",
                "M84",
            ]
        ),
    )

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, **kwargs) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE", "mc_percent": 0, "bed_temper": 29}}}

    class FakeFtpsClient:
        def probe_storage(self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False) -> dict:
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(self, **kwargs) -> dict:
            raise AssertionError("prefer_http_artifact must not fall back to FTPS upload")

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "prefer_http_artifact": True,
            "public_base_url": "http://192.0.2.100:7860",
            "print": {
                "start_immediately": False,
                "physical_intent": False,
                "confirm_physical_print": False,
                "stop_after_start": True,
            },
            "ejection": {
                "enabled": True,
                "allow_ejection": True,
                "use_ejection_only_project_file": True,
                "position": "center",
            },
        }
    )

    assert result["ok"] is True
    assert result["ejection_only_project_file"] is True
    assert result["upload"]["route"] == "http_artifact"
    assert result["upload"]["remote_path"].startswith("http://192.0.2.100:7860/printer-artifacts/bambu/")
    assert result["upload"]["filename"].endswith(".gcode.3mf")
    assert result["project_file_draft"]["payload"]["print"]["url"].startswith("http://192.0.2.100:7860/printer-artifacts/bambu/")
    assert result["project_file_draft"]["payload"]["print"]["subtask_name"] == Path(result["upload"]["filename"]).stem


def test_test_mode_installed_printer_blocks_autoejection_without_actual_extrusion_bounds(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch", "push_direction": "center"})
    sliced = tmp_path / "travel-only.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(sliced, gcode="G90\nG0 X10 Y10 Z10 F1200\nM84\n")
    gcode_lines: list[dict[str, object]] = []

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, **kwargs) -> dict:
            state = "RUNNING" if kwargs.get("force_refresh") else "IDLE"
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": state, "mc_percent": 1, "bed_temper": 29}}}

        def publish_project_file_command(self, **kwargs) -> dict:
            return {"ok": True, "status": "published", "will_publish": True, "published": True, "sequence_id": "seq-start", "topic": kwargs.get("topic")}

        def publish_print_control_command(self, **kwargs) -> dict:
            return {"ok": True, "status": "published", "will_publish": True, "published": True, "sequence_id": "seq-stop", "command": kwargs.get("command"), "topic": kwargs.get("topic")}

        def publish_gcode_line_command(self, **kwargs) -> dict:
            gcode_lines.append(kwargs)
            return {"ok": True, "status": "published", "published": True}

    class FakeFtpsClient:
        def probe_storage(self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False) -> dict:
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(self, *, local_path: Path, remote_path: str, host: str, username: str, access_code: str, timeout_sec: float, delete_after: bool = False) -> dict:
            return {"ok": True, "status": "uploaded", "storage": "ftps", "remote_path": remote_path, "sha256": hashlib.sha256(Path(local_path).read_bytes()).hexdigest(), "delete_after": delete_after}

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
                "stop_after_start": True,
            },
            "ejection": {
                "enabled": True,
                "allow_ejection": True,
                "standalone_after_start_stop": True,
                "position": "center",
                "object_size_mm": [30.0, 30.0, 30.0],
            },
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_AUTOEJECTION_SOURCE_EXTRUSION_BOUNDS_REQUIRED"
    assert result["autoejection_patch"]["ok"] is False
    assert result["autoejection_patch"]["failure_code"] == "BAMBU_AUTOEJECTION_SOURCE_EXTRUSION_BOUNDS_REQUIRED"
    assert result["ejection_result"] == {}
    assert gcode_lines == []


def test_test_mode_installed_printer_can_start_after_previous_cancelled_failed_state(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    sliced = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(sliced)
    controls: list[dict[str, object]] = []

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(
            self,
            *,
            host: str,
            serial: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            force_refresh: bool = False,
        ) -> dict:
            state = "PREPARE" if force_refresh else "FAILED"
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": state}}}

        def publish_project_file_command(self, **kwargs) -> dict:
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-start",
                "topic": kwargs.get("topic"),
            }

        def publish_print_control_command(self, **kwargs) -> dict:
            controls.append(kwargs)
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-stop",
                "command": kwargs.get("command"),
                "topic": kwargs.get("topic"),
            }

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(
            self,
            *,
            local_path: Path,
            remote_path: str,
            host: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            delete_after: bool = False,
        ) -> dict:
            return {
                "ok": True,
                "status": "uploaded",
                "storage": "ftps",
                "remote_path": remote_path,
                "sha256": hashlib.sha256(Path(local_path).read_bytes()).hexdigest(),
                "delete_after": delete_after,
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
                "stop_after_start": True,
            },
        }
    )

    assert result["ok"] is True
    assert result["status"] == "TEST_PRINTER_STARTED_THEN_STOPPED"
    assert result["print_result"]["published"] is True
    assert result["print_result"]["stop"]["published"] is True
    assert result["preprint_gate"]["checks"]["printer_safe_state_verified"] is True
    assert controls and controls[0]["command"] == "stop"


def test_test_mode_installed_printer_blocks_when_start_publish_is_not_observed(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    sliced = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(sliced)
    controls: list[dict[str, object]] = []

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(
            self,
            *,
            host: str,
            serial: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            force_refresh: bool = False,
        ) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "FAILED"}}}

        def publish_project_file_command(self, **kwargs) -> dict:
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-start",
                "topic": kwargs.get("topic"),
            }

        def publish_print_control_command(self, **kwargs) -> dict:
            controls.append(kwargs)
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-stop",
                "command": kwargs.get("command"),
                "topic": kwargs.get("topic"),
            }

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(
            self,
            *,
            local_path: Path,
            remote_path: str,
            host: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            delete_after: bool = False,
        ) -> dict:
            return {
                "ok": True,
                "status": "uploaded",
                "storage": "ftps",
                "remote_path": remote_path,
                "sha256": hashlib.sha256(Path(local_path).read_bytes()).hexdigest(),
                "delete_after": delete_after,
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
                "stop_after_start": True,
            },
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_PROJECT_FILE_START_FAILED"
    assert result["print_result"]["published"] is True
    assert result["print_result"]["post_publish_status"]["status"] == "failed"
    assert result["print_result"].get("stop_after_start") is not True
    assert result["preprint_gate"]["checks"]["start_command_draft_prepared"] is True
    assert controls == []


def test_test_mode_installed_printer_does_not_send_second_standalone_project_file(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch", "push_direction": "center"})
    sliced = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(
        sliced,
        gcode="\n".join(
            [
                "G90",
                "M82",
                "G92 E0",
                "G1 X30 Y40 Z0.2 E0.1 F1200",
                "G1 X70 Y40 Z0.2 E0.2 F1200",
                "G1 X70 Y80 Z6.0 E0.3 F1200",
                "G1 X30 Y80 Z12.0 E0.4 F1200",
                "M84",
            ]
        ),
    )
    controls: list[dict[str, object]] = []
    published: list[dict[str, object]] = []
    force_reads = 0

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, **kwargs) -> dict:
            nonlocal force_reads
            if kwargs.get("force_refresh"):
                force_reads += 1
                state = "RUNNING" if force_reads == 1 else "FAILED"
            else:
                state = "IDLE"
            return {
                "ok": True,
                "received_at": "now",
                "report": {"print": {"gcode_state": state, "mc_percent": 1, "bed_temper": 29}},
            }

        def publish_project_file_command(self, **kwargs) -> dict:
            published.append(kwargs)
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": f"seq-start-{len(published)}",
                "topic": kwargs.get("topic"),
            }

        def publish_print_control_command(self, **kwargs) -> dict:
            controls.append(kwargs)
            return {
                "ok": True,
                "status": "published",
                "will_publish": True,
                "published": True,
                "sequence_id": "seq-stop",
                "command": kwargs.get("command"),
                "topic": kwargs.get("topic"),
            }

    class FakeFtpsClient:
        def probe_storage(self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False) -> dict:
            return {"ok": True, "storage": "ftps", "selected_remote_dir": "cache"}

        def upload_file(self, *, local_path: Path, remote_path: str, host: str, username: str, access_code: str, timeout_sec: float, delete_after: bool = False) -> dict:
            return {
                "ok": True,
                "status": "uploaded",
                "storage": "ftps",
                "local_path": str(local_path),
                "remote_path": remote_path,
                "sha256": hashlib.sha256(Path(local_path).read_bytes()).hexdigest(),
                "delete_after": delete_after,
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "test",
            "test_printer_path": "installed_printer",
            "allow_test_printer_live": True,
            "test_printer_transport": "real",
            "bambu_artifact_path": str(sliced),
            "print": {
                "start_immediately": True,
                "physical_intent": True,
                "confirm_physical_print": True,
                "stop_after_start": True,
            },
            "ejection": {
                "enabled": True,
                "allow_ejection": True,
                "standalone_after_start_stop": False,
                "use_ejection_only_project_file": True,
                "position": "center",
                "object_size_mm": [30.0, 30.0, 30.0],
            },
        }
    )

    assert result["ok"] is True
    assert result["status"] == "TEST_PRINTER_EJECTION_PROJECT_STARTED"
    assert len(published) == 1
    assert controls == []
    assert result["ejection_only_project_file"] is True
    assert result["ejection_result"] == {}
    assert any(
        item["step"] == "BAMBU_NATIVE_AUTOEJECTION_PATCH" and item["status"] == "ok"
        for item in result["step_trace"]
    )


def test_live_bambu_uploads_explicit_artifact_to_verified_cache_dir_when_remote_path_not_overridden(
    tmp_path: Path,
) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    sliced = tmp_path / "sp-1.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(sliced)
    uploaded: dict[str, str | bool] = {}

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {"ok": False, "read_ok": True, "failure_code": "BAMBU_FTPS_WRITE_FAILED"}

        def probe_upload_paths(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, candidate_dirs=None
        ) -> dict:
            return {
                "ok": True,
                "write_ok": True,
                "storage": "ftps",
                "selected_remote_dir": "cache",
                "selected_remote_path": "cache/atr-ftps-path-probe.txt",
            }

        def upload_file(
            self,
            *,
            local_path,
            remote_path: str,
            host: str,
            username: str,
            access_code: str,
            timeout_sec: float,
            delete_after: bool = False,
        ) -> dict:
            uploaded["remote_path"] = remote_path
            return {
                "ok": True,
                "status": "uploaded",
                "remote_path": remote_path,
                "size_bytes": 20,
                "sha256": "abc123",
                "delete_after": False,
                "deleted": False,
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-1",
            "bambu_artifact_path": str(sliced),
        }
    )

    assert result["ok"] is True
    assert uploaded["remote_path"] == "cache/sp-1.gcode.3mf"
    assert result["project_file_draft"]["payload"]["print"]["url"] == "file:///cache/sp-1.gcode.3mf"


def test_live_bambu_blocks_local_gcode_3mf_when_requested_plate_gcode_is_missing(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    sliced = tmp_path / "sp-wrong-plate.gcode.3mf"
    with zipfile.ZipFile(sliced, "w") as archive:
        archive.writestr("Metadata/plate_2.gcode", "G90\nM84\n")
        archive.writestr("3D/3dmodel.model", "<model />")

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {"ok": True, "storage": "ftps", "entries_sample": []}

        def upload_file(self, **kwargs) -> dict:
            raise AssertionError("missing local plate G-code must block before FTPS upload")

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-wrong-plate",
            "bambu_artifact_path": str(sliced),
            "plate_id": 1,
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_PROJECT_FILE_PARAM_MISMATCH"
    assert result["artifact_plate_validation"]["ok"] is False
    assert result["artifact_plate_validation"]["expected_plate_path"] == "Metadata/plate_1.gcode"
    assert "Metadata/plate_2.gcode" in result["artifact_plate_validation"]["available_plate_paths"]
    assert result["project_file_draft"]["ok"] is False
    assert result["project_file_draft"]["failure_code"] == "BAMBU_PROJECT_FILE_PARAM_MISMATCH"
    assert result["preprint_gate"]["checks"]["start_command_draft_prepared"] is False
    assert result["device_screen"]["actions"]["can_start_print"] is False


def test_live_bambu_blocks_invalid_plate_id_before_upload(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    sliced = tmp_path / "sp-invalid-plate.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(sliced, plate_id=1)

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {"ok": True, "storage": "ftps", "entries_sample": []}

        def upload_file(self, **kwargs) -> dict:
            raise AssertionError("invalid plate_id must block before FTPS upload")

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-invalid-plate",
            "bambu_artifact_path": str(sliced),
            "plate_id": "abc",
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_PROJECT_FILE_PARAM_MISMATCH"
    assert result["artifact_plate_validation"]["ok"] is False
    assert result["artifact_plate_validation"]["plate_id"] == 0
    assert result["project_file_draft"]["ok"] is False
    assert result["preprint_gate"]["checks"]["start_command_draft_prepared"] is False


def test_live_bambu_with_http_artifact_url_verifies_transfer_without_ftps_write(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {
                "ok": False,
                "read_ok": True,
                "failure_code": "BAMBU_FTPS_WRITE_FAILED",
                "error": "553 Could not create file.",
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-1",
            "bambu_artifact_url": "http://192.168.50.10:8080/artifacts/sp-1.gcode.3mf",
        }
    )

    assert result["ok"] is True
    assert result["failure_code"] == ""
    assert result["status"] == "HTTP_ARTIFACT_READY_NOT_STARTED"
    assert result["device_screen"]["connection"]["transfer"] == "connected"
    assert result["project_file_draft"]["ok"] is True
    assert result["project_file_draft"]["payload"]["print"]["url"] == "http://192.168.50.10:8080/artifacts/sp-1.gcode.3mf"
    assert result["preprint_gate"]["checks"]["mqtt_authenticated_or_virtual"] is True
    assert result["preprint_gate"]["checks"]["storage_transfer_path_verified"] is True
    assert result["preprint_gate"]["checks"]["start_command_draft_prepared"] is True
    assert result["device_screen"]["actions"]["can_start_print"] is True


def test_live_bambu_with_http_artifact_url_warns_but_continues_when_ftps_has_too_many_connections(
    tmp_path: Path,
) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {
                "ok": False,
                "storage": "ftps",
                "failure_code": "BAMBU_FTPS_TOO_MANY_CONNECTIONS",
                "error": "421 There are too many connections",
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-http-route",
            "bambu_artifact_url": "http://192.168.50.10:8080/artifacts/sp-http-route.gcode.3mf",
        }
    )

    assert result["ok"] is True
    assert result["failure_code"] == ""
    assert result["status"] == "HTTP_ARTIFACT_READY_NOT_STARTED"
    assert result["ftps_probe"]["failure_code"] == "BAMBU_FTPS_TOO_MANY_CONNECTIONS"
    assert result["upload"]["route"] == "http_artifact"
    assert result["preprint_gate"]["checks"]["storage_transfer_path_verified"] is True
    action_codes = [item["code"] for item in result["operator_actions"]]
    assert "BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE" in action_codes
    assert "BAMBU_FTPS_TOO_MANY_CONNECTIONS" in action_codes
    assert result["device_screen"]["actions"]["can_start_print"] is True


def test_live_bambu_with_http_artifact_url_blocks_invalid_plate_id_without_crashing(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {
                "ok": False,
                "read_ok": True,
                "failure_code": "BAMBU_FTPS_WRITE_FAILED",
                "error": "553 Could not create file.",
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-invalid-plate",
            "bambu_artifact_url": "http://192.168.50.10:8080/artifacts/sp-invalid-plate.gcode.3mf",
            "plate_id": "abc",
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_PROJECT_FILE_PARAM_MISMATCH"
    assert result["project_file_draft"]["ok"] is False
    assert result["project_file_draft"]["failure_code"] == "BAMBU_PROJECT_FILE_PARAM_MISMATCH"
    assert result["preprint_gate"]["checks"]["start_command_draft_prepared"] is False
    assert result["device_screen"]["actions"]["can_start_print"] is False


def test_live_bambu_does_not_treat_plain_remote_path_as_http_artifact_route_when_ftps_write_fails(
    tmp_path: Path,
) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            return {
                "ok": False,
                "read_ok": True,
                "failure_code": "BAMBU_FTPS_WRITE_FAILED",
                "error": "553 Could not create file.",
            }

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-1",
            "bambu_artifact_url": "cache/sp-1.gcode.3mf",
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_FTPS_WRITE_FAILED"
    assert result["status"] == "preprint_communication_failed"
    assert result["preprint_gate"]["checks"]["storage_transfer_path_verified"] is False
    assert result["device_screen"]["connection"]["transfer"] == "read_only"


def test_live_bambu_blocks_physical_stl_upload_when_slicer_is_disabled(tmp_path: Path) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path), repo_root=tmp_path)
    profile = manager.config.default_profile
    BambuConnectionMemory(profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "20PTEST000001",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret"},
        }
    )
    stl = tmp_path / "sp-1.stl"
    stl.write_bytes(b"mesh")

    class FakeProbe:
        def probe_tls_port(self, host: str, port: int, timeout_sec: float) -> dict:
            return {"ok": True, "port": port}

    class FakeMqttClient:
        def read_snapshot(self, *, host: str, serial: str, username: str, access_code: str, timeout_sec: float) -> dict:
            return {"ok": True, "received_at": "now", "report": {"print": {"gcode_state": "IDLE"}}}

    class FakeFtpsClient:
        def probe_storage(
            self, *, host: str, username: str, access_code: str, timeout_sec: float, write_probe: bool = False
        ) -> dict:
            assert write_probe is True
            return {"ok": True, "storage": "ftps", "entries_sample": []}

        def upload_file(self, **kwargs) -> dict:
            raise AssertionError("STL must not be uploaded to Bambu printer storage as a sliced artifact")

    manager.live_probe = FakeProbe()
    manager.mqtt_client = FakeMqttClient()
    manager.ftps_client = FakeFtpsClient()

    result = manager.prepare(
        {
            "runtime_mode": "live",
            "run_id": "run-1",
            "specimen_id": "sp-1",
            "stl_path": str(stl),
            "upload_artifact": True,
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "BAMBU_STUDIO_SLICER_DISABLED"
    assert result["preprint_gate"]["blockers"] == ["BAMBU_STUDIO_SLICER_DISABLED"]
    assert result["device_screen"]["actions"]["can_start_print"] is False
