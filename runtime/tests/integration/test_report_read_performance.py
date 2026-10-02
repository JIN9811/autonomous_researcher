"""Read-only optimization contracts, including independent/new browser clients."""
import ast
import inspect
from importlib import import_module

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_agent_execution_graph_api import actual_controller, module_api

OWNERS = ('design', 'specimen', 'vision', 'manipulation', 'equipment', 'analysis', 'bo', 'knowledge', 'guardian')


@pytest.mark.parametrize('owner', OWNERS)
def test_declared_projection_inputs_cover_all_direct_metadata_reads(owner):
    module = import_module(f'agents.{"core." if owner in {"knowledge", "guardian"} else ""}{owner}.presentation')
    tree = ast.parse(inspect.getsource(module))
    keys = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'metadata'
                and node.func.attr == 'get' and node.args and isinstance(node.args[0], ast.Constant)):
            keys.add(node.args[0].value)
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id == 'metadata' and isinstance(node.slice, ast.Constant)):
            keys.add(node.slice.value)
    assert keys - set(module.REPORT_METADATA_KEYS) <= {'_projection_state', '_objective_status', '_objective_registry', '_relation_reconciliation'}


def test_refresh_new_window_and_new_run_use_latest_detached_data(module_api, monkeypatch):
    client, main, controller, guard, _ = module_api
    controller._ensure_orchestrator_supervisor_baseline()
    # A huge/unserializable history must not be visited by report serialization.
    controller._state.run_metadata['unused_history'] = object()
    def forbidden():
        raise AssertionError('Report copied the full runtime/planning state')
    monkeypatch.setattr(controller, 'snapshot', forbidden)
    monkeypatch.setattr(controller, 'planning_snapshot', forbidden)
    for owner in OWNERS + ('orchestrator',):
        response = client.get(f'/api/agents/{owner}/report')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
    controller._state.run_metadata['manipulation_report'] = {'task': {'task_id': 'first'}}
    first = client.get('/api/agents/manipulation/report').json()
    controller._state.run_metadata['manipulation_report']['task']['task_id'] = 'new-frame'
    second = TestClient(main.app).get('/api/agents/manipulation/report').json()
    assert first['report']['role_specific']['task']['task_id'] == 'first'
    assert second['report']['role_specific']['task']['task_id'] == 'new-frame'
    detached = main._agent_report_payload('manipulation')
    detached['role_specific']['task']['task_id'] = 'client-mutated'
    assert controller._state.run_metadata['manipulation_report']['task']['task_id'] == 'new-frame'
    controller._state.run_id = 'new-run-window'
    refreshed = client.get('/api/agents/manipulation/report').json()['report']
    assert refreshed['run_id'] == 'new-run-window'
    assert not guard.denied


def test_unknown_plugin_keeps_full_input_compatibility():
    from types import SimpleNamespace
    from app.report_snapshot import report_snapshot
    sentinel = {'state': {'plugin_private_field': True}}
    controller = SimpleNamespace(snapshot=lambda: sentinel)
    assert report_snapshot(controller, {'agent_id': 'extension'}, None) is sentinel


def test_new_window_reads_changed_module_descriptor_without_restart(module_api):
    import yaml
    client, main, controller, guard, root = module_api
    path = root / 'design' / 'ui.yaml'
    first = client.get('/api/modules/design/ui')
    assert first.status_code == 200
    descriptor = yaml.safe_load(path.read_text())
    ui = descriptor.get('ui', descriptor)
    ui['title'] = 'Fresh descriptor after settings save'
    path.write_text(yaml.safe_dump(descriptor))
    updated = TestClient(main.app).get('/api/modules/design/ui')
    assert updated.status_code == 200
    assert 'Fresh descriptor after settings save' in updated.text
    assert not guard.denied


@pytest.mark.parametrize('owner', OWNERS + ('orchestrator',))
def test_selective_snapshot_matches_legacy_report(module_api, monkeypatch, owner):
    client, main, controller, guard, _ = module_api
    import app.report_snapshot as snapshots
    # Baseline initialization is shared; compare report data, not regenerated IDs.
    controller.planning_snapshot()
    optimized = main._agent_report_payload(owner)
    monkeypatch.setattr(snapshots, 'report_snapshot', lambda c, *_: c.snapshot())
    legacy = main._agent_report_payload(owner)
    assert optimized == legacy
    assert not guard.denied
