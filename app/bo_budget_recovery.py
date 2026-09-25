"""Preserve and resume a BO-only hold caused by an obsolete workspace budget."""
import asyncio
import hashlib
import json
from collections import deque
from pathlib import Path
from uuid import uuid4

from orchestrator.state import OrchestratorState, Stage


def prepare_state(state):
    m = state.run_metadata
    wait, context = m.get('guardian_recovery_wait') or {}, m.get('_planning_resume_context') or {}
    bo = m.get('bo_agent') or {}
    decision = bo.get('decision') or {}
    total = (m.get('planning_cycle_contract') or {}).get('total_cycles')
    old = (m.get('bo_settings') or {}).get('budget')
    if (state.stage != Stage.GUARDIAN or not state.is_paused
            or any((state.stop_requested, state.safe_stop_requested, state.emergency_stop_requested))
            or m.get('active_safety_sources')
            or wait.get('status') != 'waiting' or wait.get('run_id') != state.run_id
            or wait.get('loop_id') != state.loop_count
            or wait.get('specimen_id') != state.current_experiment_spec.get('specimen_id')
            or context.get('cycle_index') != state.loop_count + 1
            or (context.get('current_spec') or {}).get('specimen_id') != wait.get('specimen_id')
            or type(total) is not int or context.get('total_cycles') != total
            or total <= state.loop_count + 1 or type(old) is not int or old >= total
            or bo.get('run_id') != state.run_id or bo.get('experiment_id') != state.experiment_id
            or bo.get('failure_code') != 'BO_OWNER_REVIEW' or decision.get('status') != 'returned'
            or decision.get('optimizer_result') is not None
            or 'budget' not in str(decision.get('reason', '')).lower()
            or (decision.get('diagnostics') or {}).get('finite_observation_count') != old):
        raise ValueError('Not a same-cycle BO budget mismatch awaiting review')
    for owner in ('equipment_agent', 'analysis_agent', 'knowledge_agent'):
        status = state.agent_status.get(owner)
        if not status or not status.success or status.run_id != state.run_id or status.loop_id != state.loop_count:
            raise ValueError('Completed same-cycle equipment, analysis and knowledge required')
    from utils.hardware_alert_lifecycle import is_active
    if any(is_active(a) for a in m.get('hardware_alerts', [])):
        raise ValueError('Hardware alerts require their existing recovery path')
    restored = state.model_copy(deep=True)
    recovery_id = 'bo-budget-' + uuid4().hex
    resolved = set()
    allowed = {('AGENT_RESULT_FAILED', 'payload', 'AGENT_RESULT_FAILED'),
        ('BO_CANDIDATE_UNSAFE', 'payload.bo_result', 'BO_OWNER_REVIEW'),
        ('CONTRACT_SCHEMA_INVALID', 'payload.bo_result.next_design_request', 'blocked'),
        ('CONTRACT_SCHEMA_INVALID', 'payload.artifact_execution', 'failed')}
    for gate in restored.run_metadata.get('guardian_gates', []):
        if (gate.get('audit_log') or {}).get('lifecycle') == 'resolved' and (gate.get('audit_log') or {}).get('resolved_by'):
            continue
        if gate.get('decision') not in {'block', 'safe_stop', 'require_human_approval'}:
            continue
        alarms = gate.get('alarms') or []
        if (gate.get('decision') != 'block' or gate.get('stage') != 'bo' or gate.get('phase') != 'post'
                or gate.get('run_id') != state.run_id or gate.get('loop_id') != state.loop_count
                or gate.get('reason_code') != 'AGENT_RESULT_FAILED' or not alarms
                or not any(a.get('message') == 'BO_OWNER_REVIEW' for a in alarms)
                or any((a.get('reason_code'), a.get('source_path'), a.get('message')) not in allowed for a in alarms)):
            raise ValueError('Unrelated unresolved Guardian gate; refusing BO-only retry')
        gate.setdefault('audit_log', {}).update(lifecycle='resolved', resolved_by=recovery_id,
            resolution='operator_authorized_budget_contract_correction', old_budget=old, run_budget=total)
        resolved.add(gate['gate_id'])
    if not resolved:
        raise ValueError('No matching BO review gate')
    for incident in restored.run_metadata.get('incident_records', []):
        if incident.get('incident_id') in resolved:
            incident.update(status='resolved', resolved_by=recovery_id)
    restored.run_metadata['bo_settings']['budget'] = total
    restored.run_metadata['guardian_recovery_wait']['status'] = 'retry_prepared'
    restored.run_metadata['bo_budget_retry'] = dict(run_id=state.run_id, experiment_id=state.experiment_id,
        loop_id=state.loop_count, specimen_id=wait['specimen_id'], status='ready', recovery_id=recovery_id)
    restored.stage = Stage.BO
    return restored


def checkpoint_path(root, run_id):
    from app.run_recovery import run_directory
    return run_directory(root, run_id) / 'recovery/bo_budget_checkpoint.json'


def save(snapshot, planning, root):
    state = OrchestratorState.model_validate(snapshot['state'])
    prepare_state(state)  # Check before storing; never mutate the running server.
    payload = json.dumps({'state': snapshot['state'], 'planning': planning}, ensure_ascii=False)
    path = checkpoint_path(root, state.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump({'sha256': hashlib.sha256(payload.encode()).hexdigest(), 'payload': payload}, stream)
    path.chmod(0o600)
    return path


def restore(controller, run_id):
    from app.controller import PLANNING_TRANSCRIPT_MEMORY_LIMIT
    from orchestrator.experimental_setup import SetupStore
    from logging_system.logger_factory import build_logger_bundle
    if (controller._state.stage != Stage.IDLE or controller.snapshot().get('is_running')
            or controller._active_safety_sources()
            or any(getattr(controller._state, k) for k in ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested'))):
        raise ValueError('BO checkpoint restore requires an idle, safe server')
    envelope = json.loads(checkpoint_path(controller._deps.run_root, run_id).read_text())
    if hashlib.sha256(envelope['payload'].encode()).hexdigest() != envelope['sha256']:
        raise ValueError('BO checkpoint integrity mismatch')
    saved = json.loads(envelope['payload'])
    state = OrchestratorState.model_validate(saved['state'])
    if state.run_id != run_id:
        raise ValueError('BO checkpoint run identity mismatch')
    restored = prepare_state(state)
    planning = saved['planning']
    transcript = Path(planning.get('transcript_path') or '').resolve()
    session = planning.get('planning_session_id')
    if (not session or not transcript.is_relative_to(Path(controller._deps.run_root).resolve())
            or transcript.name != 'live_planning_transcript.jsonl' or not transcript.is_file()):
        raise ValueError('Original planning transcript unavailable')
    messages = deque(maxlen=PLANNING_TRANSCRIPT_MEMORY_LIMIT)
    total = 0
    for line in transcript.read_text().splitlines():
        if line.strip():
            messages.append(json.loads(line)); total += 1
    store = SetupStore(transcript.parent, session)
    logger = build_logger_bundle(run_id=run_id, run_root=controller._deps.run_root,
        logging_config=controller._deps.logging_config)
    controller._state = restored
    controller._logger_bundle = logger
    controller._planning_session_id = session
    controller._canonical_planning_transcript_path = transcript
    controller._experimental_setup_store, controller._experimental_setup_session = store, session
    controller._planning_messages, controller._planning_message_total = list(messages), total
    controller._planning_bootstrapped = True
    return dict(ok=True, status='bo_resume_ready', cycle_index=state.loop_count + 1, actuation_performed=False)


async def resume(controller):
    async with controller._error_resume_lock:
        if controller._planning_handoff_active():
            return dict(ok=True, status='already_running')
        state = controller._state
        marker = state.run_metadata.get('bo_budget_retry') or {}
        if (marker.get('status') != 'ready' or state.stage != Stage.BO or not state.is_paused
                or marker.get('run_id') != state.run_id or marker.get('loop_id') != state.loop_count
                or marker.get('specimen_id') != state.current_experiment_spec.get('specimen_id')
                or controller._active_safety_sources()
                or any((state.stop_requested, state.safe_stop_requested, state.emergency_stop_requested))):
            raise ValueError('BO retry boundary changed')
        boundary = state.model_dump(mode='json', include={'run_id','experiment_id','stage','loop_count','is_paused','current_experiment_spec'})
        rejection = await controller._plc_service_start_rejection()
        if rejection: return rejection
        if (controller._state is not state or controller._active_safety_sources()
                or any((state.stop_requested,state.safe_stop_requested,state.emergency_stop_requested))
                or boundary != state.model_dump(mode='json', include=set(boundary))):
            raise ValueError('BO retry changed during PLC check')
        context = state.run_metadata['_planning_resume_context']
        marker['status'], state.is_paused = 'running', False
        async def continue_bo():
            try:
                return await controller._run_planning_cycle_series(first_spec=state.current_experiment_spec,
                    design_constraints=context.get('design_constraints') or {},
                    start_cycle=state.loop_count + 1, resume_tail_stage=Stage.BO)
            except Exception as exc:
                state.stage, state.is_paused = Stage.ERROR, True
                await controller._emit_control_event('bo_resume_failed', str(exc), {})
                return dict(ok=False, message=str(exc))
        controller._set_planning_handoff_task(asyncio.create_task(continue_bo()))
        await controller._emit_control_event('run_resume', 'Resume corrected BO budget in the same cycle; no hardware replay', marker)
        return dict(ok=True, status='resuming', resume_stage='bo', cycle_index=state.loop_count + 1)


if __name__ == '__main__':
    from urllib.request import urlopen
    def get(path):
        with urlopen('http://127.0.0.1:7860' + path, timeout=40) as response:
            return json.load(response)
    snapshot, planning = get('/api/state'), get('/api/planning/session')
    current = get('/api/state')
    old, new = prepare_state(OrchestratorState.model_validate(snapshot['state'])), prepare_state(OrchestratorState.model_validate(current['state']))
    if (old.run_id, old.loop_count, old.current_experiment_spec) != (new.run_id, new.loop_count, new.current_experiment_spec):
        raise ValueError('Run changed during checkpoint capture')
    print(save(current, planning, Path('runs')))
