"""Design-owned adapters for the shared executable graph.

Each operation delegates to the existing Design preparation, decision, report and
handoff functions.  The graph changes routing only; it does not replace their
scientific or validation logic.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from agents.base_agent import AgentResult
from agents.design.decision import decide_design
from agents.execution_graph import (
    ExecutionCatalog,
    ExecutionGraphError,
    ExecutionOperation,
    ExecutionRunResult,
    OperationResult,
    compile_execution_graph,
    installed_execution_graph,
    run_execution_graph,
)
from orchestrator.state import Mode


def default_design_execution_graph() -> dict[str, Any]:
    """Return the installed Design definition used when no module context exists."""
    return installed_execution_graph("design")


def design_execution_catalog(agent: Any) -> ExecutionCatalog:
    """Bind public operation IDs to the existing Design owner's methods."""

    async def prepare(state, ctx, scope, config):
        return OperationResult("next", {"prepared": agent._prepare_design_payload(state, ctx)})

    async def decide(state, ctx, scope, config):
        prepared = scope["prepared"]
        use_llm = state.mode != Mode.TEST or ctx.force_real_llm_in_test
        if not use_llm:
            decision = {"status": "deterministic_test", "trace": [], "llm_used": False}
            return OperationResult("accepted", {
                "decision": decision,
                "candidate": prepared["ranked"][0],
                "rationale": "Deterministic test-mode specimen candidate generated from docs algorithm.",
                "accepted_decision": True,
            })
        decision = await decide_design(agent, state, ctx, prepared)
        if decision["status"] != "accepted":
            return OperationResult("blocked", {
                "decision": decision,
                "rationale": decision.get("reason", ""),
                "review_decision": True,
            })
        candidate = next(item for item in prepared["ranked"] if item["candidate_id"] == decision["candidate_id"])
        return OperationResult("accepted", {
            "decision": decision,
            "candidate": candidate,
            "rationale": decision["reason"],
            "accepted_decision": True,
        })

    async def finalize(state, ctx, scope, config):
        decision = scope["decision"]
        if decision.get("status") not in {"accepted", "deterministic_test"} or scope.get("accepted_decision") is not True:
            raise ExecutionGraphError("Design finalization requires an accepted decision")
        owner_decision = decision if decision.get("status") == "accepted" else None
        payload = agent._finalize_design_payload(state, ctx, scope["prepared"], scope["candidate"], owner_decision)
        if owner_decision is None:
            payload["design_decision"] = decision
        result = AgentResult(
            success=True,
            summary="Specimen experiment design selected",
            data={**payload, "rationale": scope["rationale"]},
        )
        return OperationResult("next", {"agent_result": result})

    async def review_result(state, ctx, scope, config):
        decision = scope["decision"]
        if scope.get("review_decision") is not True:
            raise ExecutionGraphError("Design review result requires a blocked decision")
        blocked_report = {
            "schema": "design_report.v1", "run_id": state.run_id,
            "report_id": f"design-report-{state.run_id or 'run'}-{state.loop_count + 1}",
            "loop_index": state.loop_count + 1, "status": decision["status"],
            "evaluation_semantics": "evidence_based_v1", "design_decision": decision,
            "handoff_to_specimen": {"required_fields_present": False, "status": "blocked"},
            "next_action": "review_design_decision", "candidate_evaluation": {},
        }
        result = AgentResult(
            success=False,
            summary="Design decision requires owner review",
            data={
                "design_decision": decision,
                "failure_code": decision.get("failure_code"),
                "design_report": blocked_report,
                "design_agent_report": {**blocked_report, "schema": "design_agent_report.v1"},
            },
            next_hint="Review Design decision evidence; no candidate was committed.",
        )
        return OperationResult("next", {"agent_result": result})

    return ExecutionCatalog(
        module_id="design",
        operations=(
            ExecutionOperation(
                "design.prepare", prepare, label="Prepare candidates and evidence",
                produces=("prepared",),
            ),
            ExecutionOperation(
                "design.decide", decide, label="Composite bounded suitability decision",
                requires=("prepared",), produces=("decision", "rationale"),
                outcomes=("accepted", "blocked"), llm=True,
                outcome_produces={
                    "accepted": ("candidate", "accepted_decision"),
                    "blocked": ("review_decision",),
                },
            ),
            ExecutionOperation(
                "design.finalize", finalize, label="Finalize accepted design and handoff",
                requires=("prepared", "decision", "candidate", "rationale", "accepted_decision"),
                produces=("agent_result",),
            ),
            ExecutionOperation(
                "design.review_result", review_result, label="Return review-required result",
                requires=("decision", "review_decision"), produces=("agent_result",),
            ),
        ),
        required_outputs=("agent_result",),
    )


async def execute_design_graph(
    agent: Any,
    state: Any,
    ctx: Any,
    *,
    graph: Mapping[str, Any] | None = None,
    emit: Any = None,
    invocation: Mapping[str, Any] | None = None,
) -> ExecutionRunResult:
    """Compile one detached Design definition and execute its registered route."""
    compiled = compile_execution_graph(
        deepcopy(dict(graph)) if graph is not None else default_design_execution_graph(),
        design_execution_catalog(agent),
    )
    return await run_execution_graph(compiled, state, ctx, emit=emit, invocation=invocation)
