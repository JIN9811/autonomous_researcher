"""The archived BO owner body is one guarded composite operation."""
from copy import deepcopy

from agents.base_agent import AgentResult
from agents.bo.structure import bo_implementation_structure
from agents.execution_graph import (
    ExecutionCatalog,
    ExecutionGraphError,
    ExecutionOperation,
    OperationResult,
    compile_execution_graph,
    installed_execution_graph,
    run_execution_graph,
)


def default_bo_execution_graph():
    return installed_execution_graph("bo")


def bo_execution_catalog(agent):
    async def task(state, ctx, scope, config):
        if scope.get("task_started"):
            raise ExecutionGraphError("BO task cannot repeat within an invocation")
        scope["task_started"] = True
        return OperationResult(
            "next",
            {"task_result": await agent._run_task(state, ctx, scope["settings"])},
        )

    async def deliver(state, ctx, scope, config):
        result = scope["task_result"]
        if not isinstance(result, AgentResult):
            raise ExecutionGraphError("BO delivery requires an owner AgentResult")
        return OperationResult("next", {"agent_result": result})

    return ExecutionCatalog(
        "bo",
        (
            ExecutionOperation(
                "bo.task",
                task,
                label="Composite BO strategy, evidence and numerical task",
                requires=("settings",),
                produces=("task_result",),
                llm=True,
            ),
            ExecutionOperation(
                "bo.deliver",
                deliver,
                label="Deliver owner result",
                requires=("task_result",),
                produces=("agent_result",),
            ),
        ),
        inputs=("settings",),
        required_outputs=("agent_result",),
        implementation_structure=bo_implementation_structure,
    )


async def execute_bo_graph(
    agent, state, ctx, *, settings, graph=None, emit=None, invocation=None,
):
    compiled = compile_execution_graph(
        deepcopy(dict(graph)) if graph is not None else default_bo_execution_graph(),
        bo_execution_catalog(agent),
    )
    return await run_execution_graph(
        compiled,
        state,
        ctx,
        inputs={"settings": deepcopy(dict(settings))},
        emit=emit,
        invocation=invocation,
    )
