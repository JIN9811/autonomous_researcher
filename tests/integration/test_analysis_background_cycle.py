"""Offline Analysis-to-store cycle; no model, native executable or device exists.

The real agent, runtime, bounded decision protocol, study and SQLite store run.
Only registered preparation/solver handlers are fixtures. A thread barrier proves
measured BO is released while the background solver boundary remains occupied.
"""
import asyncio
from copy import deepcopy
import hashlib
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from agents.analysis_agent import AnalysisAgent
from agents.analysis_improvement import ImprovementStore
from agents.analysis_runtime import AnalysisRuntimeService
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


@pytest.mark.asyncio
async def test_measured_bo_precedes_real_background_study_and_remains_immutable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_id, specimen_id = 'offline-background-cycle', 'fixture-specimen'
    geometry_bytes = b'solid fixture-only-no-native-mesher\nendsolid fixture\n'
    stl = tmp_path / 'input.stl'
    stl.write_bytes(geometry_bytes)
    csv = tmp_path / 'single-acquisition.csv'
    csv.write_text('time_s,displacement_mm,force_N\n' + ''.join(
        f'{x},{x},{100 * max(x - 2, 0)}\n' for x in range(16)))
    prepared_path = tmp_path / 'fixture-prepared.inp'
    prepared_path.write_text('Fixture receipt only; no executable input.')
    state = OrchestratorState(
        run_id=run_id, experiment_id='fixture-experiment', stage=Stage.ANALYSIS,
        mode=Mode.TEST,
        current_experiment_spec={'specimen_id': specimen_id, 'specimen_size_mm': [20, 20, 20],
                                 'require_cae_solver': True},
        run_metadata={
            'specimen_result': {'specimen_id': specimen_id, 'stl_path': str(stl)},
            'equipment_result': {'ok': True, 'result_file': str(csv), 'raw_data_export': {
                'validated': True, 'run_id': run_id, 'loop_id': 0, 'specimen_id': specimen_id,
                'artifact_id': 'only-fixture-acquisition', 'path': str(csv),
                'sha256': hashlib.sha256(csv.read_bytes()).hexdigest(),
            }},
        },
    )
    experiment_spec = deepcopy(state.current_experiment_spec)
    tools = ToolRegistry()
    loop = asyncio.get_running_loop()
    solver_entered = asyncio.Event()
    release_solver = threading.Event()
    requests = []
    model_calls = []

    def prepare(payload):
        # Runtime-only hooks must reach the registered boundary, not the model.
        assert isinstance(payload['_cancel_event'], threading.Event)
        assert callable(payload['_progress_callback'])
        assert payload['computation_limits']['timeout_s'] is None
        assert Path(payload['stl_path']).read_bytes() == geometry_bytes
        assert Path(payload['stl_path']).resolve() != stl.resolve()
        requests.append(('prepare', {key: deepcopy(value) for key, value in payload.items()
                                     if not key.startswith('_')}))
        return {
            'ok': True, 'status': 'prepared',
            'prepared_input': {'inp_path': str(prepared_path), 'target_displacement_mm': 10.0},
            'mesh_quality': {
                'validity': {'status': 'valid', 'node_count': 20, 'element_count': 10},
                'quality': {'metric': 'minimum_corner_scaled_jacobian', 'minimum': .4,
                            'percentile_5': .5, 'below_threshold_fraction': 0.0},
            },
            'artifacts': {'inp_path': str(prepared_path)},
        }

    def solve(payload):
        assert payload['prepared_input']['inp_path'] == str(prepared_path)
        requests.append(('solve', {key: deepcopy(value) for key, value in payload.items()
                                   if not key.startswith('_')}))
        payload['_progress_callback']({'phase': 'fixture_native_wait',
                                       'message': 'Offline solver boundary waiting on test barrier'})
        loop.call_soon_threadsafe(solver_entered.set)
        assert release_solver.wait(5), 'Test did not release the fixture solver'
        assert Path(payload['stl_path']).read_bytes() == geometry_bytes
        return {
            'ok': True, 'status': 'complete', 'solver_mode': 'calculix_quasistatic',
            'reaction_force_displacement_curve': [
                {'displacement_mm': 0.0, 'force_N': 0.0},
                {'displacement_mm': 5.0, 'force_N': 500.0},
                {'displacement_mm': 10.0, 'force_N': 1000.0},
            ],
            'metrics': {'endpoint_reached': True}, 'artifacts': {},
        }

    async def no_model(*args, **kwargs):
        model_calls.append((args, kwargs))
        raise AssertionError('An offline virtual cycle must not call a model')

    tools.register('cae.prepare_static_analysis', prepare)
    tools.register('cae.run_static_analysis', solve)
    ctx = SimpleNamespace(tools=tools, artifact_run_root=str(tmp_path / 'runs'),
                          force_real_llm_in_test=False, complete=no_model)
    service = None
    try:
        foreground = await asyncio.wait_for(AnalysisAgent().run(state, ctx), 5)
        assert foreground.success
        assert not release_solver.is_set()
        assert foreground.data['bo_observation']['ok_for_bo'] is True
        # Integral of F=100*(x-2), from x=2 to the raw target x=10:
        # 3200 N mm / (20*20*20 mm^3) = 0.4 MJ/m^3.
        assert foreground.data['bo_observation']['objective_score'] == pytest.approx(.4)
        assert foreground.data['analysis']['cae_result'] == {}
        returned_data = deepcopy(foreground.data)
        immutable_artifacts = {
            path: Path(path).read_bytes()
            for path in foreground.data['analysis']['analysis_artifacts'].values()
            if isinstance(path, str) and Path(path).is_file()
        }
        assert immutable_artifacts
        service = tools.resource('analysis_improvement')
        assert isinstance(service, AnalysisRuntimeService)
        store = service.store(run_id)
        worker = service._workers[run_id]
        await asyncio.wait_for(solver_entered.wait(), 5)
        assert not release_solver.is_set()
        job_id = foreground.data['analysis']['fem_job']['job_id']
        running = ImprovementStore(store.root).get(job_id)
        assert running['status'] == 'running'
        assert running['result']['progress']['phase'] == 'fixture_native_wait'
        assert len(store.jobs()) == 1
        assert running['evidence']['acquisition_id'] == 'only-fixture-acquisition'
        assert running['evidence']['paired_identity_verified'] is True
        assert running['evidence']['observation'][-1][0] == 10.0
        # Altering the original after foreground completion cannot alter this job.
        stl.write_bytes(b'new unrelated geometry after the acquisition')
        release_solver.set()
        await asyncio.wait_for(worker.drain(), 5)
        finished = ImprovementStore(store.root).get(job_id)
        assert finished['status'] == 'completed'
        study = finished['result']
        assert study['status'] == 'completed'
        assert study['summary']['material_promoted'] is False
        assert study['convergence']['status'] == 'not_assessed'
        assert study['coordinate_convention']['displacement_offset_mm'] == 3.0
        assert study['experiment_curve'][0] == {'displacement_mm': 0.0, 'force_N': 100.0}
        assert study['experiment_curve'][-1] == {'displacement_mm': 12.0, 'force_N': 1300.0}
        assert study['attempts'][0]['comparison']['end_mm'] == 10.0
        assert study['attempts'][0]['endpoint_reached'] is True
        assert [decision['option_id'] for decision in study['decisions']] == [
            'prepare_mesh', 'solve_mesh', 'conclude']
        assert all(decision['source'] == 'virtual_test' for decision in study['decisions'])
        assert [name for name, _ in requests] == ['prepare', 'solve']
        assert requests[0][1]['specimen_id'] == requests[1][1]['specimen_id'] != specimen_id
        assert requests[1][1]['material']['yield_strength_mpa'] == 35.0
        assert requests[1][1]['loading']['target_strain'] == .5
        assert foreground.data == returned_data
        assert state.current_experiment_spec == experiment_spec
        assert {path: Path(path).read_bytes() for path in immutable_artifacts} == immutable_artifacts
        assert not model_calls
    finally:
        release_solver.set()
        service = service or tools.resource('analysis_improvement')
        if service is not None:
            await service.shutdown()
