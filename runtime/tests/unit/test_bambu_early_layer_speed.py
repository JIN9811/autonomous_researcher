from device_bridges.printer_fleet.bridge import BambuStudioSlicerRunner


def test_first_layer_unchanged_next_four_capped_z_slow_and_sixth_restored():
    source = '; MACHINE_START_GCODE_END\nG90\nG21\nM83\n'
    for layer in range(1, 7):
        source += (f'; CHANGE_LAYER\n; Z_HEIGHT: {layer * 0.2:.1f}\n'
                   f'G1 Z{layer * 0.2:.1f} F1200\nG1 X10 Y10 F18000\n'
                   'G1 X11 Y10 E.1 F6000\nG1 X12 Y10 E.1\n'
                   'G1 X13 Y10 E.1 F600\nG1 E-.4 F1800\n')
    patched = BambuStudioSlicerRunner._limit_early_layer_speeds(source)
    sections = patched.split('; CHANGE_LAYER\n')[1:]
    assert len(sections) == 6
    assert 'G1 X11 Y10 E.1 F6000\n' in sections[0]
    for section in sections[1:5]:
        assert 'G1 X11 Y10 E.1 F3000\nG1 F6000\n' in section
        assert 'G1 X12 Y10 E.1 F3000\nG1 F6000\n' in section
    for layer, section in enumerate(sections[:5], 1):
        assert f'G1 Z{layer * 0.2:.1f} F300\nG1 F1200\n' in section
        assert 'G1 X10 Y10 F18000\n' in section
        assert 'G1 X13 Y10 E.1 F600\n' in section
        assert 'G1 E-.4 F1800\n' in section
    assert 'G1 Z1.2 F1200\n' in sections[5]
    assert 'G1 X11 Y10 E.1 F6000\n' in sections[5]
    assert BambuStudioSlicerRunner._limit_early_layer_speeds(patched) == patched


def test_speed_limit_is_applied_even_without_a_front_prime_block(tmp_path):
    from device_bridges.printer_fleet.bridge import BambuSlicerConfig
    path = tmp_path / 'print.gcode'
    source = '; MACHINE_START_GCODE_END\nG90\nG21\nM83\n; CHANGE_LAYER\nG1 Z.2 F1200\n'
    path.write_text(source)
    runner = BambuStudioSlicerRunner(BambuSlicerConfig(), repo_root=tmp_path)
    runner._postprocess_front_test_line_artifact(path)
    assert 'G1 Z.2 F300' in path.read_text()
