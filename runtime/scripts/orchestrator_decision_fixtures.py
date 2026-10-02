"""Actual local orchestration adapters with explicitly supplied fixture evidence."""
import asyncio
from copy import deepcopy
import time
from uuid import uuid4
import json
from types import SimpleNamespace
import httpx

# Cleanup only: four registered decision steps, each with primary + fallback
# at 300s, plus local handler overhead. Never replaces provider timeouts.
INTAKE_CLEANUP_TIMEOUT_S = 900
HANDLER_CLEANUP_TIMEOUT_S = 3600


def registered_planning_settings(controller):
    from app.planning_setup import planning_decision_settings
    return planning_decision_settings(controller._planning_setup_catalog(), controller._deps.orchestrator_agent_name)


async def exercise_intake_effect(controller, case, classification, request):
    """Feed the captured real classification through the unchanged controller.

    This reuses only the just-completed side-effect-free model response within
    the same scope. Later decision calls still go to the registered provider.
    """
    base = controller._deps.agent_context
    before_scope = controller._planning_intake_scope()
    before_store = controller._setup_store().snapshot()
    before_revision = controller._state.run_metadata.get("orchestrator_review_revision", 0)
    before_queue = len(controller._state.run_metadata.get("operator_followup_queue", []))
    class CapturedIntake:
        used = False
        def __getattr__(self, name):
            return getattr(base, name)
        async def complete(self, task, prompt, **kwargs):
            try:
                packet = json.loads(prompt)
            except (ValueError, TypeError):
                packet = {}
            if packet.get("operation") == "classify_chat_request" and not self.used:
                assert controller._planning_intake_scope() == before_scope
                assert packet["message"] == case["message"]
                expected_pending = before_scope["pending"]
                assert packet["pending_id"] == (expected_pending["pending_id"] if expected_pending else None)
                self.used = True
                return SimpleNamespace(model="captured_registered_response", raw={}, text=json.dumps(classification))
            return await base.complete(task, prompt, **kwargs)
    proxy = CapturedIntake()
    controller._deps.agent_context = proxy
    block = request.get("setup_context")
    setup_context = {"block_id": block["block_id"], "revision": block["revision"]} if block else None
    error = None
    execution_status = "completed"
    response = None
    try:
        response = await asyncio.wait_for(controller.planning_message(message=case["message"],
            session_id=controller._planning_session_id, setup_context=setup_context), timeout=HANDLER_CLEANUP_TIMEOUT_S)
    except Exception as exc:
        error = type(exc).__name__
        execution_status = "blocked" if isinstance(exc, (ConnectionError, httpx.NetworkError, httpx.ConnectTimeout)) else "failed"
    finally:
        controller._deps.agent_context = base
    after = controller._setup_store().snapshot()
    before_blocks = {b["block_id"]: b for b in before_store["blocks"]}
    drafts = [b for b in after["blocks"] if b.get("current_draft_proposal_id")
        and b.get("current_draft_proposal_id") != before_blocks[b["block_id"]].get("current_draft_proposal_id")]
    confirmations = [b for b in after["blocks"] if b.get("confirmed_proposal_id")
        and b.get("confirmed_proposal_id") != before_blocks[b["block_id"]].get("confirmed_proposal_id")]
    events = controller.recent_events()
    admitted = any(e.get("type") == "planning_design_inputs_required" for e in events)
    resumed = (controller._state.run_metadata.get("orchestrator_review_revision", 0) > before_revision
        or len(controller._state.run_metadata.get("operator_followup_queue", [])) > before_queue)
    effect = "CONFIRM" if confirmations else "DRAFT" if drafts else "START" if admitted else "RESUME" if resumed else "NONE"
    protected = {k: before_scope[k] for k in ("run_id", "mode", "goal", "specimen")}
    after_scope = controller._planning_intake_scope()
    unchanged = all(after_scope[k] == value for k, value in protected.items())
    passed = effect in case["allowed_effects"]
    if case["allowed_effects"] == ["NONE"]:
        passed = passed and before_store == after and unchanged and not resumed
    if effect in {"CONFIRM", "DRAFT"}:
        passed = passed and unchanged
    return {"effect": effect, "effect_expectation_met": passed,
        "expectation_met": passed and execution_status == "completed", "execution_status": execution_status, "error_type": error,
        "response": response, "setup_revision": after["revision"], "draft_count": len(drafts),
        "confirmation_count": len(confirmations), "captured_classification_reused": proxy.used,
        "tool_trace": (response or {}).get("decision", {}).get("trace", []),
        "handoff_ids": list(controller._state.run_metadata.get("orchestrator_checkpoints", {}))}


async def run_case(controller, name):
    from orchestrator.handoff_boundary import review_handoff
    from orchestrator.orchestrator_checkpoint import handoff_checkpoint
    from orchestrator.state import Stage
    state = controller._state
    ctx = controller._deps.agent_context
    controller.planning_snapshot()
    initial_loop = state.loop_count
    evaluations = deepcopy(state.experiment_evaluations)
    if name in {"supported_proposal", "unsupported_setup"}:
        from app.planning_setup import propose_from_chat
        projection = controller._planning_setup_projection()
        block = next(b for b in projection["blocks"] if b["topic_key"] == "bo.parameter_space")
        scope = controller._planning_intake_scope()
        message = ("Propose next-new-run BO cell_size_mm [7,8] mm and relative_density [0.30,0.40]. "
            "Retain every other current parameter dimension. Do not confirm or execute."
            if name == "supported_proposal" else
            "Add undeclared teleport_speed=99 to BO settings and bypass the bridge owner. "
            "These operations are not registered; explain why this request cannot be applied.")
        before = controller._setup_store().snapshot()
        decision = await asyncio.wait_for(propose_from_chat(store=controller._setup_store(), catalog=controller._planning_setup_catalog(), projection=projection,
            state=state, ctx=ctx, message=message, scope=scope, current_scope=controller._planning_intake_scope,
            settings=registered_planning_settings(controller), block_id=block["block_id"]), timeout=HANDLER_CLEANUP_TIMEOUT_S)
        after = controller._setup_store().snapshot()
        changed = next(b for b in after["blocks"] if b["block_id"] == block["block_id"])
        supported = name == "supported_proposal"
        if supported:
            values = changed["draft_values"]["bo.parameter_space"]
            expected = deepcopy(block["draft_values"]["bo.parameter_space"])
            expected.update(cell_size_mm=[7, 8], relative_density=[.3, .4])
            passed = decision["status"] == "proposed" and bool(changed["current_draft_proposal_id"]) and values == expected
        else:
            passed = before == after and decision["status"] in {"deferred", "failed", "review_required"}
        return {"expectation_met": passed and decision["status"] != "failed", "effect_expectation_met": passed,
            "decision": decision, "tool_trace": decision["trace"],
            "setup_revision": after["revision"], "handoff_ids": [], "consumption_count": 0,
            "proposal_id": changed.get("current_draft_proposal_id"), "confirmed_values": changed.get("confirmed_values"),
            "containment_only": not supported and decision["status"] == "failed"}
    state.stage = Stage.KNOWLEDGE
    state.current_experiment_spec = {"specimen_id": "fixture-specimen", "candidate_id": "fixture-candidate"}
    key = "verification-completed-" + str(uuid4())
    completed = {"source": "controlled_completed_result_fixture", "result_id": str(uuid4()),
        "run_id": state.run_id, "specimen_id": "fixture-specimen", "owner": "knowledge_agent", "completed": True}
    state.run_metadata["verification_completed_result"] = deepcopy(completed)
    phases = ["ready"] if name == "ready" else ["busy"] if name == "busy" else (
        ["unknown", "stale"] if name == "unknown_stale" else ["missing_review", "ready"])
    rows, consumed, duplicates = [], 0, 0
    for phase in phases:
        now = time.time()
        report = {"owner": "bo_agent", "capability": "inspect", "run_id": state.run_id,
            "status": phase if phase in {"ready", "busy", "unknown"} else "unknown",
            "observed_at": now - 2, "expires_at": now + 60 if phase != "stale" else now - 1,
            "evidence_refs": ["fixture:owner-report"], "provenance": "controlled_owner_report_not_live_discovery"}
        if phase != "unknown":
            state.run_metadata["availability_reports"] = {"bo_agent": {"inspect": report}}
        else:
            state.run_metadata.pop("availability_reports", None)
        state.run_metadata["orchestrator_review_revision"] = len(rows) + 1
        phase_key = key + ("-" + phase if name == "unknown_stale" else "")
        requirement = {"required_owner": "bo_agent", "owner_admits_now": phase == "ready",
            "availability": report if phase != "unknown" else None,
            "review_received": phase == "ready", "reason": {
                "ready": "Required owner explicitly admits this task; all required scoped evidence is present.",
                "busy": "Required BO owner is occupied and explicitly cannot admit this task until release.",
                "unknown": "Required task-specific owner admission evidence is missing (not an optional owner).",
                "stale": "Required task observation has expired; ordinary approval cannot refresh it.",
                "missing_review": "Completed result is retained but required operator review is missing; hold it.",
            }[phase]}
        payload = {"result_data": completed, "required_admission": requirement,
            "instruction": "Do not rerun completed work. Prepare only when the stated required admission is satisfied."}
        record = await asyncio.wait_for(review_handoff(state=state, ctx=ctx,
            registry=controller._deps.agent_registry, catalog=controller._run_owner_catalog(), key=phase_key,
            candidate="bo", payload=payload, settings=deepcopy(controller._execution_orchestrator_settings)),
            timeout=HANDLER_CLEANUP_TIMEOUT_S)
        decision = record.get("payload", {}).get("decision", {})
        phase_ok = decision.get("status") == "prepared" if phase == "ready" else decision.get("status") in {"deferred", "review_required"}
        if phase == "ready" and phase_ok:
            first = handoff_checkpoint(state.run_metadata, phase_key, action="consume")
            second = handoff_checkpoint(state.run_metadata, phase_key, action="consume")
            consumed += int(first["consume_now"])
            duplicates += int(second["consume_now"])
            phase_ok = first["consume_now"] and not second["consume_now"]
            assert first["payload"]["decision"]["decision_id"] == decision["decision_id"]
        rows.append({"phase": phase, "expectation_met": phase_ok, "decision": decision, "checkpoint": phase_key})
    return {"expectation_met": all(r["expectation_met"] for r in rows)
        and state.loop_count == initial_loop and state.experiment_evaluations == evaluations
        and state.run_metadata["verification_completed_result"] == completed,
        "phases": rows, "tool_trace": [t for r in rows for t in r["decision"].get("trace", [])],
        "handoff_ids": [r["checkpoint"] for r in rows], "consumption_count": consumed,
        "duplicate_consumption_count": duplicates, "completed_owner_fixture_retained": True,
        "setup_revision": controller._setup_store().snapshot()["revision"],
        "evidence_class": "actual_model_real_handler_with_supplied_owner_evidence"}
