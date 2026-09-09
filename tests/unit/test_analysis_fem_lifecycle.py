"""Non-actuating boundaries: measured BO must not wait for native computation."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from agents.analysis_agent import AnalysisAgent
from agents.analysis_improvement import AnalysisImprovementWorker, ImprovementStore
from agents.analysis_runtime import AnalysisRuntimeService
from mcp_tools.tool_registry import ToolRegistry
from tests.unit.test_analysis_runtime import state


@pytest.mark.asyncio
async def test_measured_bo_returns_before_solver_even_when_solver_was_required(tmp_path):
    release = threading.Event()
    tools = ToolRegistry()
    def solve(payload):
        release.wait(2)
        return {'ok': True, 'cae_metrics': {}}
    tools.register('cae.run_static_analysis', solve)
    ctx = SimpleNamespace(tools=tools, artifact_run_root=str(tmp_path), force_real_llm_in_test=False)
    s = state()
    s.current_experiment_spec['require_cae_solver'] = True
    task = asyncio.create_task(AnalysisAgent().run(s, ctx))
    try:
        await asyncio.sleep(.15)
        independent = task.done()
    finally:
        release.set()
    result = await task
    service = tools.resource('analysis_improvement')
    if service:
        await service.shutdown()
    assert independent, 'Measured BO handoff waited for optional FEM'
    assert result.success and result.data['bo_handoff']['ok_for_bo']
    assert result.data['analysis']['fem_job']['loop_key'] == 'analysis-background-test:loop-0'


@pytest.mark.asyncio
async def test_unlimited_worker_accepts_no_deadline_and_cancels_explicitly(tmp_path):
    started = asyncio.Event()
    async def execute(evidence):
        started.set()
        await asyncio.Event().wait()
    worker = AnalysisImprovementWorker(ImprovementStore(tmp_path), execute, timeout_s=None)
    job = worker.submit({'experiment_id': 'one'})
    await asyncio.wait_for(started.wait(), 1)
    assert worker.store.get(job['job_id'])['status'] == 'running'
    await worker.shutdown()
    assert worker.store.get(job['job_id'])['status'] == 'cancelled'


def test_progress_and_cancel_request_survive_reopen_without_mutating_evidence(tmp_path):
    store = ImprovementStore(tmp_path)
    job = store.submit({'run_id': 'r', 'specimen_id': 's', 'loop_key': 'r:loop-2'})
    store.claim()
    assert hasattr(store, 'update_progress'), 'durable progress required'
    store.update_progress(job['job_id'], {'phase': 'solve', 'rss_bytes': 1024})
    reopened = ImprovementStore(tmp_path)
    assert reopened.get(job['job_id'])['result']['progress']['rss_bytes'] == 1024
    assert reopened.get(job['job_id'])['evidence'] == job['evidence']
    reopened.request_cancel(job['job_id'])
    assert store.cancel_requested(job['job_id'])
    store.finish(job['job_id'], {'status': 'cancelled'})
    assert store.get(job['job_id'])['result']['progress']['phase'] == 'solve'


@pytest.mark.asyncio
async def test_native_compute_does_not_acquire_llm_lease(tmp_path):
    ctx = SimpleNamespace(tools=ToolRegistry())
    service = AnalysisRuntimeService(tmp_path, ctx)
    class ForbiddenLease:
        def acquire(self, **kwargs):
            raise AssertionError('Native CPU compute must not hold LLM lease')
    service.admission = ForbiddenLease()
    assert await service.compute(lambda: 17, background=True) == 17


@pytest.mark.asyncio
async def test_repeated_cancel_keeps_native_ownership_until_ack(tmp_path):
    service = AnalysisRuntimeService(tmp_path, SimpleNamespace(tools=ToolRegistry()))
    started, release, cancel = threading.Event(), threading.Event(), threading.Event()
    def native():
        started.set()
        release.wait(3)
    task = asyncio.create_task(service.compute(native, cancel_event=cancel))
    while not started.is_set():
        await asyncio.sleep(.01)
    try:
        task.cancel()
        await asyncio.sleep(.02)
        task.cancel()
        await asyncio.sleep(.02)
        assert cancel.is_set()
        assert not task.done()
        assert service._compute_lock.locked()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert not service._compute_lock.locked()
