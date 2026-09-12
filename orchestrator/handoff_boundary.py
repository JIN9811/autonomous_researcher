"""Invocation-local adapters for the existing controller/runtime handoffs."""
from copy import deepcopy
import asyncio
import json

from orchestrator.orchestrator_checkpoint import handoff_checkpoint
from orchestrator.supervisor import build_orchestrator_handoff_packet
from orchestrator.handoff_projection import project_handoff_prompt


def review_revision(state) -> str:
    """Only explicit replies or owner evidence changes reopen a held decision."""
    return json.dumps({"reply": state.run_metadata.get("orchestrator_review_revision", 0),
                       "owners": state.run_metadata.get("availability_reports", {})}, sort_keys=True)


def authorization_scope(state) -> dict:
    """Inputs that must remain fixed through consumption; stage may advance.

    Owner-produced observations/results are metadata, not specimen inputs. Those
    may evolve inside the admitted observation task without another model call.
    """
    metadata = state.run_metadata
    boundary = metadata.get("orchestrator_planning_boundary", {})
    return deepcopy({"run_id": state.run_id, "loop": state.loop_count, "mode": state.mode.value,
        "goal": state.active_goal, "specimen": state.current_experiment_spec,
        "setup": metadata.get("experimental_setup_snapshot"), "owners": metadata.get("availability_reports", {}),
        "policy": metadata.get("execution_policy"),
        "planning": {key: boundary.get(key) for key in ("task_id", "goal", "constraints", "previous_spec")},
        "stop": bool(state.stop_requested or state.safe_stop_requested or state.emergency_stop_requested)})


def authorization_matches(state, record: dict) -> bool:
    return record.get("payload", {}).get("authorization_scope") == authorization_scope(state)


def incoming_authorization_matches(state, incoming: dict, record: dict) -> bool:
    if record.get("status") != "consumed":
        return False
    if authorization_matches(state, record):
        return True
    # The controller's synchronous Design input builder is the only supported
    # materialization. Preserve the original consumed decision for audit.
    materialized = incoming.get("materialization", {})
    return (materialized.get("owner") == "planning_design_input"
            and materialized.get("source") == record.get("payload", {}).get("authorization_scope")
            and materialized.get("scope") == authorization_scope(state))


async def review_handoff(*, state, ctx, registry, catalog, key: str,
                         candidate: str, payload: dict, settings: dict,
                         agent_name: str = "orchestrator_agent") -> dict:
    """Review a dispatcher-admitted packet, without executing the next owner.

    A prepared packet means the existing owner may perform its own admission;
    unknown optional availability does not manufacture readiness or add a gate.
    Waits are persistent and polling is read-only until evidence/reply changes.
    """
    metadata = state.run_metadata
    record = handoff_checkpoint(metadata, key, action="read")
    revision = review_revision(state)
    request_input = {"candidate": candidate, "payload": {name: deepcopy(value) for name, value in payload.items()
        if name not in {"decision", "agent_data", "authorization_scope", "authorization_request"}}}
    if record.get("status") == "consumed" or record.get("payload", {}).get("decision", {}).get("status") == "prepared":
        if not authorization_matches(state, record) or record["payload"].get("authorization_request") != request_input:
            return {**record, "status": "stale", "consume_now": False}
    if record.get("status") == "consumed":
        return record
    if record.get("status") == "deferred" and record.get("wait", {}).get("revision") == revision:
        return record
    if record.get("payload", {}).get("decision", {}).get("status") == "prepared":
        return record
    record = handoff_checkpoint(metadata, key, action="prepare", payload=payload)
    admitted_scope = authorization_scope(state)
    admitted_payload = deepcopy(payload)
    evidence = {"boundary:result": deepcopy(record["payload"])}
    bindings = catalog.describe(state, ctx)
    owners = sorted({b["owner"] for b in bindings if b.get("owner")})
    def current_scope():
        return {"checkpoint": key, "revision": handoff_checkpoint(metadata, key, action="read").get("revision"),
                "input": revision, "current_input": review_revision(state),
                "setup_revision": metadata.get("experimental_setup_snapshot", {}).get("revision"),
                "specimen_input": json.dumps(state.current_experiment_spec, sort_keys=True),
                "authorization": authorization_scope(state),
                "request_payload": deepcopy(payload),
                "stop": bool(state.stop_requested or state.safe_stop_requested or state.emergency_stop_requested)}
    scope = current_scope()
    async def prepare(arguments):
        if current_scope() != scope or scope["stop"]:
            return {"status": "stale", "reason": "Handoff scope changed or stopped"}
        return build_orchestrator_handoff_packet(state=state, from_stage=state.stage,
            to_stage=arguments["candidate"], result_payload=admitted_payload.get("result_data", admitted_payload),
            selected_transition=payload.get("selected_transition"), guardian_context=payload.get("guardian_context"))
    async def defer(arguments):
        return {"status": "deferred", "condition": arguments["condition"]}
    async def inspect_context(arguments):
        return {"evidence": {eid: evidence[eid] for eid in arguments["evidence_ids"]}}
    async def inspect_availability(arguments):
        report = await catalog.inspect(arguments["owner"], arguments["capability"], state, ctx)
        return {"report": report}
    async def request_review(arguments):
        return {"status": "review_required", "owner": arguments["owner"], "issues": arguments["issues"]}
    context = {"scope": scope, "current_scope": current_scope, "settings": deepcopy(settings),
        "prompt_projection": project_handoff_prompt,
        "evidence": evidence, "required_evidence": ["boundary:result"],
        "handoff_candidates": [candidate], "owners": owners,
        "capabilities": {owner: ["inspect"] for owner in owners},
        "request": {"purpose": "Review the dispatcher handoff; owner admission remains authoritative.",
                    "candidate": candidate,
                    "operator_followups": deepcopy(metadata.get("operator_followup_context", [])[-20:])}}
    handlers = {"prepare_handoff": prepare, "defer": defer, "inspect_context": inspect_context,
                "inspect_availability": inspect_availability, "request_owner_review": request_review}
    try:
        result = await registry.get(agent_name).run(state, ctx, context=context, handlers=handlers)
        decision = result.data["orchestration_decision"]
        agent_data = result.data
    except asyncio.CancelledError:
        handoff_checkpoint(metadata, key, action="defer", payload={"revision": revision, "condition": "cancelled"})
        raise
    except Exception as exc:
        decision = {"status": "failed", "reason": type(exc).__name__}
        agent_data = {}
    handoff_checkpoint(metadata, key, action="prepare", payload={"decision": decision, "agent_data": agent_data,
        "authorization_scope": admitted_scope, "authorization_request": request_input})
    if decision.get("status") != "prepared":
        return handoff_checkpoint(metadata, key, action="defer", payload={"revision": revision,
            "condition": decision.get("reason"), "decision_status": decision.get("status")})
    return handoff_checkpoint(metadata, key, action="read")
