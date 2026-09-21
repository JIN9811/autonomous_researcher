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


@pytest.mark.parametrize('module_id', ['guardian', 'knowledge'])
def test_core_module_api_delivers_executable_contract_without_package_activation(module_api, module_id):
    client, _, controller, guard, root = module_api
    installed = yaml.safe_load((root / module_id / 'module.yaml').read_text())['module']
    response = client.get(f'/api/modules/{module_id}')
    assert response.status_code == 200
    payload = response.json()
    delivered = payload['module']['module']
    assert delivered['metadata']['control_view'] == installed['metadata']['control_view']
    assert delivered['execution_graph'] == installed['execution_graph']
    assert {operation['handler'] for operation in payload['execution_catalog']['operations']} == {
        f'{module_id}.task', f'{module_id}.deliver',
    }
    assert len(payload['execution_graph_revision']) == 64
    assert payload['implementation']['id'] == module_id
    assert payload['implementation']['configuration']['activation_supported'] is False
    assert payload['owner_plan_contract']['owner'] == module_id
    assert payload['owner_plan_contract']['version'] == '1.0.0'
    assert payload['owner_plan_state'] == 'default'
    assert controller._deps.agent_registry.get_module(module_id) is None
    assert guard.physical_call_count == 0


def test_core_owner_plan_validate_then_apply_uses_existing_module_store(module_api, monkeypatch):
    client, app_main, controller, guard, root = module_api
    knowledge_path = root / 'knowledge' / 'module.yaml'
    guardian_path = root / 'guardian' / 'module.yaml'
    before_knowledge = knowledge_path.read_bytes()
    before_guardian = guardian_path.read_bytes()
    payload = client.get('/api/modules/knowledge').json()['module']
    payload['module']['owner_plan'] = {
        'schema': 'ax4lab.owner_plan.v1', 'id': 'knowledge_reference',
        'owner': 'knowledge', 'version': '1.0.0', 'contract_version': '1.0.0',
        'settings': {'corpora': ['markdown'], 'decision_max_steps': 6},
    }

    validated = client.post('/api/modules/knowledge/validate', json={'module': payload})
    assert validated.status_code == 200 and validated.json()['ok'], validated.text
    assert knowledge_path.read_bytes() == before_knowledge
    applied = client.put('/api/modules/knowledge', json={
        'module': payload, 'reason': 'configured owner plan fixture', 'author': 'pytest', 'activate': True,
    })
    assert applied.status_code == 200 and applied.json()['ok'], applied.text
    assert yaml.safe_load(knowledge_path.read_text())['module']['owner_plan'] == payload['module']['owner_plan']
    assert guardian_path.read_bytes() == before_guardian

    monkeypatch.setattr(controller, 'snapshot', lambda: {'is_running': True})
    payload['module']['owner_plan']['settings']['decision_max_steps'] = 7
    busy = client.put('/api/modules/knowledge', json={'module': payload, 'activate': True})
    assert busy.status_code == 409
    assert yaml.safe_load(knowledge_path.read_text())['module']['owner_plan']['settings']['decision_max_steps'] == 6
    assert guard.physical_call_count == 0


@pytest.mark.parametrize('change', ['owner', 'setting', 'snapshot'])
def test_core_owner_plan_rejects_mismatch_unknown_setting_and_snapshot_before_persistence(module_api, change):
    client, _, _, guard, root = module_api
    path = root / 'knowledge' / 'module.yaml'
    before = path.read_bytes()
    payload = client.get('/api/modules/knowledge').json()['module']
    plan = {
        'schema': 'ax4lab.owner_plan.v1', 'id': 'knowledge_reference',
        'owner': 'knowledge', 'version': '1.0.0', 'contract_version': '1.0.0',
        'settings': {'corpora': ['markdown']},
    }
    if change == 'owner':
        plan['owner'] = 'guardian'
    elif change == 'setting':
        plan['settings']['private_memory'] = True
    else:
        plan['runtime_snapshot'] = {'run_id': 'private'}
    payload['module']['owner_plan'] = plan

    result = client.put('/api/modules/knowledge', json={'module': payload, 'activate': True})

    assert result.status_code == 200 and not result.json()['ok']
    assert path.read_bytes() == before
    assert guard.physical_call_count == 0


@pytest.mark.parametrize(
    'advisory_evidence_context',
    [
        {'trace': {'run_id': 'private-run'}},
        {'authentication': {'password': 'secret'}},
        {'reference': {'location': '/tmp/owner-plan-private-note.md'}},
        {'reference': {'address': '10.0.0.42'}},
        {'network': {'connections': ['lab-controller']}},
        {'reference': {'session_id': 'private-session'}},
        {'reference': {'sessionId': 'private-session'}},
        {'reference': {'user_id': 'private-user'}},
        {'reference': {'user-id': 'private-user'}},
    ],
)
def test_guardian_owner_plan_validate_and_apply_reject_nested_private_context_before_persistence(
    module_api, advisory_evidence_context,
):
    client, _, _, guard, root = module_api
    path = root / 'guardian' / 'module.yaml'
    before = path.read_bytes()
    payload = client.get('/api/modules/guardian').json()['module']
    payload['module']['owner_plan'] = {
        'schema': 'ax4lab.owner_plan.v1', 'id': 'guardian_reference',
        'owner': 'guardian', 'version': '1.0.0', 'contract_version': '1.0.0',
        'settings': {'advisory_evidence_context': advisory_evidence_context},
    }

    validated = client.post('/api/modules/guardian/validate', json={'module': payload})
    applied = client.put('/api/modules/guardian', json={
        'module': payload, 'reason': 'private owner plan probe', 'author': 'pytest', 'activate': True,
    })

    assert validated.status_code == 200 and not validated.json()['ok']
    assert applied.status_code == 200 and not applied.json()['ok']
    assert path.read_bytes() == before
    assert guard.physical_call_count == 0


@pytest.mark.parametrize('module_id,namespace', [
    ('guardian', 'AX4LABGuardianUI'), ('knowledge', 'AX4LABKnowledgeUI'),
])
def test_core_module_manifest_and_asset_use_registered_owner_presentation(module_api, module_id, namespace):
    client, _, _, guard, _ = module_api

    manifests = client.get('/api/runtime/agent-manifests').json()['agents']
    manifest = next(item for item in manifests if item['id'] == module_id)
    asset = client.get(f'/module-assets/{module_id}/live_report.js')

    assert manifest['implementation']['id'] == module_id
    assert manifest['implementation']['frontend']['namespace'] == namespace
    assert manifest['renderer']['dashboard'] == 'module'
    assert asset.status_code == 200
    assert namespace in asset.text
    assert guard.physical_call_count == 0


def test_core_owner_report_projection_is_read_only(module_api):
    client, _, controller, guard, _ = module_api
    controller._state.run_metadata['knowledge'] = {
        'knowledge_report': {'memory_intake': {'experiment_record_id': 'record-1'}},
        'knowledge_context': {'schema': 'knowledge_context.v1'},
        'evolution_proposal': {'schema': 'evolution_proposal.v1'},
    }
    before = deepcopy(controller._state.run_metadata)

    report = client.get('/api/agents/knowledge/report').json()['report']

    assert report['sections']['knowledge_report']['memory_intake']['experiment_record_id'] == 'record-1'
    assert report['sections']['knowledge_context']['schema'] == 'knowledge_context.v1'
    assert {key: controller._state.run_metadata[key] for key in before} == before
    assert guard.physical_call_count == 0


def test_analysis_installed_report_projection_and_graph(module_api):
    client, _, controller, guard, _ = module_api
    response = client.get("/api/modules/analysis").json()
    assert {operation["handler"] for operation in response["execution_catalog"]["operations"]} == {
        "analysis.task", "analysis.deliver"
    }
    assert len(response["execution_graph_revision"]) == 64
    state = controller._state
    state.latest_analysis.update({
        "ok": True,
        "utm_metrics": {"peak_force_N": 520.0},
        "fem_agentic_loop": {"execution": "background", "status": "queued"},
        "quality_gate": {"ok_for_bo": True},
        "decisions": [{"phase": "data_validation"}],
    })
    state.run_metadata.update(
        analysis_agent_payload={
            "analysis": {"ok": False},
            "bo_observation": {"ok_for_bo": True},
            "bo_handoff": {"schema_version": "analysis_bo_handoff_v2"},
        },
        analysis_metrics={"peak_force_N": 520.0},
    )
    before = deepcopy(state.run_metadata)
    report = client.get("/api/agents/analysis/report")
    assert report.status_code == 200
    sections = report.json()["report"]["sections"]
    assert sections["analysis_report"]["ok"] is True
    assert sections["role_specific"]["measurement"] == {"peak_force_N": 520.0}
    assert "fem" not in sections["role_specific"]
    assert sections["bo_handoff"] == {"schema_version": "analysis_bo_handoff_v2"}
    assert sections["metrics"] == {"peak_force_N": 520.0}
    assert {key: state.run_metadata[key] for key in before} == before
    assert "_projection_state" not in state.run_metadata
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
    # Attention shares this sink but is not part of the execution-graph schema.
    graph_events = [event for event in events if event["type"].startswith("execution.")]
    assert graph_events
    assert all(event["payload"]["graph_revision"] == loaded["execution_graph_revision"]
               for event in graph_events)
    assert [name for name, _ in ctx.tools.calls] == ["lerobot.rollout.start"]
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
async def test_get_save_reload_and_real_owner_execution_share_edited_edges(module_api, monkeypatch):
    """A valid API edge edit must change actual registered owner operation order."""
    client, app_main, controller, guard, module_root = module_api
    from agents.core.orchestrator import execution as owner
    from agents.core.orchestrator.agent import OrchestratorAgent
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
    from agents.core.orchestrator.execution import orchestrator_execution_catalog
    from orchestrator.langgraph_runtime import LangGraphRunLoop
    from orchestrator.state import Stage

    graph_root = tmp_path / "pinned-graph"
    shutil.copytree(Path("graphs/modules"), graph_root / "modules")
    (graph_root / "configs").mkdir(parents=True)
    shutil.copy2(Path("graphs/configs/atr_closed_loop.yaml"), graph_root / "configs" / "atr_closed_loop.yaml")
    controller._active_graph_config_path = graph_root / "configs" / "atr_closed_loop.yaml"
    controller._owner_catalog_run_id = None
    knowledge_path = graph_root / "modules" / "knowledge" / "module.yaml"
    knowledge_source = yaml.safe_load(knowledge_path.read_text(encoding="utf-8"))
    knowledge_source["module"]["owner_plan"] = {
        "schema": "ax4lab.owner_plan.v1",
        "id": "knowledge_reference",
        "owner": "knowledge",
        "version": "1.0.0",
        "contract_version": "1.0.0",
        "settings": {"corpora": ["markdown"], "decision_max_steps": 6},
    }
    knowledge_path.write_text(yaml.safe_dump(knowledge_source, sort_keys=False), encoding="utf-8")

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
    first_knowledge_ctx = first_loop._context_for_owner("knowledge_agent", Stage.KNOWLEDGE)
    assert first_knowledge_ctx.runtime_module_config()["owner_plan"]["settings"]["decision_max_steps"] == 6

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
    knowledge_source["module"]["owner_plan"]["settings"]["decision_max_steps"] = 7
    knowledge_path.write_text(yaml.safe_dump(knowledge_source, sort_keys=False), encoding="utf-8")

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
    later_knowledge_ctx = later_loop._context_for_owner("knowledge_agent", Stage.KNOWLEDGE)
    unpinned_knowledge_ctx = unpinned_loop._context_for_owner("knowledge_agent", Stage.KNOWLEDGE)
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
    assert later_knowledge_ctx.runtime_module_config()["owner_plan"]["settings"]["decision_max_steps"] == 6
    assert unpinned_knowledge_ctx.runtime_module_config()["owner_plan"]["settings"]["decision_max_steps"] == 7
    assert unpinned_compiled.entry == "plan"
    assert unpinned_compiled.revision != first_compiled.revision
    assert unpinned_design_compiled.revision != first_design_compiled.revision
    assert guard.physical_call_count == 0
