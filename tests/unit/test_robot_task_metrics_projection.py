import ast
from pathlib import Path
from types import SimpleNamespace

from utils.manipulation_execution import task_progress_counts


def test_monitor_projection_keeps_verified_task_ledger_without_copying_all_metadata():
    # Execute only the real projection, without starting the application/devices.
    tree = ast.parse(Path('app/main.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == '_manipulation_runtime_state')
    record = {'run_id': 'r', 'loop_id': 0, 'session_id': 's', 'state': 'done', 'success': True}
    metadata = {'manipulation_task_progress': {'transfer:0:s': record},
                'manipulation_execution': record, 'initial_manipulation_execution': record,
                'utm_clear_execution': {'run_id': 'r', 'loop_id': 0, 'session_id': 'c',
                                        'state': 'waiting', 'success': None},
                'irrelevant_large_payload': {'keep_out': True}}
    state = SimpleNamespace(run_id='r', stage=SimpleNamespace(value='equipment'),
                            safe_stop_requested=False, emergency_stop_requested=False,
                            run_metadata=metadata)
    ns = {'controller': SimpleNamespace(_state=state), 'Any': object}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app/main.py', 'exec'), ns)
    projected = ns['_manipulation_runtime_state']()
    counts = task_progress_counts(projected)
    assert counts['success_count'] == 1
    assert counts['pending_count'] == 1
    assert counts['attempt_count'] == 2
    assert 'irrelevant_large_payload' not in projected['run_metadata']


def test_legacy_task_snapshot_is_run_scoped_and_cannot_override_current_publisher():
    from utils.robot_task_metrics import merge_task_state
    legacy = {'run_id': 'r', 'run_metadata': {'robot_task_result': {'keep': True}}}
    saved = {'run_id': 'r', 'run_metadata': {'manipulation_task_progress': {
        'one': {'run_id': 'r', 'session_id': 's', 'state': 'done', 'success': True}}}}
    assert task_progress_counts(merge_task_state(legacy, saved))['success_count'] == 1
    assert legacy['run_metadata'] == {'robot_task_result': {'keep': True}}
    assert merge_task_state({**legacy, 'run_id': 'other'}, saved)['run_metadata'] == legacy['run_metadata']
    direct = {**legacy, 'task_progress_projection_version': 1}
    assert merge_task_state(direct, saved) is direct


def test_existing_display_summary_receives_verified_counts_without_rewriting_raw_log(tmp_path):
    import json
    from utils.robot_task_metrics import update_task_summary
    raw = tmp_path / 'motor_events.jsonl'
    raw.write_text('unchanged source')
    output = tmp_path / 'grasp_display_v5'
    output.mkdir()
    summary = output / 'policy_tracking_summary.json'
    summary.write_text(json.dumps({'sample_count': 123, 'grasp_outcomes': {'success_count': 1}}))
    state = {'run_id': 'r', 'run_metadata': {'manipulation_task_progress': {
        'one': {'run_id': 'r', 'session_id': 's', 'state': 'done', 'success': True}}}}
    update_task_summary(raw, state)
    data = json.loads(summary.read_text())
    assert data['task_progress']['success_count'] == 1
    assert data['sample_count'] == 123
    assert data['grasp_outcomes']['success_count'] == 1
    assert raw.read_text() == 'unchanged source'
