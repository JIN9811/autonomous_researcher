"""Selection must be driven by saved order, matching material and fresh AMS evidence."""
from datetime import datetime, timezone, timedelta
import json
import zipfile
from types import SimpleNamespace

import pytest


def report(*, seconds_old=0):
    return {"received_at": (datetime.now(timezone.utc) - timedelta(seconds=seconds_old)).isoformat(),
        "materials": {"tray_exist_bits": "e", "slots": [
            {"ams_id": "0", "tray_id": "0", "tray_type": "PLA", "remain_percent": 99},
            {"ams_id": "0", "tray_id": "1", "tray_type": "PLA", "remain_percent": 92},
            {"ams_id": "0", "tray_id": "2", "tray_type": "PLA", "remain_percent": 13},
            {"ams_id": "0", "tray_id": "3", "tray_type": "PETG", "remain_percent": 50},
        ]}}


def test_priority_save_reload_preserves_order(tmp_path):
    from utils import bambu_material_priority as priority
    path = tmp_path / "priority.json"
    value = {"enabled": True, "slots": ["0:2", "0:1"]}
    priority.save_priority(value, path=path)
    assert priority.load_priority(path=path) == value


def test_priority_selects_low_remaining_spool_if_ranked_first():
    from utils import bambu_material_priority as priority
    result = priority.select_material({"enabled": True, "slots": ["0:2", "0:1"]}, report(), "PLA")
    assert result["ok"]
    assert result["slot_id"] == "0:2"
    assert result["ams_mapping"] == [2]
    assert result["use_ams"] is True


def test_empty_wrong_material_and_exhausted_slots_are_skipped():
    from utils import bambu_material_priority as priority
    data = report()
    data["materials"]["slots"][2]["remain_percent"] = 0
    result = priority.select_material({"enabled": True, "slots": ["0:0", "0:3", "0:2", "0:1"]}, data, "PLA")
    assert result["slot_id"] == "0:1"
    assert len(result["skipped"]) == 3


@pytest.mark.parametrize("change", ["stale", "no_presence", "different_material", "no_slots"])
def test_missing_or_incompatible_evidence_blocks_instead_of_external_spool(change):
    from utils import bambu_material_priority as priority
    data = report(seconds_old=60 if change == "stale" else 0)
    if change == "no_presence":
        data["materials"].pop("tray_exist_bits")
    if change == "no_slots":
        data["materials"]["slots"] = []
    result = priority.select_material({"enabled": True, "slots": ["0:2", "0:1"]}, data, "ABS" if change == "different_material" else "PLA")
    assert not result["ok"]
    assert not result.get("ams_mapping")


@pytest.mark.parametrize("slots", [["0:1", "0:1"], ["128:0"], ["0:4"], []])
def test_invalid_enabled_priority_does_not_replace_saved_file(tmp_path, slots):
    from utils import bambu_material_priority as priority
    path = tmp_path / "priority.json"
    priority.save_priority({"enabled": False, "slots": []}, path=path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        priority.save_priority({"enabled": True, "slots": slots}, path=path)
    assert path.read_bytes() == before


def test_legacy_disabled_selection_needs_no_report():
    from utils import bambu_material_priority as priority
    assert priority.select_material({"enabled": False, "slots": []}, {}, "PLA") == {"ok": True, "enabled": False}


def test_single_filament_mapping_generates_correct_project_file_command():
    from device_bridges.bambu_bridge import build_bambu_project_file_command_draft
    draft = build_bambu_project_file_command_draft(serial="fixture", remote_path="cache/cube.gcode.3mf", use_ams=True, ams_mapping=[2])
    assert draft["ok"]
    assert draft["payload"]["print"]["ams_mapping"] == [2]
    assert not draft["will_publish"]


def test_mapping_follows_used_filament_index_in_artifact(tmp_path):
    from utils import bambu_material_priority as priority
    path = tmp_path / "part.gcode.3mf"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", "; filament: 3\n; filament_type = PETG;ABS;PLA\nG1 X10 E1\n")
    selected = priority.select_material({"enabled": True, "slots": ["0:2"]}, report(), "PLA")
    bound = priority.bind_artifact(selected, path)
    assert bound["ok"]
    assert bound["ams_mapping"] == [-1, -1, 2]


def test_material_mismatch_in_file_blocks_even_when_gui_says_pla(tmp_path):
    from utils import bambu_material_priority as priority
    path = tmp_path / "part.gcode.3mf"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", "; filament: 1\n; filament_type = PETG\nG1 X10 E1\n")
    selected = priority.select_material({"enabled": True, "slots": ["0:2"]}, report(), "PLA")
    assert not priority.bind_artifact(selected, path)["ok"]


def test_bridge_resolver_uses_experiment_material_and_saved_order(tmp_path):
    from utils import bambu_material_priority as priority
    from device_bridges.bambu_bridge import PrinterDeviceBridgeManager
    priority.save_priority({"enabled": True, "slots": ["0:3", "0:2", "0:1"]}, path=priority.priority_path(tmp_path))
    manager = object.__new__(PrinterDeviceBridgeManager)
    manager.repo_root = tmp_path
    manager.config = SimpleNamespace(mode="live")
    result = manager.resolve_material_selection({"experiment_spec": {"material": "PLA"}}, normalized_report=report())
    assert result["slot_id"] == "0:2"
    still_required = manager.resolve_material_selection({"runtime_mode": "live", "health_only": "false",
        "print": {"use_ejection_only_project_file": True}}, normalized_report=report())
    assert still_required["slot_id"] == "0:2"


def test_missing_local_artifact_blocks_cleanly():
    from utils import bambu_material_priority as priority
    result = priority.bind_artifact({"enabled": True, "ok": True}, None)
    assert not result["ok"]
    assert result["failure_code"] == "BAMBU_MATERIAL_ARTIFACT_EVIDENCE_REQUIRED"


def test_compact_extrusion_cannot_bypass_material_verification(tmp_path):
    from utils import bambu_material_priority as priority
    path = tmp_path / "part.gcode.3mf"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", "G1X10E1\n")
    assert not priority.bind_artifact({"enabled": True, "ok": True}, path)["ok"]


def test_negative_absolute_extrusion_still_requires_matching_material(tmp_path):
    from utils import bambu_material_priority as priority
    path = tmp_path / "part.gcode.3mf"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", "; filament: 1\n; filament_type = PETG\nM82\nG92 E-50\nG1 X10 E-49\n")
    selected = priority.select_material({"enabled": True, "slots": ["0:2"]}, report(), "PLA")
    assert priority.bind_artifact(selected, path)["failure_code"] == "BAMBU_MATERIAL_ARTIFACT_MISMATCH"
