"""Orchestrator owner operations exposed through the shared executable graph."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from agents.base_agent import AgentResult
from agents.execution_graph import (
    ExecutionCatalog,
    ExecutionOperation,
    ExecutionRunResult,
    OperationResult,
    compile_execution_graph,
    installed_execution_graph,
    run_execution_graph,
)
from agents.orchestrator_decision import decide_orchestration
from agents.orchestrator_structure import orchestrator_implementation_structure
from orchestrator.supervisor import (
    build_decision_record,
    build_mission_contract,
    build_orchestration_plan,
    build_orchestrator_control_plane_snapshot,
    build_orchestrator_followup,
)


ORCHESTRATOR_DECISION_OUTCOMES = ("prepared", "proposed", "review_required", "deferred", "failed")


def default_orchestrator_execution_graph() -> dict[str, Any]:
    """Return the installed ORC graph without decorative, nonexecuted pre labels."""
    return installed_execution_graph("orchestrator")


def orchestrator_execution_catalog(
    agent: Any,
    *,
    context: dict[str, Any] | None,
    handlers: dict[str, Any] | None,
) -> ExecutionCatalog:
    """Bind graph operations to existing ORC supervisor and decision functions."""

    async def mission(state, ctx, scope, config):
        return OperationResult("next", {"mission_contract": build_mission_contract(state=state)})

    async def plan(state, ctx, scope, config):
        return OperationResult("next", {"orchestration_plan": build_orchestration_plan(state=state)})

    async def decide(state, ctx, scope, config):
        dispatch_context = context
        dispatch_handlers = handlers
        if dispatch_context is None:
            dispatch_context = {
                "scope": {"checkpoint": "standalone"},
                "evidence": {"context:mission": scope["mission_contract"]},
                "handoff_candidates": [],
                "settings": state.run_metadata.get("orchestrator_decision_settings", {}),
            }

            async def defer(arguments):
                return {"condition": arguments["condition"], "status": "deferred"}

            dispatch_handlers = {"defer": defer}
        decision = await decide_orchestration(
            state, ctx, context=dispatch_context, handlers=dispatch_handlers or {},
        )
        outcome = decision["status"] if decision["status"] in ORCHESTRATOR_DECISION_OUTCOMES else "failed"
        return OperationResult(outcome, {"decision": decision})

    async def report(state, ctx, scope, config):
        decision = scope["decision"]
        mission_contract = scope["mission_contract"]
        orchestration_plan = scope["orchestration_plan"]
        plan_text = decision["reason"][:600]
        model = decision["model"]
        control_plane = build_orchestrator_control_plane_snapshot(
            state=state,
            mission_contract=mission_contract,
            orchestration_plan=orchestration_plan,
            next_action=plan_text,
        )
        followup = build_orchestrator_followup(
            state=state,
            stage=state.stage,
            trigger="pre_stage_plan",
            payload={
                "status": "planning",
                "mission_contract": mission_contract,
                "orchestration_plan": orchestration_plan,
                "plan_text": plan_text,
            },
            next_stage=state.stage,
        )
        record = build_decision_record(
            state=state,
            stage=state.stage,
            decision=decision["tool"] or decision["status"],
            selected=decision["arguments"].get("candidate") if decision["status"] == "prepared" else None,
            reason=decision["reason"],
            evidence_refs=decision["evidence_refs"],
        )
        record["decision_id"] = decision["decision_id"]
        record["status"] = decision["status"]
        result = AgentResult(
            success=decision["status"] == "prepared",
            summary=f"Orchestration decision: {decision['status']}",
            data={
                "plan_text": plan_text,
                "model": model,
                "mission_contract": mission_contract,
                "orchestration_plan": orchestration_plan,
                "orchestrator_control_plane": control_plane,
                "orchestrator_followup": followup,
                "decisions": [record],
                "orchestration_decision": decision,
                "metrics": {
                    "plan_text_chars": len(plan_text),
                    "followup_confidence": followup.get("confidence", 0.0),
                    "route_stage_count": len(orchestration_plan.get("route", [])),
                    "parallelizable_check_count": len(orchestration_plan.get("parallelizable_checks", [])),
                },
            },
        )
        return OperationResult("next", {"agent_result": result})

    return ExecutionCatalog(
        module_id="orchestrator",
        operations=(
            ExecutionOperation("orchestrator.mission", mission, label="Build mission contract", produces=("mission_contract",)),
            ExecutionOperation(
                "orchestrator.plan", plan, label="Build orchestration plan",
                produces=("orchestration_plan",),
            ),
            ExecutionOperation(
                "orchestrator.decide", decide, label="Composite bounded handoff decision",
                requires=("mission_contract", "orchestration_plan"), produces=("decision",),
                outcomes=ORCHESTRATOR_DECISION_OUTCOMES, llm=True,
            ),
            ExecutionOperation(
                "orchestrator.report", report, label="Build control, follow-up and decision records",
                requires=("mission_contract", "orchestration_plan", "decision"), produces=("agent_result",),
            ),
        ),
        required_outputs=("agent_result",),
        implementation_structure=orchestrator_implementation_structure,
    )


async def execute_orchestrator_graph(
    agent: Any,
    state: Any,
    ctx: Any,
    *,
    context: dict[str, Any] | None = None,
    handlers: dict[str, Any] | None = None,
    graph: Mapping[str, Any] | None = None,
    emit: Any = None,
    invocation: Mapping[str, Any] | None = None,
) -> ExecutionRunResult:
    """Compile one detached ORC definition and execute its registered route."""
    compiled = compile_execution_graph(
        deepcopy(dict(graph)) if graph is not None else default_orchestrator_execution_graph(),
        orchestrator_execution_catalog(agent, context=context, handlers=handlers),
    )
    return await run_execution_graph(compiled, state, ctx, emit=emit, invocation=invocation)
