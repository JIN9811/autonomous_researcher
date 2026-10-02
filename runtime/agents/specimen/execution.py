"""Specimen owner operations for the shared allowlisted execution graph."""
from copy import deepcopy

from agents.base_agent import AgentResult
from agents.execution_graph import (
    ExecutionCatalog, ExecutionGraphError, ExecutionOperation, OperationResult,
    compile_execution_graph, installed_execution_graph, run_execution_graph,
)
from agents.specimen.structure import specimen_implementation_structure


def default_specimen_execution_graph():
    return installed_execution_graph("specimen")


def specimen_execution_catalog(agent):
    async def prepare(state, ctx, scope, config):
        if scope.get("preparation_started"):
            raise ExecutionGraphError("Specimen preparation cannot repeat within an invocation")
        scope["preparation_started"] = True
        from utils.compute_pool import compute_enabled
        prepared = (await agent._prepare_fabrication_async(state, ctx) if compute_enabled()
                    else agent._prepare_fabrication(state, ctx))
        if isinstance(prepared, AgentResult):
            return OperationResult("operator_input", {"pending_result": prepared})
        return OperationResult("ready", {"prepared": prepared})

    async def decide(state, ctx, scope, config):
        if scope.get("fabrication_started"):
            raise ExecutionGraphError("Specimen fabrication decision cannot repeat within an invocation")
        # Set before awaiting: uncertain effects are never replayed by graph routing.
        scope["fabrication_started"] = True
        decision = await agent._decide_fabrication(state, ctx, scope["prepared"])
        executed = decision["experiment_response"] is not None
        return OperationResult("executed" if executed else "blocked", {
            "decision": decision, "executed_decision" if executed else "review_decision": True,
        })

    async def finalize(state, ctx, scope, config):
        if scope.get("executed_decision") is not True or scope["decision"]["experiment_response"] is None:
            raise ExecutionGraphError("Specimen finalization requires fabrication response")
        return OperationResult("next", {"agent_result": agent._finalize_fabrication(state, scope["prepared"], scope["decision"])})

    async def review(state, ctx, scope, config):
        if scope.get("review_decision") is not True:
            raise ExecutionGraphError("Specimen review requires blocked decision")
        return OperationResult("next", {"agent_result": agent._review_fabrication(scope["prepared"], scope["decision"])})

    async def operator_input(state, ctx, scope, config):
        return OperationResult("next", {"agent_result": scope["pending_result"]})

    return ExecutionCatalog(
        "specimen", (
            ExecutionOperation("specimen.prepare", prepare, label="Prepare geometry and manufacturing evidence",
                               outcomes=("ready", "operator_input"),
                               outcome_produces={"ready": ("prepared",), "operator_input": ("pending_result",)}),
            ExecutionOperation("specimen.decide", decide, label="Bounded fabrication decision and execution",
                               requires=("prepared",), produces=("decision",), outcomes=("executed", "blocked"), llm=True,
                               outcome_produces={"executed": ("executed_decision",), "blocked": ("review_decision",)}),
            ExecutionOperation("specimen.finalize", finalize, label="Build fabrication report and handoff",
                               requires=("prepared", "decision", "executed_decision"), produces=("agent_result",)),
            ExecutionOperation("specimen.review", review, label="Return owner review result",
                               requires=("prepared", "decision", "review_decision"), produces=("agent_result",)),
            ExecutionOperation("specimen.operator_input", operator_input, label="Return printer path request",
                               requires=("pending_result",), produces=("agent_result",)),
        ), required_outputs=("agent_result",), implementation_structure=specimen_implementation_structure,
    )


async def execute_specimen_graph(agent, state, ctx, *, graph=None, emit=None, invocation=None):
    compiled = compile_execution_graph(
        deepcopy(dict(graph)) if graph is not None else default_specimen_execution_graph(),
        specimen_execution_catalog(agent),
    )
    return await run_execution_graph(compiled, state, ctx, emit=emit, invocation=invocation)
