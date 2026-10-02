"""The existing Equipment workflow is one allowlisted composite operation."""
from copy import deepcopy

from agents.base_agent import AgentResult
from agents.equipment.structure import equipment_implementation_structure
from agents.execution_graph import (
    ExecutionCatalog,
    ExecutionGraphError,
    ExecutionOperation,
    OperationResult,
    compile_execution_graph,
    installed_execution_graph,
    run_execution_graph,
)


def default_equipment_execution_graph():
    return installed_execution_graph("equipment")


def equipment_execution_catalog(agent):
    async def task(state, ctx, scope, config):
        if scope.get("task_started"):
            raise ExecutionGraphError("Equipment task cannot repeat within an invocation")
        scope["task_started"] = True
        return OperationResult("next", {"task_result": await agent._run_task(state, ctx)})

    async def deliver(state, ctx, scope, config):
        result = scope["task_result"]
        if not isinstance(result, AgentResult):
            raise ExecutionGraphError("Equipment delivery requires an owner AgentResult")
        return OperationResult("next", {"agent_result": result})

    return ExecutionCatalog(
        "equipment",
        (
            ExecutionOperation(
                "equipment.task",
                task,
                label="Composite bounded equipment task",
                produces=("task_result",),
                llm=True,
            ),
            ExecutionOperation(
                "equipment.deliver",
                deliver,
                label="Deliver owner result",
                requires=("task_result",),
                produces=("agent_result",),
            ),
        ),
        required_outputs=("agent_result",),
        implementation_structure=equipment_implementation_structure,
    )


async def execute_equipment_graph(agent, state, ctx, *, graph=None, emit=None, invocation=None):
    compiled = compile_execution_graph(
        deepcopy(dict(graph)) if graph is not None else default_equipment_execution_graph(),
        equipment_execution_catalog(agent),
    )
    return await run_execution_graph(compiled, state, ctx, emit=emit, invocation=invocation)
