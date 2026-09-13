"""Analysis package contracts; all execution uses controlled in-process boundaries."""
from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_analysis_discovery_registers_canonical_owner_identity():
    from agents.analysis.agent import AnalysisAgent
    from agents.module_discovery import discover_agent_modules
    from agents.registry import AgentRegistry

    modules = [module for module in discover_agent_modules() if module.module_id == "analysis"]
    assert len(modules) == 1
    module = modules[0]
    assert (module.agent_name, module.version) == ("analysis_agent", "1.0.0")
    registry = AgentRegistry()
    registry.register_module(module)
    assert registry.names() == ["analysis_agent"]
    assert registry.get_module("analysis").factory is AnalysisAgent
    assert registry.get("analysis_agent").__class__ is AnalysisAgent
    assert registry.get("analysis_agent").execution_catalog().module_id == "analysis"


def test_analysis_descriptor_owns_sources_without_a_physical_low_boundary():
    from agents.analysis.module import MODULE

    root = Path(__file__).resolve().parents[2]
    descriptor = MODULE.describe()
    assert descriptor["dependencies"]["bridge_modules"] == ["cae"]
    assert descriptor["dependencies"]["tools"] == [
        "cae.prepare_static_analysis",
        "cae.run_static_analysis",
    ]
    assert descriptor["dependencies"]["direct_device_effect"] is False
    assert descriptor["storage"]["new_settings_store"] is False
    assert descriptor["storage"]["background_resource_lifetime"] == "existing_runtime_owned"
    assert descriptor["backend"] == {
        "entrypoint": "agents/analysis/agent.py",
        "decisions": "agents/analysis/decisions.py",
        "runtime": "agents/analysis/runtime.py",
        "improvement": "agents/analysis/improvement.py",
        "refinement": "agents/analysis/refinement.py",
        "mechanisms": "agents/analysis/mechanisms.py",
        "calibration": "agents/analysis/calibration.py",
        "fem": "agents/analysis/fem.py",
        "execution": "agents/analysis/execution.py",
        "structure": "agents/analysis/structure.py",
        "presentation": "agents/analysis/presentation.py",
    }
    for path in descriptor["backend"].values():
        for item in path if isinstance(path, list) else [path]:
            if isinstance(item, str) and "/" in item:
                assert (root / item).is_file(), item
    assert (root / descriptor["documentation"]).is_file()


def test_analysis_source_catalog_resolves_real_symbols_and_has_no_fake_low_node():
    from agents.analysis.agent import AnalysisAgent

    root = Path(__file__).resolve().parents[2]
    catalog = AnalysisAgent().execution_catalog().describe()
    structure = catalog["implementation_structure"]
    assert set(structure["operations"]) == {"analysis.task", "analysis.deliver"}
    areas = set()
    for operation in structure["operations"].values():
        node_ids = {"$operation", *(node["id"] for node in operation["nodes"])}
        for edge in operation["edges"]:
            assert edge["source"] in node_ids and edge["target"] in node_ids
        for node in operation["nodes"]:
            areas.add(node["area"])
            source = node["source"]
            tree = ast.parse((root / source["path"]).read_text(encoding="utf-8"))
            scope = tree.body
            for part in source["symbol"].split("."):
                resolved = next(
                    (
                        item for item in scope
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        and item.name == part
                    ),
                    None,
                )
                assert resolved is not None, source
                scope = resolved.body if isinstance(resolved, ast.ClassDef) else []
    assert "high" in areas and "middle" in areas and "guardian" in areas and "knowledge" in areas
    assert "low" not in areas


class _Owner:
    def __init__(self):
        from agents.base_agent import AgentResult

        self.result = AgentResult(success=True, summary="measured result", data={"analysis": {"ok": True}})
        self.calls = 0

    async def _run_task(self, state, ctx):
        self.calls += 1
        return self.result


@pytest.mark.asyncio
async def test_analysis_graph_invokes_and_delivers_owner_result_once():
    from agents.analysis.execution import execute_analysis_graph

    owner = _Owner()
    execution = await execute_analysis_graph(owner, object(), object())
    assert execution.result is owner.result
    assert execution.outputs["agent_result"] is owner.result
    assert owner.calls == 1
    assert [item["node_id"] for item in execution.trace if item["status"] == "completed"] == ["task", "deliver"]


@pytest.mark.asyncio
async def test_analysis_graph_rejects_a_second_composite_before_repeating_owner_work():
    from agents.analysis.execution import default_analysis_execution_graph, execute_analysis_graph
    from agents.execution_graph import ExecutionGraphError

    graph = default_analysis_execution_graph()
    graph["nodes"].append({"id": "repeat", "handler": "analysis.task", "area": "middle", "llm": True})
    graph["edges"] = [
        {"source": "task", "target": "repeat", "on": "next", "kind": "execution"},
        {"source": "repeat", "target": "deliver", "on": "next", "kind": "evidence"},
    ]
    owner = _Owner()
    with pytest.raises(ExecutionGraphError, match="cannot repeat"):
        await execute_analysis_graph(owner, object(), object(), graph=graph)
    assert owner.calls == 1


@pytest.mark.asyncio
async def test_analysis_public_run_archives_once_and_keeps_owner_result(tmp_path, monkeypatch):
    from agents.analysis.agent import AnalysisAgent
    from agents.base_agent import AgentResult
    from orchestrator.state import Mode, OrchestratorState, Stage

    state = OrchestratorState(
        run_id="analysis-archive-contract",
        experiment_id="experiment-1",
        mode=Mode.TEST,
        stage=Stage.ANALYSIS,
        current_experiment_spec={"specimen_id": "specimen-1"},
    )
    expected = AgentResult(success=True, summary="owner result", data={"analysis": {"ok": True}})
    calls = 0

    async def controlled_task(self, task_state, ctx):
        nonlocal calls
        calls += 1
        assert task_state is state
        return expected

    monkeypatch.setattr(AnalysisAgent, "_run_task", controlled_task)
    result = await AnalysisAgent().run(
        state,
        SimpleNamespace(artifact_run_root=str(tmp_path / "runs")),
    )
    attempts = list((tmp_path / "runs" / state.run_id / "runtime" / "loops" / "loop-000001" / "analysis_agent").glob("attempt-*"))
    assert result is expected
    assert calls == 1
    assert len(attempts) == 1
    assert json.loads((attempts[0] / "manifest.json").read_text())["agent"] == "analysis_agent"


def test_analysis_report_projection_preserves_state_precedence_and_inputs():
    from agents.analysis.presentation import project_analysis_report

    state_analysis = {
        "ok": True,
        "utm_metrics": {"peak_force_N": 520.0},
        "cae_result": {"status": "queued"},
        "fem_agentic_loop": {"execution": "background", "status": "queued"},
        "quality_gate": {"ok_for_bo": True},
        "trust_score": {"score": None},
        "multifidelity_comparison": {"status": "pending"},
        "decisions": [{"phase": "data_validation"}],
    }
    metadata = {
        "_projection_state": {"latest_analysis": state_analysis},
        "analysis_metrics": {"peak_force_N": 520.0},
        "analysis_agent_payload": {"analysis": {"ok": False}},
    }
    payload = {
        "analysis": {"ok": False},
        "bo_observation": {"ok_for_bo": True},
        "bo_handoff": {"schema_version": "analysis_bo_handoff_v2"},
        "experiment_evaluation": {"status": "accepted"},
        "knowledge_payload": {"schema": "analysis_knowledge_payload.v1"},
        "metrics": {"old": True},
    }
    before = deepcopy((metadata, payload))
    result = project_analysis_report(metadata, payload)
    assert result["analysis_report"] is state_analysis
    assert result["role_specific"]["measurement"]["peak_force_N"] == 520.0
    assert result["role_specific"]["fem"]["execution"] == "background"
    assert result["role_specific"]["handoff_packet"] == payload["bo_handoff"]
    assert result["decisions"] == [{"phase": "data_validation"}]
    assert result["metrics"] == {"peak_force_N": 520.0}
    assert (metadata, payload) == before
