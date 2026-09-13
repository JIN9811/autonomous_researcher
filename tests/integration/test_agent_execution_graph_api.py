"""Guarded API integration for executable agent-module definitions."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

# The imported fixture installs VerificationGuard before bootstrapping the app.
from tests.integration.test_orchestrator_setup_loop import actual_controller as actual_controller


@pytest.fixture
def module_api(actual_controller, tmp_path, monkeypatch):
    controller, guard = actual_controller
    import app.main as app_main

    module_root = tmp_path / "isolated-graphs" / "modules"
    shutil.copytree(Path("graphs/modules"), module_root)
    monkeypatch.setattr(app_main, "controller", controller)
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_ROOT", module_root)
    monkeypatch.setattr(app_main, "RUNTIME_MODULE_VERSION_ROOT", tmp_path / "module-versions")
    return TestClient(app_main.app), app_main, controller, guard, module_root


def _reversed_orchestrator_payload(client: TestClient) -> dict:
    response = client.get("/api/modules/orchestrator")
    assert response.status_code == 200
    payload = response.json()["module"]
    graph = payload["module"]["execution_graph"]
    decision_edges = [edge for edge in graph["edges"] if edge["source"] == "decide"]
    graph["entry"] = "plan"
    graph["edges"] = [
        {"source": "plan", "target": "mission", "on": "next", "kind": "execution"},
        {"source": "mission", "target": "decide", "on": "next", "kind": "execution"},
        *decision_edges,
    ]
    return payload


@pytest.mark.parametrize('module_id', ['analysis', 'bo', 'guardian', 'knowledge'])
def test_legacy_module_api_delivers_control_view_without_converting_execution(module_api, module_id):
    client, _, _, guard, root = module_api
    installed = yaml.safe_load((root / module_id / 'module.yaml').read_text())['module']
    response = client.get(f'/api/modules/{module_id}')
    assert response.status_code == 200
    delivered = response.json()['module']['module']
    assert delivered['metadata']['control_view'] == installed['metadata']['control_view']
    assert delivered['internal_graph'] == installed['internal_graph']
    assert not delivered.get('execution_graph')
    assert guard.physical_call_count == 0


def test_equipment_installed_report_projection_and_graph(module_api):
    client, _, controller, guard, _ = module_api
    response = client.get("/api/modules/equipment").json()
    assert {operation["handler"] for operation in response["execution_catalog"]["operations"]} == {
        "equipment.task", "equipment.deliver"
    }
    assert len(response["execution_graph_revision"]) == 64
    state = controller._state
    state.run_metadata.update(
        equipment_report={
            "bridge": {"provider": "windows_pyautogui"},
            "control_plan": {"program_id": "utm_cycle"},
            "screen_checks": [],
            "decision": {"handoff_status": "blocked"},
        },
        equipment_result={"status": "blocked", "failure_code": "PREFLIGHT"},
        equipment_handoff={"status": "blocked"},
        equipment_metrics={"rows": 0},
    )
    before = deepcopy(state.run_metadata)
    report = client.get("/api/agents/equipment/report")
    assert report.status_code == 200
    sections = report.json()["report"]["sections"]
    assert sections["equipment_report"]["control_plan"] == {"program_id": "utm_cycle"}
    assert sections["equipment_result"]["failure_code"] == "PREFLIGHT"
    assert sections["equipment_handoff"] == {"status": "blocked"}
    assert sections["role_specific"]["control_trace"]["program_id"] == "utm_cycle"
    assert sections["metrics"] == {"rows": 0}
    assert {key: state.run_metadata[key] for key in before} == before
    assert "_projection_state" not in state.run_metadata
    assert guard.physical_call_count == 0


def test_manipulation_installed_report_projection_and_graph(module_api):
    client, _, controller, guard, _ = module_api
    response = client.get("/api/modules/manipulation").json()
    assert {op["handler"] for op in response["execution_catalog"]["operations"]} == {
        "manipulation.task", "manipulation.deliver"}
    assert len(response["execution_graph_revision"]) == 64
    state = controller._state
    state.run_metadata.update(manipulation_report={"task": {"task_id": "transfer_to_utm"},
        "rollout_runtime": {"action_count": 7}}, latest_manipulation_agent_report={"status": "running"},
        robot_task_result={"handoff_status": "needs_post_place_vision", "decisions": []},
        manipulation_metrics={"action_count": 0})
    before = deepcopy(state.run_metadata)
    report = client.get("/api/agents/manipulation/report")
    assert report.status_code == 200
    sections = report.json()["report"]["sections"]
    assert sections["manipulation_report"]["task"] == {"task_id": "transfer_to_utm"}
    assert sections["manipulation_agent_report"] == {"status": "running"}
    assert sections["role_specific"]["rollout_runtime"] == {"action_count": 7}
    assert sections["metrics"] == {"action_count": 0}
    assert {key: state.run_metadata[key] for key in before} == before
    assert "_projection_state" not in state.run_metadata
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
async def test_saved_manipulation_graph_uses_registered_archived_owner(module_api, tmp_path, monkeypatch):
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Stage
    from tests.unit.test_manipulation_module_contract import BoundaryTools
    from tests.unit.test_manipulation_lerobot_agent import _state, _CtxStub, _isolate_manipulation_profile
    client, _, controller, guard, _ = module_api
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    payload = client.get("/api/modules/manipulation").json()["module"]
    graph = payload["module"]["execution_graph"]
    graph["nodes"][0]["id"] = "saved_task"
    graph["entry"] = "saved_task"
    graph["edges"][0]["source"] = "saved_task"
    saved = client.put("/api/modules/manipulation", json={"module": payload, "activate": True})
    assert saved.status_code == 200 and saved.json()["activated"] is True
    loaded = client.get("/api/modules/manipulation").json()
    module = loaded["module"]["module"]
    ctx, state = _CtxStub(BoundaryTools()), _state()
    ctx.active_backend = "controlled"
    ctx.force_real_llm_in_test = False
    ctx.artifact_run_root = tmp_path / "runs"
    events = []
    scoped = ModuleRuntimeContext(ctx, module, Stage.MANIPULATION, state=state,
        execution_event_emitter=events.append)
    result = await controller._deps.agent_registry.get("manipulation_agent").run(state, scoped)
    assert result.success and result.data["requested_next_stage"] == "vision"
    assert result.data["artifact_execution"]
    assert [event["payload"]["node_id"] for event in events
        if event["type"] == "execution.node.completed"] == ["saved_task", "deliver"]
    assert all(event["payload"]["graph_revision"] == loaded["execution_graph_revision"] for event in events)
    assert [name for name, _ in ctx.tools.calls] == ["lerobot.rollout.start"]
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
async def test_get_save_reload_and_real_owner_execution_share_edited_edges(module_api, monkeypatch):
    """A valid API edge edit must change actual registered owner operation order."""
    client, app_main, controller, guard, module_root = module_api
    from agents import orchestrator_execution as owner
    from agents.orchestrator_agent import OrchestratorAgent
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Stage

    initial = client.get("/api/modules/orchestrator").json()
    assert initial["execution_catalog"]["schema"] == "ax4lab.execution_catalog.v1"
    assert len(initial["execution_graph_revision"]) == 64
    assert {item["handler"] for item in initial["execution_catalog"]["operations"]} == {
        "orchestrator.mission", "orchestrator.plan", "orchestrator.decide", "orchestrator.report"
    }
    payload = _reversed_orchestrator_payload(client)
    saved = client.put(
        "/api/modules/orchestrator",
        json={"module": payload, "reason": "edge-order-integration", "author": "pytest", "activate": True},
    )
    assert saved.status_code == 200
    assert saved.json()["ok"] is True
    assert saved.json()["activated"] is True

    reloaded = client.get("/api/modules/orchestrator").json()
    assert reloaded["module"]["module"]["execution_graph"]["entry"] == "plan"
    preview = client.post("/api/modules/orchestrator/dry-run").json()
    assert preview["ok"] is True
    assert preview["mode"] == "structural_preview"
    assert preview["executes_owner_functions"] is False
    assert preview["graph_revision"] == reloaded["execution_graph_revision"]
    assert preview["paths"][0]["nodes"] == ["plan", "mission", "decide", "report"]

    calls: list[str] = []
    original_mission = owner.build_mission_contract
    original_plan = owner.build_orchestration_plan

    def mission(**kwargs):
        calls.append("mission")
        return original_mission(**kwargs)

    def plan(**kwargs):
        calls.append("plan")
        return original_plan(**kwargs)

    monkeypatch.setattr(owner, "build_mission_contract", mission)
    monkeypatch.setattr(owner, "build_orchestration_plan", plan)
    module = reloaded["module"]["module"]
    ctx = ModuleRuntimeContext(
        controller._deps.agent_context,
        module,
        Stage("orchestrator"),
        state=controller._state,
    )

    result = await OrchestratorAgent().run(controller._state, ctx)

    assert result.data["orchestration_decision"]["status"] == "deferred"
    assert calls == ["plan", "mission"]
    assert guard.physical_call_count == 0


def test_invalid_or_busy_save_never_changes_active_module_bytes(module_api, monkeypatch):
    """Validation and busy checks must happen before active module replacement."""
    client, app_main, controller, guard, module_root = module_api
    active_path = module_root / "orchestrator" / "module.yaml"
    before = active_path.read_bytes()
    invalid = _reversed_orchestrator_payload(client)
    invalid["module"]["execution_graph"]["nodes"][0]["handler"] = "python.arbitrary_import"

    rejected = client.put(
        "/api/modules/orchestrator",
        json={"module": invalid, "reason": "invalid-handler", "author": "pytest", "activate": True},
    )

    assert rejected.status_code == 200
    assert rejected.json()["ok"] is False
    assert "unknown handler" in " ".join(rejected.json()["errors"])
    assert active_path.read_bytes() == before

    dual_source = _reversed_orchestrator_payload(client)
    dual_source["module"]["internal_graph"] = [
        {"id": "phantom", "label": "Must not run", "kind": "internal_step"},
    ]
    rejected_dual_source = client.put(
        "/api/modules/orchestrator",
        json={"module": dual_source, "reason": "dual-source", "author": "pytest", "activate": True},
    )
    assert rejected_dual_source.status_code == 200
    assert rejected_dual_source.json()["ok"] is False
    assert "must be empty when execution_graph" in " ".join(rejected_dual_source.json()["errors"])
    assert active_path.read_bytes() == before

    missing_graph = _reversed_orchestrator_payload(client)
    missing_graph["module"].pop("execution_graph")
    rejected_missing_graph = client.put(
        "/api/modules/orchestrator",
        json={"module": missing_graph, "reason": "missing-graph", "author": "pytest", "activate": True},
    )
    assert rejected_missing_graph.status_code == 200
    assert rejected_missing_graph.json()["ok"] is False
    assert "execution_graph is required" in " ".join(rejected_missing_graph.json()["errors"])
    assert active_path.read_bytes() == before

    mismatched_owner = _reversed_orchestrator_payload(client)
    mismatched_owner["module"]["handler"] = "agent.guardian_agent"
    rejected_mismatched_owner = client.put(
        "/api/modules/orchestrator",
        json={"module": mismatched_owner, "reason": "mismatched-owner", "author": "pytest", "activate": True},
    )
    assert rejected_mismatched_owner.status_code == 200
    assert rejected_mismatched_owner.json()["ok"] is False
    assert "handler must remain agent.orchestrator_agent" in " ".join(rejected_mismatched_owner.json()["errors"])
    assert active_path.read_bytes() == before

    missing_result = _reversed_orchestrator_payload(client)
    missing_result["module"]["execution_graph"] = {
        "schema": "ax4lab.execution_graph.v1",
        "entry": "mission",
        "nodes": [{"id": "mission", "handler": "orchestrator.mission", "area": "middle"}],
        "edges": [],
        "terminals": ["mission"],
    }
    rejected_missing_result = client.put(
        "/api/modules/orchestrator",
        json={"module": missing_result, "reason": "missing-result", "author": "pytest", "activate": True},
    )
    assert rejected_missing_result.status_code == 200
    assert rejected_missing_result.json()["ok"] is False
    assert "terminal" in " ".join(rejected_missing_result.json()["errors"])
    assert "agent_result" in " ".join(rejected_missing_result.json()["errors"])
    assert active_path.read_bytes() == before

    monkeypatch.setattr(controller, "snapshot", lambda: {"is_running": True})
    busy = client.put(
        "/api/modules/orchestrator",
        json={"module": deepcopy(_reversed_orchestrator_payload(client)), "activate": True},
    )
    assert busy.status_code == 409
    assert active_path.read_bytes() == before
    assert guard.physical_call_count == 0


def test_controller_snapshot_survives_into_later_real_run_loops(actual_controller, tmp_path):
    """Editing module YAML after controller pinning must not change later loop contexts."""
    controller, guard = actual_controller
    from agents.design.execution import design_execution_catalog
    from agents.execution_graph import compile_execution_graph
    from agents.orchestrator_execution import orchestrator_execution_catalog
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Stage

    graph_root = tmp_path / "pinned-graph"
    shutil.copytree(Path("graphs/modules"), graph_root / "modules")
    (graph_root / "configs").mkdir(parents=True)
    shutil.copy2(Path("graphs/configs/atr_closed_loop.yaml"), graph_root / "configs" / "atr_closed_loop.yaml")
    controller._active_graph_config_path = graph_root / "configs" / "atr_closed_loop.yaml"
    controller._owner_catalog_run_id = None

    first_loop = controller._new_execution_run_loop(interval_seconds=0.0, on_event=None)
    first_design_ctx = first_loop._context_for_stage(Stage.DESIGN)
    first_design_compiled = compile_execution_graph(
        first_design_ctx.runtime_module_config()["execution_graph"],
        design_execution_catalog(controller._deps.agent_registry.get("design_agent")),
    )
    first_ctx = first_loop._context_for_owner(controller._deps.orchestrator_agent_name, Stage.DESIGN)
    first_graph = first_ctx.runtime_module_config()["execution_graph"]
    first_compiled = compile_execution_graph(
        first_graph,
        orchestrator_execution_catalog(
            controller._deps.agent_registry.get(controller._deps.orchestrator_agent_name),
            context=None,
            handlers=None,
        ),
    )
    assert first_compiled.entry == "mission"

    module_path = graph_root / "modules" / "orchestrator" / "module.yaml"
    source = yaml.safe_load(module_path.read_text(encoding="utf-8"))
    edited = source["module"]["execution_graph"]
    decision_edges = [edge for edge in edited["edges"] if edge["source"] == "decide"]
    edited["entry"] = "plan"
    edited["edges"] = [
        {"source": "plan", "target": "mission", "on": "next", "kind": "execution"},
        {"source": "mission", "target": "decide", "on": "next", "kind": "execution"},
        *decision_edges,
    ]
    module_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    design_path = graph_root / "modules" / "design" / "module.yaml"
    design_source = yaml.safe_load(design_path.read_text(encoding="utf-8"))
    design_source["module"]["execution_graph"]["nodes"][0]["label"] = "Edited after controller pin"
    design_path.write_text(yaml.safe_dump(design_source, sort_keys=False), encoding="utf-8")

    later_loop = controller._new_execution_run_loop(interval_seconds=0.0, on_event=None)
    later_design_ctx = later_loop._context_for_stage(Stage.DESIGN)
    later_design_compiled = compile_execution_graph(
        later_design_ctx.runtime_module_config()["execution_graph"],
        design_execution_catalog(controller._deps.agent_registry.get("design_agent")),
    )
    later_ctx = later_loop._context_for_owner(controller._deps.orchestrator_agent_name, Stage.DESIGN)
    later_compiled = compile_execution_graph(
        later_ctx.runtime_module_config()["execution_graph"],
        orchestrator_execution_catalog(
            controller._deps.agent_registry.get(controller._deps.orchestrator_agent_name),
            context=None,
            handlers=None,
        ),
    )
    unpinned_loop = LangGraphRunLoop(
        state=controller._state,
        agent_registry=controller._deps.agent_registry,
        orchestrator_agent_name=controller._deps.orchestrator_agent_name,
        ctx=controller._deps.agent_context,
        logger=controller._logger_bundle.logger,
        interval_seconds=0.0,
        graph_config_path=controller._active_graph_config_path,
        module_root=graph_root,
    )
    unpinned_ctx = unpinned_loop._context_for_owner(controller._deps.orchestrator_agent_name, Stage.DESIGN)
    unpinned_design_ctx = unpinned_loop._context_for_stage(Stage.DESIGN)
    unpinned_design_compiled = compile_execution_graph(
        unpinned_design_ctx.runtime_module_config()["execution_graph"],
        design_execution_catalog(controller._deps.agent_registry.get("design_agent")),
    )
    unpinned_compiled = compile_execution_graph(
        unpinned_ctx.runtime_module_config()["execution_graph"],
        orchestrator_execution_catalog(
            controller._deps.agent_registry.get(controller._deps.orchestrator_agent_name),
            context=None,
            handlers=None,
        ),
    )

    assert later_compiled.entry == "mission"
    assert later_compiled.revision == first_compiled.revision
    assert later_design_compiled.revision == first_design_compiled.revision
    assert unpinned_compiled.entry == "plan"
    assert unpinned_compiled.revision != first_compiled.revision
    assert unpinned_design_compiled.revision != first_design_compiled.revision
    assert guard.physical_call_count == 0
