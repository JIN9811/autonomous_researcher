#!/usr/bin/env python3
"""Exercise real API/local Analysis decisions with NO native or hardware work.

Two evidence layers: exact saved native receipts through the ordinary FEM path,
and a clearly labeled analytic forward fixture through the calibration search.
Every client is pinned to one registered model; fallback cannot hide failures.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents.analysis_calibration import calibrate
from agents.analysis_decisions import compact_evidence, decide
from agents.analysis_fem import run_fem_study
from scripts.validation.run_analysis_fem_cycle import Journal, build_context, pin_validation_backend, write_json


async def check_backend(backend, model, output, archive, cases_path):
    output.mkdir(parents=True, exist_ok=False)
    journal = Journal(output)
    context, _ = build_context(ROOT / 'configs', output, journal)
    ctx = pin_validation_backend(context, backend, model=model)
    actual_model = ctx.model_router.select('analysis_reasoning').primary
    decisions, results = [], []
    started = time.monotonic()

    async def choose(phase, info, options):
        tick = time.monotonic()
        decision = await decide(ctx, phase, info, options, background=True, timeout_s=300)
        decisions.append({'phase': phase, 'elapsed_s': time.monotonic() - tick, 'decision': decision,
                          'input': compact_evidence(info), 'options': options})
        write_json(output / 'decisions.json', decisions)
        print(json.dumps({'backend': backend, 'model': actual_model, 'phase': phase,
                          'decision': decision['option_id'], 'elapsed_s': decisions[-1]['elapsed_s']}), flush=True)
        return decision

    for case in json.loads(cases_path.read_text())['cases']:
        try:
            decision = await choose(case['phase'], case['input'], case['options'])
            results.append({'case': case['name'], 'passed': decision['option_id'] == case['expected'],
                            'expected': case['expected'], 'actual': decision['option_id']})
        except Exception as exc:
            results.append({'case': case['name'], 'passed': False, 'error': f'{type(exc).__name__}: {exc}'})

    # Actual archived native evidence. Replay only identical semantic requests;
    # preserve source files and clearly distinguish replay from a fresh solve.
    evidence = json.loads((archive / 'evidence.json').read_text())
    evidence['policy'].update(max_fem_jobs=1, max_mesh_actions=1, mesh_size_factors=[1])
    saved = {}
    for stem, name in [('001-cae-prepare_static_analysis', 'cae.prepare_static_analysis'),
                       ('002-cae-run_static_analysis', 'cae.run_static_analysis')]:
        saved[name] = (json.loads((archive / f'{stem}.request.json').read_text()),
                       json.loads((archive / f'{stem}.result.json').read_text()))
    calls = []

    async def archived_tool(name, payload):
        expected, result = saved[name]
        for key in ('material', 'stl_path', 'mesh_size_mm', 'loading', 'surface_remesh',
                    'boundary_tolerance_mm', 'increments', 'computation_limits'):
            if payload.get(key) != expected.get(key):
                raise ValueError(f'Archived request mismatch: {key}')
        calls.append(name)
        return deepcopy(result)

    try:
        result = await run_fem_study(evidence, choose, archived_tool, lambda event: None)
        write_json(output / 'archived_native_workflow.json', result)
        results.append({'case': 'archived_native_workflow', 'passed': result['status'] == 'completed'
                        and calls == ['cae.prepare_static_analysis', 'cae.run_static_analysis'],
                        'status': result['status'], 'tool_calls': calls,
                        'native_execution': 'archived receipt replay, not a fresh solve'})
    except Exception as exc:
        results.append({'case': 'archived_native_workflow', 'passed': False, 'error': f'{type(exc).__name__}: {exc}'})

    # The real retained acquisition contains no independent material/deformation
    # characterization. Verify the actual calibration entry cannot execute FE.
    unsupported = deepcopy(evidence)
    unsupported['policy']['calibration'] = {
        'initial': {'peak_flow_mpa': 60, 'residual_flow_mpa': 25, 'decay_plastic_strain': .1},
        'bounds': {'residual_flow_mpa': [15, 40]}, 'max_evaluations': 3, 'step_fraction': .2}
    unsupported['policy'].pop('mechanism_evidence', None)
    denied_calls = []
    async def no_solver(name, payload):
        denied_calls.append(name)
        raise AssertionError('Unsupported physical hypothesis must not reach the solver boundary')
    try:
        held = await calibrate(unsupported, choose, no_solver, lambda event: None)
        write_json(output / 'unsupported_acquisition_review.json', held)
        results.append({'case': 'actual_acquisition_blocks_unsupported_softening',
                        'passed': held['status'] == 'held' and not denied_calls
                        and held['summary'].get('failure_code') == 'FEM_MECHANISM_EVIDENCE_REQUIRED',
                        'status': held['status'], 'tool_calls': denied_calls})
    except Exception as exc:
        results.append({'case': 'actual_acquisition_blocks_unsupported_softening', 'passed': False,
                        'error': f'{type(exc).__name__}: {exc}'})

    # Known synthetic response F(x) = q_peak * x / 4, so q_peak=40 reproduces
    # F(10)=100. Only the external native boundary is substituted. Measurements
    # and paired identity here are explicit test fixtures, never physical proof.
    fixture = deepcopy(evidence)
    fixture.update(job_id=f'backend-fixture-{backend}', observation=[[0, 0], [10, 100]],
                   experiment_curve=[[0, 0], [10, 100]], coordinate_convention={'name': 'raw_displacement'})
    fixture['payload'].update(target_displacement_mm=10, material={'elastic_modulus_mpa': 1800, 'poisson_ratio': .35})
    fixture['policy'] = {'max_fem_jobs': 1, 'max_mesh_actions': 1, 'mesh_size_factors': [1],
                        'calibration': {'initial': {'peak_flow_mpa': 30, 'residual_flow_mpa': 20, 'decay_plastic_strain': .1},
                                        'bounds': {'peak_flow_mpa': [20, 60]}, 'max_evaluations': 2, 'step_fraction': .25}}
    characterization = output / 'characterization-fixture.json'
    write_json(characterization, {'scope': 'software fixture only, not a real coupon or deformation comparison'})
    fixture['input_hashes'][str(characterization)] = hashlib.sha256(characterization.read_bytes()).hexdigest()
    fixture['acquisition_ids'] = ['lattice-software-fixture']
    fixture['policy']['mechanism_evidence'] = {
        'material_basis': {'kind': 'printed_material_coupon', 'refs': [str(characterization)],
                           'acquisition_ids': ['coupon-software-fixture'], 'same_print_process': True,
                           'post_yield_softening_observed': True},
        'deformation_comparison': {'status': 'consistent', 'refs': [str(characterization)]},
    }
    write_json(output / 'controlled_calibration_evidence.json', fixture)
    fixture_calls = []

    async def fixture_choose(phase, info, options):
        return await choose(phase, {**info, 'evaluation_scope':
            'Software-only calibration-loop validation. Paired identity/measurements and forward solver are explicit controlled fixtures; no physical validity claim.'}, options)

    async def fixture_tool(name, payload):
        fixture_calls.append({'tool': name, 'material': deepcopy(payload['material'])})
        if name == 'cae.prepare_static_analysis':
            return {'ok': True, 'prepared_input': {'inp_path': '/software-fixture'},
                    'mesh_quality': {'validity': 'valid', 'quality': 'good'}}
        if name != 'cae.run_static_analysis':
            raise ValueError('Unregistered fixture boundary')
        force = payload['material']['plastic_curve'][0][0]
        return {'ok': True, 'status': 'complete', 'solver_mode': 'calculix_quasistatic',
                'reaction_force_displacement_curve': [
                    {'displacement_mm': x, 'force_N': force * x / 4} for x in [0, 2, 4, 6, 8, 10]],
                'evidence_scope': 'analytic forward fixture, not real CalculiX'}

    try:
        result = await calibrate(fixture, fixture_choose, fixture_tool, lambda event: None)
        write_json(output / 'controlled_calibration_workflow.json', result)
        results.append({'case': 'controlled_calibration_workflow',
                        'passed': result['status'] == 'completed'
                        and (result['calibration'].get('best_parameters') or {}).get('peak_flow_mpa') == 40
                        and result['calibration'].get('retention_status') == 'retained_for_research',
                        'status': result['status'], 'tool_calls': fixture_calls,
                        'evidence_scope': 'real LLM, actual calibration code, analytic forward test fixture'})
    except Exception as exc:
        results.append({'case': 'controlled_calibration_workflow', 'passed': False, 'error': f'{type(exc).__name__}: {exc}'})
    summary = {'backend': backend, 'model': actual_model, 'fallback_enabled': False,
               'passed': sum(r['passed'] for r in results), 'total': len(results), 'cases': results,
               'elapsed_s': time.monotonic() - started, 'native_or_hardware_executions': 0,
               'source_archive': str(archive), 'source_evidence_sha256': hashlib.sha256((archive / 'evidence.json').read_bytes()).hexdigest()}
    write_json(output / 'result.json', summary)
    print(json.dumps({k:v for k,v in summary.items() if k != 'cases'}), flush=True)
    return summary


async def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for backend, model in [('openai', None), ('vllm', 'gemma4:31b')]:
        results.append(await check_backend(backend, model, args.output / backend, args.archive, args.cases))
    write_json(args.output / 'result.json', {'backends': results, 'passed': all(r['passed'] == r['total'] for r in results)})
    return 0 if all(r['passed'] == r['total'] for r in results) else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive', type=Path, default=ROOT / 'artifacts/runs/validation-fem-20260909-long-cycle-03')
    parser.add_argument('--cases', type=Path, default=ROOT / 'scripts/validation/fixtures/analysis_mechanism_decisions.json')
    args = parser.parse_args()
    if not args.execute:
        parser.error('--execute authorizes real model inference only; no native/device execution')
    raise SystemExit(asyncio.run(main(args)))
