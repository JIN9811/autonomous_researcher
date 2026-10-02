"""Request-scoped, detached report inputs; no response cache or run-state store."""
from importlib import import_module

_SUPERVISOR_KEYS = (
    'orchestrator_followups', 'orchestrator_decision_register',
    'orchestrator_handoff_packets', 'loop_reflections',
    'latest_orchestrator_followup', 'latest_orchestrator_handoff',
    'orchestrator_parallel_checks', 'latest_orchestrator_parallel_checks',
    'latest_loop_reflection', 'latest_mission_contract', 'mission_contract',
    'latest_orchestration_plan', 'latest_orchestrator_control_plane', 'active_graph_id',
)


def report_snapshot(controller, definition, installed):
    """Select before serialization; retain full compatibility for undeclared plugins."""
    if definition['agent_id'] == 'orchestrator':
        keys, fields = _SUPERVISOR_KEYS, ()
    else:
        project = getattr(installed, 'project_report', None)
        module = import_module(project.__module__) if project is not None else None
        keys = getattr(module, 'REPORT_METADATA_KEYS', None)
        fields = getattr(module, 'REPORT_STATE_FIELDS', ())
        if keys is None:
            return controller.snapshot()
    # Preserve the existing baseline refresh behavior; never cache live state.
    controller._ensure_orchestrator_supervisor_baseline()
    state = controller._state
    include = {key: True for key in (
        'run_id', 'experiment_id', 'mode', 'stage', 'active_goal',
        'current_experiment_spec', 'loop_count', *fields,
    )}
    include['run_metadata'] = set(keys) | {f"{definition['stage']}_agent_payload"}
    return {
        'state': state.model_dump(mode='json', include=include),
        'is_running': bool(controller._run_task and not controller._run_task.done())
                      or controller._planning_handoff_active(),
    }
