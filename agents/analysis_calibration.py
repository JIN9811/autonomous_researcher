"""Feature-informed, computation-only inverse FE studies.

Measured curves are objective evidence, never constitutive input. Each candidate
is an actual forward FEM solve with a small analytic material law. One specimen
can calibrate a hypothesis, but cannot establish independent predictive validity.
"""
from __future__ import annotations

from copy import deepcopy
import math

import numpy as np

from agents.analysis_fem import _clip, _coordinates, _curve, _target, _verify_inputs
from agents.analysis_improvement import curve_error


PARAMETERS = {'peak_flow_mpa', 'residual_flow_mpa', 'decay_plastic_strain'}


def _positive(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a model parameter')
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Positive finite parameter required')
    return value


def _full_curve(rows, target):
    target = _positive(target)
    curve = _curve(rows)
    if curve[0][0] > 1e-8 or curve[-1][0] < target - 1e-8:
        raise ValueError('Full declared comparison domain required; no extrapolation')
    return _clip(curve, 0., target)


def response_features(curve, target_mm):
    """Deterministic features in an already declared displacement convention.

    Secants/windows are fractions of the requested domain, not claims of a
    measured Young modulus or automatic identification of physical regimes.
    """
    rows = _full_curve(curve, target_mm)
    data = np.asarray(rows)
    target = float(target_mm)
    peak = max(rows, key=lambda row: row[1])
    def value(fraction):
        return float(np.interp(fraction * target, data[:, 0], data[:, 1]))
    def integral(points):
        return sum((b[0] - a[0]) * (a[1] + b[1]) / 2 for a, b in zip(points, points[1:]))
    return {'peak_force_N': peak[1], 'peak_displacement_mm': peak[0],
            'work_J': integral(rows) / 1000,
            'early_secant_N_per_mm': (value(.08) - value(.02)) / (.06 * target),
            'middle_mean_force_N': integral(_clip(rows, .4 * target, .8 * target)) / (.4 * target),
            'late_secant_N_per_mm': (value(1) - value(.8)) / (.2 * target),
            'end_force_N': value(1), 'domain_mm': [0., target]}


def compare_response(observed, predicted, target_mm):
    observed, predicted = _full_curve(observed, target_mm), _full_curve(predicted, target_mm)
    exp, sim = response_features(observed, target_mm), response_features(predicted, target_mm)
    scale = max(abs(y) for _, y in observed)
    if scale <= 0 or exp['work_J'] <= 0:
        raise ValueError('Positive measured loading response required')
    # Force and slope norms do not explode for a nearly flat late response.
    peak_position_norm = max(exp['peak_displacement_mm'], .01 * target_mm)
    errors = {
        'normalized_rmse_pct': 100 * curve_error(observed, predicted) / scale,
        'peak_force_pct': 100 * (sim['peak_force_N'] - exp['peak_force_N']) / scale,
        'peak_position_pct': 100 * (sim['peak_displacement_mm'] - exp['peak_displacement_mm']) / peak_position_norm,
        'work_pct': 100 * (sim['work_J'] - exp['work_J']) / exp['work_J'],
        'early_secant_normalized_pct': 100 * (sim['early_secant_N_per_mm'] - exp['early_secant_N_per_mm']) * (.06 * target_mm) / scale,
        'middle_mean_force_pct': 100 * (sim['middle_mean_force_N'] - exp['middle_mean_force_N']) / scale,
        'late_secant_normalized_pct': 100 * (sim['late_secant_N_per_mm'] - exp['late_secant_N_per_mm']) * (.2 * target_mm) / scale,
    }
    weights = {'normalized_rmse_pct': .35, 'peak_force_pct': .15, 'peak_position_pct': .15,
               'work_pct': .15, 'early_secant_normalized_pct': .05,
               'middle_mean_force_pct': .1, 'late_secant_normalized_pct': .05}
    return {'objective': sum(weights[k] * (v / 100) ** 2 for k, v in errors.items()),
            'objective_definition': 'weighted squared dimensionless full-domain feature/curve errors',
            'weights': weights, 'errors': errors, 'experiment': exp, 'prediction': sim,
            'comparison_domain_mm': [0., float(target_mm)], 'extrapolation_applied': False}


def material_from_parameters(parameters, base_material):
    """An exponential saturation/softening hypothesis in equivalent plastic strain.

    The material law has no access to target specimen response or geometry.
    This local law is not regularized; mesh sensitivity remains a separate gate.
    """
    if set(parameters) != PARAMETERS:
        raise ValueError('Exactly the registered constitutive parameters are required')
    peak, residual, decay = (_positive(parameters[k]) for k in
                             ('peak_flow_mpa', 'residual_flow_mpa', 'decay_plastic_strain'))
    if residual > peak:
        raise ValueError('Residual flow must not exceed initial flow in this model family')
    # Resolve the analytic law, not a measured specimen curve. At 8 decay scales
    # the remaining transient is <0.04%; CalculiX holds the final value thereafter.
    strains = sorted({0., *[decay * i / 4 for i in range(1, 33)], 1.0})
    material = deepcopy(base_material)
    material['yield_strength_mpa'] = peak
    material['plastic_curve'] = [[residual + (peak - residual) * math.exp(-p / decay), p] for p in strains]
    return material


def _search_policy(evidence):
    policy = evidence['policy']['calibration']
    initial = {k: _positive(v) for k, v in policy['initial'].items()}
    material_from_parameters(initial, evidence['payload'].get('material', {}))
    bounds = policy['bounds']
    if not isinstance(bounds, dict) or not bounds or set(bounds) - PARAMETERS:
        raise ValueError('Explicit registered parameter bounds required')
    bounds = {k: tuple(_positive(v) for v in interval) for k, interval in bounds.items()}
    if any(len(b) != 2 or b[0] >= b[1] or not b[0] <= initial[k] <= b[1] for k, b in bounds.items()):
        raise ValueError('Initial parameters must lie inside finite increasing bounds')
    maximum = policy.get('max_evaluations', 5)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 32:
        raise ValueError('At most 32 evaluations per isolated study')
    step = _positive(policy.get('step_fraction', .25))
    if step > .5:
        raise ValueError('Search step fraction must not exceed one half of each interval')
    return initial, bounds, maximum, step


async def calibrate(evidence, choose, call_tool, emit):
    """Bounded deterministic pattern search using the existing FEM study path.

    No promotion/store writes. A fresh prediction requires a frozen exported
    material plus a different acquisition; no claim of that test is made here.
    """
    from agents.analysis_fem import run_fem_study

    evidence = deepcopy(evidence)
    records, decisions, attempts = [], [], []
    calibration = {'status': 'no_eligible_candidate', 'records': records, 'best_parameters': None,
                   'best_comparison': None, 'independent_validation': 'not_performed',
                   'model_family': 'local_exponential_post_yield', 'material_parameter_source': 'bounded_inverse_FE_study',
                   'regularization': 'none; transfer requires separate mesh-sensitivity evidence',
                   'search_method': 'bounded_coordinate_pattern_search'}
    result = {'status': 'held', 'attempts': attempts, 'decisions': decisions, 'calibration': calibration,
              'summary': {'material_promoted': False, 'convergence': {'status': 'not_assessed'}},
              'convergence': {'status': 'not_assessed'}}
    try:
        _verify_inputs(evidence)
        if evidence.get('source_kind') != 'measured' or evidence.get('paired_identity_verified') is not True:
            raise ValueError('Paired measured acquisition identity required for calibration')
        initial, bounds, maximum, step = _search_policy(evidence)
        observed, convention = _coordinates(evidence)
        target = _target(evidence, evidence['payload'])
        features = response_features(observed, target)
        compare_response(observed, observed, target)  # Reject unusable loading before any expensive work.
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        result.update(status='failed')
        result['summary'].update(failure_code='FEM_CALIBRATION_INVALID', detail=str(exc))
        return result
    calibration.update(initial=initial, bounds=bounds, max_evaluations=maximum,
                       fixed_material=deepcopy(evidence['payload'].get('material', {})))
    result.update(experiment_curve=[{'displacement_mm': x, 'force_N': y} for x, y in observed],
                  coordinate_convention=convention)
    result['summary'].update(target_displacement_mm=target, coordinate_convention=convention)
    from agents.analysis_mechanisms import assess_mechanisms, evidence_options
    mechanism = assess_mechanisms(evidence, [], result['convergence'])
    result['mechanism_assessment'] = mechanism
    calibration['mechanism_assessment'] = mechanism
    options = {'calibrate': 'cae.prepare_static_analysis', 'hold': None} if mechanism['calibration_admissible'] else {
        **evidence_options(mechanism), 'hold': None}
    decision = await choose('fem_calibration_assessment', {
        'model_family': calibration['model_family'], 'initial_parameters': initial, 'bounds': bounds,
        'measured_features': features, 'independent_validation': 'not_performed',
        'purpose': 'Calibration-only model hypothesis; no material promotion. Existing geometry and loading stay frozen.',
        'local_softening_limitation': calibration['regularization'],
        'mechanism_assessment': mechanism,
    }, options)
    decisions.append(decision)
    if not mechanism['calibration_admissible']:
        result['summary']['failure_code'] = 'FEM_MECHANISM_EVIDENCE_REQUIRED'
        selected = decision.get('option_id')
        result['summary']['next_evidence_action'] = selected if selected in options else 'hold'
        emit({'phase': 'fem_evidence_requested', 'status': 'held', 'mechanism_assessment': mechanism,
              'message': 'Material/deformation evidence required before constitutive identification'})
        return result
    if decision.get('option_id') != 'calibrate' or decision.get('tool', 'cae.prepare_static_analysis') != 'cae.prepare_static_analysis':
        return result
    best, visited, stopped = None, set(), False

    async def evaluate(parameters):
        nonlocal best, stopped
        key = tuple((k, round(parameters[k], 12)) for k in sorted(parameters))
        if key in visited or len(records) >= maximum or stopped:
            return
        try:
            material = material_from_parameters(parameters, evidence['payload'].get('material', {}))
        except ValueError:
            visited.add(key)
            return
        visited.add(key)
        child = deepcopy(evidence)
        child['policy'].pop('calibration')
        # Search compares the same declared discretization. Distinct material
        # candidates must never be mistaken for a mesh-convergence sequence.
        child['policy'].update(max_mesh_actions=1, max_fem_jobs=1, mesh_size_factors=[1.])
        child['job_id'] = f"{evidence['job_id']}-cal-{len(records) + 1:03d}"
        child['payload']['material'] = material
        child['payload'].pop('reference_calibration', None)
        child['calibration_context'] = {'candidate_parameters': parameters, 'measured_features': features,
                                       'previous_candidates': records, 'purpose': 'calibration only, no promotion'}
        emit({'phase': 'fem_calibration_candidate', 'parameters': parameters, 'candidate_number': len(records) + 1,
              'message': 'Forward FEM with numerically proposed constitutive parameters', 'attempts': deepcopy(attempts)})
        def child_progress(event):
            event = deepcopy(event)
            event['attempts'] = deepcopy(attempts) + event.get('attempts', [])
            event.pop('status', None)
            if event.get('phase') == 'fem_study_finished':
                event['phase'] = 'fem_calibration_candidate_finished'
            emit(event)
        study = await run_fem_study(child, choose, call_tool, child_progress)
        mechanism = study.get('mechanism_assessment') or assess_mechanisms(child, study['attempts'], study['convergence'])
        result['mechanism_assessment'] = mechanism
        calibration['mechanism_assessment'] = mechanism
        if mechanism['numerical_status'] == 'incomplete':
            result['status'] = 'held'
            result['summary']['next_evidence_action'] = 'review_solver_diagnostics'
            calibration['retention_status'] = 'held'
            stopped = True
        record = {'parameters': deepcopy(parameters), 'material': material, 'status': study['status'],
                  'attempt_ids': [a['attempt_id'] for a in study['attempts']], 'comparison': None,
                  'mechanism_assessment': mechanism}
        records.append(record)
        for attempt in study['attempts']:
            attempt['calibration_parameters'] = deepcopy(parameters)
            attempt['material'] = deepcopy(material)
            attempts.append(attempt)
        decisions.extend(study['decisions'])
        if study.get('summary', {}).get('next_evidence_action'):
            result['status'] = 'held'
            result['summary']['next_evidence_action'] = study['summary']['next_evidence_action']
            calibration['retention_status'] = 'held'
            stopped = True
        if any(d.get('option_id') == 'hold' for d in study['decisions']):
            result['status'] = 'held'
            calibration['retention_status'] = 'held'
            stopped = True
        if study['status'] in {'cancelled', 'held', 'failed'}:
            result['status'] = study['status']
            stopped = True
        full = [a for a in study['attempts'] if a['endpoint_reached'] and a['solver_status'] == 'complete'
                and a.get('solver_mode') in {'calculix_quasistatic', 'calculix'}]
        if full:
            try:
                record['comparison'] = compare_response(observed, full[-1]['curve'], target)
                if best is None or record['comparison']['objective'] < best['comparison']['objective']:
                    best = record
            except ValueError as exc:
                record['ineligible_reason'] = str(exc)
        emit({'phase': 'fem_calibration_result', 'candidate': deepcopy(record),
              'message': 'Full-domain feature and curve errors; partial solves cannot be selected',
              'attempts': deepcopy(attempts), 'calibration': deepcopy(calibration)})

    await evaluate(initial)
    while len(records) < maximum and not stopped:
        center = deepcopy(best['parameters'] if best else initial)
        before = best['comparison']['objective'] if best else math.inf
        count = len(records)
        for name, (lower, upper) in bounds.items():
            for sign in (1, -1):
                trial = {**center, name: min(upper, max(lower, center[name] + sign * step * (upper - lower)))}
                await evaluate(trial)
        if best is None or best['comparison']['objective'] >= before:
            step /= 2
        if step < 1e-3 or (count == len(records) and step < .01):
            break
        if best and best['comparison']['objective'] < 1e-12:
            break
    if best:
        calibration.update(best_parameters=best['parameters'], best_material=best['material'],
                           best_comparison=best['comparison'], best_attempt_ids=best['attempt_ids'])
        errors = best['comparison']['errors']
        limits = {k: 20. for k in errors}
        limits.update(normalized_rmse_pct=10., peak_force_pct=10., work_pct=10.)
        passed = all(abs(errors[k]) <= limit for k, limit in limits.items())
        calibration.update(status='calibrated' if passed else 'fit_incomplete', acceptance_limits_pct=limits,
                           calibration_criteria_passed=passed)
        if not stopped:
            result['status'] = 'completed'
        review = await choose('fem_calibration_review', {
            'calibration': calibration, 'measured_features': features,
            'convergence': result['convergence'],
            'required_next_evidence': 'Mesh and increment sensitivity, then frozen forward prediction on a different acquisition.',
        }, {'retain_candidate': None, 'hold': None})
        decisions.append(review)
        calibration['review'] = review
        if review.get('option_id') != 'retain_candidate' or review.get('tool') is not None:
            result['status'] = 'held' if result['status'] not in {'failed', 'cancelled'} else result['status']
            calibration['retention_status'] = 'held'
        else:
            calibration.setdefault('retention_status', 'retained_for_research')
    elif not stopped:
        result['status'] = 'partial' if any(a['curve'] for a in attempts) else 'held'
    result['summary'].update(attempt_count=len(attempts), solve_count=sum(a['solver_status'] != 'not_run' for a in attempts),
                             full_target_solve_count=sum(a['endpoint_reached'] for a in attempts))
    emit({'phase': 'fem_calibration_finished', 'message': 'Calibration study retained; baseline and measured BO objective unchanged',
          'status': result['status'], 'attempts': deepcopy(attempts), 'calibration': deepcopy(calibration)})
    return result


def freeze_candidate(result, evidence):
    """Export a constitutive candidate usable by forward CAE without target CSV.

    This freezes parameters, not their validity. Adoption is explicit and the
    independent-validation/promotion gate remains owned by the existing registry.
    """
    calibration = result['calibration']
    from agents.analysis_mechanisms import assess_mechanisms
    mechanism = assess_mechanisms(evidence, result.get('attempts', []), result.get('convergence', {}))
    if not mechanism['calibration_admissible']:
        raise ValueError('Supported material and deformation evidence required before forward export')
    if result.get('status') != 'completed' or calibration.get('retention_status') != 'retained_for_research':
        raise ValueError('Only an explicitly retained completed study can export a forward candidate')
    if not calibration.get('best_parameters') or not calibration.get('best_comparison'):
        raise ValueError('A full-domain native candidate is required before export')
    return {'schema': 'analysis_frozen_material_candidate.v1', 'status': 'candidate_not_promoted',
            'model_family': calibration['model_family'],
            'parameters': deepcopy(calibration['best_parameters']),
            'material': deepcopy(calibration['best_material']),
            'source_job_id': evidence['job_id'], 'source_input_hashes': deepcopy(evidence['input_hashes']),
            'calibration_domain_mm': deepcopy(calibration['best_comparison']['comparison_domain_mm']),
            'coordinate_convention': deepcopy(result['coordinate_convention']),
            'calibration_errors': deepcopy(calibration['best_comparison']['errors']),
            'numerical_convergence': deepcopy(result['convergence']),
            'independent_validation': 'not_performed', 'regularization': calibration['regularization'],
            'retention_status': calibration['retention_status'], 'review': deepcopy(calibration['review']),
            'mechanism_assessment': mechanism,
            'use': 'Pass material to existing cae.prepare_static_analysis / cae.run_static_analysis with new geometry and loading; do not pass the target measurement.'}
