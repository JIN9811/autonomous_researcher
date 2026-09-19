"""Retry only proven pre-device SPC failures through the normal planning loop.

The archive is authoritative: unknown/in-flight tools or any printer operation
require a different recovery path. Resume never turns a failed check into a pass.
"""
import asyncio
from collections import Counter
from copy import deepcopy
import hashlib
import json

from app.run_recovery import run_directory
from orchestrator.state import Stage


PURE_TOOLS = frozenset({
    'geometry.generate_metamaterial_stl', 'geometry.check_mesh_quality',
    'geometry.check_manufacturability', 'artifact.create_specimen_handoff',
})


def current_failure(state):
    owner = state.agent_status.get('specimen_agent')
    return bool(state.stage == Stage.ERROR and owner and owner.success is False
                and owner.run_id == state.run_id and owner.loop_id == state.loop_count)


def validate(controller):
    state = controller._state
    if (not current_failure(state) or controller.snapshot().get('is_running')
            or controller._planning_handoff_active() or controller._planning_request_lock.locked()):
        raise ValueError('SPC retry requires an inactive same-cycle failed owner')
    if controller._active_safety_sources() or any(getattr(state, key) for key in
            ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested')):
        raise ValueError('Resolve safety controls before SPC retry')
    spec = state.current_experiment_spec
    context = state.run_metadata.get('_planning_resume_context') or {}
    cycle = state.loop_count + 1
    if not isinstance(context, dict) or not isinstance(context.get('current_spec'), dict):
        raise ValueError('Missing SPC continuation context')
    if (not spec.get('specimen_id') or context.get('cycle_index') != cycle
            or context.get('current_spec', {}).get('specimen_id') != spec['specimen_id']
            or int(context.get('total_cycles') or 0) < cycle):
        raise ValueError('SPC continuation context does not match the current specimen/cycle')
    loop = run_directory(controller._deps.run_root, state.run_id) / 'runtime/loops' / f'loop-{cycle:06d}'
    for name in ('vision_agent', 'manipulation_agent', 'equipment_agent', 'analysis_agent', 'knowledge_agent', 'bo_agent'):
        if list((loop / name).glob('attempt-*')):
            raise ValueError('Downstream execution exists; refusing to repeat fabrication')
    attempts = sorted((loop / 'specimen_agent').glob('attempt-*'))
    if not attempts:
        raise ValueError('No durable SPC attempt; cannot prove that printing was not started')
    sources = []
    for folder in attempts:
        manifest_path = folder / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(manifest, dict):
            raise ValueError('Invalid SPC manifest')
        if (manifest.get('run_id') != state.run_id or manifest.get('loop_index') != state.loop_count
                or manifest.get('specimen_id') != spec['specimen_id']
                or manifest.get('agent') != 'specimen_agent' or manifest.get('status') != 'failed'
                or manifest.get('archive_status') != 'complete' or manifest.get('pending_tools') != 0
                or not manifest.get('execution_id')):
            raise ValueError('SPC archive is incomplete, successful, or belongs to another execution')
        events_path = folder / 'events.jsonl'
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        if any(not isinstance(e, dict) or not isinstance(e.get('payload', {}), dict) for e in events):
            raise ValueError('Invalid SPC event archive')
        calls = [event.get('payload', {}).get('tool') for event in events if event.get('event') == 'tool_started']
        finished = [e.get('payload', {}).get('tool') for e in events if e.get('event') in {'tool_result','tool_failed'}]
        if (not calls or any(tool not in PURE_TOOLS for tool in calls)
                or Counter(calls) != Counter(finished)
                or not events or events[-1].get('event') != 'agent_finished'
                or events[-1].get('payload', {}).get('status') != 'failed'):
            raise ValueError('SPC may have contacted a device; use job-bound recovery, never reprint blindly')
        result = json.loads((folder / 'result.json').read_text())
        if not isinstance(result, dict) or result.get('status') != 'failed':
            raise ValueError('SPC result is not a terminal failure')
        sources.append({'execution_id': manifest['execution_id'], 'manifest_path': str(manifest_path),
                        'events_sha256': hashlib.sha256(events_path.read_bytes()).hexdigest()})
    return {'run_id': state.run_id, 'loop_id': state.loop_count, 'cycle_index': cycle,
            'specimen_id': spec['specimen_id'], 'sources': sources}


async def resume(controller):
    async with controller._error_resume_lock:
        if controller._planning_handoff_active():
            return {'ok': True, 'status': 'already_resuming', 'run_id': controller._state.run_id}
        try:
            boundary = validate(controller)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return {'ok': False, 'status': 'blocked', 'message': str(exc)}
        rejection = await controller._plc_service_start_rejection()
        if rejection:
            return rejection
        # Recheck after the awaited PLC query; it must not change the boundary.
        try:
            if validate(controller) != boundary:
                raise ValueError('SPC recovery boundary changed')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return {'ok': False, 'status': 'blocked', 'message': str(exc)}
        state = controller._state
        spec = deepcopy(state.current_experiment_spec)
        context = deepcopy(state.run_metadata['_planning_resume_context'])
        record = {**boundary, 'status': 'running', 'scope': 'pre_device_retry'}
        state.run_metadata['specimen_retry'] = record
        state.is_paused = False
        state.retry_counters.pop('specimen', None)

        async def proceed():
            try:
                result = await controller._run_planning_specimen_stage(spec)
                if result.get('pending'):
                    record.update(status='waiting_for_input', result=result)
                    return result
                result = await controller._run_planning_cycle_series(first_spec=spec,
                    design_constraints=context.get('design_constraints') or {}, start_cycle=boundary['cycle_index'])
                record.update(status='finished' if result.get('ok') else 'needs_attention', result=result)
                return result
            except Exception as exc:
                record.update(status='needs_attention', error=f'{type(exc).__name__}: {exc}')
                state.stage, state.is_paused = Stage.ERROR, True
                await controller._emit_control_event('specimen_retry.failed',
                    'SPC retry failed; cycle and original evidence retained', dict(record), level='ERROR')
                return {'ok': False, 'message': str(exc)}

        controller._set_planning_handoff_task(asyncio.create_task(proceed()))
        await controller._emit_control_event('run_resume', 'Resuming unprinted specimen through the normal SPC path', dict(record))
        return {'ok': True, 'status': 'resuming', 'run_id': state.run_id,
                'resume_stage': 'specimen', 'cycle_index': boundary['cycle_index']}
