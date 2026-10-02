"""Restart at an unexecuted EQP selection, preserving completed print/transfer.

An explicit, single-use recovery checkpoint, not an automatic experiment retry.
"""
import asyncio
from collections import deque
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from app.equipment_selection_recovery import selection_recovery_inputs
from app.printer_wait_recovery import digest
from app.run_recovery import run_directory
from orchestrator.state import OrchestratorState, Stage


def _controller(snapshot, root):
    state = OrchestratorState.model_validate(snapshot['state'])
    return SimpleNamespace(_state=state, _deps=SimpleNamespace(run_root=root),
        _active_safety_sources=lambda: state.run_metadata.get('active_safety_sources') or {})


def _evidence_files(run, loop_id):
    loop = run / f'runtime/loops/loop-{loop_id + 1:06d}'
    return {str(p.resolve()): digest(p) for owner in
        ('specimen_agent', 'vision_agent', 'manipulation_agent', 'equipment_agent', 'analysis_agent', 'bo_agent')
        for p in sorted((loop / owner).glob('attempt-*/result.json'))}


def save_checkpoint(snapshot, planning, root, run_id):
    controller = _controller(snapshot, root)
    state = controller._state
    if state.run_id != run_id or planning.get('planning_session_id') != run_id:
        raise ValueError('Checkpoint session identity mismatch')
    wait = state.run_metadata.get('guardian_recovery_wait') or {}
    if wait.get('status') != 'waiting' or wait.get('run_id') != run_id or wait.get('loop_id') != state.loop_count:
        raise ValueError('A paused Guardian recovery wait is required')
    record, specimen = selection_recovery_inputs(controller)
    run = run_directory(root, run_id)
    transcript = Path(planning['transcript_path']).resolve()
    if transcript != run / 'live_planning_transcript.jsonl':
        raise ValueError('Transcript must belong to saved run')
    evidence = _evidence_files(run, state.loop_count)
    if any('/analysis_agent/' in p or '/bo_agent/' in p for p in evidence):
        raise ValueError('Downstream execution already exists')
    payload = {'schema': 'equipment_selection_checkpoint.v1', 'run_id': run_id,
        'snapshot': snapshot, 'planning': planning, 'record': record, 'specimen': specimen,
        'evidence': evidence, 'transcript_path': str(transcript),
        'transcript_sha256': digest(transcript), 'one_cycle_only': True}
    directory = run / 'recovery'
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / 'equipment_selection.json'
    encoded = json.dumps(payload, ensure_ascii=False)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps({'payload_json': encoded,
            'sha256': hashlib.sha256(encoded.encode()).hexdigest()}, ensure_ascii=False))
    path.chmod(0o600)
    return {'checkpoint': str(path), 'sha256': digest(path), 'run_id': run_id,
        'source_execution_id': record['execution_id'], 'actuation_performed': False}


def load_checkpoint(root, run_id):
    run = run_directory(root, run_id)
    if (run / 'recovery/equipment_selection.claim').exists():
        raise ValueError('This selection recovery was already dispatched; inspect its execution')
    envelope = json.loads((run / 'recovery/equipment_selection.json').read_text())
    if hashlib.sha256(envelope['payload_json'].encode()).hexdigest() != envelope['sha256']:
        raise ValueError('Selection checkpoint integrity mismatch')
    saved = json.loads(envelope['payload_json'])
    if saved.get('schema') != 'equipment_selection_checkpoint.v1' or saved.get('run_id') != run_id:
        raise ValueError('Invalid selection checkpoint')
    controller = _controller(saved['snapshot'], root)
    record, specimen = selection_recovery_inputs(controller)
    if record != saved['record'] or specimen != saved['specimen']:
        raise ValueError('Selection or transfer evidence changed since checkpoint')
    if _evidence_files(run, controller._state.loop_count) != saved['evidence']:
        raise ValueError('Owner execution changed since checkpoint')
    transcript = Path(saved['transcript_path']).resolve()
    if transcript != run / 'live_planning_transcript.jsonl' or digest(transcript) != saved['transcript_sha256']:
        raise ValueError('Transcript changed since checkpoint')
    return saved


def restore_checkpoint(controller, run_id):
    from app.controller import PLANNING_TRANSCRIPT_MEMORY_LIMIT
    from orchestrator.experimental_setup import SetupStore
    from logging_system.logger_factory import build_logger_bundle
    if (controller.snapshot().get('is_running') or controller._planning_request_lock.locked()
            or controller._state.stage != Stage.IDLE):
        raise ValueError('Restore requires a fresh inactive server')
    if controller._active_safety_sources() or any(getattr(controller._state, k) for k in
            ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested')):
        raise ValueError('Safety recovery required before restore')
    saved = load_checkpoint(controller._deps.run_root, run_id)
    state = OrchestratorState.model_validate(saved['snapshot']['state'])
    state.run_metadata['specimen_result'] = deepcopy(saved['specimen'])
    # Old Python tasks do not survive restart; do not route Resume to them.
    for key in ('vision_review_retry', 'printer_wait_recovery'):
        if isinstance(state.run_metadata.get(key), dict):
            state.run_metadata[key]['status'] = 'superseded_by_equipment_selection'
    state.run_metadata['equipment_selection_resume'] = {'status': 'ready', 'run_id': run_id,
        'loop_id': state.loop_count, 'specimen_id': state.current_experiment_spec['specimen_id'],
        'source_execution_id': saved['record']['execution_id'], 'one_cycle_only': True}
    transcript = Path(saved['transcript_path'])
    messages = deque(maxlen=PLANNING_TRANSCRIPT_MEMORY_LIMIT)
    total = 0
    with transcript.open() as stream:
        for line in stream:
            if line.strip():
                messages.append(json.loads(line)); total += 1
    session_id = saved['planning']['planning_session_id']
    setup = SetupStore(transcript.parent, session_id)
    bundle = build_logger_bundle(run_id=run_id, run_root=controller._deps.run_root,
        logging_config=controller._deps.logging_config)
    controller._state, controller._logger_bundle = state, bundle
    controller._planning_session_id = session_id
    controller._canonical_planning_transcript_path = transcript
    controller._experimental_setup_store, controller._experimental_setup_session = setup, session_id
    controller._planning_messages, controller._planning_message_total = list(messages), total
    controller._planning_bootstrapped = True
    return {'ok': True, 'status': 'restored_awaiting_resume', 'run_id': run_id,
        'resume_stage': 'equipment', 'actuation_performed': False}


async def resume_selection(controller):
    async with controller._error_resume_lock:
        state = controller._state
        recovery = state.run_metadata.get('equipment_selection_resume') or {}
        if recovery.get('status') == 'running' and controller._planning_handoff_active():
            return {'ok': True, 'status': 'already_resuming'}
        try:
            if (recovery.get('status') != 'ready' or controller.snapshot().get('is_running')
                    or controller._planning_request_lock.locked()
                    or recovery.get('run_id') != state.run_id or recovery.get('loop_id') != state.loop_count
                    or recovery.get('specimen_id') != state.current_experiment_spec.get('specimen_id')):
                raise ValueError('Not at restored inactive EQP selection boundary')
            record, specimen = selection_recovery_inputs(controller)
            if record['execution_id'] != recovery['source_execution_id']:
                raise ValueError('Selection identity changed')
            # Recheck immutable archives and the source checkpoint before dispatch.
            load_checkpoint(controller._deps.run_root, state.run_id)
        except (ValueError, OSError, KeyError) as exc:
            return {'ok': False, 'status': 'blocked', 'message': str(exc)}
        rejection = await controller._plc_service_start_rejection()
        if rejection:
            return rejection
        claim = run_directory(controller._deps.run_root, state.run_id) / 'recovery/equipment_selection.claim'
        try:
            with claim.open('x') as stream:
                json.dump(dict(recovery), stream)
            claim.chmod(0o600)
        except FileExistsError:
            return {'ok': False, 'status': 'blocked', 'message': 'Selection recovery already dispatched'}
        state.run_metadata['specimen_result'] = specimen
        state.run_metadata['equipment_selection_retry'] = {'source_execution_id': record['execution_id']}
        state.run_metadata['guardian_recovery_wait']['status'] = 'retry_prepared'
        state.retry_counters.pop('equipment', None)
        state.is_paused, state.stage = False, Stage.EQUIPMENT
        recovery['status'] = 'running'

        async def continue_equipment():
            try:
                result = await controller._run_planning_loop_tail(state.current_experiment_spec,
                    cycle_index=recovery['loop_id'] + 1,
                    total_cycles=controller._planning_cycle_limit(state.current_experiment_spec),
                    resume_stage=Stage.EQUIPMENT)
                failed = any(owner.success is False and owner.run_id == state.run_id
                    and owner.loop_id == recovery['loop_id'] for owner in state.agent_status.values())
                done = result.get('ok') and result.get('decision') in {'continue', 'complete', 'stop'} and not failed
                recovery.update(status='cycle_finished' if done else 'needs_attention', result=result)
                return result
            except Exception as exc:
                recovery.update(status='needs_attention', error=f'{type(exc).__name__}: {exc}')
                state.stage = Stage.ERROR
                return {'ok': False, 'message': recovery['error']}
            finally:
                state.is_paused = True
                await controller._emit_control_event('equipment_selection_recovery.finished',
                    'Restored EQP tail returned; next fabrication not dispatched', dict(recovery))

        controller._set_planning_handoff_task(asyncio.create_task(continue_equipment()))
        await controller._emit_control_event('equipment_selection_recovery.started',
            'Resumed unexecuted EQP selection; completed printing and transfer preserved', dict(recovery))
        return {'ok': True, 'status': 'resuming_equipment_selection', 'run_id': state.run_id,
            'one_cycle_only': True}


if __name__ == '__main__':
    from urllib.request import urlopen
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--root', default='runs')
    parser.add_argument('--url', default='http://127.0.0.1:7860')
    args = parser.parse_args()
    with urlopen(args.url + '/api/state', timeout=30) as response:
        snapshot = json.load(response)
    with urlopen(args.url + '/api/planning/session', timeout=30) as response:
        planning = json.load(response)
    print(json.dumps(save_checkpoint(snapshot, planning, args.root, args.run_id)))
