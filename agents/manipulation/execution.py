"""The existing Manipulation workflow is one allowlisted composite operation."""
from copy import deepcopy

from agents.base_agent import AgentResult
from agents.execution_graph import (
    ExecutionCatalog, ExecutionGraphError, ExecutionOperation, OperationResult,
    compile_execution_graph, installed_execution_graph, run_execution_graph,
)
from agents.manipulation.structure import manipulation_implementation_structure


def default_manipulation_execution_graph():
    return installed_execution_graph("manipulation")


def manipulation_execution_catalog(agent):
    async def task(state, ctx, scope, config):
        if scope.get("task_started"):
            raise ExecutionGraphError("Manipulation task cannot repeat within an invocation")
        scope["task_started"] = True
        return OperationResult("next", {"task_result": await agent._run_task(state, ctx)})

    async def deliver(state, ctx, scope, config):
        result = scope["task_result"]
        if not isinstance(result, AgentResult):
            raise ExecutionGraphError("Manipulation delivery requires an owner AgentResult")
        return OperationResult("next", {"agent_result": result})

    return ExecutionCatalog("manipulation", (
        ExecutionOperation("manipulation.task", task, label="Composite bounded manipulation task",
            produces=("task_result",), llm=True),
        ExecutionOperation("manipulation.deliver", deliver, label="Deliver owner result",
            requires=("task_result",), produces=("agent_result",)),
    ), required_outputs=("agent_result",), implementation_structure=manipulation_implementation_structure)


async def execute_manipulation_graph(agent, state, ctx, *, graph=None, emit=None, invocation=None):
    compiled = compile_execution_graph(
        deepcopy(dict(graph)) if graph is not None else default_manipulation_execution_graph(),
        manipulation_execution_catalog(agent),
    )
    return await run_execution_graph(compiled, state, ctx, emit=emit, invocation=invocation)
