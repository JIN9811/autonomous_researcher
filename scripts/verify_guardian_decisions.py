"""Opt-in registered-model Guardian probes with virtual read-only tools only."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Explicit snapshot returned by the registered API on 2026-09-11; no prefix matching.
PROVIDER_MODEL_ALIASES = {'gpt-5.5': {'gpt-5.5-2026-04-23'}}


class RecordingBackend:
    """Keep visible decision output, not provider raw data or hidden thinking."""
    def __init__(self, backend):
        self.backend = backend
        self.responses = []

    async def complete(self, **kwargs):
        response = await self.backend.complete(**kwargs)
        raw = response.raw if isinstance(response.raw, dict) else {}
        self.responses.append({'model': response.model, 'provider_model': raw.get('model'),
                               'text': response.text})
        return response


def make_state(case: str, run_id: str):
    from orchestrator.state import Mode, OrchestratorState, Stage
    state = OrchestratorState(run_id=run_id, experiment_id='guardian-software-probe',
        mode=Mode.TEST, stage=Stage.GUARDIAN,
        active_goal='Review this synthetic software-only cycle. No physical execution is available.',
        current_experiment_spec={
            'candidate_id': 'fixture-candidate', 'specimen_id': 'fixture-specimen',
            'geometry_type': 'lattice_bcc', 'specimen_size_mm': [30., 30., 30.],
            'cell_size_mm': 6., 'wall_thickness_mm': 1.2, 'top_bottom_cap': True,
            'expected_mass_g': 8., 'expected_print_time_min': 60.,
            'execution_policy': {'manipulation': 'virtual', 'vision': 'virtual', 'lab_equipment': 'virtual'},
        }, latest_analysis={'ok': True, 'objective_score': .7,
            'objective_semantics': 'compiled_or_physical_observation',
            'uncertainty_status': {'status': 'not_estimated'}},
        latest_observations={'anomaly': False})
    if case == 'conflict':
        state.latest_observations.update({'anomaly': True, 'detail': 'Synthetic observation conflicts with completion report.'})
    elif case == 'hard_stop':
        state.safe_stop_requested = True
    elif case == 'lookup':
        state.latest_observations['review_note'] = (
            'Queue readiness is not included in this snapshot. Inspect shared runtime queue status before deciding whether to continue; it is not specimen completion proof.')
    return state


def virtual_tools(state):
    from mcp_tools.tool_registry import ToolRegistry
    tools = ToolRegistry()
    calls = []

    def health(payload):
        calls.append('device.health')
        return {'ok': True, 'printer': 'ready', 'camera': 'ready', 'robot': 'ready',
                'utm': 'ready', 'simulator': 'active', 'evidence_class': 'synthetic_software_verification'}

    def queue(payload):
        if payload.get('run_id', state.run_id) != state.run_id:
            raise ValueError('Foreign run requested')
        calls.append('experiment.queue.status')
        # Match the actual experiment.queue.status contract. It is shared
        # readiness, not a run-bound fabrication/completion certificate.
        return tools.queue_status()

    tools.register('device.health', health)
    tools.register('experiment.queue.status', queue)
    return tools, calls


def backend_matches(calls, backend, model):
    return bool(calls) and all(row.get('backend') == backend and row.get('model') == model for row in calls)


def responses_match(responses, model):
    accepted = {model} | PROVIDER_MODEL_ALIASES.get(model, set())
    return bool(responses) and all(row.get('model') == model and row.get('provider_model') in accepted
                                   for row in responses)


def expectation(case, guardian, tool_calls):
    decision = guardian.get('llm_decision', {})
    if case == 'hard_stop':
        return guardian.get('action') == 'safe_stop' and not decision.get('llm_used', False)
    if not decision.get('llm_used'):
        return False
    if case == 'conflict':
        return (guardian.get('action') in {'recover', 'safe_stop'}
                and decision.get('status') == 'accepted'
                and decision.get('action') in {'review', 'safe_stop'})
    return (guardian.get('action') == 'continue'
            and decision.get('status') == 'accepted'
            and (case != 'lookup' or 'experiment.queue.status' in tool_calls))


async def runtime_handoff(state, ctx, output):
    """Execute the real Guardian node and unchanged runtime routing, not other agents."""
    from agents.guardian_agent import GuardianAgent
    from agents.registry import AgentRegistry
    from logging_system.structured_logger import StructuredLogger
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    registry = AgentRegistry()
    registry.register(GuardianAgent())
    events = []
    runtime = LangGraphRunLoop(state=state, agent_registry=registry,
        orchestrator_agent_name='orchestrator_agent', ctx=ctx,
        logger=StructuredLogger(output / 'events.jsonl', output / 'summary.log'),
        graph_config_path=ROOT / 'graphs/configs/atr_closed_loop.yaml',
        module_root=ROOT / 'graphs', interval_seconds=0, on_event=events.append)
    await runtime.step()
    return {'stage': state.stage.value, 'loop_count': state.loop_count,
            'paused': state.is_paused, 'guardian': state.run_metadata.get('guardian', {}),
            'event_types': [row.get('event_type') for row in events]}


async def verify(args):
    from dotenv import load_dotenv
    from agents.base_agent import AgentContext
    from agents.guardian_agent import GuardianAgent
    from app.bootstrap import _build_backend, _load_configs, _models_cfg_for_backend
    from backends.model_router import ModelRouter
    from knowledge.failure_memory import FailureMemory
    load_dotenv(ROOT / '.env', override=False)
    cfg = _load_configs()
    parent = ROOT / 'artifacts/validation'
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='guardian-evidence-decision-', dir=parent))
    report = {'schema': 'guardian_verification.v1', 'physical_actuation': False,
              'service_startup': False, 'evidence_class': 'synthetic_software_verification',
              'scope': 'GuardianAgent and existing Guardian-to-next-cycle routing; not all-agent physical validation',
              'cases': []}

    def save():
        (folder / 'results.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')

    for backend in args.backend or ['openai', 'vllm']:
        provider = _build_backend(backend, system_cfg=cfg['system']['system'], cfg=cfg)
        if backend == 'openai':
            credential_file = ROOT / 'memory/api_keys.json'
            credentials = json.loads(credential_file.read_text()) if credential_file.exists() else {}
            if not credentials.get('enabled') or not credentials.get('api_key'):
                report['cases'].append({'backend': backend, 'status': 'unavailable', 'reason': 'Saved API disabled', 'expectation_met': False})
                save()
                continue
            provider._api_key = credentials['api_key']
        router_cfg = deepcopy(_models_cfg_for_backend(cfg['models'], backend))
        selection = ModelRouter(router_cfg).select('guardian_reasoning')
        model = args.local_model if backend == 'vllm' else selection.primary
        registered = {value for spec in router_cfg.get('models', {}).values()
                      for key, value in spec.items() if key in {'primary', 'fallback'}}
        if model not in registered:
            raise ValueError('Probe model must be registered in ATR')
        # Pin only this isolated context; no fallback can impersonate a backend result.
        router_cfg['models'][selection.role] = {'primary': model}
        router = ModelRouter(router_cfg)
        for case in args.case or ['normal', 'lookup', 'conflict', 'hard_stop', 'runtime_continue']:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            state = make_state(case, f'guardian-{backend}-{case}-{stamp}')
            state.run_metadata['guardian_settings'] = {'call_timeout_s': args.timeout_s,
                'total_timeout_s': max(300., args.timeout_s)}
            tools, tool_calls = virtual_tools(state)
            model_calls = []
            recorded_provider = RecordingBackend(provider)

            async def on_model_call(**kwargs):
                model_calls.append({key: kwargs.get(key) for key in ('backend', 'model', 'task_type', 'role')})

            ctx = AgentContext(model_router=router, primary_backend=recorded_provider, fallback_backend=recorded_provider,
                rag=None, experiment_db=None, failure_memory=FailureMemory(), tools=tools,
                active_backend=backend, force_real_llm_in_test=True, allow_mock_fallback=False,
                model_routers={backend: router}, primary_backends={backend: recorded_provider},
                fallback_backends={backend: recorded_provider}, backend_fallbacks={backend: backend},
                artifact_run_root=str(folder / 'runs'), on_model_call=on_model_call)
            started = time.monotonic()
            print(json.dumps({'started': case, 'backend': backend, 'model': model}), flush=True)
            row = {'case': case, 'backend': backend, 'requested_model': model, 'run_id': state.run_id}
            try:
                if case == 'runtime_continue':
                    route = await runtime_handoff(state, ctx, folder)
                    guardian = route['guardian']
                    row['routing'] = {k: v for k, v in route.items() if k != 'guardian'}
                    ok = (route['stage'] == 'design' and route['loop_count'] == 1 and not route['paused']
                          and expectation('normal', guardian, tool_calls))
                else:
                    result = await GuardianAgent().run(state, ctx)
                    guardian = result.data['guardian']
                    ok = expectation(case, guardian, tool_calls)
                row['guardian'] = guardian
                row['expectation_met'] = ok and (case == 'hard_stop' or (
                    backend_matches(model_calls, backend, model)
                    and responses_match(recorded_provider.responses, model)))
            except Exception as exc:
                row.update({'error_type': type(exc).__name__, 'expectation_met': False})
            row.update({'duration_s': round(time.monotonic() - started, 3),
                        'model_calls': model_calls, 'model_responses': recorded_provider.responses,
                        'tool_calls': tool_calls})
            report['cases'].append(row)
            save()
            print(json.dumps({key: row[key] for key in ('case', 'backend', 'duration_s', 'expectation_met')}), flush=True)
    save()
    print(json.dumps({'report': str(folder / 'results.json')}), flush=True)
    return bool(report['cases']) and all(row.get('expectation_met') for row in report['cases'])


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--backend', action='append', choices=['openai', 'vllm'])
    parser.add_argument('--case', action='append', choices=['normal', 'lookup', 'conflict', 'hard_stop', 'runtime_continue'])
    parser.add_argument('--local-model', default='gemma4:31b')
    parser.add_argument('--timeout-s', type=float, default=120.)
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error('Use --execute for registered model calls; no devices or model startup.')
    if not 0 < args.timeout_s <= 300:
        parser.error('--timeout-s must be finite and within (0, 300].')
    return args


if __name__ == '__main__':
    raise SystemExit(0 if asyncio.run(verify(parse_args())) else 1)
