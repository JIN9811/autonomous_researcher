"""Operator Resume for a proven read-only failure at Equipment's entry.

Keep the live waiting loop and immutable failed execution. A new attempt identity
reruns the ordinary Equipment entry checks; no print, transfer, or gate is skipped.
"""
from copy import deepcopy
from pathlib import Path
import re
from uuid import uuid4

from orchestrator.state import Stage


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
