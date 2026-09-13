"""Installed Manipulation frontend admission over the guarded actual API."""
from tests.integration.test_agent_execution_graph_api import module_api, actual_controller


def test_manipulation_frontend_manifest_asset_and_deactivation(module_api):
    client, _, controller, guard, _ = module_api
    manifest = next(x for x in client.get('/api/runtime/agent-manifests').json()['agents'] if x['id'] == 'manipulation')
    frontend = manifest['implementation'].get('frontend', {})
    assert frontend.get('namespace') == 'AX4LABManipulationUI'
    assert manifest['renderer']['dashboard'] == 'module'
    response = client.get(frontend['asset_url'])
    assert response.status_code == 200
    assert 'AX4LABManipulationUI' in response.text
    registry = controller._deps.agent_registry
    active = set(registry.active_names()) - {'manipulation_agent'}
    registry.bind_activation(lambda: active)
    assert client.get(frontend['asset_url']).status_code == 404
    assert guard.physical_call_count == 0
    assert guard.denied == []
