"""Behavior tests for the allowlisted executable-agent graph contract."""

from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from agents.execution_graph import (
    ExecutionCatalog,
    ExecutionGraphError,
    ExecutionOperation,
    OperationResult,
    compile_execution_graph,
    run_execution_graph,
)


def _graph(*, entry: str = "a", edges: list[dict] | None = None) -> dict:
    return {
        "schema": "ax4lab.execution_graph.v1",
        "entry": entry,
        "nodes": [
            {"id": "a", "handler": "fixture.a", "label": "A", "area": "middle"},
            {"id": "b", "handler": "fixture.b", "label": "B", "area": "knowledge"},
        ],
        "edges": edges if edges is not None else [
            {"source": "a", "target": "b", "on": "next", "kind": "execution"},
        ],
        "terminals": ["b" if entry == "a" else "a"],
    }


def _catalog(calls: list[str], *, fail: str = "") -> ExecutionCatalog:
    async def operation(name, state, ctx, scope, config):
        calls.append(name)
        if fail == "error" and name == "a":
            raise RuntimeError("fixture failure")
        if fail == "cancel" and name == "a":
            raise asyncio.CancelledError
        return OperationResult("next", {name: True})

    return ExecutionCatalog(
        module_id="fixture",
        operations=(
            ExecutionOperation("fixture.a", operation=lambda *args: operation("a", *args), produces=("a",)),
            ExecutionOperation("fixture.b", operation=lambda *args: operation("b", *args), produces=("b",)),
        ),
    )


@pytest.mark.asyncio
async def test_edges_not_node_array_order_choose_execution_order():
    """Executing node-array order would incorrectly produce a,b after the edge edit."""
    calls: list[str] = []
    graph = _graph(
        entry="b",
        edges=[{"source": "b", "target": "a", "on": "next", "kind": "execution"}],
    )

    result = await run_execution_graph(compile_execution_graph(graph, _catalog(calls)), None, None)

    assert calls == ["b", "a"]
    assert [item["node_id"] for item in result.trace if item["status"] == "completed"] == ["b", "a"]


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda graph: graph["edges"].append({"source": "b", "target": "a", "on": "next", "kind": "execution"}), "cycle"),
        (lambda graph: graph["edges"].__setitem__(0, {"source": "a", "target": "missing", "on": "next", "kind": "execution"}), "unknown target"),
        (lambda graph: graph["nodes"][1].__setitem__("handler", "python.import_anything"), "unknown handler"),
        (lambda graph: graph["edges"][0].__setitem__("on", "accepted"), "outcome"),
        (lambda graph: graph["nodes"][0].__setitem__("config", {"shell": "rm"}), "config"),
    ],
)
def test_compile_rejects_invalid_structure_before_dispatch(mutation, match):
    """Removing any structural or allowlist check would admit an unsafe definition."""
    calls: list[str] = []
    graph = _graph()
    mutation(graph)

    with pytest.raises(ExecutionGraphError, match=match):
        compile_execution_graph(graph, _catalog(calls))

    assert calls == []


def test_compile_rejects_path_that_skips_required_input_producer():
    """A consumer reachable without its producer would receive undefined owner input."""
    async def noop(state, ctx, scope, config):
        return OperationResult()

    catalog = ExecutionCatalog(
        module_id="fixture",
        operations=(
            ExecutionOperation("fixture.a", noop, produces=("prepared",)),
            ExecutionOperation("fixture.b", noop, requires=("prepared",)),
            ExecutionOperation("fixture.c", noop, outcomes=("use", "skip")),
        ),
    )
    graph = {
        "schema": "ax4lab.execution_graph.v1",
        "entry": "c",
        "nodes": [
            {"id": "a", "handler": "fixture.a", "area": "middle"},
            {"id": "b", "handler": "fixture.b", "area": "high"},
            {"id": "c", "handler": "fixture.c", "area": "knowledge"},
        ],
        "edges": [
            {"source": "c", "target": "a", "on": "use", "kind": "execution"},
            {"source": "c", "target": "b", "on": "skip", "kind": "execution"},
            {"source": "a", "target": "b", "on": "next", "kind": "execution"},
        ],
        "terminals": ["b"],
    }

    with pytest.raises(ExecutionGraphError, match="required input.*prepared"):
        compile_execution_graph(graph, catalog)


@pytest.mark.asyncio
async def test_compiled_snapshot_does_not_follow_later_source_edits():
    """Reading the mutable source during traversal would switch this run to b,a."""
    calls: list[str] = []
    source = _graph()
    compiled = compile_execution_graph(source, _catalog(calls))
    source["entry"] = "b"
    source["edges"] = [{"source": "b", "target": "a", "on": "next", "kind": "execution"}]
    source["terminals"] = ["a"]

    await run_execution_graph(compiled, None, None)

    assert calls == ["a", "b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_failure_or_cancellation_never_dispatches_a_later_operation(failure):
    """Continuing after a failed/cancelled owner would create forbidden later effects."""
    calls: list[str] = []
    compiled = compile_execution_graph(_graph(), _catalog(calls, fail=failure))

    expected = RuntimeError if failure == "error" else asyncio.CancelledError
    with pytest.raises(expected):
        await run_execution_graph(compiled, None, None)

    assert calls == ["a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["outcome", "outputs"])
async def test_invalid_registered_return_emits_failed_trace_and_stops(invalid):
    """A bad owner return must not leave observers showing a running node."""
    calls: list[str] = []
    events: list[dict] = []

    async def bad(state, ctx, scope, config):
        calls.append("a")
        if invalid == "outcome":
            return OperationResult("invented", {"a": True})
        return OperationResult("next", {"undeclared": True})

    async def later(state, ctx, scope, config):
        calls.append("b")
        return OperationResult("next", {"b": True})

    catalog = ExecutionCatalog(
        "fixture",
        (
            ExecutionOperation("fixture.a", bad, produces=("a",)),
            ExecutionOperation("fixture.b", later, produces=("b",)),
        ),
    )
    compiled = compile_execution_graph(_graph(), catalog)

    with pytest.raises(ExecutionGraphError):
        await run_execution_graph(compiled, None, None, emit=events.append)

    assert calls == ["a"]
    assert [event["type"] for event in events[-2:]] == ["execution.node.failed", "execution.graph.failed"]
    assert events[-1]["payload"]["error_type"] == "ExecutionGraphError"
    assert "invented" not in repr(events[-2:])


@pytest.mark.asyncio
async def test_trace_uses_shared_ids_revision_and_never_serializes_private_inputs():
    """Leaking invocation scope into events would expose credentials to Runtime IDE clients."""
    calls: list[str] = []
    events: list[dict] = []

    result = await run_execution_graph(
        compile_execution_graph(_graph(), _catalog(calls)),
        None,
        None,
        inputs={"api_token": "do-not-emit", "private_payload": {"secret": "hidden"}},
        emit=events.append,
        invocation={"run_id": "run-1", "loop_index": 3, "invocation_id": "inv-1"},
    )

    assert result.graph_revision
    assert {event["payload"]["graph_revision"] for event in events} == {result.graph_revision}
    assert all(event["payload"]["module_id"] == "fixture" for event in events)
    assert all(event["payload"]["run_id"] == "run-1" for event in events)
    assert "do-not-emit" not in repr(events)
    assert "private_payload" not in repr(events)
    traversed = next(event for event in events if event["type"] == "execution.edge.traversed")
    assert traversed["payload"]["edge"] == {
        "source": "a", "target": "b", "on": "next", "kind": "execution"
    }


@pytest.mark.asyncio
async def test_design_owner_adapter_preserves_deterministic_policy_and_real_finalize():
    """Replacing owner computation with graph-specific logic would change the original result."""
    from agents.design.agent import DesignAgent
    from agents.design.execution import default_design_execution_graph, execute_design_graph
    from orchestrator.state import Mode, OrchestratorState, Stage
    from tests.unit.test_design_agent import _DeterministicCtxStub

    state = OrchestratorState(
        run_id="graph-design",
        experiment_id="synthetic",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict] = []

    execution = await execute_design_graph(
        DesignAgent(), state, _DeterministicCtxStub(),
        graph=default_design_execution_graph(), emit=events.append,
    )

    assert execution.result.success is True
    assert execution.result.summary == "Specimen experiment design selected"
    assert execution.result.data["design_decision"] == {
        "status": "deterministic_test", "trace": [], "llm_used": False
    }
    assert execution.result.data["rationale"] == "Deterministic test-mode specimen candidate generated from docs algorithm."
    assert [event["payload"]["node_id"] for event in events if event["type"] == "execution.node.completed"] == [
        "prepare", "decide", "finalize"
    ]


@pytest.mark.asyncio
async def test_orchestrator_owner_adapter_routes_failure_status_through_existing_report_builders():
    """A failed bounded decision still requires the original ORC report envelope."""
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.orchestrator_execution import default_orchestrator_execution_graph, execute_orchestrator_graph
    from orchestrator.state import Mode, OrchestratorState, Stage
    from tests.unit.test_orchestrator_decision import Model

    state = OrchestratorState(
        run_id="graph-orchestrator",
        experiment_id="synthetic",
        mode=Mode.TEST,
        stage=Stage.DESIGN,
    )
    events: list[dict] = []

    execution = await execute_orchestrator_graph(
        OrchestratorAgent(), state, Model(RuntimeError("offline")),
        graph=default_orchestrator_execution_graph(), emit=events.append,
    )

    assert execution.result.success is False
    assert execution.result.summary == "Orchestration decision: failed"
    assert execution.result.data["orchestration_decision"]["status"] == "failed"
    assert execution.result.data["decisions"][0]["schema"] == "decision_register.v1"
    assert [event["payload"]["node_id"] for event in events if event["type"] == "execution.node.completed"] == [
        "mission", "plan", "decide", "report"
    ]


@pytest.mark.asyncio
async def test_orchestrator_agent_run_uses_context_snapshot_and_edited_edges(monkeypatch):
    """Keeping the old fixed run body would ignore a backend module edge edit."""
    from agents import orchestrator_execution as owner
    from agents.orchestrator_agent import OrchestratorAgent
    from orchestrator.state import Mode, OrchestratorState, Stage
    from tests.unit.test_orchestrator_decision import Model

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
    graph = owner.default_orchestrator_execution_graph()
    graph["entry"] = "plan"
    graph["edges"] = [
        {"source": "plan", "target": "mission", "on": "next", "kind": "execution"},
        {"source": "mission", "target": "decide", "on": "next", "kind": "execution"},
        *[edge for edge in graph["edges"] if edge["source"] == "decide"],
    ]

    class SnapshotContext(Model):
        def runtime_module_config(self):
            return {"id": "orchestrator", "execution_graph": graph}

        async def emit_execution_event(self, event):
            self.events.append(event)

    ctx = SnapshotContext(RuntimeError("offline"))
    ctx.events = []
    state = OrchestratorState(
        run_id="edited-orchestrator", experiment_id="synthetic", mode=Mode.TEST, stage=Stage.DESIGN,
    )

    await OrchestratorAgent().run(state, ctx)

    assert calls == ["plan", "mission"]
    assert [event["payload"]["node_id"] for event in ctx.events if event["type"] == "execution.node.completed"][:2] == [
        "plan", "mission"
    ]


def test_migrated_module_schema_and_yaml_are_the_executable_owner_definitions():
    """Leaving decorative internal lists would preserve two conflicting definitions."""
    from agents.design.agent import DesignAgent
    from agents.design.execution import design_execution_catalog
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.orchestrator_execution import orchestrator_execution_catalog
    from graphs.schema import ExecutionGraphDefinition, load_module_config

    design = load_module_config("graphs/modules/design/module.yaml")
    orchestrator = load_module_config("graphs/modules/orchestrator/module.yaml")

    assert isinstance(design.execution_graph, ExecutionGraphDefinition)
    assert isinstance(orchestrator.execution_graph, ExecutionGraphDefinition)
    assert design.internal_graph == []
    assert orchestrator.internal_graph == []
    assert [step.id for step in design.pre_execution] == ["orchestrator_plan"]
    assert orchestrator.pre_execution == []
    compile_execution_graph(design.execution_graph.model_dump(exclude_none=True), design_execution_catalog(DesignAgent()))
    compile_execution_graph(
        orchestrator.execution_graph.model_dump(exclude_none=True),
        orchestrator_execution_catalog(OrchestratorAgent(), context=None, handlers=None),
    )


def test_module_runtime_context_detaches_nested_execution_graph_snapshot():
    """Mutating a source module after invocation capture must not alter its graph."""
    from types import SimpleNamespace
    from agents.orchestrator_execution import default_orchestrator_execution_graph
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Stage

    source = {"id": "orchestrator", "execution_graph": default_orchestrator_execution_graph()}
    ctx = ModuleRuntimeContext(
        SimpleNamespace(active_backend="controlled", tools=None), source, Stage("orchestrator"),
    )
    source["execution_graph"]["entry"] = "report"

    assert ctx.runtime_module_config()["execution_graph"]["entry"] == "mission"


def test_migrated_runtime_never_traverses_legacy_internal_graph():
    """A migrated module must not regain a second editable execution source."""
    from orchestrator.langgraph_runtime import LangGraphRunLoop

    runtime = object.__new__(LangGraphRunLoop)

    assert runtime._module_internal_steps(
        {
            "execution_graph_migrated": True,
            "internal_graph": [
                {"id": "phantom", "handler": "agent.design_agent", "handler_configured": True},
            ],
        }
    ) == []


def test_catalog_required_outputs_reject_prepare_only_terminal_before_dispatch():
    """Removing the reporting operation must not produce a completed owner graph."""
    calls: list[str] = []
    catalog = ExecutionCatalog(
        "fixture",
        _catalog(calls).operations[:1],
        required_outputs=("agent_result",),
    )
    graph = {
        "schema": "ax4lab.execution_graph.v1",
        "entry": "prepare",
        "nodes": [{"id": "prepare", "handler": "fixture.a", "area": "middle"}],
        "edges": [],
        "terminals": ["prepare"],
    }

    with pytest.raises(ExecutionGraphError, match="terminal.*agent_result"):
        compile_execution_graph(graph, catalog)

    assert calls == []


def test_terminal_must_produce_fresh_owner_result_not_reuse_earlier_scope_value():
    """A later terminal decision must not complete with a stale earlier AgentResult."""
    async def noop(state, ctx, scope, config):
        return OperationResult()

    catalog = ExecutionCatalog(
        "fixture",
        (
            ExecutionOperation("fixture.report", noop, produces=("agent_result",)),
            ExecutionOperation("fixture.decide", noop, produces=("decision",)),
        ),
        required_outputs=("agent_result",),
    )
    graph = {
        "schema": "ax4lab.execution_graph.v1",
        "entry": "report",
        "nodes": [
            {"id": "report", "handler": "fixture.report", "area": "middle"},
            {"id": "decide", "handler": "fixture.decide", "area": "high"},
        ],
        "edges": [{"source": "report", "target": "decide", "on": "next", "kind": "execution"}],
        "terminals": ["decide"],
    }

    with pytest.raises(ExecutionGraphError, match="terminal.*agent_result"):
        compile_execution_graph(graph, catalog)


def test_design_outcome_contract_rejects_swapped_accepted_and_blocked_routes():
    """Editable edges must not send a blocked decision through accepted finalization."""
    from agents.design.agent import DesignAgent
    from agents.design.execution import default_design_execution_graph, design_execution_catalog

    graph = deepcopy(default_design_execution_graph())
    for edge in graph["edges"]:
        if edge["source"] == "decide":
            edge["target"] = "owner_review" if edge["on"] == "accepted" else "finalize"

    with pytest.raises(ExecutionGraphError, match="required input"):
        compile_execution_graph(graph, design_execution_catalog(DesignAgent()))


@pytest.mark.asyncio
async def test_design_finalization_defensively_rejects_nonaccepted_decision(monkeypatch):
    """Direct adapter misuse must stop before the original finalizer sees no candidate."""
    from agents.design.agent import DesignAgent
    from agents.design.execution import design_execution_catalog

    agent = DesignAgent()
    called: list[str] = []
    monkeypatch.setattr(agent, "_finalize_design_payload", lambda *args: called.append("finalize"))
    operation = design_execution_catalog(agent).operation("design.finalize")
    scope = {
        "prepared": {},
        "decision": {"status": "review_required"},
        "candidate": None,
        "rationale": "blocked",
        "accepted_decision": False,
    }

    with pytest.raises(ExecutionGraphError, match="accepted decision"):
        await operation.operation(None, None, scope, {})

    assert called == []


@pytest.mark.asyncio
async def test_repeated_decision_clears_stale_outcome_specific_outputs():
    """A later blocked decision must invalidate an earlier accepted candidate marker."""
    outcomes = iter(("accepted", "blocked"))

    async def decide(state, ctx, scope, config):
        outcome = next(outcomes)
        outputs = {"decision": outcome}
        if outcome == "accepted":
            outputs.update(candidate="candidate-1", accepted_marker=True)
        else:
            outputs["review_marker"] = True
        return OperationResult(outcome, outputs)

    async def finalize(state, ctx, scope, config):
        return OperationResult("next", {"agent_result": "finalized"})

    async def review(state, ctx, scope, config):
        return OperationResult("next", {"agent_result": "review"})

    catalog = ExecutionCatalog(
        "fixture",
        (
            ExecutionOperation(
                "fixture.decide",
                decide,
                produces=("decision",),
                outcomes=("accepted", "blocked"),
                outcome_produces={
                    "accepted": ("candidate", "accepted_marker"),
                    "blocked": ("review_marker",),
                },
            ),
            ExecutionOperation(
                "fixture.finalize", finalize, requires=("accepted_marker",), produces=("agent_result",),
            ),
            ExecutionOperation(
                "fixture.review", review, requires=("review_marker",), produces=("agent_result",),
            ),
        ),
        required_outputs=("agent_result",),
    )
    graph = {
        "schema": "ax4lab.execution_graph.v1",
        "entry": "decision_1",
        "nodes": [
            {"id": "decision_1", "handler": "fixture.decide", "area": "high"},
            {"id": "decision_2", "handler": "fixture.decide", "area": "high"},
            {"id": "finalize", "handler": "fixture.finalize", "area": "middle"},
            {"id": "review", "handler": "fixture.review", "area": "guardian"},
        ],
        "edges": [
            {"source": "decision_1", "target": "decision_2", "on": "accepted", "kind": "execution"},
            {"source": "decision_1", "target": "review", "on": "blocked", "kind": "validation"},
            {"source": "decision_2", "target": "finalize", "on": "accepted", "kind": "execution"},
            {"source": "decision_2", "target": "review", "on": "blocked", "kind": "validation"},
        ],
        "terminals": ["finalize", "review"],
    }

    result = await run_execution_graph(compile_execution_graph(graph, catalog), None, None)

    assert result.result == "review"
    assert "candidate" not in result.outputs
    assert "accepted_marker" not in result.outputs
