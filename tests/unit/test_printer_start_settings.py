import hashlib
import zipfile

import pytest

from device_bridges.printer_fleet.bridge import BambuSlicerConfig, BambuStudioSlicerRunner
from utils.printer_profile import load_prusa_print_profile, save_prusa_print_profile


def source_gcode():
    source = ('; nozzle load line\nM109 S220\nG130 X100 E12\n; nozzle load line end\n'
              '; MACHINE_START_GCODE_END\nG90\nG21\nM83\n')
    for layer in range(1, 7):
        source += (f'; CHANGE_LAYER\n; OBJECT_ID: 1\nG1 X10 Y10 F6000\n'
                   f'G1 Z{layer * 0.2:.1f} F1200\nG1 X11 Y10 E.1 F6000\n')
    return source


SETTINGS = {'start_point_prime_mm': 0.03, 'early_layer_speed_mm_s': 35.0, 'early_layer_z_speed_mm_s': 2.0}


@pytest.mark.parametrize('suffix', ['.gcode', '.gcode.3mf'])
@pytest.mark.parametrize('limit_enabled', [True, False])
@pytest.mark.parametrize('prime', [0.03, 0.4, 1.0])
@pytest.mark.parametrize('prime_enabled,z_enabled', [(True, True), (False, True), (True, False), (False, False)])
def test_saved_gui_defaults_reach_generated_gcode_and_archive_checksum(tmp_path, suffix, limit_enabled, prime, prime_enabled, z_enabled):
    profile_path = tmp_path / 'memory/prusa_print_profile.json'
    settings = {**SETTINGS, 'start_point_prime_mm': prime, 'early_layer_speed_limit_enabled': limit_enabled,
                'start_point_prime_enabled': prime_enabled, 'early_layer_z_speed_limit_enabled': z_enabled}
    save_prusa_print_profile(settings, path=profile_path)
    loaded = load_prusa_print_profile(profile_path)
    assert {key: loaded.get(key) for key in settings} == settings
    artifact = tmp_path / f'print{suffix}'
    if suffix == '.gcode':
        artifact.write_text(source_gcode())
    else:
        with zipfile.ZipFile(artifact, 'w') as archive:
            archive.writestr('Metadata/plate_1.gcode', source_gcode())
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(), repo_root=tmp_path)
    runner._postprocess_front_test_line_artifact(artifact)
    if suffix == '.gcode':
        text = artifact.read_text()
    else:
        with zipfile.ZipFile(artifact) as archive:
            data = archive.read('Metadata/plate_1.gcode')
            assert archive.read('Metadata/plate_1.gcode.md5').decode() == hashlib.md5(data).hexdigest()
            text = data.decode()
    assert text.count(f'G1 E{prime:g} F60') == int(prime_enabled)
    layers = text.split('; CHANGE_LAYER\n')[1:]
    assert 'G1 X11 Y10 E.1 F6000' in layers[0]
    for section in layers[1:5]:
        if limit_enabled:
            assert 'G1 X11 Y10 E.1 F2100\nG1 F6000' in section
        else:
            assert 'G1 X11 Y10 E.1 F6000' in section
            assert 'F2100' not in section
    for i, section in enumerate(layers[:5], 1):
        assert (f'G1 Z{i * 0.2:.1f} F120\nG1 F1200' if z_enabled else f'G1 Z{i * 0.2:.1f} F1200') in section
    assert 'G1 Z1.2 F1200' in layers[5]
    assert 'G1 X11 Y10 E.1 F6000' in layers[5]


def test_profile_preserves_zero_prime(tmp_path):
    path = tmp_path / 'profile.json'
    save_prusa_print_profile({**SETTINGS, 'start_point_prime_mm': 0}, path)
    assert load_prusa_print_profile(path).get('start_point_prime_mm') == 0


@pytest.mark.parametrize('limit_enabled', [True, False])
def test_recovered_cli_output_uses_same_snapshot_after_profile_changes(tmp_path, limit_enabled):
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(), repo_root=tmp_path)
    path = tmp_path / 'memory/prusa_print_profile.json'
    save_prusa_print_profile({**SETTINGS, 'early_layer_speed_limit_enabled': limit_enabled}, path)
    snapshot = runner._print_start_settings()
    save_prusa_print_profile({'start_point_prime_mm': 0}, path)
    raw = tmp_path / 'plate_1.gcode'
    raw.write_text(source_gcode())
    source = tmp_path / 'specimen.stl'
    source.write_text('solid specimen\nendsolid specimen\n')
    artifact = tmp_path / 'recovered.gcode.3mf'
    result = runner._recover_gcode_3mf_after_cli_crash(outputs=[raw], export_path=artifact,
        source_path=source, output_dir=tmp_path, returncode=-11, print_start_settings=snapshot)
    assert result['ok']
    with zipfile.ZipFile(artifact) as archive:
        data = archive.read('Metadata/plate_1.gcode')
        assert b'G1 E0.03 F60' in data
        assert (b'G1 X11 Y10 E.1 F2100' if limit_enabled else b'G1 X11 Y10 E.1 F6000') in data.split(b'; CHANGE_LAYER\n')[2]
        assert b'G1 Z0.2 F120' in data
        assert archive.read('Metadata/plate_1.gcode.md5').decode() == hashlib.md5(data).hexdigest()
    runner._postprocess_front_test_line_artifact(artifact, print_start_settings=snapshot)
    with zipfile.ZipFile(artifact) as archive:
        assert archive.read('Metadata/plate_1.gcode') == data


def test_new_limits_require_reslicing_instead_of_cumulative_patching():
    patched = BambuStudioSlicerRunner._limit_early_layer_speeds(source_gcode())
    with pytest.raises(ValueError, match='re-slice'):
        BambuStudioSlicerRunner._limit_early_layer_speeds(patched, early_layer_speed_mm_s=35)


def test_disabling_limit_on_already_capped_artifact_requires_original_source():
    patched = BambuStudioSlicerRunner._limit_early_layer_speeds(source_gcode())
    with pytest.raises(ValueError, match='re-slice'):
        BambuStudioSlicerRunner._limit_early_layer_speeds(patched, early_layer_speed_limit_enabled=False)


@pytest.mark.parametrize('field,value', [
    ('start_point_prime_mm', -0.01), ('start_point_prime_mm', float('inf')),
    ('start_point_prime_mm', float('nan')),
    ('early_layer_speed_mm_s', 0), ('early_layer_speed_mm_s', 1001),
    ('early_layer_z_speed_mm_s', 0), ('early_layer_z_speed_mm_s', 21),
    ('early_layer_z_speed_mm_s', float('nan')),
])
def test_invalid_start_settings_cannot_be_saved(tmp_path, field, value):
    with pytest.raises(ValueError):
        save_prusa_print_profile({**SETTINGS, field: value}, tmp_path / 'profile.json')


def test_machine_max_caps_are_accepted_without_accelerating_slower_moves(tmp_path):
    settings = {**SETTINGS, 'early_layer_speed_mm_s': 1000, 'early_layer_z_speed_mm_s': 20}
    save_prusa_print_profile(settings, tmp_path / 'memory/prusa_print_profile.json')
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(), repo_root=tmp_path)
    text, _ = runner._remove_front_test_line_from_gcode(source_gcode(), **runner._print_start_settings())
    assert 'G1 X11 Y10 E.1 F6000' in text
    assert 'G1 Z0.4 F1200' in text
    assert 'F60000' not in text
