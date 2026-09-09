"""Bounded, registered-candidate numerical refinement."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import time

from agents.analysis_improvement import curve_error, digest
from utils.calculix_quasistatic import validate_plastic_curve


def _candidates(policy, base):
    bounds = policy.get('bounds', {})
    allowed = {'elastic_modulus_mpa', 'poisson_ratio', 'yield_strength_mpa'}
    candidates = []
    for patch in policy.get('candidates', [])[:12]:
        if not isinstance(patch, dict) or set(patch) != {'material'} or not isinstance(patch['material'], dict) or not patch['material']:
            continue
        valid = True
        for key, value in patch['material'].items():
            if key == 'plastic_curve':
                try:
                    curve = validate_plastic_curve(value)
                    intervals = [bounds.get('flow_stress_mpa'), bounds.get('plastic_strain')]
                    if not curve or any(not isinstance(b, list) or len(b) != 2 for b in intervals):
                        raise ValueError('Explicit stress and plastic-strain bounds required')
                    for column, interval in enumerate(intervals):
                        lower, upper = map(float, interval)
                        if not all(math.isfinite(v) for v in (lower, upper)) or lower > upper:
                            raise ValueError('Invalid material curve bounds')
                        if any(not lower <= row[column] <= upper for row in curve):
                            raise ValueError('Material curve outside bounds')
                except (ValueError, TypeError, OverflowError):
                    valid = False
                    break
                continue
            interval = bounds.get(key)
            if key not in allowed or not isinstance(interval, list) or len(interval) != 2:
                valid = False
                break
            try:
                lower, upper, value = float(interval[0]), float(interval[1]), float(value)
                valid &= all(math.isfinite(x) for x in (lower, upper, value)) and lower <= value <= upper
                valid &= (-1 < value < 0.5) if key == 'poisson_ratio' else value > 0
            except (ValueError, TypeError):
                valid = False
        if valid:
            parameters = deepcopy(base)
            parameters['material'] = deepcopy({**base.get('material', {}), **patch['material']})
            candidates.append(parameters)
    return candidates


def _result_curve(result):
    if not result.get('ok') or result.get('solver_mode') not in {'calculix_quasistatic', 'calculix'}:
        raise ValueError('Real converged solver evidence required')
    curve = result.get('reaction_force_displacement_curve', [])
    if not curve and isinstance(result.get('result'), dict):
        curve = result['result'].get('reaction_force_displacement_curve', [])
    return [[float(p['displacement_mm']), float(p['force_N'])] for p in curve]


async def refine(store, evidence, choose, solve):
    """Select on training data, validate one candidate once on held-out experiments.

    `choose` receives phase/evidence/registered options; `solve` is a narrow
    computation-only callback. Neither receives a live mutable runtime state.
    Missing bounds/data means waiting, not invented parameter identification.
    """
    policy = evidence.get('policy', {})
    scope = evidence.get('scope', '')
    records = {}
    validation_ids = store.validation_ids(scope)
    raw_hashes = set()
    for job in store.jobs():
        item = job['evidence']
        acquisition = item.get('acquisition_id')
        raw_hash = item.get('raw_sha256')
        if (item.get('scope') == scope and item.get('source_kind') == 'measured'
                and item.get('paired_identity_verified') is True and item.get('observation')
                and acquisition and raw_hash and acquisition not in validation_ids and raw_hash not in raw_hashes):
            records.setdefault(acquisition, item)
            raw_hashes.add(raw_hash)
    decisions, receipts = [], []
    base = evidence.get('model', {})
    candidates = _candidates(policy, base.get('parameters', {}))
    if len(records) < 2 or not candidates:
        decision = await choose('improvement_assessment', {
            'independent_experiments': len(records), 'bounded_candidates': len(candidates),
            'missing': 'independent matching experiments and explicit parameter candidates/bounds',
        }, {'hold': None})
        return {'status': 'needs_more_data', 'reason': 'independent_evidence_or_parameter_bounds_required', 'decisions': [decision]}

    samples = list(records.values())[-4:]
    train, holdout = samples[:-1], samples[-1:]
    max_jobs = min(120, max(1, int(policy.get('max_solver_jobs', 12))))
    wall = min(3600.0, max(1.0, float(policy.get('max_wall_time_s', 600))))
    tolerance = float(policy.get('convergence_relative_tolerance', 0.02))
    if not math.isfinite(tolerance) or not 0 < tolerance < 1 or not math.isfinite(wall):
        return {'status': 'held', 'reason': 'invalid_numerical_policy'}
    started = time.monotonic()
    cache = {}

    async def evaluate(parameters, sample):
        curves = []
        for factor in (1.0, 0.75, 0.5):
            payload = deepcopy(sample['payload'])
            payload['material'] = deepcopy(parameters['material'])
            payload['mesh_size_mm'] = float(parameters.get('mesh_size_mm', payload.get('mesh_size_mm', 2))) * factor
            for filename, expected in sample.get('input_hashes', {}).items():
                if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != expected:
                    raise ValueError('Frozen input changed')
            key = digest({'payload': payload, 'input_hashes': sample.get('input_hashes', {}),
                          'solver_identity': policy.get('solver_identity'), 'method': 'three_mesh_curve_v1'})
            if key not in cache:
                # Cross-job reuse is enabled only with an explicit solver/build
                # identity. Unknown executable versions are never reused.
                cached = store.cached_solver(key) if policy.get('solver_identity') else None
                if cached is not None:
                    cache[key] = _result_curve(cached)
                    curves.append(cache[key])
                    continue
                if len(receipts) >= max_jobs or time.monotonic() - started >= wall:
                    raise TimeoutError('Refinement budget exhausted')
                payload['specimen_id'] = f"improve-{key[:24]}"
                payload['source'] = 'analysis_background_improvement'
                payload['computation_limits'] = {'timeout_s': max(1, wall - (time.monotonic() - started)), 'threads': 1,
                                                 'max_mesh_elements': int(policy.get('max_mesh_elements', 500000))}
                result = await solve(payload)
                receipts.append({'payload_hash': key, 'experiment_id': sample['experiment_id'],
                                 'mesh_size_mm': payload['mesh_size_mm'], 'ok': bool(result.get('ok')),
                                 'result': result})
                cache[key] = _result_curve(result)
                if policy.get('solver_identity'):
                    store.cache_solver(key, result)
            curves.append(cache[key])
        # Convergence is an explicit curve metric, independent of fit quality.
        scale = max(abs(y) for _, y in curves[-1])
        delta_coarse = curve_error(curves[0], curves[1])
        delta_fine = curve_error(curves[1], curves[2])
        converged = delta_fine <= tolerance * max(scale, 1e-12) and delta_fine <= delta_coarse + 1e-12
        return curve_error(sample['observation'], curves[-1]), converged

    try:
        baseline_train = [await evaluate(base['parameters'], item) for item in train]
        remaining = {f'evaluate_{i}': params for i, params in enumerate(candidates)}
        best = None
        while remaining:
            decision = await choose('improvement_candidate', {
                'baseline_train_error': sum(x[0] for x in baseline_train) / len(train),
                'candidates': remaining, 'solver_calls_used': len(receipts), 'solver_budget': max_jobs,
            }, {**{key: 'cae.run_static_analysis' for key in remaining}, 'hold': None})
            decisions.append(decision)
            if decision.get('option_id') == 'hold':
                break
            if decision.get('option_id') not in remaining:
                raise ValueError('Unregistered refinement option')
            parameters = remaining.pop(decision['option_id'])
            errors = [await evaluate(parameters, item) for item in train]
            error = sum(x[0] for x in errors) / len(train)
            if all(x[1] for x in errors) and error < sum(x[0] for x in baseline_train) / len(train) and (best is None or error < best[0]):
                best = (error, parameters)
        if best is None or not all(x[1] for x in baseline_train):
            return {'status': 'held', 'reason': 'no_converged_training_improvement', 'decisions': decisions, 'receipts': receipts}
        # Candidate selected before accessing holdout response; no further fitting.
        store.reserve_validation(scope, digest({'parent': base['version'], 'parameters': best[1]}),
                                 [s['acquisition_id'] for s in train], holdout[0]['acquisition_id'])
        before = [await evaluate(base['parameters'], item) for item in holdout]
        after = [await evaluate(best[1], item) for item in holdout]
        validation = {
            'train_ids': [s['acquisition_id'] for s in train], 'holdout_ids': [s['acquisition_id'] for s in holdout],
            'baseline_error': sum(x[0] for x in before) / len(before),
            'candidate_error': sum(x[0] for x in after) / len(after),
            'numerically_valid': all(x[1] for x in before + after), 'within_bounds': True,
            'comparison_compatible': True, 'cost_within_budget': len(receipts) <= max_jobs and time.monotonic() - started <= wall,
            'secondary_checks_passed': True, 'secondary_checks': 'No extra objective quantities configured; curve convergence required.',
            'evidence_refs': [digest(item) for item in samples], 'method': 'three_mesh_curve_convergence_and_heldout_rms',
        }
        tested_parameters = deepcopy(best[1])
        tested_parameters['mesh_size_mm'] = float(best[1]['mesh_size_mm']) * 0.5
        validation['validated_mesh_size_mm'] = tested_parameters['mesh_size_mm']
        candidate = store.save_candidate(scope, base['version'], tested_parameters, validation)
        decision = await choose('improvement_validation', validation, {'promote': 'analysis.promote_model', 'hold': None})
        decisions.append(decision)
        if decision.get('option_id') != 'promote':
            return {'status': 'held', 'candidate': candidate, 'validation': validation, 'decisions': decisions, 'receipts': receipts}
        store.promote(candidate['version'])
        return {'status': 'promoted', 'model_version': candidate['version'], 'validation': validation, 'decisions': decisions, 'receipts': receipts}
    except TimeoutError:
        return {'status': 'budget_exhausted', 'decisions': decisions, 'receipts': receipts}
    except (ValueError, KeyError, OSError) as exc:
        return {'status': 'held', 'reason': type(exc).__name__, 'detail': str(exc), 'decisions': decisions, 'receipts': receipts}
