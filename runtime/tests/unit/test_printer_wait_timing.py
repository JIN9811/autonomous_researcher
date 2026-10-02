import zipfile

import pytest

from utils.printer_wait_timing import completion_wait_timing, sliced_duration_seconds


def artifact(tmp_path, prediction=6311):
    path = tmp_path / 'slice.gcode.3mf'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('Metadata/slice_info.config', f'<config><plate><metadata key="index" value="1"/>'
                         f'<metadata key="prediction" value="{prediction}"/></plate></config>')
    return path


def test_actual_slicer_duration_overrides_design_proxy(tmp_path):
    path = artifact(tmp_path)
    assert sliced_duration_seconds(path) == 6311
    timeout, poll = completion_wait_timing({'expected_print_time_min':58.73}, {
        'expected_print_time_min':58.73, 'slicer_result':{'sliced_artifact_path':str(path)}})
    assert timeout == 6311 * 1.25
    assert poll == 2


def test_selected_plate_only_and_plain_gcode(tmp_path):
    path = artifact(tmp_path)
    assert sliced_duration_seconds(path, 2) is None
    path = tmp_path / 'slice.gcode'
    path.write_text('; estimated printing time (normal mode) = 1h 45m 11s\n')
    assert sliced_duration_seconds(path) == 6311


def test_missing_invalid_estimate_has_conservative_fallback(tmp_path):
    assert sliced_duration_seconds(tmp_path / 'missing.3mf') is None
    assert completion_wait_timing({'expected_print_time_min':1}, {})[0] == 21600
    assert sliced_duration_seconds(artifact(tmp_path, 'nan')) is None


def test_short_slice_minimum_margin_and_larger_printer_eta():
    assert completion_wait_timing({}, {'slicer_result':{'estimated_print_time_sec':120}})[0] == 1020
    assert completion_wait_timing({}, {'slicer_result':{'estimated_print_time_sec':120},
        'device_screen':{'job':{'remaining_min':120}}})[0] == 9000


@pytest.mark.parametrize('timeout', [0, 5, 180])
def test_explicit_deadline_and_zero_poll_preserved(timeout):
    assert completion_wait_timing({'printer_completion_timeout_sec':timeout,
        'printer_completion_poll_sec':0}, {}) == (timeout, 0)
