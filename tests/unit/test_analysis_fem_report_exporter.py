"""Report calculations and rendering use finite, actual shared-domain evidence."""
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/validation/report_analysis_fem_cycle.py'


def reporter():
    spec = importlib.util.spec_from_file_location('fem_report_exporter', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def points(rows):
    return [{'displacement_mm': x, 'force_N': y} for x, y in rows]


def test_metrics_use_common_range_and_exact_axis_integrated_residual():
    report = reporter()
    metric, table = report.compare_curves(points([(0, 0), (2, 4), (4, 8)]),
                                           points([(0, 0), (1, 3), (2, 6)]),
                                           target=4, height=2, area=4)
    assert metric['comparison_domain_mm'] == [0, 2]
    assert metric['coverage_pct'] == 50
    assert metric['experiment_peak_N'] == 4
    assert metric['simulation_peak_N'] == 6
    assert metric['experiment_work_J'] == .004
    assert metric['simulation_work_J'] == .006
    assert metric['peak_error_pct'] == pytest.approx(50)
    assert metric['work_error_pct'] == pytest.approx(50)
    assert metric['rmse_N'] == pytest.approx(2 / math.sqrt(3))
    assert table[-1]['engineering_strain'] == 1
    assert table[-1]['simulation_stress_MPa'] == 1.5
    assert all(row['displacement_mm'] <= 2 for row in table)


def test_exporter_refuses_live_or_incomplete_runner_directory(tmp_path):
    report = reporter()
    (tmp_path / 'evidence.json').write_text('{}')
    with pytest.raises(ValueError, match='finished'):
        report.export_report(tmp_path)
    assert not (tmp_path / 'report').exists()


def saved_case(tmp_path):
    from test_cae_field_view import fixture
    fields = fixture()
    fields['frames'][0]['value'] = .5
    fields['frames'][0]['fields']['U']['values'][-1] = [0, 0, -.2]
    fields['frames'].append({'value': .6, 'fields': {'U': fields['frames'][0]['fields']['U']}})
    field_path = tmp_path / 'manifest.fields.json'
    field_path.write_text(json.dumps(fields))
    curve_path = tmp_path / 'curve.json'
    curve_path.write_text(json.dumps({'curve': [
        {'step_time': 0, 'displacement_mm': 0, 'force_N': 0},
        {'step_time': .5, 'displacement_mm': 2, 'force_N': 6}]}))
    observed = points([(0, 0), (2, 4), (4, 8)])
    evidence = {'payload': {'specimen_id': 'fixture', 'specimen_size_mm': [2, 2, 2],
                           'target_strain': 2, 'material': {'yield_strength_mpa': 35}},
                'specimen_geometry': {'gauge_length_mm': 2, 'cross_section_area_mm2': 4},
                'experiment_curve': observed}
    result = {'status': 'partial', 'experiment_curve': observed,
              'coordinate_convention': {'name': 'raw_displacement'},
              'summary': {'target_displacement_mm': 4}, 'attempts': [{
                  'attempt_id': 'attempt-1', 'mesh_size_mm': .6, 'endpoint_reached': False,
                  'solver_status': 'partial', 'curve': points([(0, 0), (1, 3), (2, 6)]),
                  'field_asset_path': str(field_path), 'artifacts': {'curve_json_path': str(curve_path)}}]}
    (tmp_path / 'evidence.json').write_text(json.dumps(evidence))
    (tmp_path / 'result.json').write_text(json.dumps(result))
    (tmp_path / 'run_metadata.json').write_text(json.dumps({'source_files_unchanged': True}))
    (tmp_path / 'resources_summary.json').write_text(json.dumps({'elapsed_s': 10, 'peak_tree_rss_bytes': 2000}))
    return field_path


def test_export_uses_last_complete_actual_frame_and_preserves_sources(tmp_path):
    pytest.importorskip('pyvista')
    from PIL import Image
    report = reporter()
    field_path = saved_case(tmp_path)
    before = report.sha256(field_path)
    output = report.export_report(tmp_path)
    assert output['status'] == 'partial'
    assert output['selected_attempt_id'] == 'attempt-1'
    assert output['contours']['frame_index'] == 0
    assert output['contours']['frame_value'] == .5
    assert output['contours']['compression_mm'] == 2
    assert output['contours']['deformation_scale'] == 1
    assert output['contours']['fields']['S_MISES']['units'] == 'MPa'
    assert output['contours']['fields']['U']['units'] == 'mm'
    assert report.sha256(field_path) == before
    assert Path(output['artifacts']['comparison_pdf']).is_file()
    for key in ('comparison_png', 'stress_png', 'displacement_png'):
        with Image.open(output['artifacts'][key]) as image:
            assert image.width >= 3000
            assert image.height >= 1500
    metrics = json.loads((tmp_path / 'report/metrics.json').read_text())
    assert metrics['comparison']['coverage_pct'] == 50
    assert metrics['resources']['elapsed_s'] == 10
    assert metrics['raw_bo_objective_changed'] is False
