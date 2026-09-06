"""Priority persistence is independent of the Print Defaults form."""
from types import SimpleNamespace
from fastapi.testclient import TestClient
from datetime import datetime, timezone
import hashlib
import zipfile
import pytest


@pytest.fixture
def printer(tmp_path, monkeypatch):
    from device_bridges.bambu_bridge import PrinterDeviceBridgeManager, BambuConnectionMemory
    from utils.bambu_material_priority import save_priority, priority_path
    manager = PrinterDeviceBridgeManager.from_devices_config({"devices": {"printer": {
        "default_profile_id": "fixture", "profiles": {"fixture": {"provider": "bambulab_x2d",
            "connection_memory_path": str(tmp_path / "connection.json")}},
    }}}, repo_root=tmp_path)
    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload({
        "host": "192.0.2.42", "serial": "fixture", "auth": {"access_code": "fixture-only", "username": "bblp", "mode": "lan_access_code"}})
    raw = {"print": {"gcode_state": "IDLE", "ams": {"tray_exist_bits": "6", "ams": [{"id": "0", "tray": [
        {"id": "1", "tray_type": "PLA", "remain": 92}, {"id": "2", "tray_type": "PLA", "remain": 13}]}]}}}
    uploads = []
    monkeypatch.setattr(manager.live_probe, "probe_tls_port", lambda *args: {"ok": True})
    monkeypatch.setattr(manager.mqtt_client, "read_snapshot", lambda **kwargs: {
        "ok": True, "report": raw, "received_at": datetime.now(timezone.utc).isoformat()})
    monkeypatch.setattr(manager.ftps_client, "probe_storage", lambda **kwargs: {"ok": True, "storage": "ftps"})
    def upload(**kwargs):
        uploads.append(kwargs)
        return {"ok": True, "remote_path": "part.gcode.3mf", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size}
    monkeypatch.setattr(manager.ftps_client, "upload_file", upload)
    monkeypatch.setattr(manager.mqtt_client, "publish_project_file_command", lambda **kwargs: pytest.fail("No publish allowed"))
    save_priority({"enabled": True, "slots": ["0:2", "0:1"]}, path=priority_path(tmp_path))
    path = tmp_path / "artifacts/bambu_http_exports/fixture123/part.gcode.3mf"
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", "; filament: 1\n; filament_type = PLA\nG90\nM83\nG1 X10 Y10 E1\n")
    return manager, path, raw, uploads


def test_real_prepare_and_gui_draft_choose_same_saved_slot_without_publish(printer, monkeypatch):
    from app import main
    manager, path, _raw, uploads = printer
    result = manager.prepare({"runtime_mode": "live", "material": "PLA", "bambu_artifact_path": str(path)})
    assert result["ok"], result
    assert result["material_selection"]["slot_id"] == "0:2"
    assert result["project_file_draft"]["payload"]["print"]["ams_mapping"] == [2]
    assert not result["project_file_draft"]["will_publish"]
    assert len(uploads) == 1
    monkeypatch.setattr(main, "_printer_bridge_manager", lambda: manager)
    remote_url = "http://192.0.2.10:7860/printer-artifacts/bambu/fixture123/part.gcode.3mf"
    draft = TestClient(main.app).post("/api/printer/start-command-draft", json={"remote_path": remote_url, "material": "PLA"}).json()
    assert draft["ok"], draft
    assert draft["payload"]["print"]["ams_mapping"] == [2]
    assert draft["material_selection"]["artifact_material_verified"]
    assert draft["payload"]["print"]["url"] == remote_url
    assert not draft["will_publish"]


def test_no_compatible_material_blocks_before_upload(printer):
    manager, path, raw, uploads = printer
    raw["print"]["ams"]["tray_exist_bits"] = "0"
    result = manager.prepare({"runtime_mode": "live", "material": "PLA", "bambu_artifact_path": str(path)})
    assert not result["ok"]
    assert result["failure_code"] == "BAMBU_MATERIAL_NO_COMPATIBLE_SLOT"
    assert uploads == []


def test_genuine_motion_only_artifact_does_not_need_loaded_material(printer):
    manager, path, raw, _uploads = printer
    raw["print"]["ams"]["tray_exist_bits"] = "0"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", "G90\nG1 X10 Y10 Z1 F1200\n")
    result = manager.prepare({"runtime_mode": "live", "bambu_artifact_path": str(path)})
    assert result["ok"], result
    assert result["project_file_draft"]["payload"]["print"]["use_ams"] is False


def test_virtual_readiness_draft_does_not_read_mqtt(printer, monkeypatch):
    from app import main
    manager, path, _raw, _uploads = printer
    monkeypatch.setattr(manager.mqtt_client, "read_snapshot", lambda **kwargs: pytest.fail("Virtual readiness must not contact hardware"))
    req = main.PrinterSpcReadinessRequest(mode="test", remote_path=str(path))
    draft = main._priority_project_file_draft(manager, req, serial="fixture", remote_path=str(path))
    assert draft["ok"]
    assert draft["material_selection"]["status"] == "deferred_virtual"


def test_changed_slot_between_gui_draft_and_prepare_blocks_start():
    from app.main import _bambu_start_gate_blockers
    blockers, _checks = _bambu_start_gate_blockers(draft={"ok": True, "material_selection": {
        "ok": True, "enabled": True, "artifact_material_verified": True, "slot_id": "0:2", "ams_mapping": [2]}},
        prepare_result={"material_selection": {"ok": True, "enabled": True, "artifact_material_verified": True,
            "slot_id": "0:1", "ams_mapping": [1]}}, operator_confirmed=True, guardian_approved=True, dry_run=False)
    assert "BAMBU_MATERIAL_SELECTION_CHANGED" in blockers


def test_priority_api_saves_order_and_rejects_duplicates_without_touching_profile(tmp_path, monkeypatch):
    from app import main
    manager = SimpleNamespace(repo_root=tmp_path, fleet_selection=lambda: (SimpleNamespace(provider="bambulab_x2d"), "fixture"))
    monkeypatch.setattr(main, "_printer_bridge_manager", lambda: manager)
    client = TestClient(main.app)
    value = {"enabled": True, "slots": ["0:2", "0:1"]}
    saved = client.post("/api/printer/material-priority", json=value)
    assert saved.status_code == 200
    assert saved.json()["priority"] == value
    assert client.get("/api/printer/material-priority").json()["priority"] == value
    assert client.post("/api/printer/material-priority", json={"enabled": True, "slots": ["0:1", "0:1"]}).status_code == 422
    assert client.get("/api/printer/material-priority").json()["priority"] == value
    assert not (tmp_path / "memory/prusa_print_profile.json").exists()
