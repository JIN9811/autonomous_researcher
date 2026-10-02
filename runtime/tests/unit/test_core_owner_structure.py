"""Executable core owners keep one composite task and one fresh delivery."""

from __future__ import annotations

import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.base_agent import AgentResult
from agents.execution_graph import ExecutionGraphError, compile_execution_graph, run_execution_graph


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "module_id,agent_path",
    [
        ("knowledge", "agents.core.knowledge.agent.KnowledgeAgent"),
        ("guardian", "agents.core.guardian.agent.GuardianAgent"),
    ],
)
def test_core_catalog_declares_only_composite_task_and_fresh_delivery(module_id, agent_path):
    """Exposing source-detail nodes as operations would create a second run path."""
    module_name, class_name = agent_path.rsplit(".", 1)
    module = __import__(module_name, fromlist=[class_name])
    agent = getattr(module, class_name)()

    catalog = agent.execution_catalog()

    assert [item.handler for item in catalog.operations] == [
        f"{module_id}.task", f"{module_id}.deliver",
    ]
    assert catalog.required_outputs == ("agent_result",)
    assert catalog.operation(f"{module_id}.deliver").requires == ("task_result",)
    assert catalog.describe()["implementation_structure"]["operations"].keys() == {
        f"{module_id}.task", f"{module_id}.deliver",
    }


@pytest.mark.parametrize("module_id", ["knowledge", "guardian"])
def test_core_graph_rejects_delivery_without_task_or_unregistered_operation(module_id):
    """A terminal delivery cannot manufacture a result or call arbitrary code."""
    agent_module = __import__(f"agents.core.{module_id}.agent", fromlist=["*"])
    agent = getattr(agent_module, f"{module_id.title()}Agent")()
    catalog = agent.execution_catalog()
    delivery_only = {
        "schema": "ax4lab.execution_graph.v1",
        "entry": "deliver",
        "nodes": [{"id": "deliver", "handler": f"{module_id}.deliver", "area": "middle"}],
        "edges": [],
        "terminals": ["deliver"],
    }

    with pytest.raises(ExecutionGraphError, match="required input"):
        compile_execution_graph(delivery_only, catalog)

    delivery_only["nodes"][0]["handler"] = "python.unregistered"
    with pytest.raises(ExecutionGraphError, match="unknown handler"):
        compile_execution_graph(delivery_only, catalog)


@pytest.mark.asyncio
@pytest.mark.parametrize("module_id", ["knowledge", "guardian"])
async def test_core_default_graph_calls_original_task_once_and_delivers_same_result(module_id):
    """Wrapping the task must preserve object identity and exactly-once side effects."""
    execution = __import__(f"agents.core.{module_id}.execution", fromlist=["*"])
    expected = AgentResult(success=True, summary=f"{module_id} result", data={module_id: {"ok": True}})

    class Owner:
        calls = 0

        async def _run_task(self, state, ctx):
            self.calls += 1
            return expected

    owner = Owner()
    result = await getattr(execution, f"execute_{module_id}_graph")(
        owner, SimpleNamespace(run_id="run", loop_count=0), None,
        graph=getattr(execution, f"default_{module_id}_execution_graph")(),
    )

    assert owner.calls == 1
    assert result.result is expected
    assert result.outputs["task_result"] is expected
    assert [item["handler"] for item in result.trace if item["status"] == "completed"] == [
        f"{module_id}.task", f"{module_id}.deliver",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_id", ["knowledge", "guardian"])
async def test_core_composite_task_refuses_repeat_before_second_side_effect(module_id):
    """Duplicating the task node must stop before invoking the owner twice."""
    execution = __import__(f"agents.core.{module_id}.execution", fromlist=["*"])
    expected = AgentResult(success=True, summary="result", data={})

    class Owner:
        calls = 0

        async def _run_task(self, state, ctx):
            self.calls += 1
            return expected

    owner = Owner()
    graph = {
        "schema": "ax4lab.execution_graph.v1",
        "entry": "task_1",
        "nodes": [
            {"id": "task_1", "handler": f"{module_id}.task", "area": "middle", "llm": True},
            {"id": "task_2", "handler": f"{module_id}.task", "area": "middle", "llm": True},
            {"id": "deliver", "handler": f"{module_id}.deliver", "area": "middle"},
        ],
        "edges": [
            {"source": "task_1", "target": "task_2", "on": "next", "kind": "execution"},
            {"source": "task_2", "target": "deliver", "on": "next", "kind": "execution"},
        ],
        "terminals": ["deliver"],
    }

    compiled = compile_execution_graph(graph, getattr(execution, f"{module_id}_execution_catalog")(owner))
    with pytest.raises(ExecutionGraphError, match="cannot repeat"):
        await run_execution_graph(compiled, SimpleNamespace(run_id="run", loop_count=0), None)

    assert owner.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("module_id", ["knowledge", "guardian"])
async def test_public_run_delegates_to_execute_once(module_id, monkeypatch):
    """The archive wrapper must surround one executable owner invocation, not each operation."""
    agent_module = __import__(f"agents.core.{module_id}.agent", fromlist=["*"])
    agent = getattr(agent_module, f"{module_id.title()}Agent")()
    expected = AgentResult(success=True, summary="delegated", data={})
    calls = []

    async def execute(state, ctx):
        calls.append((state, ctx))
        return expected

    monkeypatch.setattr(agent, "_execute", execute)
    state = SimpleNamespace(run_id="run", loop_count=0)
    ctx = SimpleNamespace(artifact_run_root=None)

    assert await agent.run(state, ctx) is expected
    assert calls == [(state, ctx)]


@pytest.mark.parametrize("module_id", ["knowledge", "guardian"])
def test_core_source_relationships_resolve_without_becoming_operations(module_id):
    """Every presented responsibility must point to real code while the route stays composite."""
    execution = __import__(f"agents.core.{module_id}.execution", fromlist=["*"])
    structure = getattr(execution, f"{module_id}_execution_catalog")(SimpleNamespace()).describe()[
        "implementation_structure"
    ]
    for detail in structure["operations"].values():
        ids = {"$operation", *(node["id"] for node in detail["nodes"])}
        assert all(edge["source"] in ids and edge["target"] in ids for edge in detail["edges"])
        for node in detail["nodes"]:
            source = node["source"]
            path = ROOT / source["path"]
            tree = ast.parse(path.read_text(encoding="utf-8"))
            symbol = source["symbol"].split(".")[-1]
            assert any(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item.name == symbol
                for item in ast.walk(tree)
            ), source


@pytest.mark.parametrize("module_id", ["knowledge", "guardian"])
def test_core_presentation_contract_is_not_a_discovery_module(module_id):
    """Core UI/report reuse must not enroll core owners in specialist discovery."""
    agent_module = __import__(f"agents.core.{module_id}.agent", fromlist=["*"])
    owner_module = __import__(f"agents.core.{module_id}.module", fromlist=["*"])
    agent = getattr(agent_module, f"{module_id.title()}Agent")()

    contract = agent.core_module()

    assert contract.module_id == module_id
    assert contract.agent_name == f"{module_id}_agent"
    assert not hasattr(owner_module, "MODULE")
    assert agent.core_module() is contract


def test_guardian_structure_shows_failure_evidence_reaching_advisory_through_design_validation():
    from agents.core.guardian.structure import guardian_implementation_structure

    detail = guardian_implementation_structure()["operations"]["guardian.task"]
    edges = {(edge["source"], edge["target"], edge["label"]) for edge in detail["edges"]}

    assert ("failures", "design_gate", "validate design history") in edges
    assert ("design_gate", "advisory", "validated design evidence") in edges
    assert not any(source == "failures" and target == "advisory" for source, target, _ in edges)
