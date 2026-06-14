import json
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from device_bridges.bambu_bridge import BambuConnectionMemory, PrinterDeviceBridgeManager


def _save_ready_manipulation_consumer(tmp_path: Path, monkeypatch) -> Path:
    """Persist the real saved-profile shape required before Bambu autoejection handoff."""
    profile_path = tmp_path / "memory" / "manipulation_agent_bridge.json"
    policy_dir = tmp_path / "outputs" / "train" / "robot-pickoff-policy" / "pretrained_model"
    policy_dir.mkdir(parents=True, exist_ok=True)
    (policy_dir / "model.safetensors").write_bytes(b"test policy marker")
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "robotis_omx_ai",
                "manipulation_strategy": "pi05_lerobot_policy",
                "task_id": "transfer_to_utm",
                "skill_id": "transfer_to_utm",
                "source_location": "3dp_output_area",
                "target_location": "utm_fixture",
                "policy_type": "pi05",
                "policy_backend": "lerobot_cli",
                "policy_path": str(policy_dir),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_main, "MANIPULATION_AGENT_PROFILE_PATH", profile_path)
    return profile_path


def test_printer_gui_route_loads() -> None:
    client = TestClient(app)

    response = client.get("/printer")

    assert response.status_code == 200
    assert "3DP Printer GUI" in response.text
    assert "Bambu Lab Device Bridge" in response.text
    assert "printer-connection-serial-input" in response.text
    assert "printer-connection-access-code-input" in response.text
    assert "Device Screen" in response.text
    assert "printer-fleet-profile-input" in response.text
    assert "btn-printer-fleet-save" in response.text
    assert "btn-printer-start-command-draft" in response.text
    assert "btn-printer-start-gate" in response.text
    assert "btn-printer-spc-readiness" in response.text
    assert "printer-start-operator-confirmed-input" in response.text
    assert "printer-start-guardian-approved-input" in response.text
    assert "printer-start-dry-run-input" in response.text
    assert "printer-start-gate-mode-detail" in response.text
    assert "printer-spc-readiness-levels" in response.text
    assert "printer-spc-readiness-summary" in response.text
    assert "printer-spc-next-actions" in response.text
    assert "printer-connection-action-summary" in response.text
    assert "printer-connection-action-list" in response.text
    assert "printer-camera-live-state" in response.text
    assert "printer-control-state" in response.text
    assert "btn-printer-video-status" in response.text
    assert "printer-camera-proxy-state" in response.text
    assert "printer-material-slot-list" in response.text
    assert "printer-evidence-cards" in response.text
    assert "btn-printer-http-artifact-route" in response.text
    assert "btn-printer-bambu-slice-artifact" in response.text
    assert "btn-printer-bambu-prestart-check" in response.text
    assert "printer-prestart-check-summary" in response.text
    assert "printer-prestart-check-steps" in response.text
    assert "printer-bambu-source-path-input" in response.text
    assert "printer-autoejection-status-summary" in response.text
    assert "Autoejection Gate / Test" in response.text
    assert "Check Handoff Left" in response.text
    assert "btn-printer-autoejection-fill-handoff" in response.text
    assert "printer-bambu-artifact-path-input" in response.text
    assert "printer-bambu-public-base-url-input" in response.text
    assert "btn-printer-start-publish" in response.text
    assert "/static/printer.js" in response.text


def test_printer_gui_does_not_treat_profile_ejection_checkbox_as_bambu_ejection_ready() -> None:
    script = (Path(__file__).resolve().parents[2] / "web" / "static" / "printer.js").read_text(encoding="utf-8")

    assert "autoEjection.enabled || profile.allow_ejection" not in script
    assert "policy upload=${Boolean(gates.allow_upload)}" in script
    assert "actual upload=${Boolean(actions.can_upload)}" in script
    assert "auto-eject=${Boolean(autoEjection.enabled)}" in script
    assert "/api/printer/http-artifact-route" in script
    assert "/api/printer/bambu-slice-artifact" in script
    assert "/api/printer/bambu-prestart-check" in script
    assert "btnBambuPrestartCheck" in script
    assert "renderPrestartCheck" in script
    assert "btnBambuSliceArtifact" in script
    assert "/api/printer/start-gate" in script
    assert "/api/printer/start-publish" in script
    assert "/api/printer/spc-readiness" in script
    assert "/api/printer/video-status" in script
    assert "/api/printer/fleet" in script
    assert "/api/printer/autoejection-status" in script
    assert "/api/printer/autoejection-config" in script
    assert "updateAutoejectionButtonLabels" in script
    assert "fillManipulationHandoffDefaults" in script
    assert "Preset filled locally" in script
    assert "consumer_readiness" in script
    assert "Manipulation consumer" in script
    assert "Check Handoff Center" in script
    assert "Autoeject Center" in script
    assert 'await refreshStatus("live");\n    await refreshAutoejectionStatus();' in script
    assert "verify_fetch: true" in script
    assert "lastHttpArtifactUrl = fetchReady ? data.artifact_url || \"\" : \"\";" in script
    assert "HTTP artifact ${probeText}" in script
    assert "readStartGateOptions" in script
    assert "startOperatorConfirmedInput" in script
    assert "startGuardianApprovedInput" in script
    assert "startDryRunInput" in script
    assert "renderReadinessLevels" in script
    assert "data.readiness_levels" in script
    assert "data.autoejection_handoff" in script
    assert "Manipulation Agent handoff" in script
    assert "renderConnectionActionGuidance" in script
    assert "printer-connection-action-list" in script
    assert "lastFleetPayload" in script
    assert "incoming.available_printers" in script
    assert "BAMBU_LAN_MODE_NOT_CONFIRMED" in script
    assert "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED" in script
    assert "BAMBU_FTPS_WRITE_FAILED" in script
    assert "BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE" in script
    assert "connection-action-card" in script
    assert "operator_confirmed: true" not in script
    assert "guardian_approved: true" not in script
    assert "screen.progress_panel" in script
    assert "screen.camera_panel" in script
    assert "screen.control_panel" in script
    assert "screen.material_panel" in script
    assert "screen.evidence_cards" in script
    assert "cameraPanel.proxy_ready" in script
    assert "printer-video-stream" in script
    assert "printerStatusManualOverride" in script
    assert 'refreshStatus("live", { initial: true })' in script
    assert 'refreshStatus("live", { manual: true })' in script
    assert "renderConfig(data);\n  renderDeviceScreen(data);" in script


def test_printer_status_api_redacts_connection_and_reports_gates() -> None:
    client = TestClient(app)

    response = client.get("/api/printer/status?mode=test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "bambulab_x2d"
    assert payload["selected_printer"]["profile_id"] == "bambulab_x2d_lab_01"
    assert any(item["provider"] == "prusa_mk4s" for item in payload["available_printers"])
    assert payload["automatic_fallback"] is False
    assert payload["device_screen"]["schema"] == "printer_device_screen.v1"
    assert payload["device_screen"]["job"]["progress_percent"] is None
    assert payload["device_screen"]["actions"]["can_start_print"] is False
    assert payload["preprint_gate"]["schema"] == "preprint_real_communication_gate.v1"
    assert "password" not in payload.get("connection", {})
    assert payload["live_gates"]["allow_start_print"] is False
    assert payload["slicer"]["executable_env"] == "BAMBU_STUDIO_EXECUTABLE"


def test_printer_fleet_api_saves_explicit_active_profile_without_fallback(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        },
                        "prusa_mk4s_lab_01": {
                            "provider": "prusa_mk4s",
                            "connection_memory_path": str(tmp_path / "prusa_connection.json"),
                            "enabled": True,
                        },
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    save_response = client.post("/api/printer/fleet", json={"profile_id": "prusa_mk4s_lab_01"})
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["ok"] is True
    assert saved["active_profile_id"] == "prusa_mk4s_lab_01"
    assert saved["automatic_fallback"] is False

    status_response = client.get("/api/printer/status?mode=test")
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["provider"] == "prusa_mk4s"
    assert payload["selected_printer"]["profile_id"] == "prusa_mk4s_lab_01"
    assert payload["selected_printer"]["selection_reason"] == "fleet_memory_profile_id"
    assert payload["automatic_fallback"] is False


def test_printer_live_status_api_uses_preprint_gate_not_health_only(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    calls: list[dict] = []

    def fake_prepare(payload: dict) -> dict:
        calls.append(dict(payload))
        return {
            "ok": False,
            "provider": "bambulab_x2d",
            "selected_printer": {
                "profile_id": "bambulab_x2d_lab_01",
                "provider": "bambulab_x2d",
                "label": "Bambu Lab X2D - Lab 01",
            },
            "available_printers": manager.available_printers(),
            "automatic_fallback": False,
            "device_screen": {
                "schema": "printer_device_screen.v1",
                "connection": {"mqtt": "connected", "transfer": "read_only"},
                "job": {"progress_percent": 100},
                "actions": {"can_upload": False, "can_start_print": False},
            },
            "preprint_gate": {"schema": "preprint_real_communication_gate.v1", "blockers": ["BAMBU_FTPS_WRITE_FAILED"]},
            "operator_actions": [{"code": "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED", "severity": "blocking"}],
            "autoejection": {"enabled": False, "provider": "none", "status": "not_configured"},
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.get("/api/printer/status?mode=live")

    assert response.status_code == 200
    payload = response.json()
    assert calls == [{"runtime_mode": "live", "health_only": False}]
    assert payload["live_gates"]["allow_upload"] is False
    assert payload["device_screen"]["connection"]["transfer"] == "read_only"
    assert payload["operator_actions"][0]["code"] == "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED"


def test_printer_video_status_api_probes_bambu_live_view_without_echoing_secret(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )

    def fake_probe_live_view(**kwargs) -> dict:
        assert kwargs["host"] == "192.0.2.42"
        assert kwargs["access_code"] == "secret-code"
        return {
            "ok": True,
            "status": "streaming_candidate",
            "stream_kind": "rtsps",
            "port": 322,
            "stream_url": "rtsps://192.0.2.42:322/streaming/live/1",
            "proxy_ready": False,
            "proxy_url": "",
            "blockers": ["BAMBU_VIDEO_PROXY_FFMPEG_MISSING"],
        }

    manager.video_client.probe_live_view = fake_probe_live_view  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.get("/api/printer/video-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tool"] == "printer.bambu.video_status"
    assert payload["provider"] == "bambulab_x2d"
    assert payload["video_status"]["status"] == "streaming_candidate"
    assert payload["video_status"]["stream_kind"] == "rtsps"
    assert payload["video_status"]["proxy_ready"] is False
    assert payload["device_screen"]["camera_panel"]["proxy_ready"] is False
    assert payload["device_screen"]["camera_panel"]["blockers"] == ["BAMBU_VIDEO_PROXY_FFMPEG_MISSING"]
    assert "secret-code" not in response.text


def test_printer_video_stream_endpoint_uses_saved_bambu_connection_without_echoing_secret(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)

    captured: dict[str, object] = {}

    class FakeStdout:
        def __init__(self) -> None:
            self._chunks = [b"--ffmpeg\r\nContent-Type: image/jpeg\r\n\r\nFAKEJPEG\r\n", b""]

        def read(self, _size: int) -> bytes:
            return self._chunks.pop(0)

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = FakeStdout()
            self.returncode = None

        def terminate(self) -> None:
            self.returncode = 0

        def wait(self, timeout=None) -> int:  # noqa: ANN001
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.returncode = -9

    def fake_popen(command, **kwargs):  # noqa: ANN001
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(app_main.subprocess, "Popen", fake_popen)
    client = TestClient(app)

    response = client.get("/api/printer/video-stream.mjpeg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert b"FAKEJPEG" in response.content
    assert b"secret-code" not in response.content
    assert captured["command"][0] == "/usr/bin/ffmpeg"
    assert captured["kwargs"]["stdin"] == app_main.subprocess.DEVNULL


def test_printer_upload_path_probe_api_returns_redacted_candidate_results(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )

    def fake_probe_upload_paths(**kwargs) -> dict:
        assert kwargs["host"] == "192.0.2.42"
        assert kwargs["access_code"] == "secret-code"
        assert kwargs["candidate_dirs"] == ["", "cache"]
        return {
            "ok": True,
            "write_ok": True,
            "selected_remote_dir": "cache",
            "selected_remote_path": "cache/atr-ftps-path-probe.txt",
            "candidates": [
                {"remote_dir": "", "remote_path": "atr-ftps-path-probe.txt", "ok": False, "error": "553"},
                {"remote_dir": "cache", "remote_path": "cache/atr-ftps-path-probe.txt", "ok": True},
            ],
        }

    manager.ftps_client.probe_upload_paths = fake_probe_upload_paths  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post("/api/printer/upload-path-probe", json={"candidate_dirs": ["", "cache"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["selected_remote_dir"] == "cache"
    assert payload["candidates"][1]["ok"] is True
    assert "secret-code" not in response.text


def test_printer_start_command_draft_api_returns_guarded_project_file_payload(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-command-draft",
        json={"remote_path": "cache/specimen.gcode.3mf", "subtask_name": "specimen", "use_ams": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["will_publish"] is False
    assert payload["start_enabled"] is False
    assert payload["topic"] == "device/SERIAL123/request"
    assert payload["payload"]["print"]["command"] == "project_file"
    assert payload["payload"]["print"]["url"] == "file:///cache/specimen.gcode.3mf"
    assert "secret-code" not in response.text


def test_printer_start_gate_api_blocks_publish_until_all_live_gates_are_satisfied(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )

    def fake_prepare(payload: dict) -> dict:
        assert payload["runtime_mode"] == "live"
        assert payload["health_only"] is False
        return {
            "ok": False,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "device_screen": {
                "actions": {"can_start_print": False, "can_prepare_start_command": True},
                "connection": {"mqtt": "connected", "transfer": "read_only"},
            },
            "preprint_gate": {
                "state": "blocked",
                "blockers": ["BAMBU_FTPS_WRITE_FAILED"],
                "checks": {
                    "mqtt_authenticated_or_virtual": True,
                    "latest_report_fresh": True,
                    "printer_safe_state_verified": True,
                    "storage_transfer_path_verified": False,
                    "start_command_draft_prepared": True,
                },
            },
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-gate",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.gcode.3mf",
            "subtask_name": "specimen-gate",
            "operator_confirmed": False,
            "guardian_approved": False,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tool"] == "printer.bambu.start_gate"
    assert payload["ready_to_publish"] is False
    assert payload["will_publish"] is False
    assert payload["start_enabled"] is False
    assert payload["draft"]["payload"]["print"]["command"] == "project_file"
    assert payload["draft"]["payload"]["print"]["url"].startswith("http://192.168.50.10")
    assert "BAMBU_OPERATOR_CONFIRMATION_REQUIRED" in payload["blockers"]
    assert "BAMBU_GUARDIAN_APPROVAL_REQUIRED" in payload["blockers"]
    assert "BAMBU_DEVICE_SCREEN_START_DISABLED" in payload["blockers"]
    assert "BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED" in payload["blockers"]
    assert "BAMBU_START_DRY_RUN" in payload["blockers"]
    assert "secret-code" not in response.text


def test_printer_start_gate_api_reports_ready_without_publishing_when_all_checks_pass(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )

    def fake_prepare(payload: dict) -> dict:
        return {
            "ok": True,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "device_screen": {
                "actions": {"can_start_print": True, "can_prepare_start_command": True},
                "connection": {"mqtt": "connected", "transfer": "connected"},
            },
            "preprint_gate": {
                "state": "uploaded_not_started",
                "blockers": [],
                "checks": {
                    "mqtt_authenticated_or_virtual": True,
                    "latest_report_fresh": True,
                    "printer_safe_state_verified": True,
                    "storage_transfer_path_verified": True,
                    "start_command_draft_prepared": True,
                },
            },
            "operator_actions": [],
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-gate",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.gcode.3mf",
            "subtask_name": "specimen-ready",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["blockers"] == []
    assert payload["ready_to_publish"] is True
    assert payload["start_enabled"] is True
    assert payload["will_publish"] is False
    assert payload["message"] == "Bambu start gate is ready, but this endpoint does not publish by itself."
    assert "secret-code" not in response.text


def test_printer_start_publish_api_blocks_without_calling_mqtt_when_gate_fails(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )

    def fake_prepare(payload: dict) -> dict:
        return {
            "ok": False,
            "provider": "bambulab_x2d",
            "device_screen": {
                "actions": {"can_start_print": False, "can_prepare_start_command": True},
                "connection": {"mqtt": "connected", "transfer": "read_only"},
            },
            "preprint_gate": {
                "state": "blocked",
                "blockers": ["BAMBU_FTPS_WRITE_FAILED"],
                "checks": {
                    "mqtt_authenticated_or_virtual": True,
                    "latest_report_fresh": True,
                    "printer_safe_state_verified": True,
                    "storage_transfer_path_verified": False,
                    "start_command_draft_prepared": True,
                },
            },
        }

    class FakeMqttClient:
        def publish_project_file_command(self, **kwargs) -> dict:
            raise AssertionError("blocked start-publish must not call MQTT publish")

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    manager.mqtt_client = FakeMqttClient()
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-publish",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.gcode.3mf",
            "subtask_name": "specimen-blocked",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["ready_to_publish"] is False
    assert payload["will_publish"] is False
    assert payload["published"] is False
    assert "BAMBU_FTPS_WRITE_FAILED" in payload["blockers"]
    assert "secret-code" not in response.text


def test_printer_start_publish_api_publishes_after_ready_gate_and_explicit_approval(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )
    published: dict[str, object] = {}

    def fake_prepare(payload: dict) -> dict:
        return {
            "ok": True,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "device_screen": {
                "actions": {"can_start_print": True, "can_prepare_start_command": True},
                "connection": {"mqtt": "connected", "transfer": "connected"},
            },
            "preprint_gate": {
                "state": "uploaded_not_started",
                "blockers": [],
                "checks": {
                    "mqtt_authenticated_or_virtual": True,
                    "latest_report_fresh": True,
                    "printer_safe_state_verified": True,
                    "storage_transfer_path_verified": True,
                    "start_command_draft_prepared": True,
                },
            },
            "operator_actions": [],
        }

    class FakeMqttClient:
        def publish_project_file_command(self, **kwargs) -> dict:
            published.update(kwargs)
            return {
                "ok": True,
                "status": "published",
                "tool": "printer.bambu.mqtt_publish",
                "topic": kwargs["topic"],
                "will_publish": True,
                "published": True,
            }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    manager.mqtt_client = FakeMqttClient()
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-publish",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.gcode.3mf",
            "subtask_name": "specimen-ready",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["ready_to_publish"] is True
    assert payload["will_publish"] is True
    assert payload["published"] is True
    assert payload["publish_result"]["topic"] == "device/SERIAL123/request"
    assert published["host"] == "192.0.2.42"
    assert published["serial"] == "SERIAL123"
    assert published["access_code"] == "secret-code"
    assert published["payload"]["print"]["command"] == "project_file"
    assert "secret-code" not in response.text


def test_printer_spc_readiness_api_aggregates_real_bambu_gates_without_publishing(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )
    calls: list[dict] = []

    def fake_prepare(payload: dict) -> dict:
        calls.append(dict(payload))
        return {
            "ok": False,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "device_screen": {
                "schema": "printer_device_screen.v1",
                "connection": {"mqtt": "connected", "transfer": "read_only"},
                "job": {"state": "FINISH", "progress_percent": 100},
                "actions": {"can_upload": False, "can_start_print": False, "can_prepare_start_command": True},
            },
            "preprint_gate": {
                "state": "blocked",
                "blockers": ["BAMBU_FTPS_WRITE_FAILED"],
                "checks": {
                    "mqtt_authenticated_or_virtual": True,
                    "latest_report_fresh": True,
                    "printer_safe_state_verified": True,
                    "storage_transfer_path_verified": False,
                    "start_command_draft_prepared": True,
                },
            },
            "operator_actions": [{"code": "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED", "severity": "blocking"}],
            "autoejection": {"enabled": False, "provider": "none", "status": "not_configured"},
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/spc-readiness",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.gcode.3mf",
            "subtask_name": "spc-readiness",
            "operator_confirmed": False,
            "guardian_approved": False,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == [
        {
            "runtime_mode": "live",
            "health_only": False,
            "bambu_artifact_url": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.gcode.3mf",
            "subtask_name": "spc-readiness",
            "plate_id": 1,
            "use_ams": False,
            "ams_mapping": None,
            "timelapse": False,
            "bed_leveling": False,
            "flow_cali": False,
            "vibration_cali": False,
            "layer_inspect": False,
        }
    ]
    assert payload["ok"] is True
    assert payload["tool"] == "printer.spc_readiness"
    assert payload["status"] == "blocked"
    assert payload["ready_for_live_print"] is False
    assert payload["autonomous_cycle_ready"] is False
    assert payload["will_publish"] is False
    assert payload["operator_summary"]["severity"] == "blocked"
    assert payload["operator_summary"]["primary_blocker"] == "BAMBU_FTPS_WRITE_FAILED"
    assert payload["evidence"]["device_connection"]["mqtt"] == "connected"
    assert payload["evidence"]["device_connection"]["transfer"] == "read_only"
    assert any(action["code"] == "BAMBU_FTPS_WRITE_FAILED" for action in payload["next_actions"])
    assert any(action["code"] == "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED" for action in payload["next_actions"])
    assert {level["id"] for level in payload["readiness_levels"]} == {
        "connection",
        "transfer_path",
        "start_approval",
        "publish_command",
        "autoejection",
    }
    transfer_level = next(level for level in payload["readiness_levels"] if level["id"] == "transfer_path")
    assert transfer_level["status"] == "blocked"
    assert "BAMBU_FTPS_WRITE_FAILED" in transfer_level["blocking_codes"]
    approval_level = next(level for level in payload["readiness_levels"] if level["id"] == "start_approval")
    assert approval_level["status"] == "waiting"
    assert set(approval_level["blocking_codes"]) >= {
        "BAMBU_START_DRY_RUN",
        "BAMBU_OPERATOR_CONFIRMATION_REQUIRED",
        "BAMBU_GUARDIAN_APPROVAL_REQUIRED",
    }
    assert "BAMBU_FTPS_WRITE_FAILED" in payload["blockers"]
    assert "BAMBU_OPERATOR_CONFIRMATION_REQUIRED" in payload["blockers"]
    assert "BAMBU_AUTOEJECTION_NOT_REQUESTED" in payload["autoejection"]["blockers"]
    assert {section["id"] for section in payload["sections"]} >= {
        "printer_connection",
        "device_screen",
        "preprint_gate",
        "start_gate",
        "autoejection_gate",
    }
    assert "secret-code" not in response.text


def test_printer_spc_readiness_reports_technical_ready_separate_from_approval(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )

    def fake_prepare(payload: dict) -> dict:
        return {
            "ok": True,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "device_screen": {
                "schema": "printer_device_screen.v1",
                "connection": {"mqtt": "connected", "transfer": "connected", "video": "streaming"},
                "job": {"state": "IDLE", "progress_percent": 0},
                "actions": {"can_upload": True, "can_start_print": True, "can_prepare_start_command": True},
            },
            "preprint_gate": {
                "state": "uploaded_not_started",
                "blockers": [],
                "checks": {
                    "mqtt_authenticated_or_virtual": True,
                    "latest_report_fresh": True,
                    "printer_safe_state_verified": True,
                    "storage_transfer_path_verified": True,
                    "start_command_draft_prepared": True,
                },
            },
            "operator_actions": [],
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/spc-readiness",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.gcode.3mf",
            "subtask_name": "spc-readiness-ready-but-not-approved",
            "operator_confirmed": False,
            "guardian_approved": False,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready_for_live_print"] is False
    assert payload["technical_ready_for_start"] is True
    assert payload["operator_summary"]["technical_gate"] == "ready"
    assert payload["operator_summary"]["approval_gate"] == "waiting"
    transfer_level = next(level for level in payload["readiness_levels"] if level["id"] == "transfer_path")
    approval_level = next(level for level in payload["readiness_levels"] if level["id"] == "start_approval")
    publish_level = next(level for level in payload["readiness_levels"] if level["id"] == "publish_command")
    assert transfer_level["status"] == "ready"
    assert approval_level["status"] == "waiting"
    assert set(approval_level["blocking_codes"]) == {
        "BAMBU_START_DRY_RUN",
        "BAMBU_OPERATOR_CONFIRMATION_REQUIRED",
        "BAMBU_GUARDIAN_APPROVAL_REQUIRED",
    }
    assert publish_level["status"] == "blocked"
    assert "secret-code" not in response.text


def test_printer_http_artifact_route_exports_file_and_returns_guarded_draft(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )
    artifact = tmp_path / "specimen.gcode.3mf"
    artifact.write_bytes(b"bambu sliced payload")
    export_root = tmp_path / "exports"
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main, "BAMBU_HTTP_EXPORT_ROOT", export_root)
    monkeypatch.setattr(app_main, "_detect_printer_reachable_host", lambda printer_host: "192.168.50.10")

    async def fake_fetch_probe(artifact_url: str, *, expected_sha256: str, timeout_sec: float = 3.0) -> dict[str, object]:
        return {
            "ok": True,
            "status_code": 200,
            "size_bytes": len(b"bambu sliced payload"),
            "sha256": expected_sha256,
            "matches_expected_sha256": True,
            "failure_code": "",
            "message": "Artifact URL fetched successfully and sha256 matched.",
        }

    monkeypatch.setattr(app_main, "_probe_bambu_http_artifact_fetch", fake_fetch_probe)
    client = TestClient(app)

    response = client.post(
        "/api/printer/http-artifact-route",
        json={"artifact_path": str(artifact), "subtask_name": "specimen-http"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["artifact_url"].startswith("http://192.168.50.10")
    assert payload["artifact"]["sha256"]
    assert payload["printer_fetch_ready"] is True
    assert payload["server_fetch_probe"]["ok"] is True
    assert payload["operator_actions"][0]["code"] == "BAMBU_HTTP_ARTIFACT_FETCH_VERIFIED"
    assert payload["start_command_draft"]["payload"]["print"]["url"] == payload["artifact_url"]
    assert payload["start_command_draft"]["will_publish"] is False
    assert "secret-code" not in response.text
    served_path = urlparse(payload["artifact_url"]).path
    served = client.get(served_path)
    assert served.status_code == 200
    assert served.content == b"bambu sliced payload"


def test_printer_bambu_slice_artifact_api_creates_real_sliced_artifact_without_publish(tmp_path, monkeypatch) -> None:
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
printf 'api sliced payload' > "$out/specimen.gcode.3mf"
""",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    source = tmp_path / "specimen.stl"
    source.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                    "bambu": {
                        "slicer": {
                            "enabled": True,
                            "executable_path": str(fake_cli),
                            "output_dir": str(tmp_path / "bambu_sliced"),
                            "timeout_sec": 5,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/bambu-slice-artifact",
        json={"source_path": str(source), "specimen_id": "specimen"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tool"] == "printer.bambu.slice_artifact"
    assert payload["provider"] == "bambulab_x2d"
    assert payload["will_publish"] is False
    assert payload["start_enabled"] is False
    assert Path(payload["sliced_artifact_path"]).exists()
    assert Path(payload["sliced_artifact_path"]).read_bytes() == b"api sliced payload"
    assert payload["artifact"]["sha256"] == payload["sha256"]


def test_printer_bambu_prestart_check_runs_slice_http_gate_and_autoejection_without_publish(tmp_path, monkeypatch) -> None:
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
printf 'prestart sliced payload' > "$out/specimen.gcode.3mf"
""",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    source = tmp_path / "specimen.stl"
    source.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                    "bambu": {
                        "slicer": {
                            "enabled": True,
                            "executable_path": str(fake_cli),
                            "output_dir": str(tmp_path / "bambu_sliced"),
                            "timeout_sec": 5,
                        }
                    },
                    "autoejection": {
                        "enabled": False,
                        "provider": "none",
                        "memory_path": str(tmp_path / "bambu_autoejection.json"),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
        }
    )
    manager.save_autoejection_config(
        {
            "enabled": True,
            "provider": "manipulation_agent",
            "verified_routine_id": "robot-pickoff-v1",
            "pre_eject_vision_profile": "bambu-bed-occupied-check",
            "post_eject_vision_profile": "bambu-bed-clear-check",
        }
    )

    def fake_prepare(payload: dict) -> dict:
        assert payload.get("bambu_artifact_url", "").startswith("http://192.168.50.10")
        return {
            "ok": True,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "device_screen": {
                "schema": "printer_device_screen.v1",
                "connection": {"mqtt": "connected", "transfer": "connected", "video": "available"},
                "actions": {"can_upload": True, "can_start_print": True, "can_prepare_start_command": True},
            },
            "preprint_gate": {
                "state": "http_artifact_ready_not_started",
                "technical_ready_for_start": True,
                "approval_ready_for_start": True,
                "ready_for_live_print": True,
                "blockers": [],
                "checks": {
                    "mqtt_authenticated_or_virtual": True,
                    "latest_report_fresh": True,
                    "storage_transfer_path_verified": True,
                    "printer_safe_state_verified": True,
                    "start_command_draft_prepared": True,
                },
            },
            "operator_actions": [],
        }

    async def fake_fetch_probe(artifact_url: str, *, expected_sha256: str, timeout_sec: float = 3.0) -> dict[str, object]:
        return {
            "ok": True,
            "status_code": 200,
            "size_bytes": len(b"prestart sliced payload"),
            "sha256": expected_sha256,
            "matches_expected_sha256": True,
            "failure_code": "",
            "message": "Artifact URL fetched successfully and sha256 matched.",
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main, "BAMBU_HTTP_EXPORT_ROOT", tmp_path / "exports")
    monkeypatch.setattr(app_main, "_detect_printer_reachable_host", lambda printer_host: "192.168.50.10")
    monkeypatch.setattr(app_main, "_probe_bambu_http_artifact_fetch", fake_fetch_probe)
    _save_ready_manipulation_consumer(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/printer/bambu-prestart-check",
        json={
            "source_path": str(source),
            "specimen_id": "specimen",
            "subtask_name": "specimen-prestart",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tool"] == "printer.bambu.prestart_check"
    assert payload["will_publish"] is False
    assert payload["published"] is False
    assert Path(payload["sliced_artifact_path"]).exists()
    assert payload["artifact_url"].startswith("http://192.168.50.10")
    assert payload["http_artifact_route"]["printer_fetch_ready"] is True
    assert payload["start_gate"]["ready_to_publish"] is True
    assert payload["spc_readiness"]["autoejection_handoff"]["recommended_consumer_agent"] == "ManipulationAgent"
    assert payload["autoejection_handoff"]["routine_id"] == "robot-pickoff-v1"
    assert [step["id"] for step in payload["steps"]] == [
        "slice_artifact",
        "http_artifact_route",
        "start_gate",
        "spc_readiness",
        "autoejection_handoff",
    ]
    assert all("secret-code" not in str(value) for value in payload.values())


def test_printer_http_artifact_route_reports_fetch_probe_blocker(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    from device_bridges.bambu_bridge import BambuConnectionMemory

    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )
    artifact = tmp_path / "specimen.gcode.3mf"
    artifact.write_bytes(b"bambu sliced payload")
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main, "BAMBU_HTTP_EXPORT_ROOT", tmp_path / "exports")
    monkeypatch.setattr(app_main, "_detect_printer_reachable_host", lambda printer_host: "192.168.50.10")

    async def fake_fetch_probe(artifact_url: str, *, expected_sha256: str, timeout_sec: float = 3.0) -> dict[str, object]:
        return {
            "ok": False,
            "failure_code": "BAMBU_HTTP_ARTIFACT_FETCH_FAILED",
            "message": "probe failed",
        }

    monkeypatch.setattr(app_main, "_probe_bambu_http_artifact_fetch", fake_fetch_probe)
    client = TestClient(app)

    response = client.post(
        "/api/printer/http-artifact-route",
        json={"artifact_path": str(artifact), "subtask_name": "specimen-http"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["printer_fetch_ready"] is False
    assert payload["server_fetch_probe"]["failure_code"] == "BAMBU_HTTP_ARTIFACT_FETCH_FAILED"
    assert payload["operator_actions"][0]["severity"] == "warning"
    assert "secret-code" not in response.text


def test_printer_http_artifact_route_rejects_loopback_public_base_url(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "specimen.gcode.3mf"
    artifact.write_bytes(b"payload")
    client = TestClient(app)

    response = client.post(
        "/api/printer/http-artifact-route",
        json={"artifact_path": str(artifact), "public_base_url": "http://127.0.0.1:18080"},
    )

    assert response.status_code == 400
    assert "BAMBU_HTTP_ARTIFACT_URL_NOT_PRINTER_REACHABLE" in response.text


def test_printer_profile_api_reports_saved_print_defaults() -> None:
    client = TestClient(app)

    response = client.get("/api/printer/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["profile"]["printer_model"] == "Bambu Lab X2D"
    assert payload["profile"]["storage"] == "ftps"
    assert payload["profile"]["start_immediately_live"] is False
    assert isinstance(payload["profile"]["allow_ejection"], bool)
    assert payload["profile_path"].endswith("memory/prusa_print_profile.json")
    assert payload["connection_memory_path"].endswith("memory/bambu_connection.json")
    assert payload["slicer"]["executable_env"] == "BAMBU_STUDIO_EXECUTABLE"
    assert payload["slicer"]["executable_path"].endswith("install/bambustudio/bambu-studio-wrapper")
    assert payload["slicer"]["output_dir"].endswith("artifacts/bambu_sliced")
    assert payload["live_gates"]["allow_upload"] is False
    assert payload["live_gates"]["allow_start_print"] is False


def test_printer_profile_api_uses_bambu_autoejection_config_not_profile_checkbox(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                    "autoejection": {"enabled": False, "provider": "none"},
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(
        app_main,
        "load_prusa_print_profile",
        lambda: {
            "printer_model": "Bambu Lab X2D",
            "printer_profile": "bambulab_x2d_pla_0p4_nozzle",
            "storage": "ftps",
            "allow_ejection": True,
        },
    )
    client = TestClient(app)

    response = client.get("/api/printer/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"]["allow_ejection"] is True
    assert payload["auto_ejection"]["enabled"] is False
    assert payload["auto_ejection"]["mode"] == "not_configured"
    assert payload["auto_ejection"]["can_run_test"] is False
    assert "BAMBU_AUTOEJECTION_NOT_REQUESTED" in payload["auto_ejection"]["blockers"]


def test_printer_autoejection_status_api_reports_real_configured_gate(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                    "autoejection": {
                        "enabled": True,
                        "provider": "external_robot_pickoff",
                        "require_verified_routine": True,
                        "require_pre_eject_vision": True,
                        "require_post_eject_vision": True,
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.get("/api/printer/autoejection-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tool"] == "printer.autoejection_status"
    assert payload["provider"] == "bambulab_x2d"
    assert payload["autoejection"]["requested"] is True
    assert payload["autoejection"]["enabled"] is False
    assert payload["autoejection"]["status"] == "blocked"
    assert payload["autoejection"]["can_run_test"] is False
    assert "BAMBU_AUTOEJECTION_ROUTINE_NOT_VERIFIED" in payload["autoejection"]["blockers"]
    assert "BAMBU_PRE_EJECT_VISION_PROFILE_REQUIRED" in payload["autoejection"]["blockers"]
    assert "BAMBU_POST_EJECT_VISION_PROFILE_REQUIRED" in payload["autoejection"]["blockers"]


def test_printer_autoejection_handoff_blocks_without_saved_manipulation_defaults(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                    "autoejection": {
                        "enabled": False,
                        "provider": "none",
                        "memory_path": str(tmp_path / "bambu_autoejection.json"),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main, "MANIPULATION_AGENT_PROFILE_PATH", tmp_path / "memory" / "manipulation_agent_bridge.json")
    client = TestClient(app)

    config = client.post(
        "/api/printer/autoejection-config",
        json={
            "enabled": True,
            "provider": "manipulation_agent",
            "verified_routine_id": "robot-pickoff-v1",
            "pre_eject_vision_profile": "bambu-bed-occupied-check",
            "post_eject_vision_profile": "bambu-bed-clear-check",
        },
    ).json()

    assert config["autoejection"]["can_run_test"] is True
    assert config["consumer_readiness"]["ready"] is False
    assert "MANIPULATION_AGENT_DEFAULTS_NOT_SAVED" in config["consumer_readiness"]["blockers"]

    status = client.get("/api/printer/autoejection-status").json()
    assert status["autoejection"]["status"] == "configured"
    assert status["consumer_readiness"]["ready"] is False

    test = client.post(
        "/api/printer/autoejection-test",
        json={"mode": "live", "position": "center", "object_size_mm": [30, 30, 30]},
    ).json()

    assert test["ok"] is False
    assert test["failure_code"] == "BAMBU_AUTOEJECTION_CONSUMER_NOT_READY"
    assert test["autoejection"]["can_run_test"] is True
    assert test["consumer_readiness"]["ready"] is False
    assert test.get("autoejection_handoff", {}) == {}


def test_printer_autoejection_config_api_persists_verified_bambu_gate(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                    "autoejection": {
                        "enabled": False,
                        "provider": "none",
                        "memory_path": str(tmp_path / "bambu_autoejection.json"),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    _save_ready_manipulation_consumer(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/printer/autoejection-config",
        json={
            "enabled": True,
            "provider": "external_robot_pickoff",
            "verified_routine_id": "robot-pickoff-v1",
            "pre_eject_vision_profile": "bambu-bed-occupied-check",
            "post_eject_vision_profile": "bambu-bed-clear-check",
            "require_verified_routine": True,
            "require_pre_eject_vision": True,
            "require_post_eject_vision": True,
            "fallback_to_robot_pickoff": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tool"] == "printer.autoejection_config"
    assert payload["autoejection"]["enabled"] is True
    assert payload["autoejection"]["can_run_test"] is True
    assert payload["autoejection"]["blockers"] == []
    assert payload["consumer_readiness"]["ready"] is True
    assert payload["settings_path"].endswith("bambu_autoejection.json")

    status = client.get("/api/printer/autoejection-status").json()
    assert status["autoejection"]["status"] == "configured"
    assert status["autoejection"]["verified_routine_id"] == "robot-pickoff-v1"

    def fake_prepare(payload: dict) -> dict:
        return {
            "ok": False,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "device_screen": {
                "schema": "printer_device_screen.v1",
                "connection": {"mqtt": "connected", "transfer": "read_only"},
                "actions": {"can_upload": False, "can_start_print": False, "can_prepare_start_command": True},
            },
            "preprint_gate": {"state": "blocked", "blockers": ["BAMBU_FTPS_WRITE_FAILED"], "checks": {}},
            "operator_actions": [],
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    readiness = client.post(
        "/api/printer/spc-readiness",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.gcode.3mf",
            "subtask_name": "spc-readiness",
            "operator_confirmed": False,
            "guardian_approved": False,
            "dry_run": True,
        },
    ).json()
    auto_section = next(section for section in readiness["sections"] if section["id"] == "autoejection_gate")
    assert auto_section["status"] == "ready"
    assert readiness["autoejection"]["can_run_test"] is True
    assert readiness["consumer_readiness"]["ready"] is True


def test_printer_spc_readiness_includes_bambu_autoejection_handoff_when_configured(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                    "autoejection": {
                        "enabled": False,
                        "provider": "none",
                        "memory_path": str(tmp_path / "bambu_autoejection.json"),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    BambuConnectionMemory(tmp_path / "bambu_connection.json").save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "TESTSERIAL123",
            "printer_name": "x2d-test",
            "auth": {"username": "bblp", "access_code": "dummy-access-code"},
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
        }
    )
    manager.save_autoejection_config(
        {
            "enabled": True,
            "provider": "manipulation_agent",
            "verified_routine_id": "robot-pickoff-v1",
            "pre_eject_vision_profile": "bambu-bed-occupied-check",
            "post_eject_vision_profile": "bambu-bed-clear-check",
        }
    )

    def fake_prepare(payload: dict) -> dict:
        return {
            "ok": True,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "device_screen": {
                "schema": "printer_device_screen.v1",
                "connection": {"mqtt": "connected", "transfer": "connected", "video": "available"},
                "actions": {"can_upload": True, "can_start_print": True, "can_prepare_start_command": True},
            },
            "preprint_gate": {
                "state": "http_artifact_ready_not_started",
                "technical_ready_for_start": True,
                "approval_ready_for_start": True,
                "ready_for_live_print": True,
                "blockers": [],
                "checks": {"storage_transfer_path_verified": True},
            },
            "operator_actions": [],
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    _save_ready_manipulation_consumer(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/printer/spc-readiness",
        json={
            "mode": "live",
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/specimen.3mf",
            "subtask_name": "spc-readiness",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["autoejection"]["can_run_test"] is True
    assert payload["consumer_readiness"]["ready"] is True
    assert payload["autoejection_handoff"]["schema"] == "bambu_autoejection_provider_handoff.v1"
    assert payload["autoejection_handoff"]["recommended_consumer_agent"] == "ManipulationAgent"
    assert payload["autoejection_handoff"]["next_tool"] == "lerobot.manipulation-agent.run"
    assert payload["autoejection_handoff"]["requires_guardian_approval"] is True
    assert payload["autoejection_handoff"]["requires_operator_confirmation"] is True
    assert payload["autoejection_handoff"]["motion_started"] is False
    assert payload["autoejection_handoff"]["dry_run_only"] is True
    assert payload["will_publish"] is False


def test_printer_connection_api_saves_bambu_connection_without_echoing_secret(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/connection",
        json={
            "host": "192.168.50.77",
            "serial": "TESTSERIAL123",
            "printer_name": "x2d-lab-test",
            "auth_mode": "lan_access_code",
            "username": "bblp",
            "access_code": "test-access-code",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["connection"]["host"] == "192.168.50.77"
    assert payload["connection"]["serial"] == "TESTSERIAL123"
    assert payload["connection"]["access_code_set"] is True
    assert '"access_code":' not in response.text
    assert "test-access-code" not in response.text


def test_printer_autoejection_test_emits_runtime_workspace_event(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                    "autoejection": {
                        "enabled": False,
                        "provider": "none",
                        "memory_path": str(tmp_path / "bambu_autoejection.json"),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/autoejection-test",
        json={"mode": "test", "position": "center", "start_immediately": False, "object_size_mm": [10, 10, 5]},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["tool"] == "printer.autoejection_test"
    assert payload["failure_code"] == "BAMBU_AUTOEJECTION_NOT_CONFIGURED"
    assert any(
        event.get("type") == "tool.failed"
        and event.get("node_id") == "specimen"
        and event.get("payload", {}).get("tool") == "printer.autoejection_test"
        for event in app_main.controller.recent_events()
    )


def test_configured_bambu_autoejection_test_creates_provider_handoff_without_prusa_bedsweep(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "bambulab_x2d_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        }
                    },
                    "autoejection": {
                        "enabled": False,
                        "provider": "none",
                        "memory_path": str(tmp_path / "bambu_autoejection.json"),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    manager.save_autoejection_config(
        {
            "enabled": True,
            "provider": "external_robot_pickoff",
            "verified_routine_id": "robot-pickoff-v1",
            "pre_eject_vision_profile": "bambu-bed-occupied-check",
            "post_eject_vision_profile": "bambu-bed-clear-check",
        }
    )

    def fail_if_prusa_workflow_is_used():
        raise AssertionError("Bambu autoejection must not route to the Prusa bed-sweep workflow")

    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main, "_printer_workflow", fail_if_prusa_workflow_is_used)
    _save_ready_manipulation_consumer(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/printer/autoejection-test",
        json={"mode": "live", "position": "center", "start_immediately": True, "object_size_mm": [30, 30, 20]},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["provider"] == "bambulab_x2d"
    assert payload["status"] == "provider_handoff_ready"
    assert payload["motion_started"] is False
    assert payload["consumer_readiness"]["ready"] is True
    assert payload["handoff"]["provider"] == "external_robot_pickoff"
    assert payload["handoff"]["routine_id"] == "robot-pickoff-v1"
    assert payload["handoff"]["position"] == "center"
    assert payload["handoff"]["object_size_mm"] == [30, 30, 20]
    assert payload["handoff"]["recommended_consumer_agent"] == "ManipulationAgent"
    assert payload["handoff"]["requires_guardian_approval"] is True
    assert payload["handoff"]["requires_operator_confirmation"] is True
    assert payload["handoff"]["motion_started"] is False
    assert payload["handoff"]["dry_run_only"] is True
