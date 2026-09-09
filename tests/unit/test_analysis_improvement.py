"""Persistent model updates must not rewrite a running experiment."""
import asyncio

import pytest

from agents import analysis_improvement as module


def store_at(tmp_path):
    assert hasattr(module, 'ImprovementStore'), 'durable improvement store is required'
    return module.ImprovementStore(tmp_path)


def test_enqueue_is_durable_deduplicated_and_immutable(tmp_path):
    store = store_at(tmp_path)
    evidence = {'experiment_id': 'e1', 'curve': [1, 2], 'scope': 's'}
    first = store.submit(evidence)
    evidence['curve'].append(3)
    assert store.get(first['job_id'])['evidence']['curve'] == [1, 2]
    second = store_at(tmp_path).submit({'experiment_id': 'e1', 'curve': [1, 2], 'scope': 's'})
    assert second['job_id'] == first['job_id']
    assert len(store.jobs()) == 1


def test_claim_is_exclusive_and_restart_does_not_repeat_running_work(tmp_path):
    store = store_at(tmp_path)
    job = store.submit({'experiment_id': 'e1'})
    assert store.claim()['job_id'] == job['job_id']
    assert store_at(tmp_path).claim() is None
    store.recover_interrupted()
    assert store.get(job['job_id'])['status'] == 'interrupted'
    assert store.claim() is None


def test_same_loop_model_is_frozen_after_promotion(tmp_path):
    store = store_at(tmp_path)
    first = store.pin_model('s', 'loop-1', {'material': {'elastic_modulus_mpa': 100}})
    candidate = store.save_candidate('s', first['version'], {'material': {'elastic_modulus_mpa': 120}}, validation())
    store.promote(candidate['version'])
    assert store.pin_model('s', 'loop-1', {}) == first
    assert store.pin_model('s', 'loop-2', {})['version'] == candidate['version']
    assert store.pin_model('other-scope', 'loop-2', {})['version'] != candidate['version']


def validation():
    return {'train_ids': ['train-1'], 'holdout_ids': ['validation-1'],
            'baseline_error': 10.0, 'candidate_error': 5.0,
            'numerically_valid': True, 'within_bounds': True,
            'comparison_compatible': True, 'cost_within_budget': True,
            'secondary_checks_passed': True, 'evidence_refs': ['heldout-curve-hash']}


@pytest.mark.parametrize('patch', [
    {'holdout_ids': []}, {'holdout_ids': ['train-1']}, {'candidate_error': 20},
    {'candidate_error': float('nan')}, {'numerically_valid': False},
    {'within_bounds': False}, {'comparison_compatible': False}, {'evidence_refs': []},
])
def test_model_cannot_be_promoted_without_independent_valid_evidence(tmp_path, patch):
    store = store_at(tmp_path)
    base = store.pin_model('s', 'loop-1', {})
    with pytest.raises(ValueError):
        candidate = store.save_candidate('s', base['version'], {'material': {}}, {**validation(), **patch})
        store.promote(candidate['version'])
    assert store.pin_model('s', 'loop-2', {})['version'] == base['version']


@pytest.mark.asyncio
async def test_background_work_does_not_block_submit_and_shutdown_records_cancel(tmp_path):
    store = store_at(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()
    async def execute(evidence):
        started.set()
        await release.wait()
        return {'status': 'completed'}
    worker = module.AnalysisImprovementWorker(store, execute)
    first = worker.submit({'experiment_id': 'e1'})
    await asyncio.wait_for(started.wait(), 1)
    second = worker.submit({'experiment_id': 'e2'})
    assert second['status'] == 'queued'
    await worker.shutdown()
    assert store.get(first['job_id'])['status'] == 'cancelled'
    assert store.get(second['job_id'])['status'] == 'queued'


@pytest.mark.asyncio
async def test_worker_failure_is_recorded_and_new_evidence_can_progress(tmp_path):
    store = store_at(tmp_path)
    async def execute(evidence):
        if evidence['experiment_id'] == 'bad':
            raise ValueError('invalid evidence')
        return {'status': 'needs_more_data', 'reason': 'independent experiment required'}
    worker = module.AnalysisImprovementWorker(store, execute)
    first = worker.submit({'experiment_id': 'bad'})
    second = worker.submit({'experiment_id': 'good'})
    await asyncio.wait_for(worker.drain(), 1)
    assert store.get(first['job_id'])['status'] == 'failed'
    assert store.get(second['job_id'])['status'] == 'needs_more_data'
    await worker.shutdown()


@pytest.mark.asyncio
async def test_worker_resumes_existing_queue_and_polls_cross_process_submissions(tmp_path):
    store = store_at(tmp_path)
    initial = store.submit({'experiment_id': 'already-queued'})
    completed = asyncio.Event()
    async def execute(evidence):
        if evidence['experiment_id'] == 'external':
            completed.set()
        return {'status': 'completed'}
    worker = module.AnalysisImprovementWorker(store, execute)
    worker.start(poll_interval_s=0.01, max_jobs=2, max_runtime_s=1)
    await asyncio.wait_for(worker.drain(), 1)
    assert store.get(initial['job_id'])['status'] == 'completed'
    external = store_at(tmp_path).submit({'experiment_id': 'external'})
    await asyncio.wait_for(completed.wait(), 1)
    await worker.drain()
    assert store.get(external['job_id'])['status'] == 'completed'
    await worker.shutdown()


def test_interrupted_retry_is_deliberate_and_bounded(tmp_path):
    store = store_at(tmp_path)
    job = store.submit({'experiment_id': 'restart'})
    store.claim()
    store.recover_interrupted()
    assert store.submit({'experiment_id': 'restart'})['status'] == 'interrupted'
    store.retry_interrupted(job['job_id'])
    assert store.claim()['job_id'] == job['job_id']
    store.recover_interrupted()
    with pytest.raises(ValueError, match='retry'):
        store.retry_interrupted(job['job_id'])


def test_holdout_is_reserved_once_and_never_reused_as_training(tmp_path):
    store = store_at(tmp_path)
    store.reserve_validation('s', 'candidate1', ['acq1'], 'acq2')
    reopened = store_at(tmp_path)
    assert reopened.validation_ids('s') == {'acq2'}
    with pytest.raises(ValueError, match='validation'):
        reopened.reserve_validation('s', 'candidate2', ['acq1'], 'acq2')
    with pytest.raises(ValueError, match='validation'):
        reopened.reserve_validation('s', 'candidate2', ['acq2'], 'acq3')
    with pytest.raises(ValueError, match='validation'):
        reopened.reserve_validation('s', 'candidate2', ['acq3'], 'acq1')


def test_successful_solver_cache_is_persistent_and_does_not_accept_failed_results(tmp_path):
    store = store_at(tmp_path)
    store.cache_solver('job', {'ok': True, 'solver_mode': 'calculix', 'curve': [[0, 0], [1, 2]]})
    assert store_at(tmp_path).cached_solver('job')['curve'] == [[0, 0], [1, 2]]
    with pytest.raises(ValueError):
        store.cache_solver('failed', {'ok': False})


@pytest.mark.asyncio
async def test_worker_window_caps_execution_and_storage_failure_does_not_break_shutdown(tmp_path, monkeypatch):
    import sqlite3
    store = store_at(tmp_path)
    started = asyncio.Event()
    async def execute(evidence):
        started.set()
        await asyncio.Event().wait()
    worker = module.AnalysisImprovementWorker(store, execute, timeout_s=10)
    job = store.submit({'experiment_id': 'bounded'})
    worker.start(poll_interval_s=0.01, max_runtime_s=0.02)
    await asyncio.wait_for(worker.drain(), 0.3)
    assert store.get(job['job_id'])['status'] == 'budget_exhausted'
    # SQLite may become unavailable during shutdown; it must not prevent the
    # application from continuing to release its other resources.
    started.clear()
    worker.submit({'experiment_id': 'shutdown'})
    await asyncio.wait_for(started.wait(), 0.3)
    await asyncio.sleep(0)
    def locked(*args):
        raise sqlite3.OperationalError('locked')
    monkeypatch.setattr(store, 'finish', locked)
    await worker.shutdown()


def test_curve_error_uses_shared_domain_not_csv_row_count():
    assert hasattr(module, 'curve_error'), 'physical comparison is required'
    assert module.curve_error([[0, 0], [1, 2]], [[0, 0], [0.5, 1], [1, 2]]) == 0
    with pytest.raises(ValueError):
        module.curve_error([[0, 0], [2, 4]], [[0, 0], [1, 2]])
