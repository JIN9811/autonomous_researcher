"""Vision's real owner boundaries for the shared allowlisted graph runner."""
from copy import deepcopy

from agents.base_agent import AgentResult
from agents.execution_graph import (
    ExecutionCatalog, ExecutionGraphError, ExecutionOperation, OperationResult,
    compile_execution_graph, installed_execution_graph, run_execution_graph,
)
from agents.vision.structure import vision_implementation_structure


def default_vision_execution_graph():
    return installed_execution_graph("vision")


def vision_execution_catalog(agent):
    def once(scope, key):
        if scope.get(key):
            raise ExecutionGraphError("Vision owner operation cannot repeat within an invocation")
        # Mark before entering code that can await or have uncertain device effects.
        scope[key] = True

    async def prepare(state, ctx, scope, config):
        once(scope, "preparation_started")
        prepared = agent._prepare_observation(state, ctx)
        if isinstance(prepared, AgentResult):
            return OperationResult("prepared_result", {"prepared_result": prepared})
        if prepared["route"] == "clearance":
            return OperationResult("clearance", {"clearance_admitted": True})
        return OperationResult("ready", {"observation_prepared": prepared})

    async def observe(state, ctx, scope, config):
        once(scope, "observation_started")
        result = await agent._observe_and_review(state, ctx, scope["observation_prepared"])
        return OperationResult("next", {"observation_result": result})

    async def clearance(state, ctx, scope, config):
        once(scope, "clearance_started")
        if scope.get("clearance_admitted") is not True:
            raise ExecutionGraphError("Vision clearance requires its admission branch")
        return OperationResult("next", {"clearance_result": await agent._verify_clearance(state, ctx)})

    def delivery(key):
        async def deliver(state, ctx, scope, config):
            result = scope[key]
            if not isinstance(result, AgentResult):
                raise ExecutionGraphError("Vision delivery requires an owner AgentResult")
            return OperationResult("next", {"agent_result": result})
        return deliver

    return ExecutionCatalog("vision", (
        ExecutionOperation("vision.prepare", prepare, label="Task admission and preflight",
            outcomes=("ready", "clearance", "prepared_result"), outcome_produces={
                "ready": ("observation_prepared",), "clearance": ("clearance_admitted",),
                "prepared_result": ("prepared_result",)}),
        ExecutionOperation("vision.observe", observe, label="Composite observation, interlock, stop and review",
            requires=("observation_prepared",), produces=("observation_result",), llm=True),
        ExecutionOperation("vision.clearance", clearance, label="Composite UTM clearance verification and review",
            requires=("clearance_admitted",), produces=("clearance_result",), llm=True),
        ExecutionOperation("vision.deliver", delivery("observation_result"), label="Deliver observation result",
            requires=("observation_result",), produces=("agent_result",)),
        ExecutionOperation("vision.deliver_prepared", delivery("prepared_result"), label="Deliver preflight or stop result",
            requires=("prepared_result",), produces=("agent_result",)),
        ExecutionOperation("vision.deliver_clearance", delivery("clearance_result"), label="Deliver clearance result",
            requires=("clearance_result",), produces=("agent_result",)),
    ), required_outputs=("agent_result",), implementation_structure=vision_implementation_structure)


async def execute_vision_graph(agent, state, ctx, *, graph=None, emit=None, invocation=None):
    compiled = compile_execution_graph(
        deepcopy(dict(graph)) if graph is not None else default_vision_execution_graph(),
        vision_execution_catalog(agent),
    )
    return await run_execution_graph(compiled, state, ctx, emit=emit, invocation=invocation)
