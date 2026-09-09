"""Two production software loops while Analysis native-compute ownership is busy.

Only acquisition/fabrication are fixtures; Design, Analysis, Knowledge, BO,
Guardian and the LangGraph state/transition implementation are production code.
No controller bootstrap, device registry, real model, or native executable exists.
All project-relative configuration, memory and artifacts resolve beneath tmp_path.

Optional ATR_PARALLEL_NATIVE_PID records an independently launched real solver's
identity/CPU ticks before and after the software loops, proving wall-time overlap.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import pytest
import yaml

from agents.analysis_agent import AnalysisAgent
from agents.analysis_runtime import service_for
from agents.base_agent import AgentContext, AgentResult, BaseAgent
from agents.bo_agent import BOAgent
from agents.design_agent import DesignAgent
from agents.guardian_agent import GuardianAgent
from agents.knowledge_agent import KnowledgeAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.registry import AgentRegistry
from backends.mock_llm import MockLLMBackend
from backends.model_router import ModelRouter
from knowledge.experiment_db import ExperimentDB
from knowledge.failure_memory import FailureMemory
from logging_system.structured_logger import StructuredLogger
from mcp_tools.experiment_tools import register_experiment_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.langgraph_runtime import LangGraphRunLoop
from orchestrator.state import Mode, OrchestratorState, Stage
from utils import paths


class _OfflineRAG:
    async def retrieve(self, **kwargs):
        return {'coverage': 1.0, 'local_chunks': [], 'web_results': []}


class _CSVAcquisitionBoundary(BaseAgent):
    """Replace physical fabrication/acquisition, never analytical agents."""
    name = 'equipment_agent'

    async def run(self, state, ctx):
        folder = Path(ctx.artifact_run_root) / state.run_id / 'fixture_inputs'
        folder.mkdir(parents=True, exist_ok=True)
        specimen_id = state.current_experiment_spec['specimen_id']
        stl = folder / f'loop-{state.loop_count}.stl'
        stl.write_text('solid fixture_not_for_native_execution\nendsolid\n')
        csv = folder / f'loop-{state.loop_count}.csv'
        csv.write_text('time_s,displacement_mm,force_N\n' + ''.join(
            f'{x},{x},{(100 + 10 * state.loop_count) * x}\n' for x in range(21)))
        state.run_metadata['specimen_result'] = {
            'ok': True, 'specimen_id': specimen_id, 'stl_path': str(stl),
        }
        # This is a file fixture, not a claim of completed physical equipment
        # workflow; never arm the physical UTM disposal/clearance state machine.
        result = {'ok': True, 'status': 'offline_csv_ready', 'result_file': str(csv),
                  'raw_data_export': {'validated': True, 'run_id': state.run_id,
                      'loop_id': state.loop_count, 'specimen_id': specimen_id,
                      'artifact_id': f'fixture-acquisition-{state.loop_count}', 'path': str(csv),
                      'sha256': hashlib.sha256(csv.read_bytes()).hexdigest()}}
        return AgentResult(success=True, summary='Non-actuating CSV acquisition fixture',
                           data={'equipment_result': result,
                                 'protocol_note': 'Offline CSV fixture; no equipment command issued.'})


def _native_snapshot():
    raw = os.environ.get('ATR_PARALLEL_NATIVE_PID')
    if not raw:
        return None
    pid = int(raw)
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    assert stat[0] not in {'Z', 'X', 'x'}, 'External native solver already terminated'
    return {'pid': pid, 'start_ticks': int(stat[19]), 'state': stat[0],
            'cpu_ticks': int(stat[11]) + int(stat[12]),
            'utc': datetime.now(timezone.utc).isoformat()}


@pytest.mark.asyncio
async def test_two_measured_loops_reach_next_design_while_native_compute_is_busy(tmp_path, monkeypatch):
    # Regression: awaiting optional native work in measured Analysis would block
    # loop 1 before BO; losing the measured handoff would reject its observation.
    source_root = Path(__file__).resolve().parents[2]
    shutil.copytree(source_root / 'graphs', tmp_path / 'graphs')
    shutil.copytree(source_root / 'configs', tmp_path / 'configs')
    monkeypatch.setattr(paths, 'project_root', lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(GuardianAgent, 'TEST_LOOP_CYCLE_LIMIT', 2)

    def forbidden(*args, **kwargs):
        raise AssertionError('Offline closed-loop test attempted external execution')

    # Hard tripwires protect against accidental future network/native additions.
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    graph_path = tmp_path / 'graphs/configs/atr_closed_loop.yaml'
    document = yaml.safe_load(graph_path.read_text())
    graph = document['graph']
    graph['transitions']['design'] = 'equipment'
    # The fixture has no physical specimen to clear; omit only the physical
    # post-acquisition clearance routes, retaining the production Analysis tail.
    graph['edges'] = [edge for edge in graph['edges'] if not (
        edge['source'] == 'equipment' and edge.get('metadata', {}).get('runtime_edge') == 'logical_transition'
        and edge['target'] != 'analysis')]
    for edge in graph['edges']:
        metadata = edge.get('metadata', {})
        if edge['source'] == 'design' and metadata.get('runtime_edge') == 'logical_transition':
            edge['target'] = 'equipment'
            metadata['to_stage'] = 'equipment'
            edge['label'] = 'Offline acquisition boundary after production Design'
    graph_path.write_text(yaml.safe_dump(document, sort_keys=False))

    tools = ToolRegistry()
    register_experiment_tools(tools)
    # The study may queue, but no native bridge is registered in this process.
    tools.register('cae.prepare_static_analysis', lambda payload: {
        'ok': False, 'status': 'blocked', 'failure_code': 'OFFLINE_NATIVE_NOT_REGISTERED'})
    tools.register('cae.run_static_analysis', forbidden)
    backend = MockLLMBackend()
    context = AgentContext(model_router=ModelRouter(yaml.safe_load((tmp_path / 'configs/models.yaml').read_text())),
        primary_backend=backend, fallback_backend=backend, rag=_OfflineRAG(),
        experiment_db=ExperimentDB(), failure_memory=FailureMemory(), tools=tools,
        force_real_llm_in_test=False, allow_mock_fallback=False,
        artifact_run_root=str(tmp_path / 'runs'))
    registry = AgentRegistry()
    for agent in (OrchestratorAgent(), DesignAgent(), _CSVAcquisitionBoundary(),
                  AnalysisAgent(), KnowledgeAgent(), BOAgent(), GuardianAgent()):
        registry.register(agent)
    state = OrchestratorState(run_id='parallel-software-loop', experiment_id='offline-measured-loop',
        mode=Mode.TEST, stage=Stage.DESIGN, active_goal='maximize compression energy density',
        current_experiment_spec={'specimen_size_mm': [20, 20, 20], 'expected_mass_g': 6.0})
    run_dir = tmp_path / 'runs' / state.run_id
    run_dir.mkdir(parents=True)
    events = []
    runtime = LangGraphRunLoop(state=state, agent_registry=registry,
        orchestrator_agent_name='orchestrator_agent', ctx=context,
        logger=StructuredLogger(run_dir / 'events.jsonl', run_dir / 'summary.log'),
        graph_config_path=graph_path, module_root=tmp_path / 'graphs',
        interval_seconds=0, max_retry_per_stage=0, on_event=events.append)
    service = service_for(context)
    started = threading.Event()
    release = threading.Event()

    def busy_native_boundary():
        started.set()
        assert release.wait(60), 'Test did not release its offline compute barrier'

    occupied = asyncio.create_task(service.compute(busy_native_boundary))
    records = []
    native_before = _native_snapshot()
    started_utc = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.monotonic()
    try:
        while not started.is_set():
            await asyncio.sleep(.005)
        for _ in range(18):
            previous = state.stage
            await asyncio.wait_for(runtime.step(), 20)
            assert not state.is_paused, state.run_metadata.get('guardian')
            assert state.stage != Stage.ERROR, state.model_dump(mode='json')
            if previous == Stage.ANALYSIS:
                observed = state.latest_analysis['bo_observation']
                assert observed['ok_for_bo'] is True
                assert observed['fidelity'] == 'utm_high'
                assert state.latest_analysis['uncertainty'] is None
                assert state.latest_analysis['cae_result'] == {}
                assert Path(state.latest_analysis['source']['path']).is_relative_to(tmp_path)
                records.append({'kind': 'analysis', 'loop': state.loop_count,
                    'observation_id': observed['observation_id'], 'score': observed['objective_score']})
            elif previous == Stage.BO:
                bo = state.run_metadata['bo_agent']
                records.append({'kind': 'bo', 'loop': state.loop_count,
                    'result': deepcopy(bo),
                    'recommended_constraints': deepcopy(state.run_metadata['bo_recommended_constraints'])})
            elif previous == Stage.DESIGN:
                records.append({'kind': 'design', 'loop': state.loop_count,
                    'specimen_id': state.current_experiment_spec['specimen_id'],
                    'report': deepcopy(state.run_metadata.get('design_report', {}))})
            assert not occupied.done(), 'Foreground released its own test barrier'
            if state.stage == Stage.COMPLETE:
                break
        assert state.stage == Stage.COMPLETE and state.loop_count == 2
        analyses = [r for r in records if r['kind'] == 'analysis']
        designs = [r for r in records if r['kind'] == 'design']
        bos = [r for r in records if r['kind'] == 'bo']
        assert len(analyses) == len(designs) == 2
        assert len(bos) == 1  # Terminal loop does not request an unused next design.
        assert len({r['observation_id'] for r in analyses}) == 2
        assert designs[0]['specimen_id'] != designs[1]['specimen_id']
        assert designs[1]['report']['prior_context']['prior_count'] >= 1
        assert designs[1]['report']['prior_context']['best_prior']['uncertainty'] is None
        assert designs[1]['report']['prior_context']['bo_recommendation']
        for observation, bo in zip(analyses, bos):
            assert observation['observation_id'] in bo['result']['observation_integrity']['accepted_observation_ids']
        assert [r['kind'] for r in records] == ['design', 'analysis', 'bo', 'design', 'analysis']
        native_after = _native_snapshot()
        if native_before:
            assert (native_before['pid'], native_before['start_ticks']) == (native_after['pid'], native_after['start_ticks'])
            assert native_after['cpu_ticks'] > native_before['cpu_ticks']
        receipt = {'status': 'passed', 'started_utc': started_utc,
            'finished_utc': datetime.now(timezone.utc).isoformat(),
            'elapsed_s': time.monotonic() - started_monotonic,
            'native_before': native_before, 'native_after': native_after,
            'completed_loops': state.loop_count, 'records': records,
            'physical_execution': False, 'real_model_calls': False,
            'graph_path': str(graph_path), 'artifact_root': str(run_dir)}
        receipt_path = run_dir / 'parallel_closed_loop_receipt.json'
        receipt_path.write_text(json.dumps(receipt, indent=2, default=str))
        print(json.dumps({'parallel_closed_loop_receipt': str(receipt_path),
            **{k: receipt[k] for k in ('status', 'started_utc', 'finished_utc', 'elapsed_s',
                                      'native_before', 'native_after', 'completed_loops')}}))
    finally:
        release.set()
        await occupied
        await service.shutdown()
