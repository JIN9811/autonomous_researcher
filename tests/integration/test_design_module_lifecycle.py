"""Applied IDE graph changes must control Design without operating any device."""
from copy import deepcopy
import asyncio
from pathlib import Path
import shutil

import pytest

from test_orchestrator_setup_loop import actual_controller


@pytest.fixture
def lifecycle(actual_controller, monkeypatch, tmp_path):
    controller, guard = actual_controller
    import app.bootstrap as bootstrap
    monkeypatch.setattr(bootstrap, "load_runtime", lambda: controller)
    from app import main
    from fastapi.testclient import TestClient
    source = Path(__file__).resolve().parents[2] / "graphs"
    graph_root = tmp_path / "graphs"
    shutil.copytree(source, graph_root)
    monkeypatch.setattr(main, "controller", controller)
    monkeypatch.setattr(main, "RUNTIME_GRAPH_CONFIG_ROOT", graph_root / "configs")
    monkeypatch.setattr(main, "RUNTIME_GRAPH_CONFIG_PATH", graph_root / "configs/atr_closed_loop.yaml")
    monkeypatch.setattr(main, "RUNTIME_MODULE_ROOT", graph_root / "modules")
    monkeypatch.setattr(main, "RUNTIME_GRAPH_VERSION_ROOT", tmp_path / "graph_versions")
    monkeypatch.setattr(main, "RUNTIME_MODULE_VERSION_ROOT", tmp_path / "module_versions")
    controller._active_graph_config_path = graph_root / "configs/atr_closed_loop.yaml"
    original = main._load_runtime_graph_config("atr_closed_loop").model_dump(mode="json")
    yield TestClient(main.app), controller, original, graph_root
    assert guard.physical_call_count == 0 and not guard.denied


def without_design(original):
    """Operator removes Design and explicitly connects Guardian to completion."""
    graph = deepcopy(original)
    graph["nodes"] = [node for node in graph["nodes"] if node["id"] != "design"]
    graph["stage_dispatch"].pop("design")
    graph["transitions"] = {key: value for key, value in graph["transitions"].items()
                            if key != "design" and value != "design"}
    graph["edges"] = [edge for edge in graph["edges"]
                      if edge["source"] != "design" and edge["target"] != "design"
                      and edge.get("metadata", {}).get("from_stage") != "design"
                      and edge.get("metadata", {}).get("to_stage") != "design"]
    graph["transitions"]["guardian"] = "complete"
    continuation = deepcopy(next(edge for edge in original["edges"]
                                 if edge.get("metadata", {}).get("from_stage") == "guardian"
                                 and edge.get("metadata", {}).get("to_stage") == "design"))
    continuation["target"] = "complete"
    continuation["metadata"]["to_stage"] = "complete"
    graph["edges"].append(continuation)
    return graph


def active_ids(client):
    response = client.get("/api/runtime/agent-manifests")
    assert response.status_code == 200
    return {item["id"] for item in response.json()["agents"]}


def apply(client, graph, activate=True):
    response = client.put("/api/graphs/atr_closed_loop", json={"graph": graph, "activate": activate})
    assert response.status_code == 200, response.text
    assert response.json()["ok"], response.text
    return response.json()


def test_ide_remove_and_readd_reconciles_execution_gui_and_owner_without_deleting_data(lifecycle, tmp_path):
    client, controller, original, graph_root = lifecycle
    registry = controller._deps.agent_registry
    instance = registry.get("design_agent")
    archive = tmp_path / "retained-result.json"
    archive.write_text('{"historical":true}')
    before_config = (graph_root / "modules/design/module.yaml").read_bytes()
    assert "design" in active_ids(client)
    apply(client, without_design(original))
    assert "design" not in active_ids(client)
    assert "design" not in {item["agent_id"] for item in client.get("/api/agents").json()["agents"]}
    assert "design_agent" not in {row["owner"] for row in controller._planning_setup_catalog().bindings()}
    assert registry.get_installed("design_agent") is instance
    with pytest.raises(KeyError, match="inactive"):
        registry.get("design_agent")
    assert client.get("/api/agents/design/report").status_code == 404
    assert client.get("/module-assets/design/live_report.js").status_code == 404
    module_response = client.get("/api/modules/design")
    assert module_response.status_code == 200
    module_payload = module_response.json()
    assert module_payload["execution_catalog"]["module_id"] == "design"
    assert module_payload["execution_catalog"]["required_outputs"] == ["agent_result"]
    assert len(module_payload["execution_graph_revision"]) == 64
    assert archive.read_text() == '{"historical":true}'
    assert (graph_root / "modules/design/module.yaml").read_bytes() == before_config
    apply(client, original)
    assert "design" in active_ids(client)
    assert registry.get("design_agent") is instance
    assert client.get("/api/agents/design/report").status_code == 200
    assert client.get("/module-assets/design/live_report.js").status_code == 200


def test_validate_draft_previews_owner_delta_without_applying_it(lifecycle):
    client, _, original, _ = lifecycle
    response = client.post("/api/graphs/atr_closed_loop/validate-draft",
                           json={"graph": without_design(original), "activate": False})
    assert response.status_code == 200 and response.json()["ok"]
    impact = response.json()["module_lifecycle"]
    assert impact["removed"] == ["design_agent"]
    assert impact["added"] == []
    assert "design_agent" in impact["applied"]
    assert "design_agent" not in impact["draft"]
    assert impact["history_preserved"] and not impact["running"]
    assert "design" in active_ids(client)


def test_draft_and_invalid_activation_never_change_membership(lifecycle):
    client, _, original, _ = lifecycle
    apply(client, without_design(original), activate=False)
    assert "design" in active_ids(client)
    invalid = deepcopy(original)
    next(node for node in invalid["nodes"] if node["id"] == "design")["handler"] = "agent.uninstalled_agent"
    response = client.put("/api/graphs/atr_closed_loop", json={"graph": invalid, "activate": True})
    assert response.status_code == 200 and response.json()["ok"] is False
    assert "design" in active_ids(client)


def test_running_activation_is_rejected_without_partial_change(lifecycle, monkeypatch):
    client, controller, original, _ = lifecycle
    snapshot = controller.snapshot
    monkeypatch.setattr(controller, "snapshot", lambda: {**snapshot(), "is_running": True})
    response = client.put("/api/graphs/atr_closed_loop", json={"graph": without_design(original), "activate": True})
    assert response.status_code == 409
    assert "design" in active_ids(client)


def test_removed_design_rejects_direct_planning_before_any_tool(lifecycle):
    client, controller, original, _ = lifecycle
    apply(client, without_design(original))
    result = asyncio.run(controller._handoff_planning_to_design(goal="Generate a candidate", constraints={}))
    assert result["failure_code"] == "DESIGN_MODULE_INACTIVE"


def test_renamed_graph_node_keeps_module_attached_and_manifest_unique(lifecycle):
    client, controller, original, _ = lifecycle
    graph = deepcopy(original)
    design = next(node for node in graph["nodes"] if node["id"] == "design")
    design["id"] = "design_reference"
    graph["stage_dispatch"]["design"] = "design_reference"
    for edge in graph["edges"]:
        for key in ("source", "target"):
            if edge[key] == "design":
                edge[key] = "design_reference"
    apply(client, graph)
    assert "design_agent" in controller._deps.agent_registry.active_names()
    manifests = client.get("/api/runtime/agent-manifests").json()["agents"]
    assert sum(item["id"] == "design" for item in manifests) == 1


def test_pre_execution_owner_keeps_its_frontend_without_a_standalone_node(lifecycle):
    import yaml
    client, controller, original, graph_root = lifecycle
    path = graph_root / "modules/specimen/module.yaml"
    payload = yaml.safe_load(path.read_text())
    payload["module"].setdefault("pre_execution", []).append(
        {"id": "design_precheck", "handler": "agent.design_agent", "enabled": True})
    path.write_text(yaml.safe_dump(payload))
    apply(client, without_design(original))
    assert "design_agent" in controller._deps.agent_registry.active_names()
    manifests = client.get("/api/runtime/agent-manifests").json()["agents"]
    design = next(item for item in manifests if item["id"] == "design")
    assert design["handler"] == "agent.design_agent"
    assert design["implementation"]["id"] == "design"
    assert design["activation"]["role"] == "pre_execution"
    assert design["stage"] == "design"
    assert design["graph_stage"] == "specimen"
    controller._state.run_metadata["design_agent_payload"] = {
        "design_report": {"candidate_generation": {"candidate_count": 7}}}
    report = client.get("/api/agents/design/report").json()["report"]
    assert report["role_specific"]["candidate_board"]["candidate_count"] == 7
    from app import main
    assert not main._event_matches_agent(
        {"event_type": "node.completed", "message": "Fabrication done",
         "payload": {"agent": "specimen", "stage": "specimen"}}, main._agent_definition("design"))


def test_editor_load_does_not_reactivate_excluded_module(lifecycle):
    client, controller, original, _ = lifecycle
    registry = controller._deps.agent_registry
    installed = registry.get("design_agent")
    apply(client, without_design(original))
    response = client.post("/api/modules/design/load")
    assert response.status_code == 200
    assert not response.json()["runtime_effect"]["changes_runtime_execution"]
    assert "design" not in active_ids(client)
    assert registry.get_installed("design_agent") is installed
    with pytest.raises(KeyError, match="inactive"):
        registry.get("design_agent")
    module_payload = client.get("/api/modules/design").json()
    assert module_payload["execution_catalog"]["module_id"] == "design"
    assert len(module_payload["execution_graph_revision"]) == 64
    client.post("/api/modules/design/unload")


@pytest.mark.parametrize("handler", ["runtime.step_complete", "module.generated_adapter"])
def test_attached_non_agent_module_retains_metadata_without_design_execution_admission(lifecycle, handler):
    import yaml
    client, controller, _, graph_root = lifecycle
    registry = controller._deps.agent_registry
    installed = registry.get_module("design").describe()
    path = graph_root / "modules/design/module.yaml"
    payload = yaml.safe_load(path.read_text())
    payload["module"]["handler"] = handler
    payload["module"]["pre_execution"] = []
    path.write_text(yaml.safe_dump(payload))
    # Read applied module config only: this test never executes an adapter.
    manifests = client.get("/api/runtime/agent-manifests").json()["agents"]
    design = next(item for item in manifests if item["id"] == "design")
    assert design["handler"] == handler
    # Implementation describes installed code, not admission to execute it.
    assert design["implementation"] == installed
    assert design["activation"]["included"] is True
    assert design["activation"]["owner"] == ""
    assert "design_agent" not in registry.active_names()
    with pytest.raises(KeyError, match="inactive"):
        registry.get("design_agent")
    assert client.get("/module-assets/design/live_report.js").status_code == 404
