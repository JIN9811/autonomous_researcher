#!/usr/bin/env python3
"""Export read-only evidence from a FINISHED Analysis FEM validation runner.

Chart contract
--------------
Question: how does the actual solver response compare with its paired measured
compression curve, and what field state was actually reached? The exporter does
not infer agreement from completion or promote the retained yield-35 baseline.
Family: two aligned multi-series line panels (F-D and engineering S-S), because
they show the same physical trajectory in dimensional and normalized units.
Comparison: independently recomputed, exact piecewise-linear shared-domain work
and axis-integrated RMS residual; never extrapolate a partial solve. Both panels
use the same shared range. A separate full-target view makes missing coverage
visible; using the same line family is intentional for this zoom comparison.
Sufficiency: >=2 finite, strictly increasing measured and computed observations;
show sparse solver knots, never synthesize increments or smooth the solution.
Surface: explicit publication PNG/PDF exports, Matplotlib Agg. 12.8 x 6.4 inches
at 300 dpi, quiet white background, charcoal measurement and blue dashed solver
(single-root palette; line style also distinguishes the curves in grayscale).
Contours: existing validated load_fields/render_png only; last complete U and
S_MISES frame; true deformation scale=1, units mm/MPa. Viridis is the existing
scientific sequential scalar-map exception to the comparison palette. No AI
images and no archived contour substitution. Original FRD files are never read.
Outputs: run/report/{comparison,comparison_full_target}.{png,pdf}, real stress
and displacement PNGs, shared_points.csv, metrics.json and provenance.json.
QA: hand-check analytic fixtures, inspect exported PNGs, retain hashes, state
coordinate convention, partial/full status, requested/shared domains, sample
counts, material assumptions, source limitations and unchanged raw BO objective.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError(f'Missing or over-budget JSON artifact: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, data):
    with Path(path).open('w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=True, allow_nan=False)


def curve_array(rows):
    import numpy as np
    array = np.asarray([[row['displacement_mm'], row['force_N']] for row in rows], dtype=float)
    if (array.ndim != 2 or array.shape[1] != 2 or len(array) < 2 or not np.isfinite(array).all()
            or not (np.diff(array[:, 0]) > 0).all()):
        raise ValueError('At least two finite strictly increasing curve observations are required')
    return array


def compare_curves(observed, simulated, *, target, height, area):
    """Independent shared-domain calculation, not copied from study summaries."""
    import numpy as np
    if any(not math.isfinite(value) or value <= 0 for value in (target, height, area)):
        raise ValueError('Positive finite target, initial height and initial area are required')
    exp, sim = curve_array(observed), curve_array(simulated)
    start, end = max(0., exp[0, 0], sim[0, 0]), min(target, exp[-1, 0], sim[-1, 0])
    if end <= start:
        raise ValueError('Measured and computed curves have no common interval')
    axis = np.unique(np.r_[start, end, exp[(exp[:, 0] > start) & (exp[:, 0] < end), 0],
                           sim[(sim[:, 0] > start) & (sim[:, 0] < end), 0]])
    measured, computed = np.interp(axis, exp[:, 0], exp[:, 1]), np.interp(axis, sim[:, 0], sim[:, 1])
    residual = computed - measured
    rmse = float(np.sqrt(np.sum(np.diff(axis) *
        (residual[:-1] ** 2 + residual[:-1] * residual[1:] + residual[1:] ** 2) / 3) / (end - start)))
    exp_peak, sim_peak = float(measured.max()), float(computed.max())
    exp_work, sim_work = float(np.trapezoid(measured, axis) / 1000), float(np.trapezoid(computed, axis) / 1000)
    metric = {'comparison_domain_mm': [float(start), float(end)], 'requested_domain_mm': [0., target],
              'coverage_pct': float(100 * (end - start) / target),
              'experiment_peak_N': exp_peak, 'simulation_peak_N': sim_peak,
              'peak_error_pct': 100 * (sim_peak - exp_peak) / abs(exp_peak) if exp_peak else None,
              'experiment_work_J': exp_work, 'simulation_work_J': sim_work,
              'work_error_pct': 100 * (sim_work - exp_work) / abs(exp_work) if exp_work else None,
              'rmse_N': rmse, 'normalized_rmse_pct': 100 * rmse / abs(exp_peak) if exp_peak else None,
              'experiment_point_count': len(exp), 'simulation_point_count': len(sim),
              'initial_height_mm': height, 'initial_area_mm2': area,
              'rmse_definition': 'sqrt(exact integral of piecewise-linear force residual squared / shared displacement span)',
              'work_definition': 'Trapezoidal force-displacement integral on shared interval; N mm / 1000 = J',
              'stress_definition': 'engineering stress = force / initial planned area; N/mm2 = MPa',
              'strain_definition': 'engineering strain = compression displacement / initial planned height',
              'extrapolation_applied': False}
    table = [{'displacement_mm': float(x), 'engineering_strain': float(x / height),
              'experiment_force_N': float(e), 'simulation_force_N': float(s),
              'experiment_stress_MPa': float(e / area), 'simulation_stress_MPa': float(s / area),
              'residual_N': float(s - e)} for x, e, s in zip(axis, measured, computed)]
    return metric, table


def _plot_comparison(directory, observed, simulated, metrics, *, specimen, status, convention):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    exp, sim = curve_array(observed), curve_array(simulated)
    start, end = metrics['comparison_domain_mm']
    target = metrics['requested_domain_mm'][1]
    height, area = metrics['initial_height_mm'], metrics['initial_area_mm2']
    contact = convention.get('name') == 'contact_threshold'
    coordinate = 'Contact-referenced compression' if contact else 'Recorded displacement'
    output = {}
    with plt.rc_context({'font.family': 'DejaVu Sans', 'font.size': 11, 'axes.spines.top': False,
                         'axes.spines.right': False, 'axes.edgecolor': '#454545', 'text.color': '#242424',
                         'axes.labelcolor': '#242424', 'xtick.color': '#454545', 'ytick.color': '#454545'}):
        for full in (False, True):
            stem = 'comparison_full_target' if full else 'comparison'
            domain = (0., target) if full else (start, end)
            fig, axes = plt.subplots(1, 2, figsize=(12.8, 6.4), dpi=300)
            fig.subplots_adjust(top=.72, bottom=.20, left=.075, right=.98, wspace=.24)
            for index, (axis, xscale, yscale, xlabel, ylabel) in enumerate(zip(axes, [1, height], [1000, area],
                    [f'{coordinate} (mm)', 'Engineering strain (mm/mm)'], ['Force (kN)', 'Engineering stress (MPa)'])):
                # Clip each source independently; interpolation stays inside its observed domain.
                for data, label, color, style in ((exp, 'Paired physical experiment', '#292929', '-'),
                                                   (sim, 'CalculiX, retained yield-35 baseline', '#2563A6', '--')):
                    lower, upper = max(domain[0], data[0, 0]), min(domain[1], data[-1, 0])
                    x = np.unique(np.r_[lower, data[(data[:, 0] > lower) & (data[:, 0] < upper), 0], upper])
                    y = np.interp(x, data[:, 0], data[:, 1])
                    axis.plot(x / xscale, y / yscale, label=label, color=color, linestyle=style, linewidth=1.8)
                    if data is sim and len(sim) < 12:
                        mask = (sim[:, 0] >= lower) & (sim[:, 0] <= upper)
                        axis.plot(sim[mask, 0] / xscale, sim[mask, 1] / yscale, 'o',
                                  markerfacecolor='white', markeredgecolor=color, markersize=4)
                if full and end < target:
                    axis.axvspan(end / xscale, target / xscale, color='#eeeeee', zorder=-1)
                    axis.axvline(end / xscale, color='#777777', linestyle=':', linewidth=1)
                axis.set(xlim=(domain[0] / xscale, domain[1] / xscale), xlabel=xlabel, ylabel=ylabel)
                low, high = axis.get_ylim()
                axis.set_ylim(min(0, low), max(0, high))
                axis.grid(axis='y', color='#dddddd', linewidth=.6)
                axis.set_title('Force–displacement' if index == 0 else 'Engineering stress–strain', loc='left', fontsize=12, pad=12)
            handles, labels = axes[0].get_legend_handles_labels()
            fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(.5, .83), ncol=2, frameon=False, fontsize=10)
            fig.suptitle(f'{specimen} — measured and simulated compression', x=.075, ha='left', y=.97, fontsize=16)
            fig.text(.075, .895, f'{status.upper()}  |  Shared interval {start:.6g}–{end:.6g} mm of requested 0–{target:g} mm'
                     f'  |  Coverage {metrics["coverage_pct"]:.2f}%', fontsize=11)
            detail = ('Requested-range view; grey region has no shared computed coverage.' if full else
                      f'Shared-range view only; H₀ = {height:g} mm, A₀ = {area:g} mm². No extrapolation.')
            fig.text(.075, .108, detail, fontsize=10)
            offset = (f'Experiment-only contact offset {convention.get("displacement_offset_mm", 0):.6g} mm; '
                      f'force baseline {convention.get("force_offset_N", 0):.6g} N. ' if contact else '')
            fig.text(.075, .062, offset + 'Raw BO objective unchanged; no force fitting or material promotion.', fontsize=9)
            for suffix in ('png', 'pdf'):
                path = directory / f'{stem}.{suffix}'
                fig.savefig(path, dpi=300, facecolor='white')
                output[f'{stem}_{suffix}'] = str(path)
            plt.close(fig)
    return output


def _actual_contours(run, directory, attempt, specimen, status):
    from utils.cae_field_view import load_fields, render_png
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from PIL import Image

    filename = attempt.get('field_asset_path') or attempt.get('artifacts', {}).get('field_asset_path')
    if not filename:
        return {'status': 'unavailable', 'reason': 'No actual field manifest was exported'}, {}
    data = load_fields(filename, [run])
    candidates = [index for index, frame in enumerate(data['frames'])
                  if {'U', 'S_MISES'} <= frame['fields'].keys()]
    if not candidates:
        return {'status': 'unavailable', 'reason': 'No complete displacement/stress frame exists'}, {}
    index = candidates[-1]
    frame = data['frames'][index]
    value = frame.get('value')
    if not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('Selected actual field frame has no finite solver time')
    for name, units in (('U', 'mm'), ('S_MISES', 'MPa')):
        if frame['fields'][name].get('units') != units:
            raise ValueError('Field units do not match the established mm/N/MPa contract')
    compression = None
    curve_path = attempt.get('artifacts', {}).get('curve_json_path')
    if curve_path:
        path = Path(curve_path).resolve()
        if not path.is_relative_to(run):
            raise ValueError('Reaction history path escapes this finished run')
        timed = [row for row in read_json(path).get('curve', [])
                 if isinstance(row.get('step_time'), (int, float)) and math.isfinite(row['step_time'])]
        if timed:
            nearest = min(timed, key=lambda row: abs(row['step_time'] - value))
            if math.isclose(nearest['step_time'], value, abs_tol=5e-6, rel_tol=1e-5):
                compression = float(nearest['displacement_mm'])
    metadata = {'status': 'exported', 'field_manifest': str(Path(filename).resolve()),
                'field_manifest_sha256': sha256(filename), 'frame_index': index, 'frame_value': value,
                'compression_mm': compression, 'deformation_scale': 1,
                'selection': 'last stored complete U/S_MISES frame in this run; not extrapolated',
                'source_hashes': data.get('source_hashes', {}), 'field_selection': data.get('field_selection'),
                'fields': {}, 'stress_caveat': 'Solver-extrapolated / nodally averaged stress, not raw integration-point stress'}
    outputs = {}
    for field, label, stem, units in (('S_MISES', 'von Mises stress', 'stress', 'MPa'),
                                     ('U', 'Displacement magnitude', 'displacement', 'mm')):
        pixels = render_png(data, frame=index, field=field, component=-1, scale=1, edges=False)
        with Image.open(BytesIO(pixels)) as raster:
            fig = plt.figure(figsize=(12.8, 8.0), dpi=300, facecolor='white')
            axis = fig.add_axes([0, .08, 1, .80])
            axis.imshow(raster)
            axis.axis('off')
            fig.text(.035, .956, f'{specimen} — {label} ({units})', fontsize=17, color='#242424')
            at = f'compression {compression:.6g} mm' if compression is not None else 'compression unavailable in timed reaction history'
            fig.text(.035, .914, f'{status.upper()}  |  solver time {value:.7g}  |  {at}  |  physical deformation scale 1×', fontsize=11)
            fig.text(.035, .035, 'Actual solver fields only. Stress is solver-extrapolated / nodally averaged; material not independently validated.', fontsize=10)
            path = directory / f'{stem}.png'
            fig.savefig(path, dpi=300, facecolor='white')
            plt.close(fig)
        outputs[f'{stem}_png'] = str(path)
        metadata['fields'][field] = {'units': units, 'path': str(path), 'sha256': sha256(path)}
    return metadata, outputs


def export_report(run, *, attempt_index=None, overwrite=False, reviewed_result=None):
    run = Path(run).resolve()
    result_path = Path(reviewed_result).resolve() if reviewed_result else run / 'result.json'
    if not result_path.is_relative_to(run):
        raise ValueError('Reviewed result must belong to the same archived run')
    if not result_path.is_file():
        raise ValueError('A finished runner result.json is required; live FRD files are never inspected')
    result, evidence = read_json(result_path), read_json(run / 'evidence.json')
    if result.get('status') not in {'completed', 'partial'}:
        raise ValueError('Only finished completed/partial runner results can be exported')
    metadata = read_json(run / 'run_metadata.json')
    if metadata.get('source_files_unchanged') is False:
        raise ValueError('Runner source-hash audit failed; report would not have reliable provenance')
    verified_inputs = {}
    for filename, expected in evidence.get('input_hashes', {}).items():
        path = Path(filename).resolve()
        if not path.is_relative_to(run) or sha256(path) != expected:
            raise ValueError('Frozen run input hash does not match retained evidence')
        verified_inputs[str(path)] = expected
    attempts = result.get('attempts', [])
    eligible = [index for index, attempt in enumerate(attempts) if len(attempt.get('curve', [])) >= 2]
    selected = eligible[-1] if attempt_index is None and eligible else attempt_index
    if selected not in eligible:
        raise ValueError('Select an existing attempt with an actual computed curve')
    attempt = attempts[selected]
    payload, geometry = evidence['payload'], evidence.get('specimen_geometry', {})
    size = geometry.get('specimen_size_mm') or payload.get('specimen_size_mm')
    height = float(geometry.get('gauge_length_mm') or size[2])
    area = float(geometry.get('cross_section_area_mm2') or float(size[0]) * float(size[1]))
    target = float(result['summary']['target_displacement_mm'])
    observed = result.get('experiment_curve') or result.get('summary', {}).get('comparison_curve')
    if not observed:
        raise ValueError('Finished study must retain its declared-coordinate comparison curve')
    convention = result.get('coordinate_convention') or {'name': 'raw_displacement'}
    comparison, table = compare_curves(observed, attempt['curve'], target=target, height=height, area=area)
    complete = bool(attempt.get('endpoint_reached') and attempt.get('solver_status') == 'complete')
    if complete and attempt['curve'][-1]['displacement_mm'] < target - max(1e-8, target * 1e-6):
        raise ValueError('Complete-solve receipt conflicts with its actual curve endpoint')
    status = 'completed' if complete else 'partial'
    directory = run / 'report'
    directory.mkdir(exist_ok=overwrite)
    specimen = str(payload.get('specimen_id') or evidence.get('specimen_id') or 'Specimen')
    artifacts = _plot_comparison(directory, observed, attempt['curve'], comparison,
                                 specimen=specimen, status=status, convention=convention)
    for row in table:
        row['experimental_raw_stroke_mm'] = row['displacement_mm'] + float(convention.get('displacement_offset_mm', 0))
    with (directory / 'shared_points.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    contours, images = _actual_contours(run, directory, attempt, specimen, status)
    artifacts.update(images)
    resources = read_json(run / 'resources_summary.json') if (run / 'resources_summary.json').is_file() else metadata.get('resources', {})
    stored = attempt.get('comparison', {})
    comparisons = {key: {'study_value': stored.get(key), 'independent_value': comparison[key],
                         'matches': math.isclose(float(stored[key]), comparison[key], rel_tol=1e-7, abs_tol=1e-7)}
                   for key in ('peak_error_pct', 'work_error_pct', 'rmse_N')
                   if isinstance(stored.get(key), (int, float)) and comparison.get(key) is not None}
    result_report = {'schema': 'analysis_fem_validation_report.v1', 'status': status,
                     'selected_attempt_id': attempt['attempt_id'], 'selected_attempt_index': selected,
                     'attempt_selection': 'last attempt with an actual curve, unless explicitly requested; not best-fit selection',
                     'comparison': comparison, 'comparison_crosscheck': comparisons,
                     'coordinate_convention': convention, 'material': payload.get('material'),
                     'mesh_size_mm': attempt.get('mesh_size_mm'), 'mesh_quality': attempt.get('mesh_quality'),
                     'convergence': result.get('convergence'), 'resources': resources, 'contours': contours,
                     'raw_bo_objective_changed': False, 'material_promoted': False,
                     'artifacts': artifacts, 'caveats': [
                         'Same-acquisition comparison only; no independent predictive validation or material promotion.',
                         'Engineering strain/stress use planned initial height/area, not local true strain/stress.',
                         'No fixture compliance correction, displacement fit, or post-hoc force scaling is applied.',
                         'Partial curves describe only their computed interval; target completion is separate from agreement.',
                         'Resource measurements exclude external LLM server resources; consult sampler limitation metadata.']}
    write_json(directory / 'metrics.json', result_report)
    sources = {str(path): sha256(path) for path in (result_path, run / 'evidence.json', run / 'run_metadata.json')}
    if (run / 'resources_summary.json').is_file():
        sources[str(run / 'resources_summary.json')] = sha256(run / 'resources_summary.json')
    write_json(directory / 'provenance.json', {'schema': 'analysis_fem_report_provenance.v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'run_directory': str(run),
        'source_json_hashes': sources, 'verified_frozen_inputs': verified_inputs,
        'runner_source_hashes_before': metadata.get('source_hashes_before'),
        'runner_source_hashes_after': metadata.get('source_hashes_after'),
        'source_files_unchanged': metadata.get('source_files_unchanged'),
        'original_frd_read': False, 'contours': contours,
        'artifact_hashes': {path: sha256(path) for path in artifacts.values()},
        'exporter': str(Path(__file__).resolve()), 'exporter_sha256': sha256(__file__)})
    return result_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run_directory', type=Path)
    parser.add_argument('--attempt-index', type=int, help='Zero-based explicit attempt selection; default last attempt with a curve')
    parser.add_argument('--overwrite-report', action='store_true', help='Replace only this exporter\'s report files on an explicit rerun')
    args = parser.parse_args(argv)
    report = export_report(args.run_directory, attempt_index=args.attempt_index, overwrite=args.overwrite_report)
    print(json.dumps({'status': report['status'], 'comparison': report['comparison'],
                      'contours': report['contours'].get('status'), 'artifacts': report['artifacts']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
