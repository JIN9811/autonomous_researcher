"""Bounded, evidence-driven FEM studies, separate from material promotion.

All external activity is injected. Native preparation and solving require an
explicit bounded decision, and mesh validity/quality gates cannot be overridden
by model prose. The owner handles serialization, cancellation and persistence.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path

import numpy as np

from agents.analysis_improvement import curve_error
from agents.analysis_mechanisms import assess_mechanisms, evidence_options


PREPARE = 'cae.prepare_static_analysis'
SOLVE = 'cae.run_static_analysis'


def _finite_evidence(value):
    """Unknown/nonfinite native metrics remain null, never fabricated numbers."""
    if isinstance(value, dict):
        return {key: _finite_evidence(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_evidence(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Nonfinite numerical evidence')
    return number


def _curve(rows, *, min_points=2):
    points = [[_number(p['displacement_mm']), _number(p['force_N'])]
              if isinstance(p, dict) else [_number(p[0]), _number(p[1])]
              for p in rows]
    if len(points) < min_points or any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        raise ValueError('A finite, strictly increasing curve is required')
    return points


def _points(rows):
    return [{'displacement_mm': x, 'force_N': y} for x, y in rows]


def _clip(rows, start, end):
    array = np.asarray(rows, dtype=float)
    axis = sorted({start, end, *(x for x, _ in rows if start < x < end)})
    return [[float(x), float(y)] for x, y in zip(axis, np.interp(axis, array[:, 0], array[:, 1]))]


def _comparison(observed, simulated, target):
    empty = {'end_mm': None, 'peak_error_pct': None, 'work_error_pct': None, 'rmse_N': None}
    if len(observed) < 2 or len(simulated) < 2:
        return empty
    start = max(observed[0][0], simulated[0][0], 0.0)
    end = min(observed[-1][0], simulated[-1][0], target)
    if end <= start:
        return empty
    exp, sim = _clip(observed, start, end), _clip(simulated, start, end)
    peak_exp, peak_sim = max(y for _, y in exp), max(y for _, y in sim)
    def work(curve):
        return sum((b[0] - a[0]) * (a[1] + b[1]) / 2 for a, b in zip(curve, curve[1:]))
    work_exp, work_sim = work(exp), work(sim)
    return {'end_mm': end,
            'peak_error_pct': 100 * (peak_sim - peak_exp) / abs(peak_exp) if peak_exp else None,
            'work_error_pct': 100 * (work_sim - work_exp) / abs(work_exp) if work_exp else None,
            'rmse_N': curve_error(exp, sim)}


def _coordinates(evidence):
    # Foreground observations may already be clipped at the raw loading target.
    # Detect contact against the full measured curve before selecting overlap.
    rows = _curve(evidence.get('experiment_curve') or evidence.get('observation') or [])
    convention = deepcopy(evidence.get('coordinate_convention') or {'name': 'raw_displacement'})
    name = convention.get('name', 'raw_displacement')
    convention.update(displacement_offset_mm=0.0, force_offset_N=0.0)
    if name == 'contact_threshold':
        baseline = rows[0][1]
        threshold = max(_number(convention.get('absolute_force_threshold_N', 2)),
                        _number(convention.get('relative_force_threshold', .01)) * max(y for _, y in rows))
        if threshold < 0:
            raise ValueError('Contact threshold must not be negative')
        contact = next((x for x, y in rows if y - baseline > threshold), None)
        if contact is None:
            raise ValueError('Declared contact threshold was not reached')
        convention.update(displacement_offset_mm=contact, force_offset_N=baseline,
                          threshold_N=threshold, method='first_threshold_crossing_no_fitted_shift')
        rows = [[x - contact, y - baseline] for x, y in rows if x >= contact]
        rows = _curve(rows)
    elif name != 'raw_displacement':
        raise ValueError('Unknown displacement coordinate convention')
    return rows, convention


def _target(evidence, payload):
    loading = payload.get('loading') or {}
    explicit = payload.get('target_displacement_mm', loading.get('target_displacement_mm'))
    if explicit is None:
        geometry = evidence.get('specimen_geometry') or {}
        size = payload.get('specimen_size_mm') or geometry.get('specimen_size_mm') or []
        height = size[2] if len(size) >= 3 else payload.get('gauge_length_mm', geometry.get('gauge_length_mm'))
        explicit = _number(loading.get('target_strain', payload.get('target_strain'))) * _number(height)
    target = _number(explicit)
    if target <= 0:
        raise ValueError('Positive declared loading target required')
    return target


def _verify_inputs(evidence):
    hashes = evidence.get('input_hashes') or {}
    source = (evidence.get('payload') or {}).get('stl_path')
    if source and str(Path(source).resolve()) not in {str(Path(p).resolve()) for p in hashes}:
        raise ValueError('Frozen geometry has no hash')
    for filename, expected in hashes.items():
        actual = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('Frozen input hash changed')


def _mesh_gate(mesh, policy):
    if not isinstance(mesh, dict):
        return False, 'invalid_or_unknown'
    validity, quality = mesh.get('validity'), mesh.get('quality')
    valid = validity.get('status') == 'valid' if isinstance(validity, dict) else validity == 'valid'
    if not valid:
        return False, 'invalid_or_unknown'
    if isinstance(quality, dict):
        try:
            good = (_number(quality['minimum']) > 0 and
                    _number(quality['percentile_5']) >= _number(policy.get('mesh_quality_min_percentile_5', .1)) and
                    _number(quality['below_threshold_fraction']) <= _number(policy.get('mesh_quality_max_bad_fraction', .05)))
        except (KeyError, TypeError, ValueError):
            good = False
    else:
        good = quality in {'good', 'acceptable'}
    return good, 'acceptable' if good else 'poor_or_unknown'


def _convergence(attempts, target, policy, requested):
    tolerance = _number(policy.get('convergence_tolerance_pct', 5.0))
    full = [a for a in attempts if a['endpoint_reached'] and a['solver_status'] == 'complete'
            and a['curve'] and a['curve'][0]['displacement_mm'] <= 0]
    distinct = {a['mesh_size_mm']: a for a in full}
    rows = sorted(distinct.values(), key=lambda a: a['mesh_size_mm'], reverse=True)
    output = {'status': 'insufficient_evidence' if requested else 'not_assessed',
              'full_resolution_count': len(rows), 'required_resolution_count': 3,
              'tolerance_pct': tolerance, 'comparisons': []}
    if len(rows) < 3:
        return output
    for first, second in zip(rows[-3:], rows[-2:]):
        metrics = _comparison(_curve(first['curve']), _curve(second['curve']), target)
        peak = max(abs(p['force_N']) for p in first['curve'])
        metrics['normalized_rmse_pct'] = 100 * metrics['rmse_N'] / peak if peak else None
        metrics['attempt_ids'] = [first['attempt_id'], second['attempt_id']]
        output['comparisons'].append(metrics)
    output['status'] = 'converged' if all(
        m[key] is not None and abs(m[key]) <= tolerance
        for m in output['comparisons'] for key in ('peak_error_pct', 'work_error_pct', 'normalized_rmse_pct')
    ) else 'not_converged'
    return output


async def run_fem_study(evidence, choose, call_tool, emit):
    """Run one immutable study without timeouts or model/material promotion.

    ``policy`` may declare ``mesh_size_factors`` (default 1/.75/.5),
    ``max_mesh_actions``, ``max_fem_jobs``, and quality/convergence tolerances.
    Decisions receive trusted numerical summaries and existing image paths only.
    Cancellation intentionally propagates to the owner and its native boundary.
    """
    if (evidence.get('policy') or {}).get('calibration') is not None:
        from agents.analysis_calibration import calibrate
        return await calibrate(evidence, choose, call_tool, emit)
    evidence = deepcopy(evidence)
    attempts, decisions = [], []
    summary = {'convergence': {'status': 'not_assessed'}, 'material_promoted': False}
    result = {'status': 'held', 'attempts': attempts, 'decisions': decisions, 'summary': summary,
              'experiment_curve': [], 'coordinate_convention': {},
              'convergence': summary['convergence']}
    try:
        _verify_inputs(evidence)
    except (OSError, ValueError, TypeError):
        result['status'] = 'failed'
        summary['failure_code'] = 'FEM_INPUT_HASH_MISMATCH'
        return result
    try:
        payload = deepcopy(evidence['payload'])
        policy = evidence.get('policy') or {}
        observed, convention = _coordinates(evidence)
        target = _target(evidence, payload)
        factors = policy.get('mesh_size_factors', [1.0, .75, .5])
        sizes = [_number(payload.get('mesh_size_mm', 2)) * _number(factor) for factor in factors]
        if not sizes or len(sizes) > 32 or any(size <= 0 for size in sizes) or len(set(sizes)) != len(sizes):
            raise ValueError('Distinct positive finite mesh candidates required (at most 32)')
        max_mesh = min(len(sizes), max(0, int(policy.get('max_mesh_actions', len(sizes)))))
        max_jobs = min(32, max(0, int(policy.get('max_fem_jobs', 3))))
        if _number(policy.get('convergence_tolerance_pct', 5)) < 0:
            raise ValueError('Convergence tolerance must be nonnegative')
        if payload.get('surface_remesh'):
            if _number(payload['surface_remesh']['edge_length_mm']) <= 0:
                raise ValueError('Positive surface resolution required')
        job_id = str(evidence['job_id'])
        if not job_id:
            raise ValueError('Study job identity required')
    except (KeyError, TypeError, ValueError, OverflowError):
        result['status'] = 'failed'
        summary['failure_code'] = 'FEM_EVIDENCE_INVALID'
        return result
    summary.update(target_displacement_mm=target, coordinate_convention=convention,
                   comparison_curve=_points(observed), mesh_candidates_mm=sizes)
    result.update(experiment_curve=_points(observed), coordinate_convention=convention)
    requested, jobs = False, 0

    def progress(phase, message, **extra):
        emit(deepcopy({'phase': phase, 'message': message, 'attempts': attempts,
                       'experiment_curve': result['experiment_curve'],
                       'coordinate_convention': convention, 'convergence': summary['convergence'], **extra}))

    async def decision(phase, options, **extra):
        info = {**evidence, 'attempts': attempts, 'summary': summary,
                'experiment_curve': result['experiment_curve'],
                'coordinate_convention': convention, **extra}
        images = list(evidence.get('image_paths') or [])
        for attempt in attempts:
            images.extend(value for value in attempt.get('artifacts', {}).values()
                          if isinstance(value, str) and value.lower().endswith(('.png', '.jpg', '.jpeg')))
        # The owner validates allowed roots before loading these artifact images.
        info['image_paths'] = list(dict.fromkeys(images))[-2:]
        decision_failed = False
        try:
            choice = await choose(phase, deepcopy(info), dict(options))
        except Exception as exc:
            # A failed optional review must not discard or repeat successful
            # native work. Cancellation (BaseException) still reaches the owner.
            decision_failed = True
            choice = {'option_id': 'hold', 'source': 'decision_error',
                      'error_type': type(exc).__name__,
                      'reason': 'Decision review failed; retained numerical evidence requires review.'}
            summary.update(review_status='failed', review_failure_phase=phase)
        selected = choice.get('option_id') if isinstance(choice, dict) else None
        accepted = (not decision_failed and isinstance(selected, str) and selected in options
                    and choice.get('tool', options.get(selected)) == options.get(selected))
        record = {**(choice if isinstance(choice, dict) else {}), 'phase': phase,
                  'option_id': selected if accepted else 'hold', 'accepted': accepted}
        decisions.append(record)
        progress(phase, str(record.get('reason') or 'Bounded FEM decision'), decision=record)
        return record['option_id']

    async def invoke(name, params):
        try:
            _verify_inputs(evidence)
        except (OSError, ValueError, TypeError):
            summary['failure_code'] = 'FEM_INPUT_HASH_MISMATCH'
            result['status'] = 'failed'
            return None
        try:
            response = await call_tool(name, deepcopy(params))
            if not isinstance(response, dict):
                raise ValueError('Tool returned an invalid receipt')
            return _finite_evidence(response)
        except Exception as exc:
            # CancelledError is a BaseException and must reach the owner.
            summary.update(failure_code='FEM_TOOL_ERROR', tool=name, error_type=type(exc).__name__)
            result['status'] = 'failed'
            return None

    next_action = await decision('fem_mesh', {'prepare_mesh': PREPARE, 'hold': None})
    for index, size in enumerate(sizes[:max_mesh]):
        if next_action not in {'prepare_mesh', 'remesh', 'convergence'} or jobs >= max_jobs:
            break
        attempt_id = f"fem_{hashlib.sha256(job_id.encode()).hexdigest()[:24]}_{index + 1:02d}"
        attempt = {'attempt_id': attempt_id, 'mesh_size_mm': size, 'mesh_quality': {},
                   'curve': [], 'comparison': _comparison([], [], target),
                   'field_asset_path': '', 'solver_status': 'not_run', 'endpoint_reached': False}
        attempts.append(attempt)
        params = {**deepcopy(payload), 'specimen_id': attempt_id,
                  'original_specimen_id': payload.get('specimen_id'), 'job_id': job_id,
                  **{key:evidence[key] for key in ('run_id', 'loop_key') if evidence.get(key)},
                  'mesh_size_mm': size,
                  'computation_limits': {**(payload.get('computation_limits') or {}), 'timeout_s': None}}
        if params.get('surface_remesh'):
            params['surface_remesh']['edge_length_mm'] = _number(payload['surface_remesh']['edge_length_mm']) * _number(factors[index])
            attempt['surface_remesh'] = deepcopy(params['surface_remesh'])
        progress('mesh_preparing', f'Preparing mesh {index + 1} at {size:g} mm')
        prepared = await invoke(PREPARE, params)
        if prepared is None:
            break
        attempt['mesh_quality'] = deepcopy(prepared.get('mesh_quality') or {})
        attempt['artifacts'] = deepcopy(prepared.get('artifacts') or prepared.get('paths') or {})
        if prepared.get('status') == 'cancelled':
            result['status'] = 'cancelled'
            break
        good, gate = _mesh_gate(attempt['mesh_quality'], policy)
        good = bool(good and prepared.get('ok') and prepared.get('prepared_input'))
        attempt['quality_gate'] = gate if prepared.get('ok') else 'preparation_failed'
        receipt_target = (prepared.get('prepared_input') or {}).get('target_displacement_mm')
        if receipt_target is not None:
            try:
                matches_target = math.isclose(_number(receipt_target), target, rel_tol=1e-8, abs_tol=1e-8)
            except (TypeError, ValueError):
                matches_target = False
            if not matches_target:
                good = False
                attempt['quality_gate'] = 'prepared_target_mismatch'
        if not good:
            requested = True
        more = index + 1 < max_mesh and jobs < max_jobs
        options = {}
        if good:
            options['solve_mesh'] = SOLVE
            options['convergence'] = SOLVE
        if more:
            options['remesh'] = PREPARE
        options['hold'] = None
        next_action = await decision('fem_mesh_assessment', options,
                                     prepared=prepared, convergence_required=requested)
        if next_action == 'remesh':
            continue
        if next_action not in {'solve_mesh', 'convergence'} or not good:
            break
        requested = requested or next_action == 'convergence'
        progress('fem_solving', 'Solving the assessed prepared mesh')
        solved = await invoke(SOLVE, {**params, 'prepared_input': deepcopy(prepared['prepared_input'])})
        if solved is None:
            break
        jobs += 1
        raw_curve = solved.get('reaction_force_displacement_curve', solved.get('curve', []))
        try:
            curve = _curve(raw_curve, min_points=1)
        except (KeyError, TypeError, ValueError, IndexError):
            curve = []
            attempt['curve_failure_code'] = 'FEM_CURVE_INVALID'
        attempt['curve'] = _points(curve)
        tolerance = max(1e-8, target * 1e-6)
        complete = bool(solved.get('ok') and solved.get('status') in {'complete', 'completed'} and curve and
                        curve[-1][0] >= target - tolerance and
                        (solved.get('metrics') or {}).get('endpoint_reached', True))
        attempt['endpoint_reached'] = complete
        attempt['solver_status'] = 'complete' if complete else 'partial' if curve else 'failed'
        attempt['solver_reported_status'] = solved.get('status')
        attempt['solver_mode'] = solved.get('solver_mode')
        attempt['comparison'] = _comparison(observed, curve, target)
        attempt['artifacts'].update(deepcopy(solved.get('artifacts') or {}))
        attempt['field_asset_path'] = str(attempt['artifacts'].get('field_asset_path') or solved.get('field_asset_path') or '')
        from agents.analysis_decisions import compact_evidence
        attempt['field_summary'] = compact_evidence(solved.get('field_manifest') or solved.get('field_summary') or {})
        attempt['failure_code'] = solved.get('failure_code')
        summary['convergence'] = _convergence(attempts, target, policy, requested)
        progress('fem_result', 'Comparing actual solver history over the shared displacement interval')
        if solved.get('status') == 'cancelled' or (solved.get('solve') or {}).get('status') == 'cancelled':
            result['status'] = 'cancelled'
            break
        options = {'conclude': None, 'hold': None}
        report = assess_mechanisms(evidence, attempts, summary['convergence'])
        result['mechanism_assessment'] = report
        options.update(evidence_options(report))
        if index + 1 < max_mesh and jobs < max_jobs:
            options['convergence'] = PREPARE
        next_action = await decision('fem_result', options, mechanism_assessment=report)
        if next_action in evidence_options(report):
            summary['next_evidence_action'] = next_action
            progress('fem_evidence_requested', 'Research evidence requested; no equipment or model changes',
                     next_evidence_action=next_action)
        requested = requested or next_action == 'convergence'
    summary['convergence'] = _convergence(attempts, target, policy, requested)
    result['convergence'] = summary['convergence']
    result['mechanism_assessment'] = assess_mechanisms(evidence, attempts, result['convergence'])
    summary['attempt_count'], summary['solve_count'] = len(attempts), jobs
    summary['full_target_solve_count'] = sum(a['endpoint_reached'] for a in attempts)
    if result['status'] not in {'failed', 'cancelled'}:
        result['status'] = ('completed' if any(a['endpoint_reached'] for a in attempts) else
                            'partial' if any(a['curve'] for a in attempts) else
                            'failed' if jobs else 'held')
    progress('fem_study_finished', 'FEM study finished; measured objectives and material remain unchanged',
             summary=summary, status=result['status'])
    return result
