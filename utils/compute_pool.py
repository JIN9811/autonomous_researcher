"""Bounded CPU-only workers. No controller, registry, device or LLM is submitted.

Fresh interpreters avoid importing a server/recovery launcher as __mp_main__.
Coordinator threads only exchange JSON with three independent Python processes.
The service is enabled by server startup, not by importing an agent or a test.
"""
from __future__ import annotations

import asyncio
import atexit
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import queue
import selectors
import subprocess
import sys
import threading
import time

JOBS = frozenset({'geometry.generate', 'geometry.quality', 'geometry.manufacturability',
                  'analysis.read_curve', 'analysis.metrics', 'bo.propose', 'bo.render'})
MAX_MESSAGE = 64 * 1024 * 1024
_cancellation = ContextVar('cpu_cancellation', default=None)


class ComputeError(RuntimeError):
    pass


class _Worker:
    def __init__(self):
        self.process = None

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            process.stdin.close()
            process.stdout.close()

    def exchange(self, message, cancelled, deadline):
        if self.process is None or self.process.poll() is not None:
            self.close()
            env = {key: os.environ[key] for key in ('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'VIRTUAL_ENV')
                   if key in os.environ}
            env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                       NUMEXPR_NUM_THREADS='1', MPLBACKEND='Agg')
            self.process = subprocess.Popen([sys.executable, '-m', 'utils.compute_worker'],
                cwd=Path(__file__).resolve().parents[1], env=env, close_fds=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        process = self.process
        try:
            process.stdin.write(message)
            process.stdin.flush()
            response = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if cancelled.is_set():
                        raise ComputeError('CPU job cancelled; result not applied')
                    if time.monotonic() >= deadline:
                        raise TimeoutError('CPU job exceeded its compute deadline')
                    if not selector.select(.1):
                        continue
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        raise ComputeError('CPU worker exited without a result')
                    response.extend(chunk)
                    if len(response) > MAX_MESSAGE:
                        raise ComputeError('CPU worker response exceeds 64 MiB')
                    if response.endswith(b'\n'):
                        return json.loads(response)
        except BaseException:
            self.close()  # Never automatically retry a partially written artifact.
            raise


class ComputePool:
    def __init__(self, workers=3):
        if not 1 <= workers <= 3:
            raise ValueError('Use 1–3 compute workers alongside the single controller')
        self.workers = [_Worker() for _ in range(workers)]
        self.available = queue.Queue()
        for worker in self.workers:
            self.available.put(worker)
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='cpu-worker-io')
        self.slots = threading.BoundedSemaphore(workers * 2)
        self.lock = threading.Lock()
        self.closed = False
        self.active = self.pending = self.completed = self.failed = 0
        self.cancellations = set()

    def submit(self, job, payload, *, timeout=300, cancellation=None):
        if job not in JOBS:
            raise ValueError(f'Not a CPU-only job: {job}')
        if not self.slots.acquire(blocking=False):
            raise ComputeError('CPU queue full; no work was submitted')
        try:
            message = json.dumps({'job': job, 'payload': payload}, allow_nan=False).encode() + b'\n'
            if len(message) > MAX_MESSAGE:
                raise ValueError('CPU job exceeds 64 MiB')
            cancelled = cancellation if cancellation is not None else threading.Event()
            deadline = time.monotonic() + timeout
            with self.lock:
                if self.closed:
                    raise ComputeError('CPU pool is closed')
                self.pending += 1
                self.cancellations.add(cancelled)
                future = self.executor.submit(self._run, message, cancelled, deadline)
        except BaseException:
            self.slots.release()
            raise
        def release(_):
            with self.lock:
                self.pending -= 1
                self.cancellations.discard(cancelled)
            self.slots.release()
        future.add_done_callback(release)
        return future, cancelled

    def _run(self, message, cancelled, deadline):
        worker = self.available.get()
        with self.lock:
            self.active += 1
        try:
            if cancelled.is_set() or time.monotonic() >= deadline:
                raise ComputeError('CPU job expired before execution')
            response = worker.exchange(message, cancelled, deadline)
            if not response.get('ok'):
                error = response['error']
                if error['type'] == 'BoTorchBackendError':
                    from learning.botorch_backend import BoTorchBackendError
                    raise BoTorchBackendError(error['message'], failure_code=error['failure_code'], details=error.get('details'))
                exception = {'ValueError': ValueError, 'TypeError': TypeError,
                             'FileNotFoundError': FileNotFoundError}.get(error['type'], ComputeError)
                raise exception(error['message'])
            with self.lock:
                self.completed += 1
            return response['result']
        except BaseException:
            with self.lock:
                self.failed += 1
            raise
        finally:
            with self.lock:
                self.active -= 1
            self.available.put(worker)

    def status(self):
        with self.lock:
            processes = [w.process for w in self.workers]
            return {'enabled': not self.closed, 'workers': len(self.workers),
                    'active': self.active, 'queued': self.pending-self.active,
                    'completed': self.completed, 'failed': self.failed,
                    'pids': [p.pid for p in processes if p is not None and p.poll() is None],
                    'threads_per_worker': 1, 'queue_limit': len(self.workers)}

    def close(self):
        with self.lock:
            self.closed = True
            for cancellation in self.cancellations:
                cancellation.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
        for worker in self.workers:
            worker.close()


_pool = None


def configure_compute_pool(workers=3):
    global _pool
    if _pool is not None:
        raise RuntimeError('CPU pool already configured')
    if workers:
        _pool = ComputePool(workers)


def compute_enabled():
    return _pool is not None


def compute_status():
    return _pool.status() if _pool else {'enabled': False, 'workers': 0, 'pids': []}


def compute_sync(job, payload, *, timeout=300):
    pool = _pool
    if pool is None:
        raise ComputeError('CPU pool is not configured')
    future, _ = pool.submit(job, payload, timeout=timeout, cancellation=_cancellation.get())
    return future.result()


async def compute_async(job, payload, *, timeout=300):
    pool = _pool
    if pool is None:
        from utils.compute_jobs import execute
        return execute(job, payload)
    future, cancelled = pool.submit(job, payload, timeout=timeout)
    try:
        return await asyncio.wrap_future(future)
    except asyncio.CancelledError:
        cancelled.set()
        future.cancel()
        raise


async def offload_wait(callback, *args, **kwargs):
    """Wait without blocking the event loop; cancellation reaches CPU subprocesses."""
    cancelled = threading.Event()
    token = _cancellation.set(cancelled)
    try:
        return await asyncio.to_thread(callback, *args, **kwargs)
    except asyncio.CancelledError:
        cancelled.set()
        raise
    finally:
        _cancellation.reset(token)


def run_tool_steps(steps, tools):
    value = None
    error = None
    try:
        while True:
            name, payload = steps.throw(error) if error else steps.send(value)
            error = None
            try:
                value = tools.call(name, payload)
            except Exception as exc:
                error = exc
    except StopIteration as done:
        return done.value
    finally:
        steps.close()


async def run_tool_steps_async(steps, tools, state):
    # Only immutable numerical payloads leave the main execution thread.
    identity = (state.run_id, state.experiment_id, state.loop_count)
    value = None
    error = None
    try:
        while True:
            ensure_current(state, identity)
            try:
                name, payload = steps.throw(error) if error else steps.send(value)
            except StopIteration as done:
                return done.value
            error = None
            try:
                if name.startswith('geometry.'):
                    value = await offload_wait(tools.call, name, payload)
                else:
                    value = tools.call(name, payload)
            except Exception as exc:
                error = exc
    finally:
        steps.close()


def ensure_current(state, identity):
    if (identity != (state.run_id, state.experiment_id, state.loop_count)
            or state.stop_requested or state.safe_stop_requested or state.emergency_stop_requested):
        raise asyncio.CancelledError('Discarded stale/stopped calculation')


def close_compute_pool():
    global _pool
    pool, _pool = _pool, None
    if pool is not None:
        pool.close()


atexit.register(close_compute_pool)
