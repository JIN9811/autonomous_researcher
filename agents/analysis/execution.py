"""The archived Analysis owner body is one guarded composite operation."""
from copy import deepcopy

from agents.analysis.structure import analysis_implementation_structure
from agents.base_agent import AgentResult
from agents.execution_graph import (
    ExecutionCatalog,
    ExecutionGraphError,
    ExecutionOperation,
    OperationResult,
    compile_execution_graph,
    installed_execution_graph,
    run_execution_graph,
)


def default_analysis_execution_graph():
    return installed_execution_graph("analysis")


def analysis_execution_catalog(agent):
    async def task(state, ctx, scope, config):
        if scope.get("task_started"):
            raise ExecutionGraphError("Analysis task cannot repeat within an invocation")
        scope["task_started"] = True
        return OperationResult("next", {"task_result": await agent._run_task(state, ctx)})

    async def deliver(state, ctx, scope, config):
        result = scope["task_result"]
        if not isinstance(result, AgentResult):
            raise ExecutionGraphError("Analysis delivery requires an owner AgentResult")
        return OperationResult("next", {"agent_result": result})

    return ExecutionCatalog(
        "analysis",
        (
            ExecutionOperation(
                "analysis.task",
                task,
                label="Composite measured analysis and optional background FEM task",
                produces=("task_result",),
                llm=True,
            ),
            ExecutionOperation(
                "analysis.deliver",
                deliver,
                label="Deliver owner result",
                requires=("task_result",),
                produces=("agent_result",),
            ),
        ),
        required_outputs=("agent_result",),
        implementation_structure=analysis_implementation_structure,
    )


async def execute_analysis_graph(agent, state, ctx, *, graph=None, emit=None, invocation=None):
    compiled = compile_execution_graph(
        deepcopy(dict(graph)) if graph is not None else default_analysis_execution_graph(),
        analysis_execution_catalog(agent),
    )
    return await run_execution_graph(compiled, state, ctx, emit=emit, invocation=invocation)
