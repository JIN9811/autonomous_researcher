"""Vision presentation and saved execution use the installed owner, without hardware."""
from copy import deepcopy

import pytest

from tests.integration.test_agent_execution_graph_api import module_api, actual_controller


def test_vision_module_assets_and_report_observation_precedence(module_api):
    client, app_main, controller, guard, root = module_api
    manifest = next(x for x in client.get('/api/runtime/agent-manifests').json()['agents'] if x['id'] == 'vision')
    frontend = manifest['implementation'].get('frontend', {})
    assert frontend.get('namespace') == 'AX4LABVisionUI'
    assert client.get(frontend['asset_url']).status_code == 200
    state = controller._state
    state.run_metadata.update({'latest_vision_observation': {'vision_report': {'scene_map': {'old': {}}}},
        'vision_metrics': {'confidence': 0}})
    state.latest_observations = {'vision_report': {'scene_map': {'current': {}}, 'events': [{'status': 'fresh'}]},
        'vision_agent_report': {'status': 'current'}, 'vision_signal': {'decisions': [{'decision': 'wait'}]}}
    before = deepcopy(state.run_metadata)
    sections = client.get('/api/agents/vision/report').json()['report']['sections']
    assert sections['vision_report']['scene_map'] == {'current': {}}
    assert sections['vision_agent_report'] == {'status': 'current'}
    assert sections['role_specific']['evidence_timeline'] == [{'status': 'fresh'}]
    assert sections['metrics'] == {'confidence': 0}
    assert sections['role_specific']['handoff_packet']['decisions'] == [{'decision': 'wait'}]
    assert state.run_metadata['latest_vision_observation'] == before['latest_vision_observation']
    assert '_projection_state' not in state.run_metadata
    state.run_metadata['vision_report'] = {'scene_map': {'explicit': {}}}
    assert client.get('/api/agents/vision/report').json()['report']['sections']['vision_report']['scene_map'] == {'explicit': {}}
    assert guard.physical_call_count == 0


def test_inactive_vision_cannot_execute_or_serve_frontend(module_api):
    client, app_main, controller, guard, root = module_api
    registry = controller._deps.agent_registry
    active = set(registry.active_names()) - {'vision_agent'}
    registry.bind_activation(lambda: active)
    with pytest.raises(KeyError, match='inactive'):
        registry.get('vision_agent')
    assert client.get('/module-assets/vision/live_report.js').status_code == 404


@pytest.mark.asyncio
async def test_api_saved_vision_graph_executes_registered_owner(module_api, monkeypatch, tmp_path):
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Stage
    from tests.unit.test_vision_module import context
    client, app_main, controller, guard, root = module_api
    payload = client.get('/api/modules/vision').json()['module']
    graph = payload['module']['execution_graph']
    for node in graph['nodes']:
        if node['id'] == 'observe': node['id'] = 'saved_observation'
    for edge in graph['edges']:
        for key in ('source', 'target'):
            if edge[key] == 'observe': edge[key] = 'saved_observation'
    saved = client.put('/api/modules/vision', json={'module': payload, 'activate': True})
    assert saved.status_code == 200 and saved.json()['activated'] is True
    module = client.get('/api/modules/vision').json()['module']['module']
    ctx, state = context(tmp_path, monkeypatch)
    ctx.active_backend = 'controlled'
    ctx.force_real_llm_in_test = False
    guard.allowed_tools.update(module['tools'])
    events = []
    scoped = ModuleRuntimeContext(ctx, module, Stage.VISION, state=state, execution_event_emitter=events.append)
    result = await controller._deps.agent_registry.get('vision_agent').run(state, scoped)
    assert result.success and result.data['observation']['transfer_readiness']['ready'] is True
    assert [x['payload']['node_id'] for x in events if x['type'] == 'execution.node.completed'] == ['prepare', 'saved_observation', 'deliver']
    assert guard.physical_call_count == 0
