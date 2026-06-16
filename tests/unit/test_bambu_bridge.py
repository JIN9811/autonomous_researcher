"""Unit tests for Bambu Lab printer fleet/device bridge contracts."""

from __future__ import annotations

import socket
import ssl
import json
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


def test_bambu_studio_slicer_runner_applies_default_no_skirt_profile(tmp_path: Path) -> None:
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
printf '%s\\n' "$@" > "$out/args.txt"
printf 'sliced payload' > "$out/specimen.gcode"
""",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    machine = tmp_path / "machine.json"
    process = tmp_path / "process.json"
    filament = tmp_path / "filament.json"
    machine.write_text('{"type":"machine","name":"Bambu Lab X2D 0.4 nozzle"}\n', encoding="utf-8")
    process.write_text(
        '{"type":"process","name":"0.20mm Standard @BBL X2D","skirt_loops":"1","brim_width":"5","raft_layers":"1"}\n',
        encoding="utf-8",
    )
    filament.write_text('{"type":"filament","name":"Bambu PLA Basic @BBL X2D 0.4 nozzle"}\n', encoding="utf-8")
    source = tmp_path / "specimen.stl"
    source.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    config = BambuSlicerConfig(
        enabled=True,
        executable_path=str(fake_cli),
        output_dir=str(tmp_path / "bambu_sliced"),
        timeout_sec=5,
        default_machine_profile=str(machine),
        default_process_profile=str(process),
        default_filament_profile=str(filament),
    )
    runner = BambuStudioSlicerRunner(config, repo_root=tmp_path)

    result = runner.slice(source_path=source, specimen_id="specimen")

    assert result["ok"] is True
    assert "--load-settings" in result["command"]
    assert "--load-filaments" in result["command"]
    profile = result["slicer_profile"]
    assert profile["auto_no_skirt_profile"] is True
    process_override = Path(profile["process_override_path"])
    assert process_override.exists()
    process_payload = json.loads(process_override.read_text(encoding="utf-8"))
    assert process_payload["skirt_loops"] == "0"
    assert process_payload["skirt_height"] == "0"
    assert process_payload["brim_type"] == "no_brim"
    assert process_payload["brim_width"] == "0"
    assert process_payload["raft_layers"] == "0"


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
    assert native["push_speed_mm_min"] == 1000
    assert native["sweep_z_mm"] == 50.0
    assert native["sweep_speed_mm_min"] == 1000
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
    assert "G0 X68.000" in patched_text
    assert "F420" in patched_text
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
        ams_mapping=[0, -1, -1, -1],
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


def test_live_bambu_blocks_physical_upload_when_only_stl_is_available(tmp_path: Path) -> None:
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
    assert result["failure_code"] == "BAMBU_SLICED_ARTIFACT_REQUIRED"
    assert result["preprint_gate"]["blockers"] == ["BAMBU_SLICED_ARTIFACT_REQUIRED"]
    assert result["device_screen"]["actions"]["can_start_print"] is False
