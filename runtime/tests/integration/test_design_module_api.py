"""Existing API/GUI hosting of Design's code-owned module, without device I/O."""
import pytest

from test_orchestrator_setup_loop import actual_controller


@pytest.fixture
def design_client(actual_controller, monkeypatch):
    controller, guard = actual_controller
    import app.bootstrap as bootstrap
    monkeypatch.setattr(bootstrap, "load_runtime", lambda: controller)
    from app import main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "controller", controller)
    # No lifespan: this is an in-process request, not a server or polling worker.
    yield TestClient(main.app), controller
    assert guard.physical_call_count == 0


def test_existing_module_and_runtime_api_expose_installed_design(design_client):
    client, controller = design_client
    response = client.get("/api/modules/design")
    assert response.status_code == 200
    payload = response.json()
    installed = payload["implementation"]
    assert installed == controller._deps.agent_registry.get_module("design").describe()
    assert payload["module"]["module"]["handler"] == installed["handler"] == "agent.design_agent"
    manifests = client.get("/api/runtime/agent-manifests").json()
    design = next(item for item in manifests["agents"] if item["id"] == "design")
    assert design["implementation"] == installed


@pytest.mark.parametrize('module_id', ['design', 'orchestrator'])
def test_existing_module_api_exposes_executable_graph_and_owner_catalog(design_client, module_id):
    client, _ = design_client
    response = client.get(f'/api/modules/{module_id}')
    assert response.status_code == 200
    payload = response.json()
    graph = payload['module']['module']['execution_graph']
    assert graph['schema'] == 'ax4lab.execution_graph.v1'
    assert len(graph['nodes']) == 4
    catalog = payload['execution_catalog']
    assert catalog['module_id'] == module_id
    assert catalog['required_outputs'] == ['agent_result']
    operations = {operation['handler']: operation for operation in catalog['operations']}
    assert all(node['handler'] in operations for node in graph['nodes'])
    nodes = {node['id']: node for node in graph['nodes']}
    assert all(edge['on'] in operations[nodes[edge['source']]['handler']]['outcomes'] for edge in graph['edges'])
    assert len(payload['execution_graph_revision']) == 64
    html = client.get('/ide').text
    assert html.index('src="/static/module_control_view.js') < html.index('src="/static/runtime_ide.js')


def test_live_gui_loads_common_module_host_without_eager_design_asset(design_client):
    client, _ = design_client
    response = client.get("/module-assets/design/live_report.js")
    assert response.status_code == 200
    assert "AX4LABDesignUI" in response.text
    html = client.get("/live").text
    assert 'src="/module-assets/design/live_report.js' not in html
    assert html.index('src="/static/agent_module_host.js') < html.index('src="/static/planning.js')
    assert client.get("/module-assets/design/../module.py").status_code == 404


def test_existing_report_endpoint_uses_design_owned_projection(design_client):
    client, controller = design_client
    report = {"candidate_generation": {"candidate_count": 3, "valid_count": 2},
              "candidate_evaluation": {"status": "unassessed"},
              "handoff_to_specimen": {"required_fields_present": False}}
    controller._state.run_metadata["design_report"] = report
    response = client.get("/api/agents/design/report")
    assert response.status_code == 200
    payload = response.json()["report"]["sections"]
    assert payload["role_specific"]["candidate_board"]["candidate_count"] == 3
    assert payload["role_specific"]["handoff_packet"]["required_fields_present"] is False
