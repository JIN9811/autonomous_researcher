import asyncio
import hashlib
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from utils import compute_pool as cp


@pytest.fixture
def pool():
    assert not cp.compute_enabled()
    cp.configure_compute_pool(3)
    yield cp._pool
    cp.close_compute_pool()


def test_allowlist_rejects_hardware_and_limits_configuration():
    with pytest.raises(ValueError):
        cp.ComputePool(4)
    pool = cp.ComputePool(1)
    try:
        with pytest.raises(ValueError, match='CPU-only'):
            pool.submit('printer.send', {})
        assert pool.status()['pids'] == []
    finally:
        pool.close()


@pytest.mark.asyncio
async def test_three_real_interpreters_and_responsive_parent(pool, tmp_path):
    ticks = []
    stop = asyncio.Event()
    async def heartbeat():
        while not stop.is_set():
            ticks.append(asyncio.get_running_loop().time())
            await asyncio.sleep(.01)
    beat = asyncio.create_task(heartbeat())
    results = await asyncio.gather(*(cp.compute_async('geometry.quality', {'stl_path': str(tmp_path/f'missing-{i}.stl')}) for i in range(3)))
    stop.set()
    await beat
    assert all(r['ok'] is False for r in results)
    pids = pool.status()['pids']
    assert len(set(pids)) == 3 and os.getpid() not in pids
    assert len(ticks) > 5
    assert max(b-a for a,b in zip(ticks, ticks[1:])) < 1
    assert pool.status()['completed'] == 3


def test_queue_is_bounded_and_shutdown_cancels_waiters(monkeypatch):
    started = threading.Event()
    def wait(worker, message, cancelled, deadline):
        started.set()
        cancelled.wait(5)
        raise cp.ComputeError('cancelled')
    monkeypatch.setattr(cp._Worker, 'exchange', wait)
    pool = cp.ComputePool(1)
    first, _ = pool.submit('geometry.quality', {})
    assert started.wait(2)
    second, _ = pool.submit('geometry.quality', {})
    with pytest.raises(cp.ComputeError, match='queue full'):
        pool.submit('geometry.quality', {})
    pool.close()
    assert first.done() and second.done()
    assert pool.status()['active'] == pool.status()['queued'] == 0


@pytest.mark.asyncio
async def test_cancellation_and_deadline_do_not_reuse_broken_process(pool, tmp_path):
    with pytest.raises((cp.ComputeError, TimeoutError)):
        await cp.compute_async('geometry.quality', {}, timeout=0)
    task = asyncio.create_task(cp.compute_async('geometry.quality', {}))
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(100):
        if pool.status()['active'] == 0:
            break
        await asyncio.sleep(.02)
    result = await cp.compute_async('geometry.quality', {'stl_path': str(tmp_path/'absent.stl')})
    assert result['ok'] is False
    assert pool.status()['active'] == 0


@pytest.mark.asyncio
async def test_analysis_values_identical_in_worker(pool):
    from agents.analysis.agent import AnalysisAgent
    curve = [{'time_s': float(i), 'force_N': float(i*100), 'displacement_mm': float(i)} for i in range(17)]
    geometry = {'cross_section_area_mm2': 900., 'gauge_length_mm': 30., 'mass_g': 10., 'specimen_size_mm': [30,30,30]}
    agent = AnalysisAgent()
    expected = {'metrics': agent._metrics(curve, geometry), 'stress_strain_curve': agent._stress_strain_curve(curve, geometry)}
    assert await cp.compute_async('analysis.metrics', {'curve': curve, 'geometry': geometry}) == expected


def test_geometry_algorithms_and_binary_stl_unchanged(tmp_path):
    from mcp_tools.mock_tools import _generate_geometry_stl, _check_manufacturability
    payload = {'run_id': 'cpu-test', 'specimen_id': 'cpu-specimen', 'geometry_type': 'gyroid',
               'specimen_size_mm': [10,10,10], 'wall_thickness_mm': 1.2, 'cell_size_mm': 5.,
               'tpms_resolution': 48, 'output_dir': str(tmp_path/'mesh')}
    baseline = _generate_geometry_stl(payload)
    path = Path(baseline['stl_path'])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    check = {'stl_path': str(path), 'constraints': {'geometry_type': 'gyroid', 'wall_thickness_mm': 1.2, 'cell_size_mm': 5.}}
    before_check = _check_manufacturability(check)
    cp.configure_compute_pool(3)
    try:
        result = _generate_geometry_stl(payload)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        assert result['geometry_report'] == baseline['geometry_report']
        assert _check_manufacturability(check) == before_check
    finally:
        cp.close_compute_pool()


@pytest.mark.asyncio
async def test_bo_worker_preserves_gp_candidate_and_extracts_artifacts(tmp_path):
    import torch
    from learning.bo_parameter_space import BOParameterSpace
    from learning.botorch_backend import propose_next, BoTorchBackendError
    from tests.unit.test_bo_visualization_artifacts import _visualization
    from reporting.bo_visualization_artifacts import write_bo_visualization_artifacts
    old_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    args = dict(parameter_space=BOParameterSpace.from_mapping({'cell_size_mm': [5., 10.], 'wall_thickness_mm': [.6, 1.2]}),
        observations=[{'parameters': {'cell_size_mm': x, 'wall_thickness_mm': y}, 'score': z}
                      for x,y,z in [(5,.6,8.),(6,.9,11.),(8,.7,10.),(10,1.2,9.)]],
        acquisition='expected_improvement', random_seed=13, num_restarts=2, raw_samples=16, fit_max_iter=15)
    try:
        expected = propose_next(**args).to_dict()
        baseline = write_bo_visualization_artifacts(_visualization(), tmp_path/'direct')
        baseline_csv = next(Path(r['path']).read_bytes() for r in baseline if r['path'].endswith('.csv'))
        cp.configure_compute_pool(3)
        actual = await cp.offload_wait(propose_next, **args)
        assert actual.candidate == pytest.approx(expected['candidate'])
        assert actual.posterior == pytest.approx(expected['posterior'])
        records = await cp.compute_async('bo.render', {'payload': _visualization(), 'output_dir': str(tmp_path/'worker')})
        assert {Path(r['path']).suffix for r in records} == {'.png', '.svg', '.csv'}
        assert all(Path(r['path']).stat().st_size > 0 for r in records)
        assert next(Path(r['path']).read_bytes() for r in records if r['path'].endswith('.csv')) == baseline_csv
        with pytest.raises(BoTorchBackendError):
            await cp.offload_wait(propose_next, **{**args, 'observations': []})
    finally:
        cp.close_compute_pool()
        torch.set_num_threads(old_threads)


@pytest.mark.asyncio
async def test_generator_retains_exception_handling_and_drops_stale_results():
    state = SimpleNamespace(run_id='r', experiment_id='e', loop_count=0,
                            stop_requested=False, safe_stop_requested=False, emergency_stop_requested=False)
    def recover():
        try:
            yield 'geometry.generate_metamaterial_stl', {}
        except ValueError:
            return 'recovered'
    def failed(*args):
        raise ValueError('same error')
    tools = SimpleNamespace(call=failed)
    assert cp.run_tool_steps(recover(), tools) == 'recovered'
    assert await cp.run_tool_steps_async(recover(), tools, state) == 'recovered'
    applied = []
    def stale():
        value = yield 'geometry.generate_metamaterial_stl', {}
        applied.append(value)
    def changed(*args):
        state.loop_count += 1
        return {'ok': True}
    with pytest.raises(asyncio.CancelledError):
        await cp.run_tool_steps_async(stale(), SimpleNamespace(call=changed), state)
    assert applied == []


@pytest.mark.asyncio
async def test_specimen_preparation_keeps_all_payloads_and_state_on_main_thread(tmp_path, monkeypatch):
    import json
    from copy import deepcopy
    from datetime import datetime, timezone
    from agents.specimen import agent as owner
    from orchestrator.state import OrchestratorState
    fixture = json.loads((Path(__file__).parents[1]/'fixtures/specimen_module_deterministic_golden.json').read_text()
                         .replace('$ARTIFACT_ROOT', str(tmp_path/'geometry')))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 13, tzinfo=timezone.utc)
    monkeypatch.setattr(owner, 'datetime', Clock)
    monkeypatch.setattr(owner.SpecimenMakingAgent, '_artifact_dir', lambda *a: tmp_path/'geometry')
    main_thread = threading.get_ident()
    def setup():
        calls = []
        threads = []
        def call(name, payload):
            calls.append((name, deepcopy(payload)))
            threads.append((name, threading.get_ident()))
            return deepcopy(fixture['tool_responses'][name])
        return OrchestratorState(**fixture['state_input']), SimpleNamespace(tools=SimpleNamespace(call=call),
            force_real_llm_in_test=False), calls, threads
    before, ctx, calls, _ = setup()
    agent = owner.SpecimenMakingAgent()
    expected = agent._prepare_fabrication(before, ctx)
    after, ctx, async_calls, threads = setup()
    actual = await agent._prepare_fabrication_async(after, ctx)
    assert actual == expected
    assert async_calls == calls
    assert after.model_dump() == before.model_dump()
    assert all(t != main_thread for name, t in threads if name.startswith('geometry.'))
    assert all(t == main_thread for name, t in threads if not name.startswith('geometry.'))


@pytest.mark.asyncio
async def test_bo_artifacts_keep_current_execution_directory(pool, tmp_path):
    from agents.registry import AgentRegistry
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import OrchestratorState, Mode, Stage
    from logging_system.structured_logger import StructuredLogger
    from tests.unit.test_langgraph_runtime import _runtime_bo_visualization
    state = OrchestratorState(run_id='r', experiment_id='e', mode=Mode.TEST, stage=Stage.BO)
    runtime = LangGraphRunLoop(state=state, agent_registry=AgentRegistry(), orchestrator_agent_name='orchestrator_agent',
        ctx=object(), logger=StructuredLogger(tmp_path/'structured.jsonl', tmp_path/'summary.log'),
        graph_config_path='graphs/configs/atr_closed_loop.yaml')
    manifest = tmp_path/'runtime/loops/loop-000001/bo_agent/attempt-000002/manifest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{}')
    runtime._runtime_evidence_execution = {'stage': 'vision', 'run_id': 'r', 'manifest_path': 'old.json'}
    data = {'artifact_execution': {'stage': 'bo', 'run_id': 'r', 'manifest_path': str(manifest.relative_to(tmp_path))},
            'bo_result': {'visualization': _runtime_bo_visualization()}}
    records = await runtime._register_runtime_artifacts_async(Stage.BO, 'bo_agent', data)
    plots = [r for r in records if r['key'].startswith('runtime.bo_posterior.')]
    assert len(plots) == 3
    assert all((tmp_path/r['path']).is_relative_to(manifest.parent/'derived') for r in plots)
    assert all((tmp_path/r['path']).is_file() for r in plots)
