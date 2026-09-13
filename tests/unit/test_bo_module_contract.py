"""BO package ownership contracts; numerical work stays in existing services."""
from __future__ import annotations

import importlib
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


def test_bo_discovery_and_legacy_modules_share_runtime_identity(monkeypatch):
    from agents.module_discovery import discover_agent_modules
    from agents.registry import AgentRegistry

    modules = [module for module in discover_agent_modules() if module.module_id == "bo"]
    assert len(modules) == 1
    module = modules[0]
    assert (module.agent_name, module.version) == ("bo_agent", "1.0.0")

    owner = importlib.import_module("agents.bo.agent")
    decision = importlib.import_module("agents.bo.decision")
    assert importlib.import_module("agents.bo_agent") is owner
    assert importlib.import_module("agents.bo_decision") is decision
    monkeypatch.setattr(owner, "_identity_probe", "canonical-bo", raising=False)
    assert importlib.import_module("agents.bo_agent")._identity_probe == "canonical-bo"

    registry = AgentRegistry()
    registry.register_module(module)
    assert registry.get_module("bo").factory is owner.BOAgent
    assert registry.get("bo_agent").name == "bo_agent"


def test_bo_descriptor_and_package_name_existing_services_without_a_bridge():
    from agents.bo.module import BO_MODULE

    root = Path(__file__).resolve().parents[2]
    descriptor = BO_MODULE.describe()
    assert descriptor["frontend"] == {
        "host": "/live",
        "descriptor": "graphs/modules/bo/ui.yaml",
        "asset_url": "/module-assets/bo/live_report.js",
        "namespace": "AX4LABBOUI",
        "factory": "createFrontend",
        "report_api": "/api/agents/bo/report",
    }
    assert descriptor["dependencies"]["bridge_modules"] == []
    assert descriptor["dependencies"]["direct_device_effect"] is False
    assert descriptor["storage"]["new_settings_store"] is False
    assert descriptor["backend"]["compatibility_imports"] == [
        "agents.bo_agent", "agents.bo_decision",
    ]
    for path in (
        descriptor["backend"]["entrypoint"],
        descriptor["backend"]["decision"],
        descriptor["backend"]["execution"],
        descriptor["backend"]["structure"],
        descriptor["backend"]["presentation"],
        descriptor["documentation"],
    ):
        assert (root / path).is_file(), path

    package = yaml.safe_load((root / "packages/agents/bo/package.yaml").read_text())
    assert package == {
        "schema": "ax4lab.agent_package.v1",
        "id": "bo",
        "version": "1.0.0",
        "agent_module": {"id": "bo", "version": "1.0.0"},
        "handler": "agent.bo_agent",
        "module_reference": "graphs/modules/bo/module.yaml",
        "bridge_modules": [],
    }


def test_bo_source_catalog_resolves_real_symbols_and_has_no_physical_low_node():
    from agents.bo.agent import BOAgent

    root = Path(__file__).resolve().parents[2]
    catalog = BOAgent().execution_catalog().describe()
    assert set(catalog["implementation_structure"]["operations"]) == {
        "bo.task", "bo.deliver",
    }
    assert catalog["inputs"] == ["settings"]
    areas = set()
    for operation in catalog["implementation_structure"]["operations"].values():
        node_ids = {"$operation", *(node["id"] for node in operation["nodes"])}
        for edge in operation["edges"]:
            assert edge["source"] in node_ids and edge["target"] in node_ids
        for node in operation["nodes"]:
            areas.add(node["area"])
            source = node["source"]
            tree = ast.parse((root / source["path"]).read_text(encoding="utf-8"))
            assert any(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and item.name == source["symbol"].split(".")[-1]
                for item in ast.walk(tree)
            ), source
    assert areas == {"high", "middle", "guardian", "knowledge"}


class _Owner:
    def __init__(self):
        from agents.base_agent import AgentResult

        self.calls = []
        self.result = AgentResult(True, "controlled BO", {"bo_result": {"ok": True}})

    async def _run_task(self, state, ctx, settings):
        self.calls.append(deepcopy(settings))
        return self.result


@pytest.mark.asyncio
async def test_bo_graph_passes_explicit_settings_and_delivers_the_owner_result_once():
    from agents.bo.execution import execute_bo_graph

    owner = _Owner()
    settings = {"strategy": "bo", "budget": 3}
    execution = await execute_bo_graph(owner, object(), object(), settings=settings)
    assert execution.result is owner.result
    assert execution.outputs["agent_result"] is owner.result
    assert owner.calls == [settings]
    assert [item["node_id"] for item in execution.trace if item["status"] == "completed"] == [
        "task", "deliver",
    ]


@pytest.mark.asyncio
async def test_bo_graph_rejects_a_second_task_before_repeating_numerical_work():
    from agents.bo.execution import default_bo_execution_graph, execute_bo_graph
    from agents.execution_graph import ExecutionGraphError

    graph = default_bo_execution_graph()
    graph["nodes"].append({"id": "repeat", "handler": "bo.task", "area": "middle", "llm": True})
    graph["edges"] = [
        {"source": "task", "target": "repeat", "on": "next", "kind": "execution"},
        {"source": "repeat", "target": "deliver", "on": "next", "kind": "evidence"},
    ]
    owner = _Owner()
    with pytest.raises(ExecutionGraphError, match="cannot repeat"):
        await execute_bo_graph(owner, object(), object(), settings={}, graph=graph)
    assert owner.calls == [{}]


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["run", "run_with_settings"])
async def test_bo_public_entrypoints_archive_once_and_keep_explicit_settings(
    entrypoint, tmp_path, monkeypatch,
):
    from agents.base_agent import AgentResult
    from agents.bo.agent import BOAgent
    from orchestrator.state import Mode, OrchestratorState, Stage

    state = OrchestratorState(
        run_id=f"bo-{entrypoint}-archive-contract",
        experiment_id="experiment-1",
        mode=Mode.TEST,
        stage=Stage.BO,
        run_metadata={"bo_settings": {"strategy": "bo", "budget": 2}},
    )
    expected = AgentResult(True, "controlled BO", {"bo_result": {"ok": True}})
    seen = []

    async def controlled_task(self, task_state, ctx, settings):
        assert task_state is state
        seen.append(deepcopy(settings))
        return expected

    monkeypatch.setattr(BOAgent, "_run_task", controlled_task)
    agent = BOAgent()
    ctx = SimpleNamespace(artifact_run_root=str(tmp_path / "runs"))
    if entrypoint == "run":
        result = await agent.run(state, ctx)
    else:
        result = await agent.run_with_settings(
            state, ctx, {"strategy": "bo", "budget": 5, "random_seed": 17},
        )
    attempts = list(
        (tmp_path / "runs" / state.run_id / "runtime" / "loops" / "loop-000001" / "bo_agent")
        .glob("attempt-*")
    )
    assert result is expected
    assert len(seen) == 1
    assert seen[0]["budget"] == (2 if entrypoint == "run" else 5)
    assert len(attempts) == 1
    assert json.loads((attempts[0] / "manifest.json").read_text())["agent"] == "bo_agent"


def test_bo_report_projection_prefers_current_metadata_and_preserves_full_evidence():
    from agents.bo.presentation import project_bo_report

    current = {
        "ok": True,
        "strategy": "bo",
        "acquisition": "expected_improvement",
        "budget": 8,
        "benchmark": {"strategies": {"bo": {"surrogate_trace": [
            {"selected": {"cell_size_mm": 7.2}},
        ]}}},
        "prior_summary": {"measured_count": 3, "failed_count": 1},
        "decision": {"schema": "bo_decision.v1", "status": "accepted"},
        "candidate_pool": [
            {"candidate_id": "candidate-current", "combined_score": 0.8},
            {"candidate_id": "candidate-2", "combined_score": 0.7},
            {"candidate_id": "candidate-3", "combined_score": 0.6},
        ],
        "candidate_ranking": [{"candidate_id": "candidate-current", "combined_score": 0.8}],
        "recommendation": {"candidate_id": "candidate-current", "parameters": {"cell_size_mm": 7.2}},
        "next_design_request": {"schema": "next_design_request.v1", "status": "ready"},
        "lhs_visualization": {"schema": "lhs_design_visualization.v1", "step": 4},
        "visualization": {"schema": "bo_visualization.v1", "step": 9},
        "artifacts": {"bo_decision": "/runs/current/bo_decision.json"},
    }
    metadata = {"bo_agent": current, "next_design_request": {"status": "stale"}}
    payload = {"bo_result": {"recommendation": {"candidate_id": "historical"}}}
    before = deepcopy((metadata, payload))
    projected = project_bo_report(metadata, payload)
    assert projected["bo_result"] is current
    assert projected["role_specific"]["candidate_ranking"][0]["candidate_id"] == "candidate-current"
    assert projected["role_specific"]["surrogate_panel"] == {
        "strategy": "bo",
        "benchmark_strategy": "bo",
        "acquisition": "expected_improvement",
        "budget": 8,
        "trace_step_count": 1,
        "latest_selected": {"cell_size_mm": 7.2},
        "prior_summary": {"measured_count": 3, "failed_count": 1},
    }
    assert projected["role_specific"]["decision_register"] == projected["decisions"]
    assert projected["role_specific"]["handoff_packet"]["status"] == "ready"
    assert projected["role_specific"]["lhs_visualization"]["step"] == 4
    assert projected["role_specific"]["visualization"]["step"] == 9
    assert projected["metrics"]["candidate_count"] == 3
    assert (metadata, payload) == before
