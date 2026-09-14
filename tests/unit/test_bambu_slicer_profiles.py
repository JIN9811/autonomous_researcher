"""Output settings must survive inheritance and operator overrides before slicing."""
import json
from pathlib import Path

import pytest

from device_bridges.printer_fleet.bridge import BambuSlicerConfig, BambuStudioSlicerRunner


def runner_with_profiles(tmp_path):
    files = {}
    for kind, parent in {
        'machine': {'machine_start_gcode': 'G28 ; native home', 'machine_max_acceleration_x': ['20000']},
        'process': {'sparse_infill_density': '15%', 'sparse_infill_pattern': 'grid', 'wall_generator': 'classic'},
        'filament': {'filament_density': ['1.26'], 'fan_min_speed': ['100']},
    }.items():
        folder = tmp_path / kind
        folder.mkdir()
        (folder/'parent.json').write_text(json.dumps(parent))
        child = folder/'child.json'
        child.write_text(json.dumps({'inherits': 'parent', 'name': kind, 'type': kind}))
        files[kind] = str(child)
    config = BambuSlicerConfig(default_machine_profile=files['machine'],
        default_process_profile=files['process'], default_filament_profile=files['filament'])
    return BambuStudioSlicerRunner(config, repo_root=tmp_path), files


def test_cli_profiles_include_parent_values_and_keep_native_machine_program(tmp_path):
    runner, _ = runner_with_profiles(tmp_path)
    result = runner._default_no_skirt_profile(tmp_path/'output')
    process = json.loads(Path(result['process_override_path']).read_text())
    filament = json.loads(Path(result['filament_override_path']).read_text())
    machine = json.loads(Path(result['machine_override_path']).read_text())
    assert process['sparse_infill_pattern'] == 'grid'
    assert process['sparse_infill_density'] == '15%'
    assert filament['filament_density'] == ['1.26']
    assert machine['machine_start_gcode'] == 'G28 ; native home'
    assert not process.get('inherits')
    assert process['curr_bed_type'] == 'Textured PEI Plate'
    assert process['initial_layer_speed'] == ['10']
    assert filament['textured_plate_temp'] == ['60']
    assert process['brim_type'] == 'no_brim'


def test_saved_settings_and_request_override_reach_effective_cli_profiles(tmp_path):
    runner, _ = runner_with_profiles(tmp_path)
    (tmp_path/'memory').mkdir()
    (tmp_path/'memory/prusa_print_profile.json').write_text(json.dumps({
        'bed_temperature_c': 62, 'first_layer_bed_temperature_c': 63,
        'first_layer_speed_mm_s': 12, 'layer_height_mm': .16,
        'specimen_placement': {'mode': 'custom', 'center_x_mm': 158, 'center_y_mm': 128}}))
    result = runner._default_no_skirt_profile(tmp_path/'output', experiment_spec={
        'first_layer_speed_mm_s': 10, 'bed_temperature_c': 65})
    p = json.loads(Path(result['process_override_path']).read_text())
    f = json.loads(Path(result['filament_override_path']).read_text())
    assert p['initial_layer_speed'] == ['10']
    assert p['layer_height'] == '0.16'
    assert f['textured_plate_temp'] == ['65']
    assert f['textured_plate_temp_initial_layer'] == ['63']
    assert 'specimen_placement' not in p
    assert 'allow_ejection' not in p


def test_machine_include_replaces_generic_start_with_x2d_template(tmp_path):
    runner, files = runner_with_profiles(tmp_path)
    machine = Path(files['machine'])
    (machine.parent/'native-start.json').write_text(json.dumps({
        'machine_start_gcode': 'G28 ; X2D native home\nM620 S0A'}))
    data = json.loads(machine.read_text())
    data['include'] = ['native-start']
    machine.write_text(json.dumps(data))
    result = runner._default_no_skirt_profile(tmp_path/'output')
    resolved = json.loads(Path(result['machine_override_path']).read_text())
    assert resolved['machine_start_gcode'] == 'G28 ; X2D native home\nM620 S0A'
    assert 'include' not in resolved


def test_vendor_noozle_end_marker_does_not_erase_print_body():
    text = ('G28\n;===== nozzle load line =====\nG1 X100 Y0 E12\n'
            ';===== noozle load line end =====\n; CHANGE_LAYER\nG1 X158 Y128 E1\nM18\n')
    result, count = BambuStudioSlicerRunner._remove_front_test_line_from_gcode(text)
    assert count == 1
    assert 'G1 X100' not in result
    assert '; CHANGE_LAYER\nG1 X158 Y128 E1\nM18\n' in result


def test_unclosed_prime_marker_never_discards_rest_of_file():
    text = 'G28\n; nozzle load line\nG1 X10 E1\n; CHANGE_LAYER\nG1 X158 E2\n'
    result, count = BambuStudioSlicerRunner._remove_front_test_line_from_gcode(text)
    assert result == text
    assert count == 0


@pytest.mark.parametrize('parent', ['missing', 'child'])
def test_broken_or_cyclic_inheritance_is_not_silently_sliced(tmp_path, parent):
    runner, files = runner_with_profiles(tmp_path)
    Path(files['process']).write_text(json.dumps({'inherits': parent}))
    result = runner._default_no_skirt_profile(tmp_path/'output')
    assert result['ok'] is False
    assert result['reason'] == 'profile_resolution_failed'
