"""Retry a rejected post-ejection image review, never replay completed fabrication."""
import asyncio
import hashlib
import json
from copy import deepcopy

from app.run_recovery import run_directory
from orchestrator.state import Stage


def validate_boundary(controller):
    state = controller._state
    if (controller.snapshot().get('is_running') or controller._planning_request_lock.locked()
            or controller._planning_handoff_active() or state.stage not in {Stage.COMPLETE, Stage.ERROR}):
        raise ValueError('Vision retry requires an inactive terminal workflow')
    if controller._active_safety_sources() or any(getattr(state, key) for key in
            ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested')):
        raise ValueError('Safety recovery is required before Vision retry')
    spec = state.current_experiment_spec
    specimen = state.run_metadata.get('specimen_result') or {}
    if (specimen.get('run_id') != state.run_id or specimen.get('specimen_id') != spec.get('specimen_id')
            or specimen.get('printer_completion_verified') is not True):
        raise ValueError('Same-specimen printer completion is not verified')
    completion = specimen.get('printer_completion_wait') or {}
    if (completion.get('status') != 'complete' or completion.get('run_id') != state.run_id
            or completion.get('loop_id') != state.loop_count
            or completion.get('specimen_id') != spec.get('specimen_id')):
        raise ValueError('Printer completion belongs to a different cycle')
    owner = state.agent_status.get('vision_agent')
    if (owner is None or owner.success is not False or owner.run_id != state.run_id
            or owner.loop_id != state.loop_count):
        raise ValueError('No failed Vision owner for this cycle')
    loop = run_directory(controller._deps.run_root, state.run_id) / 'runtime/loops' / f'loop-{state.loop_count + 1:06d}'
    for name in ('manipulation_agent', 'equipment_agent', 'analysis_agent', 'bo_agent'):
        downstream = state.agent_status.get(name)
        if ((downstream and downstream.run_id == state.run_id and downstream.loop_id == state.loop_count)
                or list((loop / name).glob('attempt-*'))):
            raise ValueError('Downstream execution exists; cannot rewind to pickup')
    paths = sorted((loop / 'vision_agent').glob('attempt-*/result.json'))
    if not paths:
        raise ValueError('Archived Vision failure is unavailable')
    source = paths[-1]
    archived = json.loads(source.read_text())
    decision = archived.get('data', {}).get('vision_decision') or {}
    if (archived.get('status') != 'failed' or decision.get('failure_code') != 'VISION_REVIEW_REQUIRED'
            or decision.get('contract_id') != 'active_cam' or decision.get('checkpoint') != 'image_review'
            or decision.get('run_id') != state.run_id or decision.get('loop_id') != state.loop_count
            or decision.get('specimen_id') != spec.get('specimen_id')):
        raise ValueError('Only a rejected same-cycle ActiveCam image review is retryable')
    return {'run_id': state.run_id, 'loop_id': state.loop_count, 'specimen_id': spec['specimen_id'],
            'source_path': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}


async def resume_vision_review(controller):
    async with controller._error_resume_lock:
        record = controller._state.run_metadata.get('vision_review_retry') or {}
        if record.get('status') == 'running' and controller._planning_handoff_active():
            return {'ok': True, 'status': 'already_resuming'}
        try:
            boundary = validate_boundary(controller)
            if any(record.get(key) != value for key, value in boundary.items()):
                raise ValueError('Prepared Vision retry scope changed')
        except (ValueError, OSError) as exc:
            return {'ok': False, 'status': 'blocked', 'message': str(exc)}
        rejection = await controller._plc_service_start_rejection()
        if rejection:
            return rejection
        state = controller._state
        record['status'] = 'running'
        state.is_paused = False
        state.stage = Stage.VISION
        state.retry_counters.pop('vision', None)

        async def continue_from_fresh_capture():
            try:
                context = state.run_metadata.get('_planning_resume_context') or {}
                result = await controller._run_planning_cycle_series(
                    first_spec=deepcopy(state.current_experiment_spec),
                    design_constraints=deepcopy(context.get('design_constraints') or {}),
                    start_cycle=boundary['loop_id'] + 1, resume_tail_stage=Stage.VISION)
                failed = any(owner.success is False and owner.run_id == state.run_id
                    and owner.loop_id == state.loop_count for owner in state.agent_status.values())
                done = bool(result.get('ok')) and result.get('decision') in {'continue', 'complete', 'stop'} and not failed
                record.update(status='finished' if done else 'needs_attention', result=result)
                return result
            except Exception as exc:
                record.update(status='needs_attention', error=f'{type(exc).__name__}: {exc}')
                state.stage = Stage.ERROR
                state.is_paused = True
                return {'ok': False, 'message': record['error']}
            finally:
                await controller._emit_control_event('vision_review_retry.finished',
                    'Fresh Vision retry returned through the normal cycle series', dict(record))

        controller._set_planning_handoff_task(asyncio.create_task(continue_from_fresh_capture()))
        await controller._emit_control_event('vision_review_retry.started',
            'Operator resumed at fresh ActiveCam capture; completed printing is not repeated', dict(record))
        return {'ok': True, 'status': 'resuming_fresh_vision', **boundary}
