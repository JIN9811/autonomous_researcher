"""Select scoped recovery; ordinary running loops are never relaunched."""
import importlib

from orchestrator.state import Stage


ROUTES = (
    ('vision_ros_retry', 'app.vision_ros_recovery', 'resume'),
    ('guardian_review_retry', 'app.guardian_review_recovery', 'resume_review'),
    ('equipment_selection_resume', 'app.equipment_selection_checkpoint', 'resume_selection'),
    ('vision_review_retry', 'app.vision_review_recovery', 'resume_vision_review'),
    ('printer_wait_recovery', 'app.printer_wait_recovery', 'resume_printer_wait'),
)


async def dispatch(controller):
    state = controller._state
    if controller._active_safety_sources() or any(getattr(state, key) for key in
            ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested')):
        return {'ok': False, 'status': 'blocked', 'message': 'Use the existing safety recovery controls first.'}
    task = getattr(controller, '_run_task', None)
    active = controller._planning_handoff_active() or (task is not None and not task.done())
    if active:
        if not state.is_paused:
            return {'ok': True, 'status': 'already_running', 'run_id': state.run_id}
        boundary = (state.run_id, state.experiment_id, state.loop_count)
        rejection = await controller._plc_service_start_rejection()
        if rejection:
            return rejection
        if (controller._state is not state or boundary != (state.run_id, state.experiment_id, state.loop_count)
                or controller._active_safety_sources()
                or any(getattr(state, key) for key in
                       ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested'))):
            return {'ok': False, 'status': 'blocked', 'message': 'Resume boundary or safety state changed.'}
        task = getattr(controller, '_run_task', None)
        if not (controller._planning_handoff_active() or (task is not None and not task.done())):
            return {'ok': False, 'status': 'blocked', 'message': 'Paused execution ended while checking Resume.'}
        state.is_paused = False
        await controller._emit_control_event('run_resume', 'Existing paused execution resumed; no stage redispatched',
                                             {'status': 'resumed', 'operator_action': True})
        return {'ok': True, 'status': 'resumed', 'run_id': state.run_id}
    metadata = state.run_metadata
    for key, module, function in ROUTES:
        record = metadata.get(key) or {}
        if not isinstance(record, dict):
            continue
        if record.get('run_id') != state.run_id:
            continue  # Old recovery markers are audit, not current routing authority.
        if record.get('experiment_id') and record['experiment_id'] != state.experiment_id:
            continue
        if key == 'vision_ros_retry' and record.get('status') == 'cycle_finished':
            if record.get('loop_id') == state.loop_count - 1 and state.stage == Stage.DESIGN:
                return await getattr(importlib.import_module(module), 'resume_completed_cycle')(controller)
        loop = record.get('cycle') if key == 'guardian_review_retry' else record.get('loop_id')
        if loop != state.loop_count or record.get('status') not in {'ready', 'running'}:
            continue
        if record.get('specimen_id') and record['specimen_id'] != state.current_experiment_spec.get('specimen_id'):
            continue
        return await getattr(importlib.import_module(module), function)(controller)
    from app.specimen_resume import current_failure, resume
    if current_failure(state):
        return await resume(controller)
    if state.stage == Stage.ERROR:
        return None  # Existing proven Equipment terminal-review recovery remains authoritative.
    return {'ok': False, 'status': 'blocked', 'run_id': state.run_id,
            'message': 'No active paused execution or matching recovery checkpoint; no device action was started.'}
