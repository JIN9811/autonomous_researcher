#!/usr/bin/env python3
"""Run one isolated, real Analysis FEM study against the retained same-STL CSV.

No application/controller bootstrap, hardware tools, model lifecycle management,
global config writes or material promotion. Calibration requires an explicit
bounded study configuration; the ordinary baseline path is unchanged. Computation has
no wall deadline. Existing configured LLM HTTP timeouts remain transport limits.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_ARCHIVE = ROOT / 'artifacts/analysis_validation/20260909-specimen-1/request.json'


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def public(value):
    if isinstance(value, dict):
        return {str(key): public(item) for key, item in value.items() if not str(key).startswith('_')}
    if isinstance(value, (tuple, list)):
        return [public(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path, value):
    with Path(path).open('w', encoding='utf-8') as stream:
        json.dump(public(value), stream, ensure_ascii=True, allow_nan=False, indent=2)


class Journal:
    def __init__(self, output):
        self.path = output / 'progress.jsonl'
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.native_pids = set()

    def emit(self, event):
        record = {'at': datetime.now(timezone.utc).isoformat(),
                  'elapsed_s': time.monotonic() - self.started, **public(event)}
        with self.lock, self.path.open('a', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=True, allow_nan=False)
            stream.write('\n')
            pid = event.get('pid')
            if pid and event.get('status') == 'running' and pid not in self.native_pids:
                self.native_pids.add(pid)
                print(json.dumps({'kind': 'START_NATIVE', 'pid': pid, 'phase': event.get('phase'),
                                  'at': record['at'], 'runner_pid': os.getpid(),
                                  'run_elapsed_s': time.monotonic() - self.started}), flush=True)
        if event.get('kind') in {'decision', 'tool_started', 'tool_finished', 'finished', 'signal'}:
            print(json.dumps({key: value for key, value in record.items()
                              if key in {'kind', 'at', 'elapsed_s', 'phase', 'tool', 'status', 'option_id', 'reason'}}), flush=True)


class ProcessTreeSampler:
    """One-second process-tree observations, retaining CPU totals for exited PIDs."""
    def __init__(self, output):
        import psutil
        self.psutil = psutil
        self.root = psutil.Process()
        self.path = output / 'resources.jsonl'
        self.stop = threading.Event()
        self.started = time.monotonic()
        self.cpu_by_identity = {}
        self.peak_rss = 0
        self.sample_count = 0
        self.thread = threading.Thread(target=self._run, name='fem-validation-resources', daemon=True)

    def _sample(self):
        processes = [self.root]
        try:
            processes += self.root.children(recursive=True)
        except self.psutil.Error:
            pass
        rows = []
        for process in processes:
            try:
                with process.oneshot():
                    cpu = process.cpu_times()
                    identity = (process.pid, process.create_time())
                    seconds = cpu.user + cpu.system
                    self.cpu_by_identity[identity] = max(seconds, self.cpu_by_identity.get(identity, 0))
                    rows.append({'pid': process.pid, 'name': process.name(), 'cpu_time_s': seconds,
                                 'rss_bytes': process.memory_info().rss, 'threads': process.num_threads()})
            except self.psutil.Error:
                continue
        rss = sum(row['rss_bytes'] for row in rows)
        self.peak_rss = max(self.peak_rss, rss)
        self.sample_count += 1
        row = {'elapsed_s': time.monotonic() - self.started, 'tree_rss_bytes': rss,
               'peak_tree_rss_bytes': self.peak_rss,
               'observed_cumulative_cpu_time_s': sum(self.cpu_by_identity.values()), 'processes': rows}
        with self.path.open('a', encoding='utf-8') as stream:
            json.dump(row, stream)
            stream.write('\n')

    def _run(self):
        while not self.stop.is_set():
            self._sample()
            self.stop.wait(1.0)
        self._sample()

    def finish(self):
        self.stop.set()
        self.thread.join()
        return {'elapsed_s': time.monotonic() - self.started, 'sample_interval_s': 1.0,
                'sample_count': self.sample_count, 'peak_tree_rss_bytes': self.peak_rss,
                'observed_cumulative_cpu_time_s': sum(self.cpu_by_identity.values()),
                'observed_process_count': len(self.cpu_by_identity),
                'scope': 'runner and recursively discovered children; excludes external LLM servers',
                'limitation': 'Sampled CPU is a lower bound; short-lived children may escape 1-second sampling. Summed RSS may double-count shared pages.'}


def prepare_evidence(archive_request, output, *, max_fem_jobs, max_mesh_actions, mesh_size_mm=.6,
                     surface_distance_mm=.05):
    from agents.analysis_agent import AnalysisAgent

    mesh_size_mm = float(mesh_size_mm)
    if not math.isfinite(mesh_size_mm) or not .05 <= mesh_size_mm <= 5:
        raise ValueError('Mesh size must be finite and between 0.05 and 5 mm')
    surface_distance_mm = float(surface_distance_mm)
    if not math.isfinite(surface_distance_mm) or not 0 < surface_distance_mm <= .05:
        raise ValueError('Surface operation distance must be positive and at most 0.05 mm')
    archive_request = Path(archive_request).resolve()
    archive = json.loads(archive_request.read_text())
    source_analysis = Path(archive['source_analysis_result']).resolve()
    analysis = json.loads(source_analysis.read_text())['data']['analysis']
    original = deepcopy(archive['request'])
    stl = Path(original['stl_path']).resolve()
    csv = Path(analysis['source']['path']).resolve()
    hashes = {str(path): sha256(path) for path in (archive_request, source_analysis, stl, csv)}
    if archive.get('stl_sha256') and archive['stl_sha256'] != hashes[str(stl)]:
        raise ValueError('Archived STL hash does not match current source')
    expected_csv = analysis['source'].get('sha256') or (analysis['source'].get('fingerprint') or {}).get('sha256')
    if expected_csv and expected_csv != hashes[str(csv)]:
        raise ValueError('Archived CSV hash does not match current source')
    inputs = output / 'inputs'
    inputs.mkdir(exist_ok=False)
    frozen_hashes = {}
    copied = {}
    for label, source in (('specimen', stl), ('measurement', csv), ('archive_request', archive_request), ('source_analysis', source_analysis)):
        destination = inputs / f'{label}{source.suffix}'
        shutil.copyfile(source, destination)
        digest = sha256(destination)
        if digest != hashes[str(source)]:
            raise ValueError('Source changed while creating frozen input copy')
        frozen_hashes[str(destination.resolve())] = digest
        copied[label] = str(destination.resolve())
    curve, source_receipt = AnalysisAgent()._read_curve_file(copied['measurement'])
    if not source_receipt.get('ok') or len(curve) < 2:
        raise ValueError('Existing Analysis parser did not produce a measured curve')
    run_id = output.name
    geometry = deepcopy(analysis['specimen_geometry'])
    payload = {**original, 'run_id': run_id, 'loop_key': f'{run_id}:loop-1',
               'job_id': f'{run_id}-fem', 'runtime_mode': 'live', 'mode': 'live',
               'runtime_solver_enabled': True, 'require_solver': True,
               'stl_path': copied['specimen'], 'mesh_size_mm': mesh_size_mm,
               'material': {'elastic_modulus_mpa': 1800, 'poisson_ratio': .35, 'yield_strength_mpa': 35},
               'boundary_tolerance_mm': .005 * float(geometry['gauge_length_mm']),
               'surface_remesh': {'method': 'isotropic', 'edge_length_mm': mesh_size_mm,
                                  'iterations': 8, 'max_surface_distance_mm': surface_distance_mm},
               'computation_limits': {'timeout_s': None, 'threads': 4, 'equation_solver_threads': 1,
                                      'max_mesh_elements': 500000}}
    payload.pop('reference_calibration', None)
    evidence = {'schema': 'analysis_improvement_evidence.v1', 'job_kind': 'fem',
                'run_id': run_id, 'job_id': payload['job_id'], 'loop_key': payload['loop_key'],
                'specimen_id': original['specimen_id'], 'source_kind': 'measured',
                'raw_sha256': hashes[str(csv)], 'acquisition_id': 'sha256:' + hashes[str(csv)],
                'paired_identity_verified': True, 'virtual_decisions': False,
                'input_hashes': frozen_hashes, 'payload': payload, 'experiment_curve': curve,
                'specimen_geometry': geometry,
                'coordinate_convention': {'name': 'contact_threshold', 'relative_force_threshold': .01,
                                          'absolute_force_threshold_N': 2.0},
                'policy': {'max_fem_jobs': max_fem_jobs, 'max_mesh_actions': max_mesh_actions,
                           'mesh_size_factors': [1, .75, .5], 'convergence_tolerance_pct': 5}}
    metadata = {'schema': 'analysis_fem_validation_run.v1', 'source_hashes_before': hashes,
                'frozen_input_hashes': frozen_hashes, 'source_analysis_result': str(source_analysis),
                'source_parser': source_receipt, 'physical_devices_used': False,
                'calibration_applied': False, 'material_promoted': False,
                'baseline': 'retained isotropic-remesh yield-35 reference, not a validated material model',
                'native_timeout_s': None, 'worker_timeout_s': None, 'mesh_size_mm': mesh_size_mm,
                'maximum_fem_jobs': max_fem_jobs, 'maximum_mesh_actions': max_mesh_actions}
    return evidence, metadata


def configure_material_hypothesis(evidence, metadata, configuration):
    """Run a declared forward hypothesis, never a fitted/promoted material."""
    from utils.calculix_quasistatic import validate_plastic_curve
    allowed = {'label', 'basis', 'material'}
    if not isinstance(configuration, dict) or set(configuration) != allowed:
        raise ValueError('Material hypothesis requires only label, basis and material')
    if not all(isinstance(configuration[key], str) and configuration[key].strip()
               for key in ('label', 'basis')):
        raise ValueError('Material hypothesis label and basis are required')
    material = deepcopy(configuration['material'])
    keys = {'elastic_modulus_mpa', 'poisson_ratio', 'yield_strength_mpa', 'plastic_curve'}
    if not isinstance(material, dict) or set(material) - keys:
        raise ValueError('Unsupported material hypothesis fields')
    try:
        if any(isinstance(material.get(key), bool) for key in keys - {'plastic_curve'}):
            raise ValueError('Boolean material constants are invalid')
        modulus = float(material['elastic_modulus_mpa'])
        poisson = float(material['poisson_ratio'])
        if not (math.isfinite(modulus) and modulus >= 1e-9 and math.isfinite(poisson) and -.99 <= poisson <= .499):
            raise ValueError('Invalid elastic constants')
        if ('plastic_curve' in material) == ('yield_strength_mpa' in material):
            raise ValueError('Provide exactly one plastic law')
        if 'plastic_curve' in material:
            material['plastic_curve'] = validate_plastic_curve(material['plastic_curve'])
            if not material['plastic_curve']:
                raise ValueError('An explicit plastic curve cannot be empty')
        else:
            value = float(material['yield_strength_mpa'])
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid yield strength')
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError('Invalid material hypothesis') from exc
    evidence['payload']['material'] = material
    for key in ('elastic_modulus_mpa', 'poisson_ratio', 'yield_strength_mpa'):
        evidence['payload'].pop(key, None)
    evidence['material_hypothesis'] = deepcopy(configuration)
    metadata.update(material_hypothesis=deepcopy(configuration),
                    independent_validation='not_performed', material_promoted=False,
                    calibration_applied=False)


def configure_calibration(evidence, metadata, configuration):
    """Opt in to calibration without changing the measured or physical inputs."""
    from agents.analysis_calibration import _search_policy
    configuration = deepcopy(configuration)
    mechanism = configuration.pop('mechanism_evidence', None)
    candidate = {**evidence, 'policy': {**evidence['policy'], 'calibration': configuration}}
    if mechanism is not None:
        candidate['policy']['mechanism_evidence'] = mechanism
    _search_policy(candidate)
    evidence['policy'] = candidate['policy']
    metadata.update(calibration_applied=False, calibration_requested=True,
                    calibration_method='feature_informed_inverse_FE',
                    calibration_policy=deepcopy(configuration),
                    independent_validation='not_performed', material_promoted=False)


def build_context(config_dir, output, journal):
    """Construct only CAE and current configured inference; never bootstrap the app."""
    from agents.base_agent import AgentContext
    from backends.llm_lease import LLMLeaseCoordinator
    from backends.model_router import ModelRouter
    from backends.nemoclaw_vllm_runtime import NemoClawVLLMRuntime
    from backends.openai_client import OpenAIBackend
    from backends.vllm_client import VLLMBackend
    from dotenv import load_dotenv
    from knowledge.experiment_db import ExperimentDB
    from knowledge.failure_memory import FailureMemory
    from knowledge.rag import HybridRAG, LocalRAGIndex, WebRetriever
    from mcp_tools.cae_tools import register_cae_tools
    from mcp_tools.tool_registry import ToolRegistry
    from utils.config_loader import load_all_configs

    load_dotenv(ROOT / '.env', override=False)
    # Live GUI's registered API credential is persisted here; never print it.
    key_settings_path = ROOT / 'memory' / 'api_keys.json'
    key_settings = json.loads(key_settings_path.read_text()) if key_settings_path.is_file() else {}
    saved_key = key_settings.get('api_key', '') if key_settings.get('enabled') else ''
    config = load_all_configs(Path(config_dir))
    systems = config['system']
    system = systems.get('system', systems)
    models = config['models']
    active = os.getenv('AUTONOMOUS_BACKEND', str(system.get('inference_backend', 'vllm'))).lower()
    active = {'api': 'openai', 'cloud': 'openai', 'openai-api': 'openai'}.get(active, active)
    fallback = str(models.get('backend', {}).get('fallback') or 'openai')
    if {active, fallback} - {'vllm', 'openai'}:
        raise ValueError('This no-model-lifecycle CLI supports configured vllm/OpenAI endpoints only; no backend was changed')
    vllm = systems.get('vllm', {})
    cloud = systems.get('openai', {})
    backends = {
        'vllm': VLLMBackend(base_url=os.getenv('VLLM_BASE_URL', vllm.get('base_url', 'http://127.0.0.1:8001/v1')),
            timeout_s=float(os.getenv('VLLM_TIMEOUT_S', vllm.get('timeout_seconds', 300))),
            api_key=os.getenv('VLLM_API_KEY', vllm.get('api_key', 'EMPTY')),
            model_base_urls=dict(vllm.get('model_base_urls', {})),
            nemoclaw_runtime=NemoClawVLLMRuntime.from_config(vllm.get('nemoclaw_k8s', {}))),
        'openai': OpenAIBackend(base_url=os.getenv('OPENAI_BASE_URL', cloud.get('base_url', 'https://api.openai.com/v1')),
            timeout_s=float(os.getenv('OPENAI_TIMEOUT_S', cloud.get('timeout_seconds', 300))),
            api_key=os.getenv('OPENAI_API_KEY') or saved_key or cloud.get('api_key', ''),
            organization=os.getenv('OPENAI_ORG_ID', cloud.get('organization', '')),
            project=os.getenv('OPENAI_PROJECT_ID', cloud.get('project', '')),
            reasoning_effort=os.getenv('OPENAI_REASONING_EFFORT', cloud.get('reasoning_effort', ''))),
    }
    routers = {}
    for name in backends:
        branch = deepcopy(models)
        branch['models'] = deepcopy(models.get('backend_models', {}).get(name, models.get('models', {})))
        for role in ('orchestrator', 'e4b'):
            override = os.getenv(f'AUTONOMOUS_{name.upper()}_{role.upper()}_MODEL') or os.getenv(f'AUTONOMOUS_{role.upper()}_MODEL')
            if override:
                branch['models'].setdefault(role, {})['primary'] = override
        routers[name] = ModelRouter(branch)
    tools = ToolRegistry()
    devices = deepcopy(config['devices'])
    cae = devices.setdefault('devices', {}).setdefault('cae', {})
    cae['artifact_dir'] = str(output / 'cae')
    cae['reference_utm_globs'] = []
    register_cae_tools(tools, devices, repo_root=ROOT)
    ctx = AgentContext(model_router=routers[active], primary_backend=backends[active],
        fallback_backend=backends[fallback], tools=tools,
        rag=HybridRAG(LocalRAGIndex([]), WebRetriever(None, None)), experiment_db=ExperimentDB(),
        failure_memory=FailureMemory(), active_backend=active, force_real_llm_in_test=True,
        allow_mock_fallback=False, model_routers=routers, primary_backends=backends,
        fallback_backends={active: backends[fallback]}, backend_fallbacks={active: fallback},
        llm_lease=LLMLeaseCoordinator(), artifact_run_root=str(output.parent),
        on_model_call=lambda **details: journal.emit({'kind': 'model_call', **details}))
    profile = {'active_backend': active, 'configured_backend_fallback': fallback,
               'analysis_primary_model': routers[active].select('analysis_reasoning').primary,
               'analysis_fallback_model': routers[fallback].select('analysis_reasoning').primary,
               'routing_policy': 'Existing AgentContext policy, including OpenAI fallback prioritization',
               'model_lifecycle_management': 'disabled in this isolated client; no load/scale/unload calls',
               'registered_tools': tools.list_tools(), 'llm_transport_timeouts': 'existing configured values'}
    return ctx, profile


def pin_validation_backend(ctx, backend, *, model=None):
    """Pin only this isolated client; never edit GUI/runtime model selection."""
    from dataclasses import replace
    from backends.model_router import ModelRouter
    if backend not in {'openai', 'vllm'} or backend not in ctx.primary_backends:
        raise ValueError('Select a registered validation backend')
    selection = ctx.model_routers[backend].select('analysis_reasoning')
    selected = model or selection.primary
    if selected not in {selection.primary, selection.fallback}:
        raise ValueError('Validation model must already be registered for Analysis')
    router = ModelRouter({'models': {selection.role: {'primary': selected}},
                          'task_routes': {'analysis_reasoning': selection.role}})
    service = ctx.primary_backends[backend]
    return replace(ctx, active_backend=backend, model_router=router, model_routers={backend: router},
                   primary_backend=service, primary_backends={backend: service},
                   fallback_backend=service, fallback_backends={backend: service}, backend_fallbacks={})


async def execute(args, output):
    from agents.analysis_decisions import decide
    from agents.analysis_fem import run_fem_study
    from agents.analysis_runtime import AnalysisRuntimeService

    journal = Journal(output)
    sampler = ProcessTreeSampler(output)
    sampler.thread.start()
    cancel = threading.Event()
    loop = asyncio.get_running_loop()
    def request_cancel(signum):
        cancel.set()
        journal.emit({'kind': 'signal', 'status': 'cancellation_requested', 'signal': signum})
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, request_cancel, int(signum))
    metadata, result = {}, {'status': 'failed'}
    tool_counter = 0
    try:
        evidence, metadata = prepare_evidence(args.archive_request, output,
            max_fem_jobs=args.max_fem_jobs, max_mesh_actions=args.max_mesh_actions,
            mesh_size_mm=getattr(args, 'mesh_size_mm', .6),
            surface_distance_mm=getattr(args, 'surface_distance_mm', .05))
        if getattr(args, 'material_hypothesis', None):
            configuration_path = args.material_hypothesis.resolve()
            source_hash = sha256(configuration_path)
            frozen = output / 'inputs' / 'material_hypothesis.json'
            shutil.copyfile(configuration_path, frozen)
            if sha256(frozen) != source_hash:
                raise ValueError('Material hypothesis changed while copying')
            configure_material_hypothesis(evidence, metadata, json.loads(frozen.read_text()))
            evidence['input_hashes'][str(frozen)] = source_hash
            metadata['source_hashes_before'][str(configuration_path)] = source_hash
        if getattr(args, 'calibration_config', None):
            configure_calibration(evidence, metadata, json.loads(args.calibration_config.read_text()))
        from agents.analysis_mechanisms import freeze_mechanism_references
        extra_hashes = freeze_mechanism_references(evidence, output / 'inputs')
        metadata['source_hashes_before'].update(extra_hashes)
        write_json(output / 'evidence.json', evidence)
        write_json(output / 'request.json', metadata)
        ctx, profile = build_context(args.config_dir, output, journal)
        if getattr(args, 'validation_backend', None):
            ctx = pin_validation_backend(ctx, args.validation_backend, model=args.validation_model)
            profile.update(active_backend=ctx.active_backend,
                           analysis_primary_model=ctx.model_router.select('analysis_reasoning').primary,
                           validation_backend_fallback_disabled=True)
        admission = AnalysisRuntimeService(ROOT / 'runs', ctx)
        write_json(output / 'backend_profile.json', profile)

        async def choose(phase, info, options):
            if cancel.is_set():
                raise asyncio.CancelledError()
            journal.emit({'kind': 'decision_requested', 'phase': phase, 'options': options, 'evidence': info})
            decision = await decide(ctx, phase, info, options, virtual=False, background=True, timeout_s=None)
            journal.emit({'kind': 'decision', **decision})
            return decision

        async def call_tool(name, payload):
            nonlocal tool_counter
            if name not in {'cae.prepare_static_analysis', 'cae.run_static_analysis'}:
                raise ValueError('Unregistered validation tool')
            tool_counter += 1
            stem = f'{tool_counter:03d}-{name.replace(".", "-")}'
            write_json(output / f'{stem}.request.json', payload)
            journal.emit({'kind': 'tool_started', 'tool': name})
            def invoke():
                return ctx.tools.call(name, {**payload, '_cancel_event': cancel,
                                            '_progress_callback': journal.emit})
            response = await admission.compute(invoke, background=True, cancel_event=cancel)
            write_json(output / f'{stem}.result.json', response)
            journal.emit({'kind': 'tool_finished', 'tool': name, 'status': response.get('status'),
                          'receipt_path': str(output / f'{stem}.result.json')})
            return response

        result = await run_fem_study(evidence, choose, call_tool, journal.emit)
        if result.get('status') == 'completed' and (result.get('calibration') or {}).get('retention_status') == 'retained_for_research':
            from agents.analysis_calibration import freeze_candidate
            write_json(output / 'frozen_material_candidate.json', freeze_candidate(result, evidence))
    except asyncio.CancelledError:
        cancel.set()
        result = {'status': 'cancelled', 'reason': 'operator_requested_cancel',
                  'receipts': 'See progress.jsonl and numbered tool-result files for retained partial evidence'}
    except Exception as exc:
        result = {'status': 'failed', 'error_type': type(exc).__name__, 'error': str(exc)}
        journal.emit({'kind': 'error', **result})
    finally:
        resources = sampler.finish()
        after = {}
        for filename in metadata.get('source_hashes_before', {}):
            try:
                after[filename] = sha256(filename)
            except OSError:
                after[filename] = None
        metadata.update(source_hashes_after=after,
                        source_files_unchanged=bool(after) and after == metadata.get('source_hashes_before'),
                        resources=resources)
        write_json(output / 'resources_summary.json', resources)
        write_json(output / 'run_metadata.json', metadata)
        write_json(output / 'result.json', result)
        journal.emit({'kind': 'finished', 'status': result.get('status'), 'output_dir': str(output)})
    return 0 if result.get('status') in {'completed', 'partial'} else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Explicitly authorize real LLM and native computation; never starts hardware')
    parser.add_argument('--archive-request', type=Path, default=DEFAULT_ARCHIVE, help='Retained same-STL acquisition reference')
    parser.add_argument('--config-dir', type=Path, default=ROOT / 'configs', help='Read-only ATR config directory')
    parser.add_argument('--output-dir', type=Path, help='New, non-existing isolated output directory (default artifacts/runs/validation-fem-...)')
    parser.add_argument('--max-fem-jobs', type=int, choices=range(1, 4), default=1, help='Finite solver-action bound, not a wall-clock cutoff')
    parser.add_argument('--max-mesh-actions', type=int, choices=range(1, 4), default=3)
    parser.add_argument('--mesh-size-mm', type=float, default=.6,
                        help='Isolated volume/surface mesh size; source geometry checks remain unchanged')
    parser.add_argument('--surface-distance-mm', type=float, default=.05,
                        help='Remesh operation deviation bound (only tightening below 0.05 mm allowed)')
    parser.add_argument('--material-hypothesis', type=Path,
                        help='Explicit research-only forward material JSON (label, basis, material)')
    parser.add_argument('--calibration-config', type=Path,
                        help='Explicit initial parameters, bounds and max_evaluations JSON for a calibration-only study')
    parser.add_argument('--validation-backend', choices=('openai', 'vllm'),
                        help='Pin the isolated validation client; disables cross-backend fallback')
    parser.add_argument('--validation-model', help='Optional model already registered for the selected Analysis backend')
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error('--execute is required; use --help for safe inspection without any computation')
    if args.validation_model and not args.validation_backend:
        parser.error('--validation-model requires --validation-backend')
    if args.material_hypothesis and args.calibration_config:
        parser.error('--material-hypothesis and --calibration-config are mutually exclusive')
    output = (args.output_dir or ROOT / 'artifacts/runs' /
              f'validation-fem-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}-{uuid4().hex[:8]}').resolve()
    output.mkdir(parents=True, exist_ok=False)
    print(json.dumps({'output_dir': str(output), 'physical_devices_used': False, 'native_timeout_s': None}), flush=True)
    return asyncio.run(execute(args, output))


if __name__ == '__main__':
    raise SystemExit(main())
