import json
import hashlib
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from device_bridges.bambu_bridge import BambuConnectionMemory, PrinterDeviceBridgeManager


def _write_minimal_bambu_gcode_3mf(path: Path, *, plate_id: int = 1, gcode: str = "G90\nG1 X10 Y10 Z10 F1200\nM84\n") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"Metadata/plate_{int(plate_id)}.gcode", gcode)
        archive.writestr("3D/3dmodel.model", "<model />")


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
    assert "Bambu G-code Autoejection" in response.text
    assert "Run Standalone Eject: Left" in response.text
    assert "Save Autoejection Config" in response.text
    assert "Native Provider" in response.text
    assert "printer-autoejection-push-direction-input" in response.text
    assert "printer-autoejection-z-push-offset-input" in response.text
    assert 'id="printer-autoejection-z-push-offset-input"' in response.text
    assert 'value="15"' in response.text
    assert "printer-autoejection-push-lane-offset-input" in response.text
    assert "printer-autoejection-push-speed-input" in response.text
    assert 'id="printer-autoejection-push-speed-input"' in response.text
    assert 'max="12000"' in response.text
    assert 'value="6000"' in response.text
    assert "printer-autoejection-full-bed-sweep-input" in response.text
    assert "printer-autoejection-sweep-z-input" in response.text
    assert "printer-autoejection-sweep-speed-input" in response.text
    assert "operator confirmed" not in response.text
    assert "Guardian approved" not in response.text
    assert "dry-run / no publish" not in response.text
    assert "front path / door clear" not in response.text
    assert "ramp or bin ready" not in response.text
    assert "toolhead cover secured" not in response.text
    assert "release surface confirmed" not in response.text
    assert "supervised first ejection" not in response.text
    assert "Reading native G-code patch evidence." in response.text
    assert "Validate G-code Preview" in response.text
    assert "Validate Left" in response.text
    assert "Validate Center" in response.text
    assert "Validate Right" in response.text
    assert "Generate Ejection Test Artifact" in response.text
    assert "Generate Sweep Test Artifact" in response.text
    assert "btn-printer-autoejection-validate-preview" in response.text
    assert "btn-printer-autoejection-validate-left" in response.text
    assert "btn-printer-autoejection-validate-center" in response.text
    assert "btn-printer-autoejection-validate-right" in response.text
    assert "btn-printer-autoejection-test-artifact" in response.text
    assert "btn-printer-autoejection-sweep-test-artifact" in response.text
    assert "btn-printer-autoejection-fill-native" in response.text
    assert "btn-printer-autoejection-patch-artifact" in response.text
    assert "printer-autoejection-validation-details" in response.text
    assert "printer-autoejection-validation-body" in response.text
    assert "printer-bed-clear-summary" in response.text
    assert "btn-printer-bed-clear-mark" in response.text
    assert "btn-printer-bed-clear-not-clear" in response.text
    assert "Physical Proof Package" in response.text
    assert "Build Fail-Closed Proof Template" in response.text
    assert "Run Completion Audit" in response.text
    assert "btn-printer-autoejection-proof-template" in response.text
    assert "btn-printer-autoejection-completion-audit" in response.text
    assert "printer-autoejection-proof-path-input" in response.text
    assert "printer-autoejection-proof-summary" in response.text
    assert "printer-bambu-artifact-path-input" in response.text
    assert "printer-bambu-public-base-url-input" in response.text
    assert "btn-printer-start-publish" in response.text
    assert "/static/printer.js" in response.text
    assert "fallback이 아니라" not in response.text
    assert "자동 대체가 아니라" in response.text
    assert "Save Autoejection Gate" not in response.text


def test_printer_gui_does_not_treat_profile_ejection_checkbox_as_bambu_ejection_ready() -> None:
    script = (Path(__file__).resolve().parents[2] / "web" / "static" / "printer.js").read_text(encoding="utf-8")
    styles = (Path(__file__).resolve().parents[2] / "web" / "static" / "styles.css").read_text(encoding="utf-8")

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
    assert "/api/printer/bambu-autoejection-patch" in script
    assert "/api/printer/bambu-autoejection-proof-template" in script
    assert "/api/printer/bambu-autoejection-completion-audit" in script
    assert "/api/printer/bed-clear" in script
    assert "runBambuProofTemplate" in script
    assert "runBambuCompletionAudit" in script
    assert "markBedClear" in script
    assert "renderBedClearStatus" in script
    assert "updateAutoejectionButtonLabels" in script
    assert "fillNativeGcodeAutoejectionDefaults" in script
    assert 'autoejectionProviderInput.value = data.provider || data.method || "none";' in script
    assert "autoejectionPushDirectionInput" in script
    assert "push_direction:" in script
    assert "z_push_offset_mm:" in script
    assert "push_lane_offset_mm:" in script
    assert "push_speed_mm_min:" in script
    assert "enable_full_bed_sweep:" in script
    assert "sweep_z_mm:" in script
    assert "sweep_speed_mm_min:" in script
    assert "native_gcode_parameters" in script
    assert "const position = options.positionOverride ||" in script
    assert "Native G-code patch preset filled locally" in script
    assert "Press Save Autoejection Config" in script
    assert "autoejectionZPushOffsetInput.value = 15" in script
    assert "autoejectionPushSpeedInput.value = 6000" in script
    assert "autoejectionSweepSpeedInput.value = 6000" in script
    assert "Save Autoejection Gate" not in script
    assert "btnAutoejectionValidatePreview" in script
    assert "Validate G-code Preview" in script
    assert "btnAutoejectionValidateLeft" in script
    assert "btnAutoejectionValidateCenter" in script
    assert "btnAutoejectionValidateRight" in script
    assert "Validate Left" in script
    assert "Validate Center" in script
    assert "Validate Right" in script
    assert 'positionOverride: "left"' in script
    assert 'positionOverride: "center"' in script
    assert 'positionOverride: "right"' in script
    assert "validateOnly: true" in script
    assert "validate_only: Boolean(options.validateOnly)" in script
    assert "btnAutoejectionTestArtifact" in script
    assert "btnAutoejectionSweepTestArtifact" in script
    assert "/api/printer/bambu-autoejection-sweep-test" in script
    assert "Generate Sweep Test Artifact" in script
    assert "updateArtifactInput: false" in script
    assert "formatBambuAutoejectionArtifactSummary" in script
    assert "renderBambuAutoejectionValidationEvidence" in script
    assert "autoejectionValidationBody" in script
    assert "validationResult" in script
    assert "Native G-code validation ${validationPassed ? \"passed\" : \"blocked\"}" in script
    assert "schema_marker" in script
    assert "sweep_path" in script
    assert "tail_gcode" not in script
    assert "plate_gcode" not in script
    assert "data.patched_artifact_path" in script
    assert "source_plate_path" in script
    assert "object_bounds_mm" in script
    assert "blockersText" in script
    assert "consumer_readiness" in script
    assert "Native G-code patcher" in script
    assert "Run Standalone Eject: Center" in script
    assert "Generate Patched Artifact" in script
    assert 'await refreshStatus("live");\n    await refreshAutoejectionStatus();' in script
    assert "verify_fetch: true" in script
    assert "lastHttpArtifactUrl = fetchReady ? data.artifact_url || \"\" : \"\";" in script
    assert "HTTP artifact ${probeText}" in script
    assert "readStartGateOptions" in script
    assert "startOperatorConfirmedInput" in script
    assert "startGuardianApprovedInput" in script
    assert "startDryRunInput" in script
    assert "autoejectionFrontPathClearInput" in script
    assert "door_or_front_path_clear" in script
    assert "ejection_ramp_or_bin_ready" in script
    assert "toolhead_cover_secured" in script
    assert "release_surface_profile" in script
    assert "first_ejection_supervised" in script
    assert "renderReadinessLevels" in script
    assert "data.readiness_levels" in script
    assert "data.autoejection_handoff" in script
    assert "Native G-code artifact" in script
    assert "renderConnectionActionGuidance" in script
    assert "printer-connection-action-list" in script
    assert "lastFleetPayload" in script
    assert "incoming.available_printers" in script
    assert "fallback=" not in script
    assert "auto-switch=" in script
    assert "BAMBU_LAN_MODE_NOT_CONFIRMED" in script
    assert "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED" in script
    assert "BAMBU_FTPS_WRITE_FAILED" in script
    assert "BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE" in script
    assert "connection-action-card" in script
    assert "operator_confirmed: true" in script
    assert "guardian_approved: true" in script
    assert "dry_run: false" in script
    assert "screen.progress_panel" in script
    assert "screen.camera_panel" in script
    assert "screen.control_panel" in script
    assert "screen.material_panel" in script
    assert "screen.evidence_cards" in script
    assert "cameraPanel.proxy_ready" in script
    assert "printer-video-stream" in script
    assert ".printer-evidence-details pre" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "white-space: pre-wrap" in styles
    assert "printerStatusManualOverride" in script
    assert 'refreshStatus("live", { initial: true })' in script
    assert 'refreshStatus("live", { manual: true, emit: true })' in script
    assert "function startPrinterLiveMonitor()" not in script
    assert "function runPrinterMonitorTick()" not in script
    assert 'params.set("emit", "1")' in script
    assert 'event_type != "workspace_monitor_snapshot"' in Path("app/controller.py").read_text(encoding="utf-8")
    assert "renderConfig(data);\n  renderDeviceScreen(data);" in script
    sweep_body = script.split("async function runBambuSweepTestArtifact()", 1)[1].split("async function refreshAutoejectionStatus()", 1)[0]
    assert sweep_body.index('await refreshStatus("live");') < sweep_body.rindex("renderAutoejectionStatus(data);")


def test_printer_live_status_emit_updates_runtime_monitor_without_chat(tmp_path, monkeypatch) -> None:
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
    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )

    def fake_prepare(payload: dict) -> dict:
        assert payload == {"runtime_mode": "live", "health_only": True, "status_only": True, "skip_ftps_probe": True}
        return {
            "ok": True,
            "state": "RUNNING",
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "device_screen": {
                "actions": {"can_upload": True, "can_start_print": False},
                "connection": {"mqtt": "connected", "transfer": "connected"},
                "progress_panel": {"state": "RUNNING", "progress_percent": 42},
            },
            "preprint_gate": {"state": "printing", "blockers": [], "checks": {}},
            "operator_actions": [],
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)
    session_id = "printer-monitor-status-session"
    before_session = client.get(f"/api/planning/session?session_id={session_id}").json()
    before_total = before_session["message_total"]
    cursor = len(app_main.controller.recent_events())

    response = client.get("/api/printer/status?mode=live&emit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool"] == "printer.status"
    assert payload["status"] == "RUNNING"
    new_events = app_main.controller.recent_events()[cursor:]
    assert any(
        event.get("event_type") == "workspace_monitor_snapshot"
        and event.get("payload", {}).get("tool") == "printer.status"
        and event.get("payload", {}).get("monitor_snapshot", {}).get("device_screen", {}).get("progress_panel", {}).get("progress_percent") == 42
        for event in new_events
    )
    assert not any(event.get("type") == "artifact.created" for event in new_events)
    after_session = client.get(f"/api/planning/session?session_id={session_id}").json()
    assert after_session["message_total"] == before_total


def test_printer_bambu_physical_proof_template_api_writes_fail_closed_template(tmp_path, monkeypatch) -> None:
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
                        "provider": "bambu_gcode_patch",
                        "memory_path": str(tmp_path / "bambu_autoejection.json"),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    proof_path = tmp_path / "bambu_autoejection_physical_validation_template.json"
    client = TestClient(app)

    response = client.post(
        "/api/printer/bambu-autoejection-proof-template",
        json={"proof_package_path": str(proof_path)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "template_written_fail_closed"
    assert payload["completion_ready"] is False
    assert payload["provider"] == "bambulab_x2d"
    assert proof_path.exists()
    saved = json.loads(proof_path.read_text(encoding="utf-8"))
    assert saved["schema"] == "bambu_autoejection_physical_validation.v1"
    assert saved["printer"]["profile_id"] == "bambulab_x2d_lab_01"
    assert saved["next_job_gate"]["no_bambu_post_eject_bed_not_clear"] is False

    audit_response = client.post(
        "/api/printer/bambu-autoejection-completion-audit",
        json={"proof_package_path": str(proof_path)},
    )

    assert audit_response.status_code == 200
    audit = audit_response.json()
    assert audit["ok"] is False
    assert audit["status"] == "incomplete"
    assert audit["provider"] == "bambulab_x2d"
    assert "BAMBU_PHYSICAL_CENTER_EJECTION_REQUIRED" in audit["blockers"]
    assert "BAMBU_NEXT_JOB_GATE_REQUIRED" in audit["blockers"]


def test_printer_bambu_physical_proof_apis_are_blocked_for_non_bambu_profile(tmp_path, monkeypatch) -> None:
    manager = PrinterDeviceBridgeManager.from_devices_config(
        {
            "devices": {
                "printer": {
                    "mode": "test",
                    "default_profile_id": "prusa_mk4s_lab_01",
                    "connection_memory_path": str(tmp_path / "printer_fleet.json"),
                    "profiles": {
                        "prusa_mk4s_lab_01": {
                            "provider": "prusa_mk4s",
                            "connection_memory_path": str(tmp_path / "prusa_connection.json"),
                            "enabled": True,
                        },
                        "bambulab_x2d_lab_01": {
                            "provider": "bambulab_x2d",
                            "connection_memory_path": str(tmp_path / "bambu_connection.json"),
                            "enabled": True,
                        },
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    proof_path = tmp_path / "must_not_be_written.json"
    client = TestClient(app)

    template_response = client.post(
        "/api/printer/bambu-autoejection-proof-template",
        json={"proof_package_path": str(proof_path)},
    )

    assert template_response.status_code == 200
    template = template_response.json()
    assert template["ok"] is False
    assert template["status"] == "blocked"
    assert template["provider"] == "prusa_mk4s"
    assert template["failure_code"] == "BAMBU_PROOF_TEMPLATE_NOT_APPLICABLE"
    assert proof_path.exists() is False

    audit_response = client.post(
        "/api/printer/bambu-autoejection-completion-audit",
        json={"proof_package_path": str(proof_path)},
    )

    assert audit_response.status_code == 200
    audit = audit_response.json()
    assert audit["ok"] is False
    assert audit["status"] == "blocked"
    assert audit["provider"] == "prusa_mk4s"
    assert audit["failure_code"] == "BAMBU_COMPLETION_AUDIT_NOT_APPLICABLE"
    assert audit["blockers"] == ["BAMBU_COMPLETION_AUDIT_NOT_APPLICABLE"]


def test_printer_native_autoejection_status_message_does_not_claim_manipulation_consumer(tmp_path, monkeypatch) -> None:
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
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    payload = client.get("/api/printer/autoejection-status").json()

    assert payload["autoejection"]["native_gcode_patch"] is True
    assert "Native G-code patch" in payload["message"]
    assert "Manipulation Agent consumer" not in payload["message"]


def test_printer_video_status_updates_camera_without_clearing_device_screen() -> None:
    script = (Path(__file__).resolve().parents[2] / "web" / "static" / "printer.js").read_text(encoding="utf-8")

    video_status_body = script.split("async function runVideoStatus()", 1)[1].split("async function saveProfile()", 1)[0]
    assert "renderCameraPanel(data);" in video_status_body
    assert "renderDeviceScreen(data);" not in video_status_body


def test_printer_prestart_check_refreshes_camera_and_locks_command_buttons() -> None:
    script = (Path(__file__).resolve().parents[2] / "web" / "static" / "printer.js").read_text(encoding="utf-8")

    prestart_body = script.split("async function runBambuPrestartCheck()", 1)[1].split("async function runStartCommandDraft()", 1)[0]
    assert "await refreshVideoStatusCamera" in prestart_body
    assert prestart_body.index("await refreshVideoStatusCamera") < prestart_body.index("if (!sourcePath && !artifactPath)")
    assert "waitForCameraFrameLoaded" in script
    assert "printerOperationButtons" in script
    assert "setOperationButtonsLocked" in script
    lock_body = script.split("function setOperationButtonsLocked(locked)", 1)[1].split("function setDotState", 1)[0]
    assert "printerOperationLockDepth += 1;" in lock_body
    assert "button.disabled = true;" in lock_body
    assert "button.classList.add(\"busy-locked\");" in lock_body
    assert "button.disabled = Boolean(printerOperationDisabledSnapshot.get(button));" in lock_body
    assert "applyStartPublishBedClearGate" in lock_body
    operation_buttons_body = script.split("function printerOperationButtons()", 1)[1].split("function setOperationButtonsLocked", 1)[0]
    assert "btnAutoejectionValidateLeft" in operation_buttons_body
    assert "btnAutoejectionValidateCenter" in operation_buttons_body
    assert "btnAutoejectionValidateRight" in operation_buttons_body
    assert "btnEjectLeft" in operation_buttons_body
    assert "btnEjectCenter" in operation_buttons_body
    assert "btnEjectRight" in operation_buttons_body
    for function_name in [
        "runVideoStatus",
        "runBambuPrestartCheck",
        "runStartPublish",
        "runSpcReadiness",
        "runBambuAutoejectionPatchArtifact",
        "runBambuSweepTestArtifact",
        "markBedClear",
    ]:
        body = script.split(f"async function {function_name}", 1)[1].split("\nasync function ", 1)[0]
        assert "setBusy(" in body
        assert "finally" in body
        assert "setBusy(" in body.rsplit("finally", 1)[1]


def test_printer_bed_clear_uses_latest_camera_snapshot_evidence() -> None:
    script = (Path(__file__).resolve().parents[2] / "web" / "static" / "printer.js").read_text(encoding="utf-8")

    render_camera_body = script.split("function renderCameraPanel(data, options = {})", 1)[1].split("function renderDeviceScreen(data)", 1)[0]
    render_bed_clear_body = script.split("function renderBedClearStatus(data)", 1)[1].split("function escapeHtml(value)", 1)[0]
    mark_bed_clear_body = script.split("async function markBedClear(verified, button)", 1)[1].split("async function runUploadPathProbe()", 1)[0]

    assert "let lastCameraSnapshotPath" in script
    assert "lastCameraSnapshotPath = snapshotUrl || proxyUrl || lastCameraSnapshotPath;" in render_camera_body
    assert "applyStartPublishBedClearGate(Boolean(blockingCode));" in render_bed_clear_body
    assert "function applyStartPublishBedClearGate(blocked)" in script
    assert "camera_snapshot_path: lastCameraSnapshotPath" in mark_bed_clear_body


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


def test_printer_live_status_api_uses_read_only_health_check(tmp_path, monkeypatch) -> None:
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
    assert calls == [{"runtime_mode": "live", "health_only": True, "status_only": True, "skip_ftps_probe": True}]
    assert payload["live_gates"]["allow_upload"] is False
    assert payload["device_screen"]["connection"]["transfer"] == "read_only"
    assert payload["operator_actions"][0]["code"] == "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED"


def test_printer_live_status_api_probes_transfer_while_specimen_stage_is_running(tmp_path, monkeypatch) -> None:
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
            "ok": True,
            "state": "READY_TO_UPLOAD",
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
                "connection": {"mqtt": "connected", "transfer": "connected"},
                "actions": {"can_upload": True, "can_start_print": False},
                "control_panel": {"blockers": []},
            },
            "preprint_gate": {"schema": "preprint_real_communication_gate.v1", "state": "ready_to_upload", "blockers": []},
            "operator_actions": [],
            "autoejection": {"enabled": True, "provider": "bambu_gcode_patch", "status": "configured"},
        }

    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(
        app_main.controller,
        "snapshot",
        lambda: {"is_running": True, "state": {"stage": "specimen", "mode": "test"}},
    )
    manager.prepare = fake_prepare  # type: ignore[method-assign]
    client = TestClient(app)

    response = client.get("/api/printer/status?mode=live&emit=1")

    assert response.status_code == 200
    payload = response.json()
    assert calls == [{"runtime_mode": "live", "health_only": True, "status_only": True, "skip_ftps_probe": False}]
    assert payload["device_screen"]["connection"]["transfer"] == "connected"
    assert payload["live_gates"]["allow_upload"] is True


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


def test_printer_video_frame_endpoint_returns_single_jpeg_without_echoing_secret(tmp_path, monkeypatch) -> None:
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

    class Completed:
        returncode = 0
        stdout = b"\xff\xd8FAKEJPEG\xff\xd9"
        stderr = b""

    def fake_run(command, **kwargs):  # noqa: ANN001
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(app_main.subprocess, "run", fake_run)
    client = TestClient(app)

    response = client.get("/api/printer/video-frame.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8")
    assert b"secret-code" not in response.content
    assert "-frames:v" in captured["command"]
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


def test_printer_start_publish_blocks_autoeject_without_camera_frame(tmp_path, monkeypatch) -> None:
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

    def fake_probe_live_view(**_kwargs) -> dict:
        return {
            "ok": False,
            "status": "blocked",
            "failure_code": "BAMBU_VIDEO_PORT_UNREACHABLE",
            "stream_kind": "unavailable",
            "proxy_ready": False,
            "snapshot_url": "",
            "blockers": ["BAMBU_VIDEO_PORT_UNREACHABLE"],
        }

    class FakeMqttClient:
        def publish_project_file_command(self, **_kwargs) -> dict:
            raise AssertionError("autoeject publish must not run without camera evidence")

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    manager.video_client.probe_live_view = fake_probe_live_view  # type: ignore[method-assign]
    manager.mqtt_client = FakeMqttClient()
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-publish",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.autoeject.gcode.3mf",
            "subtask_name": "specimen-autoeject",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["ready_to_publish"] is False
    assert payload["published"] is False
    assert "BAMBU_AUTOEJECTION_CAMERA_FRAME_REQUIRED" in payload["blockers"]
    assert payload["camera_status"]["failure_code"] == "BAMBU_VIDEO_PORT_UNREACHABLE"


def test_printer_start_publish_allows_autoeject_without_manual_operator_checklist(tmp_path, monkeypatch) -> None:
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
    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )

    def fake_prepare(payload: dict) -> dict:
        if payload.get("post_publish_observation"):
            return {
                "ok": True,
                "provider": "bambulab_x2d",
                "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
                "device_screen": {
                    "actions": {"can_start_print": False, "can_prepare_start_command": False},
                    "connection": {"mqtt": "connected", "transfer": "connected"},
                    "progress_panel": {"gcode_state": "RUNNING"},
                },
                "preprint_gate": {"state": "running", "blockers": [], "checks": {}},
                "operator_actions": [],
            }
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

    def fake_probe_live_view(**_kwargs) -> dict:
        return {
            "ok": True,
            "status": "snapshot",
            "stream_kind": "snapshot",
            "proxy_ready": True,
            "snapshot_url": "/api/printer/video-frame.jpg",
            "snapshot_bytes": b"\xff\xd8atr-camera-frame\xff\xd9",
            "blockers": [],
        }

    class FakeMqttClient:
        def publish_project_file_command(self, **kwargs) -> dict:
            return {
                "ok": True,
                "status": "published",
                "topic": kwargs.get("topic", ""),
                "sequence_id": "seq-no-manual-checklist",
                "published": True,
                "will_publish": True,
            }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    manager.video_client.probe_live_view = fake_probe_live_view  # type: ignore[method-assign]
    manager.mqtt_client = FakeMqttClient()
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-publish",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.autoeject.gcode.3mf",
            "subtask_name": "specimen-autoeject",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["ready_to_publish"] is True
    assert payload["published"] is True
    assert payload["autoejection_operator_checklist"]["required"] is True
    assert payload["autoejection_operator_checklist"]["operator_managed"] is True
    assert payload["autoejection_operator_checklist"]["blockers"] == []
    assert payload["blockers"] == []


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
    prepare_calls: list[dict[str, object]] = []

    def fake_prepare(payload: dict) -> dict:
        prepare_calls.append(dict(payload))
        if payload.get("post_publish_observation"):
            return {
                "ok": True,
                "provider": "bambulab_x2d",
                "device_screen": {
                    "progress_panel": {
                        "gcode_state": "RUNNING",
                        "mc_percent": 1,
                        "subtask_name": "specimen-ready",
                    },
                    "actions": {"can_start_print": False, "can_prepare_start_command": False},
                },
                "preprint_gate": {
                    "state": "published_observed",
                    "blockers": [],
                    "checks": {"latest_report_fresh": True},
                },
            }
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
    assert published["timeout_sec"] == 180.0
    assert published["payload"]["print"]["command"] == "project_file"
    assert len(prepare_calls) == 2
    assert prepare_calls[1]["post_publish_observation"] is True
    assert payload["post_publish_observation"]["ok"] is True
    assert payload["post_publish_observation"]["device_screen"]["progress_panel"]["gcode_state"] == "RUNNING"
    assert payload["post_publish_observation"]["device_screen"]["progress_panel"]["mc_percent"] == 1
    assert payload["post_publish_observation"]["device_screen"]["progress_panel"]["subtask_name"] == "specimen-ready"
    assert payload["post_publish_status"] == "running"
    assert "secret-code" not in response.text


def test_printer_start_publish_distinguishes_publish_ack_from_not_started_state(tmp_path, monkeypatch) -> None:
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
        if payload.get("post_publish_observation"):
            return {
                "ok": True,
                "provider": "bambulab_x2d",
                "device_screen": {
                    "progress_panel": {
                        "gcode_state": "IDLE",
                        "mc_percent": 0,
                        "subtask_name": "specimen-ready",
                    },
                    "actions": {"can_start_print": True, "can_prepare_start_command": True},
                },
                "preprint_gate": {"state": "uploaded_not_started", "blockers": []},
            }
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
    assert payload["ok"] is False
    assert payload["published"] is True
    assert payload["post_publish_status"] == "idle"
    assert payload["failure_code"] == "BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED"
    assert payload["post_publish_failure_code"] == "BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED"


def test_printer_start_publish_locks_bed_clear_after_autoeject_publish_even_if_start_not_observed(tmp_path, monkeypatch) -> None:
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
                    "bambu": {"bed_clear_memory_path": str(tmp_path / "bambu_bed_clear.json")},
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
        if payload.get("post_publish_observation"):
            return {
                "ok": True,
                "provider": "bambulab_x2d",
                "device_screen": {
                    "progress_panel": {
                        "gcode_state": "IDLE",
                        "mc_percent": 0,
                        "subtask_name": "specimen-autoeject",
                    },
                    "actions": {"can_start_print": True, "can_prepare_start_command": True},
                },
                "preprint_gate": {"state": "uploaded_not_started", "blockers": []},
            }
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
    monkeypatch.setattr(
        app_main,
        "_bambu_autoejection_camera_gate",
        lambda manager, remote_path: {
            "required": True,
            "camera_frame_available": True,
            "camera_snapshot_path": str(tmp_path / "bed.jpg"),
            "blockers": [],
        },
    )
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-publish",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/token/specimen.autoeject.gcode.3mf",
            "subtask_name": "specimen-autoeject",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
            "door_or_front_path_clear": True,
            "ejection_ramp_or_bin_ready": True,
            "toolhead_cover_secured": True,
            "release_surface_confirmed": True,
            "release_surface_profile": "cool-plate-pla",
            "first_ejection_supervised": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["published"] is True
    assert payload["post_publish_status"] == "idle"
    assert payload["bed_clear"]["bed_clear_required"] is True
    assert payload["bed_clear"]["bed_clear_verified"] is False
    assert payload["bed_clear"]["blocking_code"] == "BAMBU_POST_EJECT_BED_NOT_CLEAR"


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
        "bed_clear",
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
    _write_minimal_bambu_gcode_3mf(artifact)
    source_manifest = Path(f"{artifact}.manifest.json")
    source_manifest.write_text(json.dumps({"schema": "test_sidecar_manifest.v1"}), encoding="utf-8")
    export_root = tmp_path / "exports"
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main, "BAMBU_HTTP_EXPORT_ROOT", export_root)
    monkeypatch.setattr(app_main, "_detect_printer_reachable_host", lambda printer_host: "192.168.50.10")

    async def fake_fetch_probe(artifact_url: str, *, expected_sha256: str, timeout_sec: float = 3.0) -> dict[str, object]:
        return {
            "ok": True,
            "status_code": 200,
            "size_bytes": artifact.stat().st_size,
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
    assert payload["artifact"]["manifest_path"]
    assert Path(payload["artifact"]["manifest_path"]).read_text(encoding="utf-8") == source_manifest.read_text(encoding="utf-8")
    assert payload["printer_fetch_ready"] is True
    assert payload["server_fetch_probe"]["ok"] is True
    assert payload["operator_actions"][0]["code"] == "BAMBU_HTTP_ARTIFACT_FETCH_VERIFIED"
    assert payload["start_command_draft"]["payload"]["print"]["url"] == payload["artifact_url"]
    assert payload["start_command_draft"]["will_publish"] is False
    assert "secret-code" not in response.text
    served_path = urlparse(payload["artifact_url"]).path
    served = client.get(served_path)
    assert served.status_code == 200
    assert served.content == artifact.read_bytes()


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
python3 - "$out/specimen.gcode.3mf" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1], "w") as archive:
    archive.writestr("Metadata/plate_1.gcode", "G90\\nG1 X10 Y10 Z10 F1200\\nM84\\n")
    archive.writestr("3D/3dmodel.model", "<model />")
PY
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

    def fake_probe_live_view(**kwargs) -> dict:
        assert kwargs["host"] == "192.0.2.42"
        assert kwargs["access_code"] == "secret-code"
        return {
            "ok": True,
            "status": "streaming_candidate",
            "stream_kind": "rtsps",
            "port": 322,
            "stream_url": "rtsps://192.0.2.42:322/streaming/live/1",
            "proxy_ready": True,
            "proxy_url": "/api/printer/video-stream.mjpeg",
            "snapshot_url": "/api/printer/video-frame.jpg",
            "blockers": [],
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
    manager.video_client.probe_live_view = fake_probe_live_view  # type: ignore[method-assign]
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
    assert payload["ok"] is True, json.dumps(
        {
            "failure_code": payload.get("failure_code"),
            "message": payload.get("message"),
            "slice_artifact": payload.get("slice_artifact"),
            "start_gate": payload.get("start_gate"),
            "spc_readiness": payload.get("spc_readiness"),
            "steps": payload.get("steps"),
        },
        ensure_ascii=False,
        indent=2,
    )
    assert payload["tool"] == "printer.bambu.prestart_check"
    assert payload["will_publish"] is False
    assert payload["published"] is False
    assert Path(payload["sliced_artifact_path"]).exists()
    assert payload["artifact_url"].startswith("http://192.168.50.10")
    assert payload["http_artifact_route"]["printer_fetch_ready"] is True
    assert payload["start_gate"]["ready_to_publish"] is True
    assert payload["video_status"]["snapshot_url"] == "/api/printer/video-frame.jpg"
    assert payload["device_screen"]["camera_panel"]["snapshot_url"] == "/api/printer/video-frame.jpg"
    assert payload["spc_readiness"]["autoejection_handoff"]["recommended_consumer_agent"] == "ManipulationAgent"
    assert payload["autoejection_handoff"]["routine_id"] == "robot-pickoff-v1"
    assert [step["id"] for step in payload["steps"]] == [
        "camera_status",
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
    _write_minimal_bambu_gcode_3mf(artifact)
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


def test_printer_http_artifact_route_blocks_missing_requested_plate_gcode(tmp_path, monkeypatch) -> None:
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
    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
        }
    )
    artifact = tmp_path / "wrong-plate.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(artifact, plate_id=2)
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main, "BAMBU_HTTP_EXPORT_ROOT", tmp_path / "exports")
    client = TestClient(app)

    response = client.post(
        "/api/printer/http-artifact-route",
        json={"artifact_path": str(artifact), "subtask_name": "wrong-plate", "plate_id": 1},
    )

    assert response.status_code == 400
    assert "BAMBU_PROJECT_FILE_PARAM_MISMATCH" in response.text
    assert not (tmp_path / "exports").exists()
    assert "secret-code" not in response.text


def test_printer_http_artifact_route_rejects_loopback_public_base_url(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "specimen.gcode.3mf"
    _write_minimal_bambu_gcode_3mf(artifact)
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
    assert payload["autoejection"]["recovery_to_robot_pickoff"] is True
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


def test_printer_autoejection_config_api_defaults_to_native_patch_without_robot_recovery_handoff(tmp_path, monkeypatch) -> None:
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
                        "provider": "bambu_gcode_patch",
                        "recovery_to_robot_pickoff": False,
                        "memory_path": str(tmp_path / "bambu_autoejection.json"),
                    },
                }
            }
        },
        repo_root=tmp_path,
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post("/api/printer/autoejection-config", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["autoejection"]["enabled"] is False
    assert payload["autoejection"]["provider"] == "bambu_gcode_patch"
    assert payload["autoejection"]["native_gcode_patch"] is True
    assert payload["autoejection"]["recovery_to_robot_pickoff"] is False
    assert payload["autoejection"]["can_run_test"] is False
    assert payload["autoejection"]["blockers"] == ["BAMBU_AUTOEJECTION_NOT_REQUESTED"]
    assert payload["autoejection"]["native_gcode_parameters"]["z_push_offset_mm"] == 15.0
    assert payload["autoejection"]["native_gcode_parameters"]["push_speed_mm_min"] == 6000
    assert payload["autoejection"]["native_gcode_parameters"]["sweep_speed_mm_min"] == 6000
    assert payload["autoejection"]["runtime_paths"]["standalone_endpoint"] == "/api/printer/autoejection-test"
    assert payload["autoejection"]["runtime_paths"]["standalone_transport"] == "project_file"
    assert payload["autoejection"]["runtime_paths"]["actual_print_transport"] == "project_file"
    assert payload["autoejection"]["runtime_paths"]["home_after_standalone"] is False


def test_printer_bambu_autoejection_patch_api_generates_native_gcode_artifact(tmp_path, monkeypatch) -> None:
    source = tmp_path / "specimen.gcode.3mf"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "Metadata/plate_1.gcode",
            "G90\nG1 X10 Y20 Z0.2 E0.02\nG1 X40 Y60 Z10.0 E1.20\nM104 S0\nM140 S0\nM84\n",
        )
        archive.writestr("3D/3dmodel.model", "<model />")
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
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/bambu-autoejection-patch",
        json={
            "artifact_path": str(source),
            "specimen_id": "specimen-cand-1",
            "position": "center",
            "plate_id": 1,
            "loop_index": 3,
            "run_id": "run-bambu-autoeject",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    patched_path = Path(payload["patched_artifact_path"])
    assert payload["ok"] is True
    assert payload["tool"] == "printer.bambu.autoejection_patch"
    assert payload["provider"] == "bambulab_x2d"
    assert payload["autoejection"]["provider"] == "bambu_gcode_patch"
    assert payload["handoff_required"] is False
    assert payload["plate_id"] == 1
    assert payload["loop_index"] == 3
    assert payload["validation"]["ok"] is True
    assert patched_path.exists()
    workspace_manifest = Path(payload["workspace_manifest_path"])
    assert workspace_manifest == tmp_path / "runs" / "run-bambu-autoeject" / "workspace" / "printer" / "bambu_autoejection_manifest.json"
    assert workspace_manifest.exists()
    assert json.loads(workspace_manifest.read_text(encoding="utf-8"))["patched_artifact_path"] == payload["patched_artifact_path"]
    assert json.loads(workspace_manifest.read_text(encoding="utf-8"))["loop_index"] == 3
    with zipfile.ZipFile(patched_path) as archive:
        assert "atr.bambu.autoejection.v1" in archive.read("Metadata/plate_1.gcode").decode("utf-8")


def test_printer_bambu_autoejection_patch_api_validate_only_does_not_write_artifact(tmp_path, monkeypatch) -> None:
    source = tmp_path / "specimen.gcode"
    source.write_text(
        "G90\nG1 X10 Y20 Z0.2 E0.02\nG1 X40 Y60 Z10.0 E1.20\nM104 S0\nM140 S0\nM84\n",
        encoding="utf-8",
    )
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
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/bambu-autoejection-patch",
        json={
            "artifact_path": str(source),
            "specimen_id": "specimen-cand-1",
            "position": "center",
            "plate_id": 1,
            "validate_only": True,
            "run_id": "run-bambu-validate-only",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tool"] == "printer.bambu.autoejection_validate"
    assert payload["status"] == "validated"
    assert payload["patched_artifact_path"] == ""
    assert payload["manifest_path"] == ""
    assert payload["workspace_manifest_path"] == ""
    assert payload["validation"]["ok"] is True
    assert not (tmp_path / "artifacts" / "bambu_autoejection").exists()
    assert not (tmp_path / "runs" / "run-bambu-validate-only").exists()


def test_printer_bambu_prestart_check_uses_native_autoejection_patched_artifact(tmp_path, monkeypatch) -> None:
    source = tmp_path / "specimen.gcode.3mf"
    plate_gcode = "G90\nG1 X10 Y20 Z0.2 E0.02\nG1 X40 Y60 Z10.0 E1.20\nM104 S0\nM140 S0\nM84\n"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", plate_gcode)
        archive.writestr("3D/3dmodel.model", "<model />")
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
    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload(
        {
            "host": "192.0.2.42",
            "serial": "SERIAL123",
            "auth": {"mode": "lan_access_code", "username": "bblp", "access_code": "secret-code"},
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
        }
    )
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})
    captured: dict[str, str] = {}

    def fake_prepare(payload: dict) -> dict:
        captured["artifact_url"] = str(payload.get("bambu_artifact_url") or "")
        assert "specimen.autoeject.gcode.3mf" in captured["artifact_url"]
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

    async def fake_fetch_probe(artifact_url: str, *, expected_sha256: str, timeout_sec: float = 3.0) -> dict[str, object]:
        assert "specimen.autoeject.gcode.3mf" in artifact_url
        return {
            "ok": True,
            "status_code": 200,
            "size_bytes": 100,
            "sha256": expected_sha256,
            "matches_expected_sha256": True,
            "failure_code": "",
            "message": "Artifact URL fetched successfully and sha256 matched.",
        }

    def fake_probe_live_view(**_kwargs) -> dict:
        return {
            "ok": True,
            "status": "streaming_candidate",
            "stream_kind": "rtsps",
            "proxy_ready": True,
            "proxy_url": "/api/printer/video-stream.mjpeg",
            "snapshot_url": "/api/printer/video-frame.jpg",
            "snapshot_bytes": b"\xff\xd8atr-camera-frame\xff\xd9",
            "blockers": [],
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    manager.video_client.probe_live_view = fake_probe_live_view  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main, "BAMBU_HTTP_EXPORT_ROOT", tmp_path / "exports")
    monkeypatch.setattr(app_main, "_detect_printer_reachable_host", lambda printer_host: "192.168.50.10")
    monkeypatch.setattr(app_main, "_probe_bambu_http_artifact_fetch", fake_fetch_probe)
    client = TestClient(app)

    response = client.post(
        "/api/printer/bambu-prestart-check",
        json={
            "artifact_path": str(source),
            "specimen_id": "specimen",
            "subtask_name": "specimen-prestart",
            "run_id": "run-prestart-autoeject",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
            "door_or_front_path_clear": True,
            "ejection_ramp_or_bin_ready": True,
            "toolhead_cover_secured": True,
            "release_surface_confirmed": True,
            "release_surface_profile": "cool-plate-pla",
            "first_ejection_supervised": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["autoejection_patch"]["ok"] is True
    assert payload["autoejection_patch"]["patched_artifact_path"].endswith("specimen.autoeject.gcode.3mf")
    workspace_manifest = Path(payload["autoejection_patch"]["workspace_manifest_path"])
    assert workspace_manifest == tmp_path / "runs" / "run-prestart-autoeject" / "workspace" / "printer" / "bambu_autoejection_manifest.json"
    assert workspace_manifest.exists()
    assert payload["http_artifact_route"]["artifact"]["source_path"].endswith("specimen.autoeject.gcode.3mf")
    assert payload["spc_readiness"]["autoejection"]["native_gcode_patch"] is True
    assert payload["autoejection_handoff"] == {}
    assert payload["video_status"]["snapshot_url"] == "/api/printer/video-frame.jpg"
    assert [step["id"] for step in payload["steps"]] == [
        "camera_status",
        "slice_artifact",
        "autoejection_patch",
        "http_artifact_route",
        "start_gate",
        "spc_readiness",
    ]
    assert captured["artifact_url"].startswith("http://192.168.50.10")


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


def test_configured_native_bambu_autoejection_test_returns_standalone_gcode_without_consumer(tmp_path, monkeypatch) -> None:
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
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/autoejection-test",
        json={"mode": "test", "position": "right", "start_immediately": True, "object_size_mm": [30, 30, 20]},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["provider"] == "bambulab_x2d"
    assert payload["status"] == "standalone_artifact_ready"
    assert payload["motion_started"] is False
    assert payload["requested_start_immediately"] is True
    assert payload["autoejection"]["provider"] == "bambu_gcode_patch"
    assert payload["consumer_readiness"]["ready"] is True
    assert payload["handoff"] == {}
    assert payload["standalone_artifact"]["tool"] == "printer.bambu.autoejection_standalone"
    assert payload["standalone_artifact"]["will_publish"] is False
    assert payload["standalone_artifact"]["start_enabled"] is False
    artifact_path = Path(payload["standalone_artifact"]["patched_artifact_path"])
    assert artifact_path.exists()
    assert "atr_position=right" in artifact_path.read_text(encoding="utf-8")


def test_live_native_bambu_standalone_autoejection_publishes_project_file_when_explicitly_armed(tmp_path, monkeypatch) -> None:
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
                        "provider": "bambu_gcode_patch",
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
            "serial": "SERIAL123",
            "printer_name": "x2d-test",
            "auth": {"username": "bblp", "access_code": "secret-code"},
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
        }
    )
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})
    manager.save_bed_clear_evidence(
        {
            "bed_clear_required": True,
            "bed_clear_verified": True,
            "verification_method": "operator",
        }
    )
    prepare_calls: list[dict[str, object]] = []

    async def fake_fetch_probe(artifact_url: str, *, expected_sha256: str, timeout_sec: float = 3.0) -> dict[str, object]:
        assert artifact_url.endswith(".autoeject.gcode.3mf")
        assert expected_sha256
        return {"ok": True, "status": "fetch_verified", "sha256": expected_sha256}

    def fake_prepare(payload: dict) -> dict:
        prepare_calls.append(dict(payload))
        return {
            "ok": True,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "upload": {"remote_path": "http://192.0.2.10/printer-artifacts/bambu/eject.gcode.3mf"},
            "print_result": {
                "ok": True,
                "will_publish": True,
                "published": True,
                "post_publish_status": {"status": "running"},
            },
            "device_screen": {
                "actions": {"can_start_print": False, "can_prepare_start_command": False},
                "connection": {"mqtt": "connected", "transfer": "connected", "video": "available"},
                "thermal": {"bed_current_c": 29, "bed_target_c": 0},
            },
            "preprint_gate": {
                "state": "blocked",
                "blockers": ["BAMBU_FTPS_TOO_MANY_CONNECTIONS"],
                "checks": {
                    "mqtt_authenticated_or_virtual": True,
                    "latest_report_fresh": True,
                    "printer_safe_state_verified": True,
                    "storage_transfer_path_verified": False,
                    "start_command_draft_prepared": False,
                },
            },
            "operator_actions": [],
        }

    def fake_video_status(_payload: dict) -> dict:
        return {
            "ok": True,
            "video_status": {
                "ok": True,
                "snapshot_url": "http://192.0.2.10/bambu/snapshot.jpg",
                "snapshot_bytes": b"\xff\xd8\xff\xe0test",
            },
            "device_screen": {"camera_panel": {"snapshot_url": "http://192.0.2.10/bambu/snapshot.jpg"}},
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    manager.video_status = fake_video_status  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(app_main, "_probe_bambu_http_artifact_fetch", fake_fetch_probe)
    client = TestClient(app)
    session_id = "autoeject-live-gui-session"
    client.get(f"/api/planning/session?session_id={session_id}")

    response = client.post(
        "/api/printer/autoejection-test",
        json={
            "mode": "live",
            "position": "center",
            "start_immediately": True,
            "object_size_mm": [30, 30, 20],
            "public_base_url": "http://192.168.50.10:18080",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
            "door_or_front_path_clear": True,
            "ejection_ramp_or_bin_ready": True,
            "toolhead_cover_secured": True,
            "release_surface_confirmed": True,
            "release_surface_profile": "cool-plate-pla",
            "first_ejection_supervised": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "standalone_motion_started"
    assert payload["motion_started"] is True
    assert payload["published"] is True
    assert payload["will_publish"] is True
    assert payload["remote_path"] == "http://192.0.2.10/printer-artifacts/bambu/eject.gcode.3mf"
    assert len(prepare_calls) == 1
    assert prepare_calls[0]["print"]["start_immediately"] is True
    assert prepare_calls[0]["print"]["physical_intent"] is True
    assert str(prepare_calls[0]["bambu_artifact_path"]).endswith(".autoeject.gcode.3mf")
    session = client.get(f"/api/planning/session?session_id={session_id}").json()
    assert any(
        message.get("role") == "printer_ai"
        and "autoejection" in json.dumps(message, ensure_ascii=False).lower()
        and message.get("specimen", {}).get("autoejection_handoff", {}).get("motion_started") is True
        for message in session["messages"]
    )


def test_live_native_bambu_standalone_autoejection_uses_project_file_artifact_with_cooldown_tail(tmp_path, monkeypatch) -> None:
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
                        "provider": "bambu_gcode_patch",
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
            "serial": "SERIAL123",
            "printer_name": "x2d-test",
            "auth": {"username": "bblp", "access_code": "secret-code"},
            "lan_mode_confirmed": True,
            "developer_mode_confirmed": True,
        }
    )
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})
    manager.save_bed_clear_evidence(
        {
            "bed_clear_required": True,
            "bed_clear_verified": True,
            "verification_method": "operator",
        }
    )
    prepare_calls: list[dict[str, object]] = []

    def fake_prepare(payload: dict) -> dict:
        prepare_calls.append(dict(payload))
        return {
            "ok": True,
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
            "upload": {"remote_path": "file:///cache/bambu-eject-center.autoeject.gcode.3mf"},
            "print_result": {
                "ok": True,
                "will_publish": True,
                "published": True,
                "post_publish_status": {"status": "running"},
            },
            "device_screen": {
                "actions": {"can_start_print": False, "can_prepare_start_command": False},
                "connection": {"mqtt": "connected", "transfer": "connected", "video": "available"},
                "thermal": {"bed_current_c": 39, "bed_target_c": 0},
            },
            "preprint_gate": {
                "state": "blocked",
                "blockers": ["BAMBU_FTPS_TOO_MANY_CONNECTIONS"],
                "checks": {
                    "mqtt_authenticated_or_virtual": True,
                    "latest_report_fresh": True,
                    "printer_safe_state_verified": True,
                    "storage_transfer_path_verified": False,
                    "start_command_draft_prepared": False,
                },
            },
            "operator_actions": [],
        }

    def fake_video_status(_payload: dict) -> dict:
        return {
            "ok": True,
            "video_status": {
                "ok": True,
                "snapshot_url": "http://192.0.2.10/bambu/snapshot.jpg",
                "snapshot_bytes": b"\xff\xd8\xff\xe0test",
            },
            "device_screen": {"camera_panel": {"snapshot_url": "http://192.0.2.10/bambu/snapshot.jpg"}},
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    manager.video_status = fake_video_status  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/autoejection-test",
        json={
            "mode": "live",
            "position": "center",
            "start_immediately": True,
            "object_size_mm": [30, 30, 12],
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
            "door_or_front_path_clear": True,
            "ejection_ramp_or_bin_ready": True,
            "toolhead_cover_secured": True,
            "release_surface_confirmed": True,
            "release_surface_profile": "cool-plate-pla",
            "first_ejection_supervised": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "standalone_motion_started"
    assert len(prepare_calls) == 1
    artifact_path = Path(str(prepare_calls[0]["bambu_artifact_path"]))
    assert artifact_path.exists()
    with zipfile.ZipFile(artifact_path) as archive:
        plate_gcode = archive.read("Metadata/plate_1.gcode").decode("utf-8")
    assert "M190 R40" in plate_gcode
    assert "G28 ; atr_autoejection_home_all_axes" not in plate_gcode


def test_configured_native_bambu_sweep_test_api_returns_full_bed_sweep_artifact(tmp_path, monkeypatch) -> None:
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
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch"})
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/bambu-autoejection-sweep-test",
        json={"mode": "test", "position": "center", "start_immediately": False, "object_size_mm": [30, 30, 20]},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["tool"] == "printer.bambu.autoejection_sweep_test"
    assert payload["provider"] == "bambulab_x2d"
    assert payload["motion_started"] is False
    assert payload["requested_start_immediately"] is False
    assert payload["standalone_artifact"]["tool"] == "printer.bambu.autoejection_sweep_test"
    artifact_path = Path(payload["standalone_artifact"]["patched_artifact_path"])
    assert artifact_path.exists()
    gcode = artifact_path.read_text(encoding="utf-8")
    assert "atr_full_bed_sweep_enabled=true" in gcode
    assert "atr_full_bed_sweep_pass=7" in gcode


def test_printer_bambu_bed_clear_evidence_api_persists_operator_gate(tmp_path, monkeypatch) -> None:
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

    blocked = client.post(
        "/api/printer/bed-clear",
        json={
            "bed_clear_required": True,
            "bed_clear_verified": False,
            "verification_method": "operator",
            "remote_path": "http://192.168.50.10:7860/printer-artifacts/bambu/token/specimen.autoeject.gcode.3mf",
            "subtask_name": "spc-bed-clear",
            "source_artifact_path": str(tmp_path / "source.gcode.3mf"),
            "source_artifact_sha256": "source-sha",
            "patched_artifact_path": str(tmp_path / "specimen.autoeject.gcode.3mf"),
            "patched_artifact_sha256": "patched-sha",
            "manifest_path": str(tmp_path / "specimen.autoeject.gcode.3mf.manifest.json"),
            "publish_sequence_id": "seq-bed-clear",
            "publish_topic": "device/SERIAL/request",
            "post_publish_status": "running",
        },
    )

    assert blocked.status_code == 200
    blocked_payload = blocked.json()
    assert blocked_payload["ok"] is True
    assert blocked_payload["bed_clear"]["bed_clear_required"] is True
    assert blocked_payload["bed_clear"]["bed_clear_verified"] is False
    assert blocked_payload["bed_clear"]["blocking_code"] == "BAMBU_POST_EJECT_BED_NOT_CLEAR"
    assert blocked_payload["bed_clear"]["patched_artifact_sha256"] == "patched-sha"

    verified = client.post(
        "/api/printer/bed-clear",
        json={"bed_clear_required": True, "bed_clear_verified": True, "verification_method": "operator"},
    ).json()
    assert verified["bed_clear"]["bed_clear_verified"] is True
    assert verified["bed_clear"]["blocking_code"] == ""
    assert verified["bed_clear"]["remote_path"].endswith("specimen.autoeject.gcode.3mf")
    assert verified["bed_clear"]["subtask_name"] == "spc-bed-clear"
    assert verified["bed_clear"]["source_artifact_sha256"] == "source-sha"
    assert verified["bed_clear"]["patched_artifact_sha256"] == "patched-sha"
    assert verified["bed_clear"]["publish_sequence_id"] == "seq-bed-clear"
    assert verified["bed_clear"]["post_publish_status"] == "running"

    loaded = client.get("/api/printer/bed-clear").json()
    assert loaded["bed_clear"]["bed_clear_verified"] is True
    assert loaded["settings_path"].endswith("bambu_bed_clear_evidence.json")
    assert loaded["bed_clear"]["patched_artifact_sha256"] == "patched-sha"


def test_printer_spc_readiness_blocks_when_bambu_bed_clear_is_required(tmp_path, monkeypatch) -> None:
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
    manager.save_bed_clear_evidence(
        {
            "bed_clear_required": True,
            "bed_clear_verified": False,
            "verification_method": "operator",
            "camera_snapshot_path": str(tmp_path / "bed_still_occupied.jpg"),
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
    client = TestClient(app)

    response = client.post(
        "/api/printer/spc-readiness",
        json={
            "mode": "live",
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/specimen.autoeject.gcode.3mf",
            "subtask_name": "spc-bed-clear",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready_for_live_print"] is False
    assert payload["technical_ready_for_start"] is False
    assert "BAMBU_POST_EJECT_BED_NOT_CLEAR" in payload["blockers"]
    assert payload["bed_clear"]["blocking_code"] == "BAMBU_POST_EJECT_BED_NOT_CLEAR"
    bed_clear_level = next(item for item in payload["readiness_levels"] if item["id"] == "bed_clear")
    assert bed_clear_level["status"] == "blocked"
    assert "BAMBU_POST_EJECT_BED_NOT_CLEAR" in bed_clear_level["blocking_codes"]


def test_printer_start_publish_locks_bed_clear_after_autoeject_artifact_success(tmp_path, monkeypatch) -> None:
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

    def fake_prepare(payload: dict) -> dict:
        if payload.get("post_publish_observation"):
            return {
                "ok": True,
                "provider": "bambulab_x2d",
                "selected_printer": manager._selected_printer_payload(manager.config.default_profile, "default_profile"),
                "device_screen": {
                    "schema": "printer_device_screen.v1",
                    "connection": {"mqtt": "connected", "transfer": "connected", "video": "available"},
                    "actions": {"can_upload": False, "can_start_print": False, "can_prepare_start_command": False},
                    "progress_panel": {"gcode_state": "RUNNING", "mc_percent": 1, "subtask_name": "spc-bed-clear"},
                },
                "preprint_gate": {
                    "state": "published_observed",
                    "technical_ready_for_start": False,
                    "approval_ready_for_start": True,
                    "ready_for_live_print": False,
                    "blockers": [],
                    "checks": {"latest_report_fresh": True},
                },
                "operator_actions": [],
            }
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

    class FakeMqttClient:
        def publish_project_file_command(self, **kwargs):
            return {"ok": True, "sequence_id": "seq-test", "published": True, "topic": kwargs.get("topic")}

    def fake_probe_live_view(**_kwargs) -> dict:
        return {
            "ok": True,
            "status": "streaming_candidate",
            "stream_kind": "rtsps",
            "proxy_ready": True,
            "proxy_url": "/api/printer/video-stream.mjpeg",
            "snapshot_url": "/api/printer/video-frame.jpg",
            "snapshot_bytes": b"\xff\xd8atr-camera-frame\xff\xd9",
            "blockers": [],
        }

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    manager.video_client.probe_live_view = fake_probe_live_view  # type: ignore[method-assign]
    manager.mqtt_client = FakeMqttClient()  # type: ignore[assignment]
    export_root = tmp_path / "exports"
    monkeypatch.setattr(app_main, "BAMBU_HTTP_EXPORT_ROOT", export_root)
    export_path = export_root / "testtoken01" / "specimen.autoeject.gcode.3mf"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes(b"patched-auto-ejection-artifact")
    source_path = tmp_path / "source.gcode.3mf"
    source_path.write_bytes(b"source-artifact")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    patched_sha = hashlib.sha256(export_path.read_bytes()).hexdigest()
    manifest_path = Path(f"{export_path}.manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "bambu_autoejection_artifact_manifest.v1",
                "source_path": str(source_path),
                "patched_artifact_path": str(export_path),
                "source_sha256": source_sha,
                "patched_sha256": patched_sha,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-publish",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/testtoken01/specimen.autoeject.gcode.3mf",
            "subtask_name": "spc-bed-clear",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
            "door_or_front_path_clear": True,
            "ejection_ramp_or_bin_ready": True,
            "toolhead_cover_secured": True,
            "release_surface_confirmed": True,
            "release_surface_profile": "cool-plate-pla",
            "first_ejection_supervised": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["published"] is True
    assert payload["bed_clear"]["bed_clear_required"] is True
    assert payload["bed_clear"]["bed_clear_verified"] is False
    assert payload["bed_clear"]["remote_path"].endswith("/testtoken01/specimen.autoeject.gcode.3mf")
    assert payload["bed_clear"]["subtask_name"] == "spc-bed-clear"
    assert payload["bed_clear"]["source_artifact_path"] == str(source_path)
    assert payload["bed_clear"]["source_artifact_sha256"] == source_sha
    assert payload["bed_clear"]["patched_artifact_path"] == str(export_path)
    assert payload["bed_clear"]["patched_artifact_sha256"] == patched_sha
    assert payload["bed_clear"]["manifest_path"] == str(manifest_path)
    assert payload["bed_clear"]["publish_sequence_id"] == "seq-test"
    assert payload["bed_clear"]["publish_topic"]
    assert payload["bed_clear"]["post_publish_status"] == "running"
    assert payload["bed_clear"]["camera_snapshot_path"].endswith(".jpg")
    assert "artifacts/bambu_camera_evidence/" in payload["bed_clear"]["camera_snapshot_path"]
    assert Path(payload["bed_clear"]["camera_snapshot_path"]).read_bytes() == b"\xff\xd8atr-camera-frame\xff\xd9"
    assert payload["bed_clear"]["blocking_code"] == "BAMBU_POST_EJECT_BED_NOT_CLEAR"
    loaded = client.get("/api/printer/bed-clear").json()
    assert loaded["bed_clear"]["blocking_code"] == "BAMBU_POST_EJECT_BED_NOT_CLEAR"
    assert loaded["bed_clear"]["camera_snapshot_path"] == payload["bed_clear"]["camera_snapshot_path"]
    assert loaded["bed_clear"]["patched_artifact_sha256"] == patched_sha


def test_printer_start_gate_blocks_when_previous_bambu_bed_clear_is_unverified(tmp_path, monkeypatch) -> None:
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
    manager.save_bed_clear_evidence({"bed_clear_required": True, "bed_clear_verified": False})

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

    manager.prepare = fake_prepare  # type: ignore[method-assign]
    monkeypatch.setattr(app_main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(app)

    response = client.post(
        "/api/printer/start-gate",
        json={
            "remote_path": "http://192.168.50.10:18080/printer-artifacts/bambu/specimen.gcode.3mf",
            "subtask_name": "blocked-by-bed-clear",
            "operator_confirmed": True,
            "guardian_approved": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready_to_publish"] is False
    assert payload["bed_clear"]["blocking_code"] == "BAMBU_POST_EJECT_BED_NOT_CLEAR"
    assert "BAMBU_POST_EJECT_BED_NOT_CLEAR" in payload["blockers"]
