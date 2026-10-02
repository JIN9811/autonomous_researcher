"""Registered Specimen API ownership under the existing no-effects guard."""
from copy import deepcopy

import pytest

from tests.integration.test_agent_execution_graph_api import module_api, actual_controller


def test_specimen_module_api_assets_report_and_catalog_use_installed_owner(module_api):
    client, app_main, controller, guard, root = module_api
    payload = client.get("/api/modules/specimen").json()
    assert payload["implementation"] == controller._deps.agent_registry.get_module("specimen").describe()
    assert payload["execution_catalog"]["module_id"] == "specimen"
    assert payload["execution_catalog"]["required_outputs"] == ["agent_result"]
    assert payload["execution_catalog"]["implementation_structure"]["operations"]["specimen.decide"]
    manifest = next(item for item in client.get("/api/runtime/agent-manifests").json()["agents"] if item["id"] == "specimen")
    assert manifest["implementation"]["frontend"]["namespace"] == "AX4LABSpecimenUI"
    asset = client.get(manifest["implementation"]["frontend"]["asset_url"])
    assert asset.status_code == 200 and "AX4LABSpecimenUI" in asset.text
    report = {"digital_thread": {"specimen_id": "current-specimen"}, "quality_gates": [{"status": "blocked"}]}
    controller._state.run_metadata["fabrication_report"] = report
    controller._state.run_metadata["specimen_metrics"] = {"quality": 0}
    response = client.get("/api/agents/specimen/report")
    assert response.status_code == 200
    sections = response.json()["report"]["sections"]
    assert sections["fabrication_report"] == report
    assert sections["role_specific"]["digital_thread"] == {"specimen_id": "current-specimen"}
    assert sections["metrics"] == {"quality": 0}
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
async def test_specimen_saved_graph_controls_real_owner_and_rejects_bypass(module_api, monkeypatch, tmp_path):
    client, app_main, controller, guard, root = module_api
    from agents.specimen.agent import SpecimenMakingAgent
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Mode, Stage
    from tests.unit.test_specimen_agent import _CtxStub, _valid_spec

    payload = client.get("/api/modules/specimen").json()["module"]
    graph = payload["module"]["execution_graph"]
    graph["nodes"].append({"id": "saved_report", "handler": "specimen.finalize", "area": "knowledge"})
    graph["edges"].append({"source": "finalize", "target": "saved_report", "on": "next", "kind": "evidence"})
    graph["terminals"] = ["saved_report" if item == "finalize" else item for item in graph["terminals"]]
    saved = client.put("/api/modules/specimen", json={"module": payload, "activate": True})
    assert saved.status_code == 200 and saved.json()["ok"] is True
    assert saved.json()["activated"] is True
    module = client.get("/api/modules/specimen").json()["module"]["module"]
    preview = client.post("/api/modules/specimen/dry-run").json()
    assert preview["executes_owner_functions"] is False
    assert any(path["nodes"] == ["prepare", "decide", "finalize", "saved_report"] for path in preview["paths"])

    # Only explicitly installed offline tool implementations are admitted below.
    ctx = _CtxStub()
    ctx.active_backend = "controlled"
    ctx.force_real_llm_in_test = False
    ctx.artifact_run_root = tmp_path / "runs"
    state = controller._state
    state.mode = Mode.TEST
    state.stage = Stage.SPECIMEN
    state.current_experiment_spec = {**_valid_spec(), "tpms_resolution": 18}
    monkeypatch.setattr(SpecimenMakingAgent, "_artifact_dir", lambda *args: tmp_path / "geometry")
    events = []
    guard.allowed_tools.update(module["tools"])
    scoped = ModuleRuntimeContext(ctx, module, Stage.SPECIMEN, state=state, execution_event_emitter=events.append)
    result = await controller._deps.agent_registry.get("specimen_agent").run(state, scoped)
    assert result.success and result.data["specimen_result"]["candidate_id"] == "cand-1-01"
    assert [event["payload"]["node_id"] for event in events if event["type"] == "execution.node.completed"] == ["prepare", "decide", "finalize", "saved_report"]
    active = (root / "specimen/module.yaml").read_bytes()
    bad = deepcopy(payload)
    for edge in bad["module"]["execution_graph"]["edges"]:
        if edge["source"] == "prepare" and edge["on"] == "ready":
            edge["target"] = "finalize"
    rejected = client.put("/api/modules/specimen", json={"module": bad, "activate": True})
    assert rejected.json()["ok"] is False
    assert (root / "specimen/module.yaml").read_bytes() == active
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_supervised_specimen_runtime_preserves_vision_route_and_failed_status(actual_controller, tmp_path, monkeypatch, success):
    """Keep the real supervisor admission that the older isolated fixture lacks."""
    from agents.base_agent import AgentResult
    from logging_system.structured_logger import StructuredLogger
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Mode, Stage
    from tests.unit.test_specimen_agent import _valid_spec
    from tests.unit.test_specimen_execution_status import specimen_data

    controller, guard = actual_controller
    state = controller._state
    state.mode, state.stage = Mode.TEST, Stage.SPECIMEN
    state.current_experiment_spec = {**_valid_spec(), "specimen_id": "specimen-1", "printer_test_path": "installed_printer"}
    owner = controller._deps.agent_registry.get("specimen_agent")
    received = []
    async def recorded_result(state, ctx):
        received.append(state.stage)
        return AgentResult(success=success, summary="Controlled fabrication outcome", data=specimen_data())
    monkeypatch.setattr(owner, "run", recorded_result)
    events = []
    runtime = LangGraphRunLoop(state=state, agent_registry=controller._deps.agent_registry,
        orchestrator_agent_name=controller._deps.orchestrator_agent_name, ctx=controller._deps.agent_context,
        logger=StructuredLogger(tmp_path / "status.jsonl", tmp_path / "status.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml", on_event=events.append)
    await runtime.step()
    assert received == [Stage.SPECIMEN]
    assert state.agent_status["specimen_agent"].state == ("running" if success else "error")
    if success:
        assert state.stage == Stage.VISION
    result = next(event for event in events if event["event_type"] == "agent_result")
    assert result["payload"]["status"] == ("running" if success else "error")
    assert guard.physical_call_count == 0
