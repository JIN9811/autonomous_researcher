"""Durable Analysis improvement jobs and immutable loop-pinned model versions.

No device capabilities or mutable experiment state are held here. SQLite provides
cross-thread/process claim and promotion transactions; the worker is owned by the
application, not by a single foreground agent invocation.
"""
from __future__ import annotations

import asyncio
import contextvars
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from typing import Any, Awaitable, Callable


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


class ImprovementStore:
    """One run's evidence queue, model registry and per-loop pins."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'improvement.sqlite3'
        with self._transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS models (version TEXT PRIMARY KEY, scope TEXT NOT NULL, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS active (scope TEXT PRIMARY KEY, version TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS pins (scope TEXT, loop TEXT, version TEXT, PRIMARY KEY(scope, loop))')
            db.execute('CREATE TABLE IF NOT EXISTS snapshots (loop TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS retries (job_id TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS dataset_roles (scope TEXT, acquisition TEXT, role TEXT, candidate TEXT, PRIMARY KEY(scope, acquisition))')
            db.execute('CREATE TABLE IF NOT EXISTS solver_cache (key TEXT PRIMARY KEY, body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS cancellations (job_id TEXT PRIMARY KEY)')

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _job(row):
        return {'job_id': row[0], 'evidence': json.loads(row[1]), 'status': row[2], 'result': json.loads(row[3])} if row else None

    def submit(self, evidence: dict) -> dict:
        body = _json(evidence)
        job_id = digest(evidence)
        with self._transaction() as db:
            existing = self._job(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
            if existing:
                return existing
            if evidence.get('paired_identity_verified'):
                for row in db.execute('SELECT body FROM jobs'):
                    prior = json.loads(row[0])
                    if prior.get('paired_identity_verified') and any(
                        evidence.get(key) and evidence[key] == prior.get(key)
                        for key in ('acquisition_id', 'raw_sha256')
                    ):
                        evidence = {**evidence, 'paired_identity_verified': False,
                                    'identity_reason': 'reused_raw_acquisition'}
                        body = _json(evidence)
                        break
            db.execute('INSERT OR IGNORE INTO jobs VALUES (?, ?, ?, ?)', (job_id, body, 'queued', '{}'))
            return self._job(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def get(self, job_id: str) -> dict | None:
        with self._transaction() as db:
            return self._job(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def jobs(self) -> list[dict]:
        with self._transaction() as db:
            return [self._job(row) for row in db.execute('SELECT * FROM jobs ORDER BY rowid')]

    def claim(self) -> dict | None:
        with self._transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (row[0],))
            return {**self._job(row), 'status': 'running'}

    def finish(self, job_id: str, result: dict) -> None:
        status = result.get('status')
        if status not in {'completed', 'partial', 'failed', 'cancelled', 'needs_more_data', 'budget_exhausted', 'held', 'promoted'}:
            raise ValueError('Invalid improvement terminal status')
        with self._transaction() as db:
            prior = db.execute('SELECT result FROM jobs WHERE id=?', (job_id,)).fetchone()
            merged = {**(json.loads(prior[0]) if prior else {}), **result}
            changed = db.execute("UPDATE jobs SET status=?, result=? WHERE id=? AND status='running'", (status, _json(merged), job_id)).rowcount
            if changed != 1:
                raise ValueError('Only a claimed job can finish')

    def update_progress(self, job_id: str, event: dict) -> None:
        """Append bounded evidence without touching the frozen job input."""
        with self._transaction() as db:
            row = db.execute('SELECT result,status FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None or row[1] != 'running':
                return
            result = json.loads(row[0])
            progress = {k: v for k, v in event.items() if k not in {'attempts', 'events'}}
            result['progress'] = {**result.get('progress', {}), **progress}
            # Native resource samples refresh state; only semantic transitions enter history.
            if 'message' in event or 'decision' in event:
                result['events'] = (result.get('events', []) + [progress])[-128:]
            if 'attempts' in event:
                result['attempts'] = event['attempts']
            db.execute('UPDATE jobs SET result=? WHERE id=?', (_json(result), job_id))

    def request_cancel(self, job_id: str) -> bool:
        with self._transaction() as db:
            row = db.execute('SELECT status,result FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None:
                raise ValueError('Unknown FEM job')
            if row[0] not in {'queued', 'running', 'interrupted'}:
                return False
            db.execute('INSERT OR IGNORE INTO cancellations VALUES (?)', (job_id,))
            if row[0] != 'running':
                result = {**json.loads(row[1]), 'status': 'cancelled', 'reason': 'operator_cancel'}
                db.execute('UPDATE jobs SET status=?,result=? WHERE id=?', ('cancelled', _json(result), job_id))
            return True

    def cancel_requested(self, job_id: str) -> bool:
        with self._transaction() as db:
            return db.execute('SELECT 1 FROM cancellations WHERE job_id=?', (job_id,)).fetchone() is not None

    def recover_interrupted(self) -> None:
        """Called by the sole application owner after acquiring its worker lock."""
        with self._transaction() as db:
            db.execute("UPDATE jobs SET status='interrupted', result=? WHERE status='running'", (_json({'reason': 'worker_restart; explicit resubmission required'}),))

    def retry_interrupted(self, job_id: str) -> None:
        """An explicit operator/runtime request, at most once per immutable job."""
        with self._transaction() as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row[0] != 'interrupted' or db.execute('SELECT 1 FROM retries WHERE job_id=?', (job_id,)).fetchone():
                raise ValueError('Interrupted retry unavailable or retry budget exhausted')
            db.execute('INSERT INTO retries VALUES (?)', (job_id,))
            db.execute("UPDATE jobs SET status='queued', result='{}' WHERE id=?", (job_id,))

    def snapshot_registry(self, loop_key: str) -> dict:
        """Freeze available versions before Design, without guessing its scope."""
        with self._transaction() as db:
            row = db.execute('SELECT body FROM snapshots WHERE loop=?', (loop_key,)).fetchone()
            if row:
                return json.loads(row[0])
            snapshot = dict(db.execute('SELECT scope, version FROM active'))
            db.execute('INSERT INTO snapshots VALUES (?, ?)', (loop_key, _json(snapshot)))
            return snapshot

    def validation_ids(self, scope: str) -> set[str]:
        with self._transaction() as db:
            return {row[0] for row in db.execute("SELECT acquisition FROM dataset_roles WHERE scope=? AND role='validation'", (scope,))}

    def reserve_validation(self, scope: str, candidate: str, train_ids: list[str], holdout_id: str):
        """Consume independent validation exactly once, including failed trials."""
        with self._transaction() as db:
            roles = dict(db.execute('SELECT acquisition, role FROM dataset_roles WHERE scope=?', (scope,)))
            if not train_ids or not holdout_id or holdout_id in train_ids or holdout_id in roles or any(roles.get(item) == 'validation' for item in train_ids):
                raise ValueError('Independent unused validation acquisition required')
            for item in train_ids:
                db.execute('INSERT OR IGNORE INTO dataset_roles VALUES (?, ?, ?, ?)', (scope, item, 'training', candidate))
            db.execute('INSERT INTO dataset_roles VALUES (?, ?, ?, ?)', (scope, holdout_id, 'validation', candidate))

    def cached_solver(self, key: str) -> dict | None:
        with self._transaction() as db:
            row = db.execute('SELECT body FROM solver_cache WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def cache_solver(self, key: str, result: dict):
        if result.get('ok') is not True or result.get('solver_mode') not in {'calculix', 'calculix_quasistatic'}:
            raise ValueError('Only successful real solver results may be cached')
        with self._transaction() as db:
            db.execute('INSERT OR IGNORE INTO solver_cache VALUES (?, ?)', (key, _json(result)))

    def pin_model(self, scope: str, loop_key: str, baseline: dict, *, registry_snapshot: dict | None = None) -> dict:
        with self._transaction() as db:
            row = db.execute('SELECT version FROM pins WHERE scope=? AND loop=?', (scope, loop_key)).fetchone()
            if not row:
                active = (db.execute('SELECT version FROM active WHERE scope=?', (scope,)).fetchone()
                          if registry_snapshot is None else
                          ((registry_snapshot[scope],) if scope in registry_snapshot else None))
                version = active[0] if active else digest({'scope': scope, 'parameters': baseline})
                if not active:
                    model = {'version': version, 'scope': scope, 'parameters': baseline, 'status': 'baseline', 'parent': None}
                    db.execute('INSERT OR IGNORE INTO models VALUES (?, ?, ?)', (version, scope, _json(model)))
                db.execute('INSERT INTO pins VALUES (?, ?, ?)', (scope, loop_key, version))
            else:
                version = row[0]
            return json.loads(db.execute('SELECT body FROM models WHERE version=?', (version,)).fetchone()[0])

    def save_candidate(self, scope: str, parent: str, parameters: dict, validation: dict) -> dict:
        model = {'scope': scope, 'parent': parent, 'parameters': parameters, 'validation': validation, 'status': 'candidate'}
        model['version'] = digest(model)
        with self._transaction() as db:
            base = db.execute('SELECT scope FROM models WHERE version=?', (parent,)).fetchone()
            if not base or base[0] != scope:
                raise ValueError('Candidate parent scope mismatch')
            db.execute('INSERT OR IGNORE INTO models VALUES (?, ?, ?)', (model['version'], scope, _json(model)))
        return model

    def promote(self, version: str) -> dict:
        with self._transaction() as db:
            row = db.execute('SELECT body FROM models WHERE version=?', (version,)).fetchone()
            if not row:
                raise ValueError('Unknown model')
            model = json.loads(row[0])
            checks = model.get('validation', {})
            train, holdout = set(checks.get('train_ids', [])), set(checks.get('holdout_ids', []))
            if not train or not holdout or train & holdout or not checks.get('evidence_refs'):
                raise ValueError('Independent validation evidence required')
            for key in ('numerically_valid', 'within_bounds', 'comparison_compatible', 'cost_within_budget', 'secondary_checks_passed'):
                if checks.get(key) is not True:
                    raise ValueError(f'Candidate failed {key}')
            before, after = checks.get('baseline_error'), checks.get('candidate_error')
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 for v in (before, after)) or after >= before:
                raise ValueError('Independent error improvement required')
            active = db.execute('SELECT version FROM active WHERE scope=?', (model['scope'],)).fetchone()
            if active and active[0] not in {model['parent'], version}:
                raise ValueError('Candidate parent superseded; revalidation required')
            db.execute('INSERT INTO active VALUES (?, ?) ON CONFLICT(scope) DO UPDATE SET version=excluded.version', (model['scope'], version))
            return model


class AnalysisImprovementWorker:
    """Event-driven worker; explicit None means no wall-clock deadline."""

    def __init__(self, store: ImprovementStore, execute: Callable[[dict], Awaitable[dict]], *, timeout_s: float | None = None):
        if timeout_s is not None and (not math.isfinite(timeout_s) or timeout_s <= 0):
            raise ValueError('Finite positive worker timeout required')
        self.store, self.execute, self.timeout_s = store, execute, timeout_s
        self._task: asyncio.Task | None = None
        self._closed = False
        self.last_error = None

    def start(self, *, poll_interval_s=0.5, max_jobs=None, max_runtime_s=None):
        """Explicitly admit queued work; optional bounds preserve legacy callers."""
        if self._closed:
            raise RuntimeError('Improvement worker is closed')
        if not (math.isfinite(poll_interval_s) and 0 < poll_interval_s <= 60
                and (max_jobs is None or isinstance(max_jobs, int) and 0 < max_jobs <= 120)
                and (max_runtime_s is None or math.isfinite(max_runtime_s) and 0 < max_runtime_s <= 3600)):
            raise ValueError('Finite worker admission limits required')
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(poll_interval_s, max_jobs, max_runtime_s),
                name='analysis-improvement', context=contextvars.Context())

    def submit(self, evidence: dict) -> dict:
        if self._closed:
            raise RuntimeError('Improvement worker is closed')
        job = self.store.submit(evidence)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name='analysis-improvement', context=contextvars.Context())
        return {key: job[key] for key in ('job_id', 'status')}

    async def _run(self, poll_interval_s=0, max_jobs=None, max_runtime_s=None):
        deadline, used = (time.monotonic() + max_runtime_s if max_runtime_s is not None else math.inf), 0
        while not self._closed and (max_jobs is None or used < max_jobs) and time.monotonic() < deadline:
            try:
                job = self.store.claim()
            except sqlite3.Error as exc:
                self.last_error = type(exc).__name__
                return
            if not job:
                if not poll_interval_s:
                    return
                await asyncio.sleep(poll_interval_s)
                continue
            used += 1
            try:
                timeout = min(self.timeout_s if self.timeout_s is not None else math.inf, max(0.001, deadline - time.monotonic()))
                execution = self.execute({**job['evidence'], '_job_id': job['job_id']})
                result = await execution if math.isinf(timeout) else await asyncio.wait_for(execution, timeout)
            except asyncio.CancelledError:
                self._finish(job['job_id'], {'status': 'cancelled', 'reason': 'application_shutdown'})
                raise
            except asyncio.TimeoutError:
                result = {'status': 'budget_exhausted', 'reason': 'wall_time'}
            except Exception as exc:
                result = {'status': 'failed', 'reason': type(exc).__name__}
            self._finish(job['job_id'], result)

    def _finish(self, job_id, result):
        try:
            self.store.finish(job_id, result)
        except sqlite3.Error as exc:
            # Leave the durable running record for startup recovery. Optional
            # storage failure cannot obstruct application resource cleanup.
            self.last_error = type(exc).__name__

    async def drain(self):
        while self._task and not self._task.done():
            if not any(job['status'] in {'queued', 'running'} for job in self.store.jobs()):
                return
            await asyncio.sleep(0.01)
        if self._task:
            await asyncio.shield(self._task)

    async def shutdown(self):
        self._closed = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


def curve_error(observed: list, simulated: list) -> float:
    """Axis-integrated RMS residual; no extrapolation or sample-count weighting."""
    import numpy as np
    exp, sim = np.asarray(observed, dtype=float), np.asarray(simulated, dtype=float)
    for curve in (exp, sim):
        if curve.ndim != 2 or curve.shape[1] != 2 or len(curve) < 2 or not np.isfinite(curve).all() or not (np.diff(curve[:, 0]) > 0).all():
            raise ValueError('Finite monotonic two-column curves required')
    if sim[0, 0] > exp[0, 0] or sim[-1, 0] < exp[-1, 0]:
        raise ValueError('Simulation does not cover observation domain')
    axis = np.unique(np.concatenate((exp[:, 0], sim[(sim[:, 0] >= exp[0, 0]) & (sim[:, 0] <= exp[-1, 0]), 0])))
    residual = np.interp(axis, sim[:, 0], sim[:, 1]) - np.interp(axis, exp[:, 0], exp[:, 1])
    # Exact integral of the square of a piecewise-linear residual.
    integral = np.sum(np.diff(axis) * (residual[:-1] ** 2 + residual[:-1] * residual[1:] + residual[1:] ** 2) / 3)
    return float(np.sqrt(integral / (axis[-1] - axis[0])))
