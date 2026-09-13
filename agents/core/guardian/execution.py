"""Guardian's archived owner body as one guarded composite operation."""

from __future__ import annotations

from copy import deepcopy

from agents.base_agent import AgentResult
from agents.core.guardian.structure import guardian_implementation_structure
from agents.execution_graph import (
    ExecutionCatalog,
    ExecutionGraphError,
    ExecutionOperation,
    OperationResult,
    compile_execution_graph,
    installed_execution_graph,
    run_execution_graph,
)


def default_guardian_execution_graph():
    return installed_execution_graph("guardian")


def guardian_execution_catalog(agent):
    async def task(state, ctx, scope, config):
        if scope.get("task_started"):
            raise ExecutionGraphError("Guardian task cannot repeat within an invocation")
        scope["task_started"] = True
        return OperationResult("next", {"task_result": await agent._run_task(state, ctx)})

    async def deliver(state, ctx, scope, config):
        result = scope["task_result"]
        if not isinstance(result, AgentResult):
            raise ExecutionGraphError("Guardian delivery requires an owner AgentResult")
        return OperationResult("next", {"agent_result": result})

    return ExecutionCatalog(
        "guardian",
        (
            ExecutionOperation(
                "guardian.task",
                task,
                label="Composite deterministic gates and advisory policy task",
                produces=("task_result",),
                llm=True,
            ),
            ExecutionOperation(
                "guardian.deliver",
                deliver,
                label="Deliver owner result",
                requires=("task_result",),
                produces=("agent_result",),
            ),
        ),
        required_outputs=("agent_result",),
        implementation_structure=guardian_implementation_structure,
    )


async def execute_guardian_graph(agent, state, ctx, *, graph=None, emit=None, invocation=None):
    compiled = compile_execution_graph(
        deepcopy(dict(graph)) if graph is not None else default_guardian_execution_graph(),
        guardian_execution_catalog(agent),
    )
    return await run_execution_graph(compiled, state, ctx, emit=emit, invocation=invocation)
