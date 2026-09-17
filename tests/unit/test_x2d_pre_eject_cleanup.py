import hashlib
import zipfile

import pytest
from device_bridges.printer_fleet.providers.bambu_autoejection import (
    BambuGcodeAutoejectionPatcher, BambuGcodeAutoejectionValidator,
    X2D_COOLDOWN_MARKER, prepare_x2d_nozzle_cooldown,
)

BODY = 'G90\nM83\nG1 X110 Y110 Z0.2 E1 F1200\nG1 X130 Y130 Z30 E1 F1200\n'
END = '''; MACHINE_END_GCODE_START
;======== X2D end gcode ==========
M400
G92 E0
M211 Z1
G90
G1 Z40 F900
M140 S0
M141 S0
M106 S0
; pull back filament to AMS
M620 S65279 B
T65279
G150.1 F8000
M621 S65279 B
M620 S65535 B
T65535
G150.1 F8000
M621 S65535 B
G150.3
M104 S0 T0; turn off hotend
M104 S0 T1; turn off hotend
M400
M17 S
M17 Z0.4
G1 Z95 F600
M17 R
M18
'''


@pytest.mark.parametrize('zip_artifact', [False, True])
def test_native_unload_cool_eject_and_park_before_motor_current_change(tmp_path, zip_artifact):
    source = tmp_path / ('test.gcode.3mf' if zip_artifact else 'test.gcode')
    if zip_artifact:
        with zipfile.ZipFile(source,'w') as z:
            z.writestr('Metadata/plate_1.gcode', BODY+END)
            z.writestr('Metadata/plate_1.gcode.md5', 'old')
            z.writestr('other', 'untouched')
    else: source.write_text(BODY+END)
    original = source.read_bytes()
    result = BambuGcodeAutoejectionPatcher(output_dir=tmp_path/'out').patch_artifact(source)
    assert result['ok'], result
    from pathlib import Path
    path=Path(result['patched_artifact_path'])
    if zip_artifact:
        with zipfile.ZipFile(path) as z:
            text=z.read('Metadata/plate_1.gcode').decode()
            assert z.read('Metadata/plate_1.gcode.md5').decode()==hashlib.md5(text.encode()).hexdigest()
            assert z.read('other')==b'untouched'
    else: text=path.read_text()
    assert source.read_bytes()==original
    assert text.startswith(BODY)
    ordered=['M621 S65535 B','M109 S140 A','M104 S0 T0','M104 S0 T1',
             '; atr.bambu.autoejection.v1','M190 R40','G0 X120.000',
             'G150.3 ; native waste-bin park','; atr.bambu.autoejection.end','M17 Z0.4','M18']
    assert [text.index(s) for s in ordered]==sorted(text.index(s) for s in ordered)
    assert text.count('T65535\n')==1 and text.count('T65279\n')==1


@pytest.mark.parametrize('change', ['missing_unload','conditional','motors_off','missing_off','current_changed'])
def test_unrecognized_or_unsafe_native_end_is_not_guessed(tmp_path, change):
    end=END
    if change=='missing_unload': end=end.replace('T65535','T12')
    if change=='conditional': end=end.replace('M620 S65279 B','M622 J1\nM620 S65279 B')
    if change=='motors_off': end=end.replace('M140 S0','M84\nM140 S0')
    if change=='missing_off': end=end.replace('M104 S0 T1','M104 S140 T1')
    if change=='current_changed': end=end.replace('M17 Z0.4','M17 Z0.2')
    source=tmp_path/'test.gcode'; source.write_text(BODY+end)
    result=BambuGcodeAutoejectionPatcher(output_dir=tmp_path/'out').patch_artifact(source)
    assert not result['ok']
    assert 'BAMBU_X2D_PRE_EJECT_CLEANUP_INVALID' in result['blockers']


def test_old_eject_before_unload_artifact_is_blocked():
    old=(BODY+END).replace('M140 S0','; atr.bambu.autoejection.v1\nM190 R40\nG0 Z20 F900\n; atr.bambu.autoejection.end\nM140 S0')
    assert 'BAMBU_X2D_PRE_EJECT_CLEANUP_INVALID' in BambuGcodeAutoejectionValidator().validate(old)['blockers']


def test_one_layer_cleanup_does_not_add_ejection_extrusion_or_retraction():
    one=BODY.replace('Z30','Z0.2')+END
    prepared=prepare_x2d_nozzle_cooldown(one)
    assert 'atr.bambu.autoejection' not in prepared
    assert prepared.split(X2D_COOLDOWN_MARKER)[0]==one.split('M104 S0 T0')[0]
    assert prepared.count(' E')==one.count(' E')
    assert prepared.count('G150.1')==one.count('G150.1')
    assert prepared.index('M109 S140 A')<prepared.index('M104 S0 T0')
    with pytest.raises(ValueError): prepare_x2d_nozzle_cooldown(prepared)


def test_header_embedded_end_template_is_not_a_second_executable_block():
    text='; machine_end_gcode = '+END.replace('\n','\\n')+'\n'+BODY+END
    assert prepare_x2d_nozzle_cooldown(text).count(X2D_COOLDOWN_MARKER)==1


@pytest.mark.parametrize('cooldown', [False, True])
def test_installed_printer_ignores_end_template_and_keeps_ejection_only_path(tmp_path, cooldown):
    from pathlib import Path
    # Match a real slicer header, including the escaped end macro retained when
    # the print body and executable end block are removed for installed tests.
    header = '; machine_end_gcode = ' + END.replace('\n', '\\n') + '\n'
    source = tmp_path / 'specimen.gcode'
    source.write_text(header + BODY + END)
    result = BambuGcodeAutoejectionPatcher(output_dir=tmp_path/'out').build_ejection_only_from_sliced_artifact(
        source, include_cooldown_wait=cooldown)
    assert result['ok'], result
    text = Path(result['patched_artifact_path']).read_text()
    assert '; atr_print_body_omitted=true' in text
    assert text.count('; atr.bambu.autoejection.v1') == 1
    commands = [line.split(';', 1)[0].strip() for line in text.splitlines()]
    assert 'T65535' not in commands and 'T65279' not in commands
    assert not any(line.startswith('M109') for line in commands)
    assert 'unrecognized_native_end' not in text
    assert source.read_text() == header + BODY + END


def test_first_layer_path_trial_preserves_first_layer_and_complete_end():
    from scripts.prepare_x2d_first_layer_path_trial import first_layer_only
    first='; CHANGE_LAYER\n; Z_HEIGHT: 0.2\nG1 X120 Y130 Z0.2 E1\n'
    later='; CHANGE_LAYER\n; Z_HEIGHT: 0.4\nG1 X140 Y150 Z0.4 E1\n'
    ending='; close powerlost recovery\nM1003 S0\n'+END
    full='; total layer number: 150\n'+first+later+ending
    trial=first_layer_only(full)
    assert first in trial and later not in trial
    assert trial.endswith(ending)
    assert '; total layer number: 1\n' in trial


def test_regular_print_prepare_path_keeps_all_layers_and_uses_validated_cleanup(tmp_path):
    from pathlib import Path
    from tests.unit.test_bambu_bridge import _devices_config
    from device_bridges.printer_fleet.bridge import PrinterDeviceBridgeManager
    source=tmp_path/'full-specimen.gcode'
    body='; total layer number: 150\n; CHANGE_LAYER\n'+BODY+'; CHANGE_LAYER\nG1 X130 Y130 Z30 E1\n'
    source.write_text(body+END)
    manager=PrinterDeviceBridgeManager.from_devices_config(_devices_config(tmp_path),repo_root=tmp_path)
    manager.save_autoejection_config({'enabled':True,'provider':'bambu_gcode_patch'})
    result=manager._patch_bambu_native_autoejection_for_prepare(artifact_path=source,
        payload={'runtime_mode':'live','specimen_id':'specimen-regular','ejection':{'enabled':True}},plate_id=1)
    assert result['ok'],result
    text=Path(result['patched_artifact_path']).read_text()
    assert text.startswith(body) and '; total layer number: 150' in text
    assert text.count('; CHANGE_LAYER')==2
    assert text.index('M621 S65535 B')<text.index('M109 S140 A')<text.index('; atr.bambu.autoejection.v1')
    assert source.read_text()==body+END
