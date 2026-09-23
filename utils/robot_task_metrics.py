"""Read-only compatibility for parents predating the task-ledger projection.

No control API or state mutation. New parents supply the ledger directly and
never use the HTTP compatibility reader.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler


TASK_KEYS = ('manipulation_task_progress', 'initial_manipulation_execution',
             'manipulation_execution', 'utm_clear_execution')


def update_task_summary(log_path, state):
    """Refresh derived display evidence only; never touch raw logs or ledgers."""
    from utils.manipulation_execution import task_progress_counts
    path = Path(log_path).parent / 'grasp_display_v5' / 'policy_tracking_summary.json'
    if not path.is_file() or not state.get('run_id'):
        return
    summary = json.loads(path.read_text())
    counts = task_progress_counts(state)
    if summary.get('task_progress') == counts and summary.get('task_progress_run_id') == state['run_id']:
        return
    summary.update(task_progress=counts, task_progress_run_id=state['run_id'])
    pending = path.with_suffix('.json.tmp')
    pending.write_text(json.dumps(summary, indent=2, sort_keys=True))
    pending.replace(path)


def merge_task_state(state, snapshot):
    if (state.get('task_progress_projection_version') == 1 or not state.get('run_id')
            or snapshot.get('run_id') != state['run_id']):
        return state
    source = snapshot.get('run_metadata') or {}
    metadata = dict(state.get('run_metadata') or {})
    metadata.update({key: source[key] for key in TASK_KEYS if isinstance(source.get(key), dict)})
    return {**state, 'run_metadata': metadata}


def read_task_state(origins):
    # Configuration comes from the parent's private pipe, not a browser request.
    origin = next((o for o in origins if urlsplit(o).hostname == '127.0.0.1'
                   and urlsplit(o).scheme == 'http'), None)
    if not origin:
        return {}
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(origin.rstrip('/') + '/api/state', timeout=3) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError('Task ledger snapshot exceeds read limit')
    state = json.loads(raw).get('state') or {}
    metadata = state.get('run_metadata') or {}
    return {'run_id': state.get('run_id'), 'run_metadata': {
        key: metadata[key] for key in TASK_KEYS if isinstance(metadata.get(key), dict)}}
