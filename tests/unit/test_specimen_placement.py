"""Operator placement survives persistence and controls pre-slice geometry safely."""
from pathlib import Path
import os
import json
import zipfile
from types import SimpleNamespace

import pytest
import trimesh

from utils.printer_profile import save_prusa_print_profile, load_prusa_print_profile
from device_bridges.bambu_bridge import BambuSlicerConfig, BambuStudioSlicerRunner


@pytest.mark.parametrize("placement, expected_ok", [
    ({"mode": "auto"}, True),
    ({"mode": "bed_center"}, True),
    ({"mode": "custom", "center_x_mm": 110, "center_y_mm": 145}, True),
    ({"mode": "custom", "center_x_mm": 25, "center_y_mm": 128}, False),
])
def test_placement_result_serializes_at_experiment_boundary(tmp_path, monkeypatch, placement, expected_ok):
    from experiments.schemas import ExperimentEvaluationResult

    center = (128, 128) if placement["mode"] == "bed_center" else (110, 145)
    runner, source, calls = runner_fixture(tmp_path, monkeypatch, output_center=center)
    bridge_result = runner.slice(source, specimen_placement=placement)
    result = ExperimentEvaluationResult(
        ok=bridge_result["ok"], experiment_id="placement-fixture", evaluation_id="placement-evaluation",
        objective={}, candidate_id="cube", mode="live", bridge="printer",
        status=bridge_result["status"], bridge_result=bridge_result,
    ).model_dump(mode="json")
    assert result["ok"] is expected_ok
    assert json.loads(json.dumps(result))["bridge_result"]["ok"] is expected_ok
    if not expected_ok:
        assert result["bridge_result"]["failure_code"] == "SPECIMEN_PLACEMENT_OUT_OF_BOUNDS"
        assert calls == []
    elif placement["mode"] != "auto":
        assert result["bridge_result"]["placement_validation"]["actual_center_mm"] == list(center)


def test_saved_placement_survives_reload_and_legacy_defaults(tmp_path):
    path = tmp_path / "profile.json"
    placement = {"mode": "custom", "center_x_mm": 110.0, "center_y_mm": 145.0}
    save_prusa_print_profile({"specimen_placement": placement}, path=path)
    assert load_prusa_print_profile(path)["specimen_placement"] == placement
    assert load_prusa_print_profile(tmp_path / "absent.json")["specimen_placement"]["mode"] == "auto"


@pytest.mark.parametrize("placement", [
    {"mode": "invalid"}, {"mode": "custom", "center_x_mm": float("nan")},
    {"mode": "custom", "center_y_mm": 300}, {"mode": "custom", "center_x_mm": -1},
])
def test_invalid_saved_coordinates_do_not_silently_fall_back(tmp_path, placement):
    with pytest.raises(ValueError):
        save_prusa_print_profile({"specimen_placement": placement}, path=tmp_path / "profile.json")
    assert not (tmp_path / "profile.json").exists()


def runner_fixture(tmp_path, monkeypatch, *, output_center=(110, 145)):
    source = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[30, 30, 10]).export(source)
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(enabled=True, executable_path="/bin/true",
        output_dir=str(tmp_path / "sliced"), auto_no_skirt_profile=False), repo_root=tmp_path)
    calls = []

    def slicer(command, **kwargs):
        calls.append(command)
        out = Path(command[command.index("--outputdir") + 1])
        cx, cy = output_center
        gcode = f"G90\nM83\nG1 Z0.2\nG1 X{cx-15} Y{cy-15}\nG1 X{cx+15} Y{cy-15} E1\nG1 X{cx+15} Y{cy+15} E1\nG1 X{cx-15} Y{cy+15} E1\nG1 Z10\n"
        with zipfile.ZipFile(out / "cube.gcode.3mf", "w") as archive:
            archive.writestr("Metadata/plate_1.gcode", gcode)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("device_bridges.bambu_bridge.subprocess.run", slicer)
    return runner, source, calls


def test_custom_center_reaches_cli_without_automatic_rearrangement(tmp_path, monkeypatch):
    runner, source, calls = runner_fixture(tmp_path, monkeypatch)
    result = runner.slice(source, specimen_placement={"mode": "custom", "center_x_mm": 110, "center_y_mm": 145})
    assert result["ok"], result
    command = calls[0]
    assert command[command.index("--arrange") + 1] == "0"
    assembly = json.loads(Path(command[command.index("--load-assemble-list") + 1]).read_text())
    obj = assembly["plates"][0]["objects"][0]
    assert obj["pos_x"] == [110]
    assert obj["pos_y"] == [145]
    assert assembly["plates"][0]["need_arrange"] is False
    assert "--center" not in command
    assert result["placement_validation"]["ok"]
    assert result["placement_validation"]["actual_center_mm"] == [110.0, 145.0]
    assert result["will_publish"] is False


def test_bed_center_is_physical_bed_not_dual_extruder_center(tmp_path, monkeypatch):
    runner, source, calls = runner_fixture(tmp_path, monkeypatch, output_center=(128, 128))
    result = runner.slice(source, specimen_placement={"mode": "bed_center"})
    assert result["ok"], result
    assembly = json.loads(Path(calls[0][calls[0].index("--load-assemble-list") + 1]).read_text())
    assert assembly["plates"][0]["objects"][0]["pos_x"] == [128]
    assert assembly["plates"][0]["objects"][0]["pos_y"] == [128]


def test_object_extent_outside_printable_area_blocks_before_cli(tmp_path, monkeypatch):
    runner, source, calls = runner_fixture(tmp_path, monkeypatch)
    result = runner.slice(source, specimen_placement={"mode": "custom", "center_x_mm": 25, "center_y_mm": 128})
    assert result["ok"] is False
    assert result["failure_code"] == "SPECIMEN_PLACEMENT_OUT_OF_BOUNDS"
    assert calls == []


@pytest.mark.parametrize("placement", [{"mode": "auto"}, {"mode": "bed_center"},
    {"mode": "custom", "center_x_mm": 110, "center_y_mm": 145}])
@pytest.mark.skipif(os.environ.get("ATR_TEST_REAL_SLICER") != "1", reason="Explicit local CLI opt-in; never publishes")
def test_installed_slicer_generates_requested_center_without_hardware(tmp_path, placement):
    root = Path(__file__).resolve().parents[2]
    source = tmp_path / "placement-cube.stl"
    trimesh.creation.box(extents=[30, 30, 2]).export(source)
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(enabled=True,
        output_dir=str(tmp_path / "sliced")), repo_root=root)
    result = runner.slice(source, specimen_placement=placement, timeout_sec=120)
    assert result["ok"], result
    assert result["will_publish"] is False
    assert result["placement_validation"]["ok"]


def test_slicer_ignoring_requested_center_does_not_expose_success(tmp_path, monkeypatch):
    runner, source, _ = runner_fixture(tmp_path, monkeypatch, output_center=(138.25, 128))
    result = runner.slice(source, specimen_placement={"mode": "bed_center"})
    assert not result["ok"]
    assert result["failure_code"] == "SPECIMEN_PLACEMENT_MISMATCH"
    assert not result.get("sliced_artifact_path")


def test_translated_source_uses_relative_shift_without_rewriting_geometry(tmp_path, monkeypatch):
    runner, source, calls = runner_fixture(tmp_path, monkeypatch)
    mesh = trimesh.creation.box(extents=[30, 30, 10])
    mesh.apply_translation([10, 20, 25])
    mesh.export(source)
    original = source.read_bytes()
    assert runner.slice(source, specimen_placement={"mode": "custom", "center_x_mm": 110, "center_y_mm": 145})["ok"]
    obj = json.loads(Path(calls[0][calls[0].index("--load-assemble-list") + 1]).read_text())["plates"][0]["objects"][0]
    assert (obj["pos_x"], obj["pos_y"], obj["pos_z"]) == ([100], [125], [-20])
    assert source.read_bytes() == original


def test_conflicting_transform_and_3mf_relocation_are_blocked(tmp_path, monkeypatch):
    runner, source, calls = runner_fixture(tmp_path, monkeypatch)
    result = runner.slice(source, specimen_placement={"mode": "bed_center"}, extra_args=["--arrange", "1"])
    assert result["failure_code"] == "SPECIMEN_PLACEMENT_CONFLICTING_ARGS"
    project = tmp_path / "project.3mf"
    with zipfile.ZipFile(project, "w") as archive:
        archive.writestr("Metadata/settings", "preserve")
    result = runner.slice(project, specimen_placement={"mode": "bed_center"})
    assert result["failure_code"] == "SPECIMEN_PLACEMENT_REQUIRES_STL"
    assert calls == []


def test_mismatched_presliced_package_blocks_before_device_prepare(tmp_path, monkeypatch):
    from device_bridges.bambu_bridge import PrinterDeviceBridgeManager
    runner, source, _ = runner_fixture(tmp_path, monkeypatch)
    artifact = runner.slice(source)["sliced_artifact_path"]
    manager = object.__new__(PrinterDeviceBridgeManager)
    manager._select_profile = lambda payload: (SimpleNamespace(provider="bambulab_x2d"), "fixture")
    manager._prepare_bambu = lambda *args, **kwargs: pytest.fail("No device preparation allowed for mismatched placement")
    result = manager.prepare({"print": {"bambu_artifact_path": artifact}, "specimen_placement": {"mode": "bed_center"}})
    assert result["failure_code"] == "SPECIMEN_PLACEMENT_MISMATCH"
    assert not result["will_publish"]


def test_existing_sliced_artifact_validation_uses_same_position_as_ejection(tmp_path):
    from utils import specimen_placement
    from device_bridges.bambu_autoejection import extract_object_bounds_mm
    path = tmp_path / "existing.3mf"
    gcode = "G90\nM83\nG1 Z0.2\nG1 X95 Y130\nG1 X125 Y130 E1\nG1 X125 Y160 E1\nG1 X95 Y160 E1\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", gcode)
    result = specimen_placement.validate_sliced_placement(path, {"mode": "custom", "center_x_mm": 110, "center_y_mm": 145})
    assert result["ok"]
    assert result["object_bounds_mm"] == extract_object_bounds_mm(gcode)
    assert not specimen_placement.validate_sliced_placement(path, {"mode": "bed_center"})["ok"]
