import asyncio
from types import SimpleNamespace

import pytest

from agents.analysis_agent import AnalysisAgent
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import OrchestratorState, Mode, Stage


def state():
    return OrchestratorState(run_id='analysis-background-test', experiment_id='e1', stage=Stage.ANALYSIS,
        mode=Mode.TEST, current_experiment_spec={'specimen_id': 's1', 'specimen_size_mm': [20, 20, 20]},
        run_metadata={'equipment_result': {'ok': True, 'utm_data': [
            {'time_s': i, 'displacement_mm': i, 'force_N': 100 * i} for i in range(16)]}})


@pytest.mark.asyncio
async def test_foreground_records_decisions_and_queues_without_waiting(tmp_path):
    tools = ToolRegistry()
    calls = []
    def cae(payload):
        calls.append(payload)
        return {'ok': True, 'tool': 'cae.run_static_analysis', 'cae_metrics': {}}
    tools.register('cae.run_static_analysis', cae)
    ctx = SimpleNamespace(tools=tools, artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    result = await AnalysisAgent().run(state(), ctx)
    assert result.success
    analysis = result.data['analysis']
    assert 'decisions' in analysis, 'foreground must contain tool selection evidence'
    assert [d['phase'] for d in analysis['decisions']] == ['data_processing', 'data_validation']
    assert analysis['improvement']['status'] == 'queued'
    assert len(calls) == 0  # Native FEM is not a foreground dependency.
    assert analysis['uncertainty'] is None
    assert analysis['uncertainty_status']['status'] == 'not_estimated'
    assert analysis['trust_score']['score'] is None
    assert analysis['objective_score'] == analysis['bo_observation']['objective_score']
    service = tools.resource('analysis_improvement')
    await service.shutdown()


@pytest.mark.asyncio
async def test_analysis_failure_does_not_enqueue_improvement(tmp_path):
    tools = ToolRegistry()
    ctx = SimpleNamespace(tools=tools, artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    invalid = state()
    invalid.current_experiment_spec['specimen_size_mm'] = [0, 0, 0]
    result = await AnalysisAgent().run(invalid, ctx)
    assert not result.success
    assert tools.resource('analysis_improvement') is None


def test_pin_loop_reuses_same_snapshot_and_does_not_change_experiment_spec(tmp_path):
    from agents import analysis_runtime as module
    assert hasattr(module, 'pin_loop'), 'runtime boundary pin required'
    s = state()
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    original = s.current_experiment_spec.copy()
    first = module.pin_loop(s, ctx)
    assert module.pin_loop(s, ctx) == first
    assert s.current_experiment_spec == original


@pytest.mark.asyncio
async def test_boundary_snapshot_uses_final_design_but_excludes_midloop_promotion(tmp_path):
    from agents.analysis_runtime import pin_loop, resolve_loop_model, service_for
    from tests.unit.test_analysis_improvement import validation
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    s = state()
    s.current_experiment_spec['cae_elastic_modulus_mpa'] = 1200
    first = resolve_loop_model(s, ctx)
    s.loop_count += 1
    s.current_experiment_spec['cae_elastic_modulus_mpa'] = 1800
    pin_loop(s, ctx)  # Before Design. Final Design has not been produced yet.
    store = service_for(ctx).store(s.run_id)
    candidate = store.save_candidate(first['scope'], first['model']['version'],
        {**first['model']['parameters'], 'material': {'elastic_modulus_mpa': 1300}}, validation())
    store.promote(candidate['version'])
    s.current_experiment_spec['cae_elastic_modulus_mpa'] = 1200
    current = resolve_loop_model(s, ctx)
    assert current['model']['parameters']['material']['elastic_modulus_mpa'] == 1200
    assert current['model']['version'] != candidate['version']
    s.loop_count += 1
    pin_loop(s, ctx)
    assert resolve_loop_model(s, ctx)['model']['version'] == candidate['version']
    await service_for(ctx).shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['raise', 'hold'])
async def test_failed_next_loop_clears_previous_ready_handoff(tmp_path, failure):
    import json
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    s = state()
    agent = AnalysisAgent()
    first = await agent.run(s, ctx)
    assert first.data['bo_observation']['ok_for_bo']
    # Exercise the actual runtime merge, including existing loop metadata.
    runtime = object.__new__(LangGraphRunLoop)
    runtime._state = s
    runtime._merge_agent_data(Stage.ANALYSIS, first.data)
    s.loop_count += 1
    async def complete(*args, **kwargs):
        if failure == 'raise':
            raise RuntimeError('LLM transport unavailable')
        return SimpleNamespace(text=json.dumps({'option_id': 'hold', 'reason': 'Insufficient evidence.'}))
    ctx.complete, ctx.force_real_llm_in_test = complete, True
    s.current_experiment_spec['require_cae_solver'] = True
    ctx.tools.register('cae.run_static_analysis', lambda payload: {})
    result = await agent.run(s, ctx)
    assert not result.success
    runtime._merge_agent_data(Stage.ANALYSIS, result.data)
    assert s.latest_analysis['bo_observation']['ok_for_bo'] is False
    assert s.latest_analysis['bo_handoff']['ok_for_bo'] is False
    assert s.latest_analysis['objective_score'] is None
    assert s.latest_analysis['uncertainty'] is None
    assert s.run_metadata['analysis_metrics'] == {}
    await ctx.tools.resource('analysis_improvement').shutdown()


@pytest.mark.asyncio
async def test_optional_sqlite_failure_does_not_break_foreground(tmp_path, monkeypatch):
    import sqlite3
    from agents.analysis_improvement import ImprovementStore
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(ImprovementStore, '__init__', unavailable)
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    result = await AnalysisAgent().run(state(), ctx)
    assert result.success
    assert result.data['bo_observation']['ok_for_bo']


@pytest.mark.asyncio
async def test_two_loop_acquisitions_accumulate_but_csv_reuse_is_not_independent(tmp_path):
    import hashlib
    from agents.analysis_runtime import service_for
    s = state()
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    service = service_for(ctx)
    stl = tmp_path / 'shape.stl'
    stl.write_text('solid same-geometry')
    for index in (1, 2, 3):
        s.loop_count = index
        specimen_id = f's{index}'
        s.current_experiment_spec['specimen_id'] = specimen_id
        s.run_metadata['specimen_result'] = {'specimen_id': specimen_id, 'stl_path': str(stl)}
        csv = tmp_path / f'raw-{min(index, 2)}.csv'
        csv.write_text(f'time_s,displacement_mm,force_N\n0,0,0\n1,10,{min(index, 2)}\n')
        s.run_metadata['equipment_result'] = {'ok': True, 'raw_data_export': {
            'validated': True, 'run_id': s.run_id, 'loop_id': index, 'specimen_id': specimen_id,
            'artifact_id': f'acquisition-{index}', 'path': str(csv),
            'sha256': hashlib.sha256(csv.read_bytes()).hexdigest()}}
        payload = AnalysisAgent()._cae_payload(s, AnalysisAgent()._specimen_geometry(s))
        service.submit(s, {'source': {'source': 'equipment_result.raw_data_export', 'path': str(csv)}},
            [{'displacement_mm': 0, 'force_N': 0}, {'displacement_mm': 10, 'force_N': index}], payload)
    records = [j['evidence'] for j in service.store(s.run_id).jobs()]
    assert len({r['acquisition_id'] for r in records[:2]}) == 2
    assert all(r['paired_identity_verified'] for r in records[:2])
    assert not records[2]['paired_identity_verified']
    assert records[2]['identity_reason'] == 'reused_raw_acquisition'
    await service.shutdown()


@pytest.mark.asyncio
async def test_specimen_and_stl_alone_do_not_prove_csv_pairing(tmp_path):
    from agents.analysis_runtime import service_for
    s = state()
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    stl, csv = tmp_path / 'shape.stl', tmp_path / 'raw.csv'
    stl.write_text('solid shape')
    csv.write_text('0,0\n10,1')
    s.run_metadata['specimen_result'] = {'specimen_id': 's1', 'stl_path': str(stl)}
    payload = AnalysisAgent()._cae_payload(s, AnalysisAgent()._specimen_geometry(s))
    service = service_for(ctx)
    service.submit(s, {'source': {'source': 'equipment_result.result_file', 'path': str(csv)}},
        [{'displacement_mm': 0, 'force_N': 0}, {'displacement_mm': 10, 'force_N': 1}], payload)
    assert service.store(s.run_id).jobs()[0]['evidence']['paired_identity_verified'] is False
    await service.shutdown()


@pytest.mark.asyncio
async def test_startup_recovers_queue_without_running_solver(tmp_path):
    from agents.analysis_runtime import AnalysisRuntimeService
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    previous = AnalysisRuntimeService(tmp_path, ctx)
    store = previous.store('restart-run')
    interrupted = store.submit({'experiment_id': 'first'})
    store.claim()
    queued = store.submit({'experiment_id': 'second'})
    service = AnalysisRuntimeService(tmp_path, ctx)
    service.recover_existing()
    assert service.status()['restart-run'][0]['status'] == 'interrupted'
    assert store.get(queued['job_id'])['status'] == 'queued'
    assert not service._workers
    assert store.get(interrupted['job_id'])['result']['reason']
    await service.shutdown()


@pytest.mark.asyncio
async def test_active_loop_boundary_resumes_prior_queue_without_new_submission(tmp_path):
    from agents.analysis_runtime import service_for, pin_loop
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    s = state()
    service = service_for(ctx)
    queued = service.store(s.run_id).submit({'experiment_id': 'prior', 'scope': 's', 'virtual_decisions': True})
    pin_loop(s, ctx, resume_background=True)
    await asyncio.wait_for(service._workers[s.run_id].drain(), 1)
    assert service.store(s.run_id).get(queued['job_id'])['status'] == 'needs_more_data'
    await service.shutdown()


@pytest.mark.asyncio
async def test_two_loop_foreground_observation_ids_are_distinct(tmp_path):
    s = state()
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    first = await AnalysisAgent().run(s, ctx)
    s.loop_count += 1
    second = await AnalysisAgent().run(s, ctx)
    assert first.data['bo_observation']['observation_id'] != second.data['bo_observation']['observation_id']
    assert first.data['experiment_evaluation']['evaluation_id'] != second.data['experiment_evaluation']['evaluation_id']
    await ctx.tools.resource('analysis_improvement').shutdown()


def test_saved_equipment_managed_export_shape_binds_without_invented_loop_fields():
    import hashlib
    import json
    from pathlib import Path
    from agents.analysis_runtime import _acquisition_identity
    root = Path(__file__).resolve().parents[2]
    loop = root / 'runs/run-20260907T043145Z-f6152b/runtime/loops/loop-000001'
    if not loop.exists():
        pytest.skip('Local read-only archived equipment shape is unavailable')
    saved_state = json.loads((loop / 'equipment_agent/attempt-000001/input.json').read_text())['state']
    data = json.loads((loop / 'equipment_agent/attempt-000001/result.json').read_text())['data']
    specimen = json.loads((loop / 'specimen_agent/attempt-000001/result.json').read_text())['data']['specimen_result']
    s = OrchestratorState.model_validate(saved_state)
    s.run_metadata.update(data)
    s.run_metadata['specimen_result'] = specimen
    csv, stl = data['equipment_result']['result_file'], specimen['stl_path']
    hashes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (csv, stl)}
    identity = _acquisition_identity(s, {'path': csv}, stl, hashes)
    assert identity['paired_identity_verified'] is True
    assert identity['raw_sha256'] == 'c0305780455d1ba2af0ce734ffce1fa904c5a4e8434bc73fe37ecd27e415e17e'
    # A later runtime loop cannot use the same managed export as a fresh trial.
    s.loop_count += 1
    assert not _acquisition_identity(s, {'path': csv}, stl, hashes)['paired_identity_verified']


@pytest.mark.asyncio
async def test_optional_fem_failure_does_not_invalidate_measured_bo(tmp_path):
    s = state()
    s.current_experiment_spec['require_cae_solver'] = True
    tools = ToolRegistry()
    tools.register('cae.run_static_analysis', lambda payload: {'ok': False, 'failure_code': 'SOLVER_FAILED'})
    ctx = SimpleNamespace(tools=tools, artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    result = await AnalysisAgent().run(s, ctx)
    assert result.success
    assert result.data['bo_observation']['ok_for_bo'] is True
    assert result.data['analysis']['fem_job']['status'] == 'queued'
    assert result.data['analysis']['cae_result'] == {}
    await tools.resource('analysis_improvement').shutdown()


@pytest.mark.parametrize('patch', [{'specimen_size_mm': [30, 30, 30]}, {'cae_boundary_condition': 'different_fixture'}])
def test_model_scope_excludes_incompatible_geometry_and_boundary(tmp_path, patch):
    from agents.analysis_runtime import resolve_loop_model
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    s = state()
    first = resolve_loop_model(s, ctx)
    s.loop_count += 1
    s.current_experiment_spec.update(patch)
    assert resolve_loop_model(s, ctx)['scope'] != first['scope']


@pytest.mark.asyncio
async def test_worker_owner_releases_process_lock_when_admission_budget_ends(tmp_path):
    from agents.analysis_runtime import AnalysisRuntimeService
    ctx = SimpleNamespace(tools=ToolRegistry(), artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    first = AnalysisRuntimeService(tmp_path, ctx)
    second = AnalysisRuntimeService(tmp_path, ctx)
    first.store('shared').submit({'experiment_id': 'first', 'scope': 's', 'virtual_decisions': True})
    assert first.resume('shared', virtual=True, max_jobs=1)
    await asyncio.wait_for(first._workers['shared'].drain(), 1)
    await asyncio.sleep(0)
    assert second.resume('shared', virtual=True, max_jobs=1)
    await first.shutdown()
    await second.shutdown()
