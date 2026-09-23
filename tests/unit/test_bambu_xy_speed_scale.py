"""Operator XY scale changes slice-time speeds, never machine programs or geometry."""
import copy
import json
from pathlib import Path

import pytest

from device_bridges.printer_fleet.bridge import BambuSlicerConfig, BambuStudioSlicerRunner
from utils.printer_profile import load_prusa_print_profile, save_prusa_print_profile


@pytest.mark.parametrize("percent", [1, 40.5, 80, 100])
def test_xy_scale_persists_and_reaches_explicit_cli_process(tmp_path, percent):
    profile = tmp_path / "memory/prusa_print_profile.json"
    save_prusa_print_profile({"xy_speed_scale_percent": percent}, profile)
    assert load_prusa_print_profile(profile)["xy_speed_scale_percent"] == percent
    source = tmp_path / "process.json"
    process = {"type": "process", "outer_wall_speed": ["200", "50"],
               "travel_speed": ["1000"], "initial_layer_speed": ["10"],
               "small_perimeter_speed": ["50%", "40"], "overhang_1_4_speed": ["0"],
               "travel_speed_z": ["20"], "retraction_speed": ["30"],
               "layer_height": "0.2", "default_acceleration": ["10000"]}
    source.write_text(json.dumps(process))
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(), repo_root=tmp_path)
    settings, evidence = runner._xy_speed_profile(tmp_path, source, percent)
    scaled = json.loads(Path(str(settings)).read_text())
    assert float(scaled["outer_wall_speed"][0]) == pytest.approx(200 * percent / 100)
    assert float(scaled["travel_speed"][0]) == pytest.approx(1000 * percent / 100)
    assert float(scaled["initial_layer_speed"][0]) == pytest.approx(10 * percent / 100)
    assert scaled["small_perimeter_speed"][0] == "50%"  # relative to the scaled wall
    assert float(scaled["small_perimeter_speed"][1]) == pytest.approx(40 * percent / 100)
    for key in ("travel_speed_z", "retraction_speed", "layer_height", "default_acceleration", "overhang_1_4_speed"):
        assert scaled[key] == process[key]
    assert json.loads(source.read_text()) == process
    assert evidence["percent"] == percent
    if percent == 100:
        assert settings == source


@pytest.mark.parametrize("value", [0, 100.1, -1, "nan", "inf", "bad", None])
def test_invalid_xy_scale_does_not_overwrite_saved_value(tmp_path, value):
    path = tmp_path / "profile.json"
    save_prusa_print_profile({"xy_speed_scale_percent": 80}, path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="xy_speed_scale_percent"):
        save_prusa_print_profile({"xy_speed_scale_percent": value}, path)
    assert path.read_bytes() == before


def test_xy_scale_resolves_inheritance_without_scaling_machine_or_filament(tmp_path):
    from device_bridges.printer_fleet.slicer_profiles import scale_xy_process_profile
    process = {"outer_wall_speed": ["200"], "fan_min_speed": ["60"],
               "machine_start_gcode": "G1 X20 F9000", "machine_end_gcode": "G1 X0 F8000",
               "filament_max_volumetric_speed": ["20"], "travel_speed_z": ["10"],
               "vertical_shell_speed": ["80%"], "bridge_speed": ["50"]}
    before = copy.deepcopy(process)
    scaled = scale_xy_process_profile(process, 80)
    assert process == before
    assert scaled["outer_wall_speed"] == ["160"]
    assert scaled["bridge_speed"] == ["40"]
    for key in set(process) - {"outer_wall_speed", "bridge_speed"}:
        assert scaled[key] == process[key]


def test_xy_scale_requires_an_explicit_process_when_no_profile_is_resolved(tmp_path):
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(), repo_root=tmp_path)
    with pytest.raises(ValueError, match="process profile"):
        runner._xy_speed_profile(tmp_path, None, 80)


def test_one_percent_honors_slicer_minimum_speeds():
    from device_bridges.printer_fleet.slicer_profiles import scale_xy_process_profile
    scaled = scale_xy_process_profile({"initial_layer_infill_speed": ["10"],
        "support_interface_speed": ["80"], "travel_speed": ["50"],
        "outer_wall_speed": ["20"], "prime_tower_max_speed": "90"}, 1)
    assert scaled == {"initial_layer_infill_speed": ["1"],
        "support_interface_speed": ["1"], "travel_speed": ["1"],
        "outer_wall_speed": ["0.2"], "prime_tower_max_speed": "10"}
