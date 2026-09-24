"""Operator Resume for a proven read-only failure at Equipment's entry.

Keep the live waiting loop and immutable failed execution. A new attempt identity
reruns the ordinary Equipment entry checks; no print, transfer, or gate is skipped.
"""
from copy import deepcopy
from pathlib import Path
import re
from uuid import uuid4

from orchestrator.state import Stage


def stopped_matches(state):
    """A completed loop counter may include a failed, never-actuated EQP tail."""
    wait = state.run_metadata.get('guardian_recovery_wait') or {}
    context = state.run_metadata.get('_planning_resume_context') or {}
    payload = state.run_metadata.get('equipment_agent_payload') or {}
    loop = wait.get('loop_id')
    return (state.stage == Stage.COMPLETE and wait.get('status') == 'stopped'
        and type(loop) is int and state.loop_count == loop + 1
        and wait.get('run_id') == state.run_id
        and bool(wait.get('specimen_id'))
        and wait['specimen_id'] == state.current_experiment_spec.get('specimen_id')
        and context.get('cycle_index') == loop + 1
        and (context.get('current_spec') or {}).get('specimen_id') == wait['specimen_id']
        and payload.get('failure_code') == 'EQUIPMENT_WORKFLOW_REVIEW_REQUIRED'
        and bool(payload.get('equipment_workflow_execution_id')))


def readonly_prefix(program):
    prefix = []
    for action in program.get('sequence', []):
        if action.get('action') not in {'screenshot', 'wait', 'wait_until_image'}:
            break
        prefix.append(deepcopy(action))
        if (action.get('action') == 'wait_until_image'
                and action.get('target') == 'entry_height_150_mm' and action.get('required') is True):
            return prefix
    raise ValueError('No read-only Equipment entry check')


def matches(state):
    wait = state.run_metadata.get('guardian_recovery_wait') or {}
    payload = state.run_metadata.get('equipment_agent_payload') or {}
    return (state.stage == Stage.GUARDIAN and state.is_paused
            and wait.get('status') == 'waiting'
            and wait.get('run_id') == state.run_id and wait.get('loop_id') == state.loop_count
            and wait.get('specimen_id') == state.current_experiment_spec.get('specimen_id')
            and bool(payload.get('equipment_workflow_execution_id'))
            and payload.get('failure_code') == 'EQUIPMENT_WORKFLOW_REVIEW_REQUIRED')


def validate_record(state, record, program):
    identity = record.get('identity') or {}
    expected = dict(run_id=state.run_id, experiment_id=state.experiment_id,
                    specimen_id=state.current_experiment_spec.get('specimen_id'))
    if (not expected['specimen_id'] or any(identity.get(k) != v for k, v in expected.items())
            or not re.fullmatch(rf'stacked-loop-{state.loop_count}(?:-restart-[a-zA-Z0-9_-]{{1,48}})?',
                                str(identity.get('sequence_id', '')))):
        raise ValueError('Equipment retry identity does not match this run/cycle/specimen')
    result = record.get('workflow_result') or {}
    data = result.get('data') or {}
    flow = data.get('equipment_skill_flow_execution') or {}
    transitions = flow.get('transitions') or []
    skill = data.get('equipment_skill_execution') or {}
    exception = data.get('equipment_skill_exception') or {}
    if (record.get('lifecycle') != 'ESCALATED' or result.get('success') is not False
            or data.get('equipment_workflow_execution_id') != record.get('execution_id')
            or flow.get('state') != 'BLOCKED' or flow.get('run_id') != state.run_id
            or len(transitions) != 1 or transitions[0].get('block_id') != 'prepare_next_specimen'
            or transitions[0].get('phase') != 'skill' or transitions[0].get('success') is not False
            or transitions[0].get('outcome') != 'failed'
            or transitions[0].get('skill_id') != exception.get('skill_id')
            or transitions[0].get('skill_version') != exception.get('version')
            or skill.get('state') != 'EXCEPTION' or skill.get('completed_segments') != []
            or skill.get('attempt') != 0
            or (data.get('equipment_workflow_recovery') or {}).get('attempts') != 0
            or exception.get('failure_code') != 'UI_LOCATOR_NOT_FOUND'
            or exception.get('segment_id') != program.get('program_id')):
        raise ValueError('Cannot prove Equipment stopped before its first device action')
    target = 'entry_height_150_mm'
    if exception.get('message') != f'Required screen target not found: {target}':
        raise ValueError('Only the initial UTM entry check can restart the whole Equipment flow')
    # A failed required locator aborts the sequential macro before any click.
    for action in program.get('sequence', []):
        if (action.get('action') == 'wait_until_image' and action.get('target') == target
                and action.get('required') is True):
            return
        if action.get('action') not in {'screenshot', 'wait', 'wait_until_image'}:
            break
    raise ValueError('Entry failure is not proven read-only; automatic restart refused')


def inputs(controller):
    from agents.equipment.agent import LabEquipmentAgent
    from utils.equipment_runtime_service import EquipmentRuntimeService
    from utils.equipment_skill_runtime import EquipmentSkillRegistry
    state = controller._state
    payload = state.run_metadata.get('equipment_agent_payload') or {}
    record = EquipmentRuntimeService(LabEquipmentAgent._RUNTIME_ROOT / 'workflow_decisions').get(
        payload['equipment_workflow_execution_id'])
    exception = record['workflow_result']['data']['equipment_skill_exception']
    root = state.current_experiment_spec.get('equipment_skill_registry_root') or Path(__file__).resolve().parents[1] / 'memory/equipment_skills'
    package = EquipmentSkillRegistry(root).get(exception['skill_id'], exception['version'])
    programs = package['programs']
    if not programs or programs[0].get('program_id') != exception['segment_id']:
        raise ValueError('Failed macro is not the first Equipment Skill segment')
    validate_record(state, record, programs[0])
    return record, programs[0]


def stopped_inputs(controller):
    """Prove the terminal counter is the same unfinished, pre-actuation cycle."""
    from types import SimpleNamespace
    from agents.equipment.agent import LabEquipmentAgent
    from utils.equipment_runtime_service import EquipmentRuntimeService
    state = controller._state
    if not stopped_matches(state) or active(controller) or controller._planning_request_lock.locked():
        raise ValueError('Not an inactive, same-specimen Equipment entry failure')
    if controller._active_safety_sources() or any(getattr(state, k) for k in
            ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested')):
        raise ValueError('Resolve safety controls before Equipment retry')
    loop = state.run_metadata['guardian_recovery_wait']['loop_id']
    normalized = state.model_copy(update={'loop_count': loop})
    record, program = inputs(SimpleNamespace(_state=normalized))
    store = EquipmentRuntimeService(LabEquipmentAgent._RUNTIME_ROOT / 'workflow_decisions')
    # Do not rewind across any later owner execution, including uncertain effects.
    for path in store.execution_root.glob('*/state.json'):
        import json
        other = json.loads(path.read_text())
        identity = other.get('identity') or {}
        if (identity.get('run_id') == state.run_id
                and identity.get('specimen_id') == state.current_experiment_spec['specimen_id']
                and other.get('execution_id') != record['execution_id']):
            raise ValueError('Another Equipment execution exists for this specimen')
    for owner in ('analysis_agent', 'knowledge_agent', 'bo_agent'):
        status = state.agent_status.get(owner)
        if status and status.run_id == state.run_id and status.loop_id == loop:
            raise ValueError('A downstream owner already executed this cycle')
    transfer = state.run_metadata.get('manipulation_execution') or {}
    placement = state.run_metadata.get('utm_verifications') or {}
    for evidence in (transfer, placement):
        if any(evidence.get(k) != v for k, v in dict(run_id=state.run_id,
                loop_id=loop, specimen_id=state.current_experiment_spec['specimen_id']).items()):
            raise ValueError('Transfer/placement does not belong to this cycle')
    first = placement.get('verification_1') or {}
    evidence = first.get('evidence') or {}
    if (transfer.get('state') != 'done' or transfer.get('success') is not True
            or first.get('confirmed') is not True or evidence.get('rollout_stopped') is not True
            or evidence.get('rollout_stop_status') != 'STOPPED'
            or not transfer.get('session_id') or evidence.get('session_id') != transfer['session_id']):
        raise ValueError('Verified placement and stopped transfer required')
    return record, program


async def recheck_entry(controller, program):
    import asyncio
    bridge = controller._deps.agent_context.tools.resource('equipment.bridge')
    if bridge is None:
        raise ValueError('Equipment bridge is unavailable')
    # No focus, click, key press, registration, or equipment motion in this probe.
    return await asyncio.to_thread(bridge.run, dict(runtime_mode='live', force_live_bridge=True,
        confirm_setup_gui_execute=True, program_id='', run_id=controller._state.run_id,
        sequence_id='entry-recheck-' + uuid4().hex, sequence=readonly_prefix(program)))


def recovery_projection(state, program, proof, recovery_id):
    """Resolve only verified UI-entry/diagnostic failures, keeping their audit."""
    from datetime import datetime, timezone
    from utils.hardware_alert_lifecycle import is_active
    if (proof.get('ok') is not True or proof.get('failure_code')
            or not any(t.get('status') == 'ok' and t.get('detail') == 'entry_height_150_mm via image'
                       for t in proof.get('step_trace', [])) or not proof.get('output_artifacts')):
        raise ValueError('Current read-only Equipment entry recheck did not pass')
    loop = state.run_metadata['guardian_recovery_wait']['loop_id']
    now = datetime.now(timezone.utc).isoformat()
    metadata = {k: deepcopy(state.run_metadata.get(k) or []) for k in
                ('hardware_alerts', 'guardian_gates', 'incident_records')}
    resolved = set()
    messages = set()
    for alert in metadata['hardware_alerts']:
        if not is_active(alert):
            continue
        code = alert.get('failure_code')
        capture = (code == 'PYAUTOGUI_SCREENSHOT_FAILED'
                   and alert.get('tool') == 'equipment.pyautogui.screenshot')
        # A rejected standalone program never ran. It is not the registered
        # workflow being retried, whose actual entry is independently checked.
        missing = (code == 'PYAUTOGUI_PROGRAM_NOT_FOUND' and alert.get('tool') == 'equipment.pyautogui.run'
            and alert.get('workflow') == 'windows_run_program'
            and str(alert.get('message', '')).startswith('Unknown program_id: ')
            and alert['message'] != 'Unknown program_id: ' + program['program_id'])
        if (alert.get('run_id') != state.run_id or alert.get('loop_id') != loop
                or alert.get('device_class') != 'equipment' or not (capture or missing)
                or alert.get('severity') == 'critical'
                or any(alert.get(k) for k in ('latched', 'safety_interlock', 'manual_reset_required'))):
            raise ValueError('Unrelated or unverified hardware alert still blocks recovery')
        resolved.add(alert['alert_id']); messages.add(alert.get('message'))
        alert.update(lifecycle='resolved', blocks_workflow=False, requires_ack=False,
            resolved_at=now, resolved_by=recovery_id, resolution='operator_entry_retry_after_fresh_ui_recheck')
    for gate in metadata['guardian_gates']:
        audit = gate.get('audit_log') or {}
        if audit.get('lifecycle') == 'resolved' and audit.get('resolved_by'):
            continue
        if gate.get('decision') not in {'block', 'safe_stop', 'require_human_approval'}:
            continue
        if gate.get('run_id') != state.run_id or gate.get('loop_id') != loop:
            if gate.get('decision') in {'block', 'safe_stop'}:
                raise ValueError('An unrelated blocking gate requires review')
            continue
        alarms = gate.get('alarms') or []
        target_message = 'Required screen target not found: entry_height_150_mm'
        entry = (gate.get('stage') == 'equipment' and gate.get('phase') == 'action'
            and gate.get('reason_code') == 'UI_LOCATOR_NOT_FOUND'
            and any(a.get('message') == target_message for a in alarms))
        post = (gate.get('stage') == 'equipment' and gate.get('phase') == 'post'
            and gate.get('reason_code') == 'MISSING_REQUIRED_INPUT'
            and any(a.get('message') == target_message for a in alarms)
            and any(a.get('message') == 'EQUIPMENT_WORKFLOW_REVIEW_REQUIRED' for a in alarms))
        diagnostic = (gate.get('stage') == 'equipment' and gate.get('phase') == 'pre'
            and gate.get('reason_code') == 'UTM_MACRO_MISMATCH' and bool(alarms)
            and all(a.get('source_path') == 'state.run_metadata.hardware_alerts'
                    and a.get('message') in messages for a in alarms))
        # A non-blocking Guardian review remains as history; current gates are
        # recomputed by the ordinary owner path, never converted into success.
        if gate.get('decision') == 'require_human_approval':
            continue
        if not (entry or post or diagnostic) or any(a.get('severity') == 'critical' for a in alarms):
            raise ValueError('A blocking gate lacks same-entry recovery evidence')
        resolved.add(gate['gate_id'])
        gate.setdefault('audit_log', {}).update(lifecycle='resolved', resolved_by=recovery_id,
            resolved_at=now, resolution='superseded_by_operator_pre_actuation_retry')
    for incident in metadata['incident_records']:
        if incident.get('incident_id') in resolved:
            incident.update(status='resolved', resolved_by=recovery_id, resolved_at=now)
    return metadata


def stopped_boundary(state):
    return deepcopy(dict(run_id=state.run_id, experiment_id=state.experiment_id,
        stage=state.stage, loop_count=state.loop_count, spec=state.current_experiment_spec,
        safety=[state.stop_requested, state.safe_stop_requested, state.emergency_stop_requested],
        evidence={k: state.run_metadata.get(k) for k in ('guardian_recovery_wait',
            'equipment_agent_payload', 'equipment_explicit_restart', '_planning_resume_context',
            'active_safety_sources', 'hardware_alerts', 'guardian_gates', 'incident_records',
            'manipulation_execution', 'utm_verifications')}))


async def resume_stopped(controller):
    import asyncio
    import json
    from app.run_recovery import run_directory
    async with controller._error_resume_lock:
        if active(controller):
            return dict(ok=True, status='already_running', run_id=controller._state.run_id)
        state = controller._state
        before_state = state.model_dump(mode='json')
        boundary = stopped_boundary(state)
        try:
            before = deepcopy(stopped_inputs(controller))
            rejection = await controller._plc_service_start_rejection()
            if rejection:
                return rejection
            proof = await recheck_entry(controller, before[1])
            if (controller._state is not state or stopped_boundary(state) != boundary
                    or stopped_inputs(controller) != before):
                raise ValueError('Equipment retry boundary changed during recheck')
            recovery_id = 'equipment-entry-recovery-' + uuid4().hex
            projection = recovery_projection(state, before[1], proof, recovery_id)
            folder = run_directory(controller._deps.run_root, state.run_id) / 'recovery'
            folder.mkdir(parents=True, exist_ok=True)
            backup = folder / ('equipment_entry_before_' + uuid4().hex + '.json')
            with backup.open('x', encoding='utf-8') as stream:
                json.dump(dict(state=before_state, source_execution=before[0], recheck=proof,
                    recovery_id=recovery_id), stream, ensure_ascii=False)
            backup.chmod(0o600)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return dict(ok=False, status='blocked', message=str(exc))
        loop = state.run_metadata['guardian_recovery_wait']['loop_id']
        context = state.run_metadata['_planning_resume_context']
        state.run_metadata.update(projection)
        if state.device_health.get('equipment') in {
                'blocking:PYAUTOGUI_SCREENSHOT_FAILED', 'blocking:PYAUTOGUI_PROGRAM_NOT_FOUND'}:
            state.device_health['equipment'] = 'ready'
        state.run_metadata['equipment_explicit_restart'] = dict(run_id=state.run_id,
            experiment_id=state.experiment_id, loop_id=loop,
            specimen_id=state.current_experiment_spec['specimen_id'], requested_by='operator',
            source_execution_id=before[0]['execution_id'], attempt_id=uuid4().hex)
        state.run_metadata['guardian_recovery_wait']['status'] = 'retry_prepared'
        state.run_metadata['equipment_entry_recovery'] = dict(recovery_id=recovery_id,
            checkpoint=str(backup), loop_id=loop, status='running', source_execution_id=before[0]['execution_id'])
        state.retry_counters.pop('equipment', None)
        state.loop_count, state.stage, state.is_paused = loop, Stage.EQUIPMENT, False
        async def continue_equipment():
            try:
                return await controller._run_planning_cycle_series(first_spec=state.current_experiment_spec,
                    design_constraints=context.get('design_constraints') or {}, start_cycle=loop + 1,
                    resume_tail_stage=Stage.EQUIPMENT)
            except Exception as exc:
                state.stage, state.is_paused = Stage.ERROR, True
                await controller._emit_control_event('equipment_entry_recovery_failed', str(exc),
                    dict(recovery_id=recovery_id, cycle_index=loop + 1))
                return dict(ok=False, status='failed', message=str(exc))
        controller._set_planning_handoff_task(asyncio.create_task(continue_equipment()))
        await controller._emit_control_event('run_resume',
            'Same-specimen Equipment entry restored after fresh UI recheck; no print or transfer replay',
            dict(recovery_id=recovery_id, checkpoint=str(backup), resume_stage='equipment', cycle_index=loop + 1))
        return dict(ok=True, status='resuming', run_id=state.run_id, resume_stage='equipment', cycle_index=loop + 1)


def prepare_stopped(controller):
    """Prepare the existing Resume dispatcher at an inactive, proven boundary."""
    from app.safe_hot_reload import reload_sources
    stopped_inputs(controller)
    root = Path(__file__).resolve().parents[1]
    reload_sources({'app.resume_routing': root / 'app/resume_routing.py'})
    return dict(ok=True, status='equipment_entry_resume_ready', run_id=controller._state.run_id,
                cycle_index=controller._state.loop_count, actuation_performed=False, workflow_resumed=False)


def active(controller):
    task = getattr(controller, '_run_task', None)
    return controller._planning_handoff_active() or (task is not None and not task.done())


def validate_boundary(controller):
    state = controller._state
    if not matches(state) or not active(controller):
        raise ValueError('Equipment entry retry requires the existing paused Guardian loop')
    if controller._active_safety_sources() or any(getattr(state, k) for k in
            ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested')):
        raise ValueError('Resolve safety controls before Equipment retry')
    record, program = inputs(controller)
    validate_record(state, record, program)
    if record['execution_id'] != state.run_metadata['equipment_agent_payload']['equipment_workflow_execution_id']:
        raise ValueError('Equipment failure identity changed')
    return record, program


async def resume(controller):
    async with controller._error_resume_lock:
        state = controller._state
        if active(controller) and not state.is_paused:
            return dict(ok=True, status='already_running', run_id=state.run_id)
        try:
            before = deepcopy(validate_boundary(controller))
            rejection = await controller._plc_service_start_rejection()
            if rejection:
                return rejection
            if controller._state is not state or validate_boundary(controller) != before:
                raise ValueError('Equipment retry boundary changed during Resume')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return dict(ok=False, status='blocked', message=str(exc))
        request = dict(run_id=state.run_id, experiment_id=state.experiment_id, loop_id=state.loop_count,
            specimen_id=state.current_experiment_spec['specimen_id'], requested_by='operator',
            source_execution_id=before[0]['execution_id'], attempt_id=uuid4().hex)
        # No await until the existing waiter has its complete new boundary.
        state.run_metadata['equipment_explicit_restart'] = request
        state.run_metadata['guardian_recovery_wait']['status'] = 'retry_prepared'
        state.retry_counters.pop('equipment', None)
        state.stage = Stage.EQUIPMENT
        state.is_paused = False
        await controller._emit_control_event('run_resume',
            'Equipment entry retry in the existing cycle; original failure and all safety gates retained', request)
        return dict(ok=True, status='resumed', run_id=state.run_id, resume_stage='equipment',
                    cycle_index=state.loop_count + 1)


async def hot_reload(controller):
    """Publish only the idle Resume dispatcher, never the suspended loop body."""
    import asyncio
    import hashlib
    import subprocess
    import sys
    from app.safe_hot_reload import reload_sources
    state = controller._state
    before = deepcopy(validate_boundary(controller))
    root = Path(__file__).resolve().parents[1]
    paths = {'app.resume_routing': root / 'app/resume_routing.py'}
    checked_paths = {**paths, 'entry_resume': Path(__file__)}
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in checked_paths.items()}
    checked = await asyncio.to_thread(subprocess.run, [sys.executable, '-m', 'pytest',
        'tests/unit/test_equipment_entry_resume.py', 'tests/unit/test_scoped_specimen_resume.py',
        'tests/unit/test_equipment_explicit_restart.py', '-q', '--tb=short'],
        cwd=root, capture_output=True, text=True, timeout=45)
    if checked.returncode:
        raise ValueError('Equipment Resume validation failed; live code retained')
    if (controller._state is not state or validate_boundary(controller) != before
            or any(hashlib.sha256(path.read_bytes()).hexdigest() != hashes[key]
                   for key, path in checked_paths.items())):
        raise ValueError('Equipment Resume boundary/source changed; live code retained')
    loaded = reload_sources(paths)
    await controller._emit_control_event('runtime.equipment_entry_resume_hotfix',
        'Resume now retries proven read-only Equipment entry failures; still paused',
        dict(modules=loaded, sha256=hashes, actuation_performed=False))
    return dict(ok=True, status='equipment_entry_resume_ready', modules=loaded, sha256=hashes,
                server_restarted=False, actuation_performed=False, workflow_resumed=False)
