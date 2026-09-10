"""Runtime binding for Analysis-owned background computation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import is_dataclass, replace
import fcntl
import hashlib
from pathlib import Path
import sqlite3
import threading

from agents.analysis_decisions import decide
from agents.analysis_improvement import AnalysisImprovementWorker, ImprovementStore, digest
from agents.analysis_refinement import refine
from backends.llm_lease import LLMLeaseCoordinator


def service_for(ctx):
    tools, root = getattr(ctx, 'tools', None), getattr(ctx, 'artifact_run_root', None)
    if tools is None or not root or not hasattr(tools, 'resource'):
        return None
    service = tools.resource('analysis_improvement')
    if service is None:
        service = AnalysisRuntimeService(Path(root), ctx)
        tools.register_resource('analysis_improvement', service)
    return service


def pin_loop(state, ctx, *, resume_background=False):
    """Freeze registry availability at the boundary, before Design is finalized."""
    existing = state.run_metadata.get('analysis_registry_snapshot', {})
    loop_key = f'{state.run_id}:loop-{state.loop_count}'
    if existing.get('loop_key') == loop_key:
        return existing
    snapshot = {'loop_key': loop_key, 'versions': {}}
    try:
        service = service_for(ctx)
        if service is not None:
            snapshot['versions'] = service.store(state.run_id).snapshot_registry(loop_key)
            if resume_background:
                service.resume(state.run_id, virtual=state.mode.value != 'live' and not getattr(ctx, 'force_real_llm_in_test', True))
    except (OSError, ValueError, sqlite3.Error) as exc:
        # Even an unavailable registry is frozen: later recovery must not adopt
        # a mid-loop promotion. Foreground still uses the finalized Design.
        snapshot['error'] = type(exc).__name__
        state.run_metadata['analysis_improvement_error'] = type(exc).__name__
    state.run_metadata['analysis_registry_snapshot'] = snapshot
    return snapshot


def resolve_loop_model(state, ctx):
    snapshot = pin_loop(state, ctx)
    loop_key = snapshot['loop_key']
    existing = state.run_metadata.get('analysis_model_pin', {})
    if existing.get('loop_key') == loop_key:
        return existing
    service = service_for(ctx)
    if service is None:
        return {}
    from agents.analysis_agent import AnalysisAgent
    agent = AnalysisAgent()
    payload = agent._cae_payload(state, agent._specimen_geometry(state))
    parameters = {'material': payload['material'], 'mesh_size_mm': payload['mesh_size_mm']}
    geometry_path = Path(payload['stl_path']) if payload.get('stl_path') else None
    scope = digest({'parameters': parameters,
                    'compatibility': {key: payload.get(key) for key in (
                        'loading', 'boundary', 'boundary_condition', 'loading_mode', 'fixture',
                        'specimen_size_mm', 'cross_section_area_mm2', 'gauge_length_mm',
                        'generated_model_caps', 'design_parameters')},
                    'geometry_sha256': hashlib.sha256(geometry_path.read_bytes()).hexdigest() if geometry_path and geometry_path.is_file() else None,
                    'objective': state.current_experiment_objective})
    model = service.store(state.run_id).pin_model(scope, loop_key, parameters,
                                                registry_snapshot=snapshot['versions'])
    pin = {'loop_key': loop_key, 'scope': scope, 'model': model}
    state.run_metadata['analysis_model_pin'] = pin
    return pin


def _acquisition_identity(state, source, original_stl, hashes):
    """Use Equipment's acquisition-to-specimen binding, never CSV presence alone.

    Archived operator attestations are imported separately as immutable evidence;
    the foreground runtime deliberately has no attestation bypass.
    """
    from agents.analysis_agent import AnalysisAgent
    equipment = AnalysisAgent._equipment_result(state)
    specimen = state.run_metadata.get('specimen_result', {})
    specimen_id = state.current_experiment_spec.get('specimen_id')
    raw_path = source.get('path')
    raw_hash, geometry_hash = hashes.get(raw_path), hashes.get(original_stl)
    result = {'acquisition_id': None, 'specimen_id': specimen_id, 'raw_sha256': raw_hash,
              'geometry_sha256': geometry_hash, 'paired_identity_verified': False,
              'identity_reason': 'equipment_acquisition_binding_required'}
    if not (raw_hash and geometry_hash and specimen_id and specimen.get('specimen_id') == specimen_id
            and specimen.get('stl_path') and Path(specimen['stl_path']).resolve() == Path(original_stl).resolve()):
        return result
    packets = [equipment.get(key, {}) for key in ('raw_data_export', 'data_acquisition', 'utm_data_ready')]
    packets += [p for p in equipment.get('output_artifacts', []) if isinstance(p, dict) and p.get('kind') == 'utm_csv']
    # Current Equipment managed exports bind loop/repeat in an exact filename,
    # not in each packet. Reuse its existing parser/hash binding against the
    # current request context; never infer identity from an arbitrary basename.
    from agents.equipment_agent import LabEquipmentAgent
    from utils.equipment_agentic_task import bind_cycle_csv_artifact
    unbound = deepcopy(equipment)
    for artifact in unbound.get('output_artifacts', []):
        if isinstance(artifact, dict):
            artifact.pop('identity_source', None)
    export_context = LabEquipmentAgent._raw_csv_export_context(state, {'specimen': specimen})
    bound = bind_cycle_csv_artifact(unbound, run_id=state.run_id, export_context=export_context)
    if any(a.get('identity_source') == 'managed_export_filename_and_local_sha256'
           for a in bound.get('output_artifacts', []) if isinstance(a, dict)):
        packets.append({**bound.get('data_acquisition', {}), 'loop_id': state.loop_count})
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        path = packet.get('path') or packet.get('linux_path') or packet.get('local_path')
        acquisition = packet.get('acquisition_id') or packet.get('artifact_id')
        loop = packet.get('loop_id', packet.get('loop_count'))
        if (equipment.get('ok') is True and acquisition and path and Path(path).resolve() == Path(raw_path).resolve()
                and packet.get('sha256') == raw_hash and packet.get('run_id') == state.run_id
                and str(loop) == str(state.loop_count) and packet.get('specimen_id') == specimen_id
                and packet.get('simulated') is not True and equipment.get('simulated') is not True
                and packet.get('geometry_sha256', geometry_hash) == geometry_hash
                and (packet.get('validated') is True or packet.get('status') in {'pulled_to_linux', 'ready'})):
            result.update(acquisition_id=str(acquisition), paired_identity_verified=True,
                          identity_reason='equipment_raw_hash_specimen_geometry_bound')
            return result
    return result


class AnalysisRuntimeService:
    def __init__(self, root, ctx):
        self.root, self.ctx = root.resolve(), ctx
        self._stores, self._workers, self._locks = {}, {}, {}
        self.admission = LLMLeaseCoordinator()
        self._compute_lock = asyncio.Lock()
        self._cancel_events = {}
        self.errors = {}

    def store(self, run_id):
        if run_id not in self._stores:
            from utils.agent_artifact_archive import _safe
            path = self.root / _safe(run_id) / 'runtime' / 'analysis_improvement'
            if not path.resolve().is_relative_to(self.root):
                raise ValueError('Invalid improvement run path')
            self._stores[run_id] = ImprovementStore(path)
        return self._stores[run_id]

    async def compute(self, call, *, background=False, cancel_event=None):
        # Native CPU work must not occupy the model lease used by foreground agents.
        async with self._compute_lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / 'analysis-fem.compute.lock').open('a') as handle:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise asyncio.CancelledError
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        await asyncio.sleep(.1)
                task = asyncio.create_task(asyncio.to_thread(call))
                try:
                    return await asyncio.shield(task)
                except asyncio.CancelledError:
                    if cancel_event is not None:
                        cancel_event.set()
                    # Keep ownership until the bridge acknowledges native termination.
                    while not task.done():
                        try:
                            await asyncio.shield(task)
                        except asyncio.CancelledError:
                            # Operator cancellation and shutdown can overlap.
                            # Neither may release a still-running native process.
                            continue
                    if not task.cancelled():
                        task.exception()  # Retrieve native failure; cancellation remains authoritative.
                    raise

    def recover_existing(self, *, max_runs=100):
        """Startup metadata recovery only; no LLM or solver work is admitted."""
        from itertools import islice
        for path in islice(self.root.glob('*/runtime/analysis_improvement/improvement.sqlite3'), max_runs):
            run_id = path.parents[2].name
            try:
                store = self.store(run_id)
                with (store.root / 'worker.lock').open('a') as handle:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    store.recover_interrupted()
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.errors[run_id] = type(exc).__name__

    def resume(self, run_id, *, virtual=False, retry_job_id=None, max_jobs=None, max_runtime_s=None):
        """Explicit active-runtime admission; startup never calls this method."""
        store = self.store(run_id)
        if run_id not in self._workers:
            handle = (store.root / 'worker.lock').open('a')
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                return False
            try:
                store.recover_interrupted()
            except BaseException:
                handle.close()
                raise
            self._locks[run_id] = handle
            async def execute(item):
                ctx = replace(self.ctx, on_model_call=None, on_tool_event=None, on_knowledge_ingest=None) if is_dataclass(self.ctx) else self.ctx
                async def choose(phase, evidence, options):
                    return await decide(ctx, phase, evidence, options, virtual=item.get('virtual_decisions', virtual), background=True)
                if item.get('job_kind') == 'fem':
                    from agents.analysis_fem import run_fem_study
                    job_id = item['_job_id']
                    cancel_event = threading.Event()
                    self._cancel_events[(run_id, job_id)] = cancel_event
                    def emit(event):
                        store.update_progress(job_id, event)
                    async def call_tool(name, data):
                        if name not in {'cae.prepare_static_analysis', 'cae.run_static_analysis'}:
                            raise ValueError('Unregistered background FEM tool')
                        def invoke():
                            request = {**data, '_cancel_event': cancel_event, '_progress_callback': emit}
                            return ctx.tools.call(name, request)
                        return await self.compute(invoke, background=True, cancel_event=cancel_event)
                    task = asyncio.create_task(run_fem_study({**item, 'job_id': job_id}, choose, call_tool, emit))
                    async def cancellation_watch():
                        while not task.done():
                            if store.cancel_requested(job_id):
                                cancel_event.set()
                                task.cancel()
                                return
                            await asyncio.sleep(.2)
                    watcher = asyncio.create_task(cancellation_watch())
                    try:
                        return await task
                    except asyncio.CancelledError:
                        cancel_event.set()
                        return {'status': 'cancelled', 'reason': 'operator_or_application_cancel'}
                    finally:
                        watcher.cancel()
                        await asyncio.gather(watcher, return_exceptions=True)
                        self._cancel_events.pop((run_id, job_id), None)
                async def solve(data):
                    return await self.compute(lambda: ctx.tools.call('cae.run_static_analysis', data), background=True)
                return await refine(store, item, choose, solve)
            self._workers[run_id] = AnalysisImprovementWorker(store, execute, timeout_s=None)
        if retry_job_id is not None:
            store.retry_interrupted(retry_job_id)
        worker = self._workers[run_id]
        previous_task = worker._task
        worker.start(max_jobs=max_jobs, max_runtime_s=max_runtime_s)
        if worker._task is not previous_task:
            def release(task):
                if self._workers.get(run_id) is worker and worker._task is task:
                    self._workers.pop(run_id, None)
                    handle = self._locks.pop(run_id, None)
                    if handle is not None:
                        handle.close()
            worker._task.add_done_callback(release)
        return True

    def submit(self, state, analysis, curve, payload, *, job_kind='refinement'):
        pin = resolve_loop_model(state, self.ctx)
        store = self.store(state.run_id)
        source = analysis.get('source', {})
        input_hashes = {}
        original_hashes = {}
        original_stl = payload.get('stl_path')
        payload = deepcopy(payload)
        for raw in (source.get('path'), payload.get('stl_path')):
            if raw and Path(raw).is_file():
                content = Path(raw).read_bytes()
                file_hash = hashlib.sha256(content).hexdigest()
                original_hashes[raw] = file_hash
                frozen = store.root / 'inputs' / f'{file_hash}{Path(raw).suffix.lower()}'
                frozen.parent.mkdir(exist_ok=True)
                if not frozen.exists():
                    with frozen.open('xb') as handle:
                        handle.write(content)
                input_hashes[str(frozen.resolve())] = file_hash
                if raw == original_stl:
                    payload['stl_path'] = str(frozen.resolve())
        identity = _acquisition_identity(state, source, original_stl, original_hashes)
        # Only measured data with explicit specimen/geometry identity can calibrate.
        source_kind = 'synthetic' if str(source.get('source', '')).startswith(('synthetic', 'cae')) else 'measured'
        observation = []
        target = float(payload['loading']['target_strain']) * float(payload['gauge_length_mm'])
        for point in curve:
            x, y = float(point['displacement_mm']), float(point['force_N'])
            if not observation or x > observation[-1][0]:
                if x <= target:
                    observation.append([x, y])
                elif observation:
                    x0, y0 = observation[-1]
                    if x0 < target:
                        observation.append([target, y0 + (y - y0) * (target - x0) / (x - x0)])
                    break
        if not observation or observation[-1][0] < target:
            identity.update(paired_identity_verified=False, identity_reason='observation_domain_incomplete')
        policy = deepcopy(state.current_experiment_spec.get('analysis_improvement', {}))
        evidence = {'schema': 'analysis_improvement_evidence.v1', 'run_id': state.run_id,
                    'job_kind': job_kind,
                    'experiment_id': state.experiment_id, 'loop_key': pin['loop_key'], 'scope': pin['scope'],
                    'model': pin['model'], 'source_kind': source_kind, **identity,
                    'input_hashes': input_hashes, 'observation': observation, 'payload': deepcopy(payload),
                    'policy': policy, 'virtual_decisions': state.mode.value != 'live' and not getattr(self.ctx, 'force_real_llm_in_test', True),
                    'analysis_artifacts': deepcopy(analysis.get('analysis_artifacts', {}))}
        if job_kind == 'fem':
            evidence.update(experiment_curve=deepcopy(curve),
                            specimen_geometry=deepcopy(analysis.get('specimen_geometry', {})),
                            coordinate_convention={'name': 'contact_threshold', 'relative_force_threshold': .01,
                                                   'absolute_force_threshold_N': 2.0})
            evidence['payload']['computation_limits'] = {
                'timeout_s': None, 'threads': 10, 'equation_solver_threads': 10,
                'max_mesh_elements': int(policy.get('max_mesh_elements', 500000)),
            }
            # Reproduce the retained reference preprocessing on this specimen's STL,
            # never reuse the archived specimen's mesh or claim material validation.
            spec = state.current_experiment_spec
            if 'cae_mesh_size_mm' not in spec and 'mesh_size_mm' not in spec:
                evidence['payload']['mesh_size_mm'] = float(policy.get('mesh_size_mm', .8))
            evidence['payload']['surface_remesh'] = deepcopy(policy.get('surface_remesh', {
                'method': 'isotropic', 'edge_length_mm': evidence['payload']['mesh_size_mm'],
                'iterations': 8, 'max_surface_distance_mm': .0275,
            }))
            evidence['payload']['boundary_tolerance_mm'] = float(policy.get('boundary_tolerance_mm',
                .005 * float(analysis['specimen_geometry']['gauge_length_mm'])))
        from agents.analysis_mechanisms import freeze_mechanism_references
        freeze_mechanism_references(evidence, store.root / 'inputs')
        owned = self.resume(state.run_id, virtual=evidence['virtual_decisions'])
        stored = store.submit(evidence)
        job = {key: stored[key] for key in ('job_id', 'status')}
        if not owned:
            job['owner'] = 'other_process'
        return {**job, 'store_path': str(store.path), 'model_version': pin['model']['version'],
                'run_id': state.run_id, 'loop_key': pin['loop_key'], 'specimen_id': identity['specimen_id']}

    def request_cancel(self, run_id, job_id):
        store = self._stores.get(run_id)
        if store is None:
            raise ValueError('Unknown active Analysis run')
        requested = store.request_cancel(job_id)
        event = self._cancel_events.get((run_id, job_id))
        if requested and event is not None:
            event.set()
        return requested

    def status(self):
        return {run: [{'job_id': j['job_id'], 'status': j['status'], 'result': {k: v for k, v in j['result'].items() if k != 'receipts'}}
                      for j in store.jobs()] for run, store in self._stores.items()}

    async def shutdown(self):
        await asyncio.gather(*(worker.shutdown() for worker in self._workers.values()))
        for handle in self._locks.values():
            handle.close()
        self._locks.clear()
