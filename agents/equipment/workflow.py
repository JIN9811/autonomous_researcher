"""Equipment-owned terminal decisions around the existing stacked Skill Flow.

The durable claim is deliberately stricter than a retry queue: an interrupted
invocation is never replayed automatically. Only the live owner can resume a
proven unexecuted failed block after a bounded recovery and another review.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

from agents.base_agent import AgentResult
from agents.equipment.decision import decide_equipment
from backends.llm_backend import LLMImageInput, MAX_LLM_IMAGE_BYTES
from policies.guardian_gate import equipment_skill_recovery_gate, gate_blocks_execution
from utils.agent_artifact_archive import record_tool_artifact
from utils.equipment_runtime_service import EquipmentRuntimeService
from utils.equipment_skill_runtime import EquipmentSkillRegistry


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


def _bounded_evidence(value, depth=0):
    """Keep raster bytes and credential-bearing fields out of model context."""
    if depth > 10:
        return "[nested evidence omitted]"
    if isinstance(value, dict):
        return {str(key): _bounded_evidence(item, depth + 1) for key, item in list(value.items())[:80]
                if str(key).lower() not in {"token", "headers", "cookies"}
                if not any(part in str(key).lower() for part in
                           ("base64", "api_key", "authorization", "password", "secret", "access_token", "auth_token"))}
    if isinstance(value, (list, tuple)):
        items = [_bounded_evidence(item, depth + 1) for item in value[:64]]
        return items + (["[additional evidence omitted]"] if len(value) > 64 else [])
    if isinstance(value, str):
        return value[:4000] + ("[text truncated]" if len(value) > 4000 else "")
    if isinstance(value, bytes):
        return "[binary evidence supplied through image protocol only]"
    return value


def _terminal_evidence(result):
    data = result.data
    summary = {key: data[key] for key in ("equipment_handoff", "raw_data_export",
        "next_specimen_readiness", "handoff_eligibility", "cross_checks", "equipment_result",
        "equipment_skill_flow_execution", "equipment_skill_exception") if key in data}
    raw_keys = ("ok", "status", "mode", "program_id", "failure_code", "message", "run_id", "specimen_id",
                "executed_action_count", "actuation_performed", "effects_known", "effect_unknown",
                "result_file", "force", "stroke", "height", "data_integrity")
    def raw_summary(raw):
        item = {key: raw[key] for key in raw_keys if key in raw}
        if isinstance(item.get("data_integrity"), dict):
            integrity = item["data_integrity"]
            item["data_integrity"] = {key: integrity[key] for key in
                ("ok", "parse_ok", "local_parse_ok", "missing_columns", "parse_failure_code", "parse_failure_message") if key in integrity}
        return item
    if "equipment_result" in summary:
        summary["equipment_result"] = raw_summary(summary["equipment_result"])
    flow = data.get("equipment_skill_flow_execution") or {}
    summary["equipment_skill_flow_execution"] = {key: flow[key] for key in
        ("flow_id", "flow_execution_id", "profile_id", "run_id", "status", "terminal", "failure_code", "transitions") if key in flow}
    if "equipment_handoff" in summary:
        handoff = summary["equipment_handoff"]
        summary["equipment_handoff"] = {key: handoff[key] for key in
            ("status", "ready_for_analysis", "run_id", "specimen_id", "artifact_id", "failure_code", "message") if key in handoff}
    compact_transitions = []
    for transition in flow.get("transitions", []):
        step = {key: transition[key] for key in
            ("block_id", "phase", "task", "summary", "outcome", "success", "target", "failure_code", "blocking", "message") if key in transition}
        evidence = transition.get("evidence") or {}
        step["evidence"] = {key: evidence[key] for key in
            ("force", "stroke", "height", "method_values", "artifact_candidate_count", "artifact_id",
             "acquisition_artifact_match", "data_parse_probe_ok", "write_complete", "row_count_probe", "columns_probe") if key in evidence}
        checks = (evidence.get("postcondition") or {}).get("screen_checks", [])
        if checks:
            step["screen_checks"] = [{key: check[key] for key in ("checkpoint", "ok", "state", "required") if key in check} for check in checks]
        compact_transitions.append(step)
    summary["equipment_skill_flow_execution"]["transitions"] = compact_transitions
    skill = data.get("equipment_skill_execution") or {}
    summary["skill_execution"] = {key: skill[key] for key in
        ("execution_id", "skill_id", "version", "state", "completed_segments", "failed_segment", "failure_code") if key in skill}
    call = _last_run(result)
    summary["last_worker_call"] = {"tool": call.get("tool"), "result": raw_summary(call.get("result") or {}),
        "payload": {key: (call.get("payload") or {})[key] for key in
            ("sequence_id", "equipment_skill_execution_id", "program_id", "bridge_id") if key in (call.get("payload") or {})}}
    return _bounded_evidence(summary)


def _stopped(state):
    return any(getattr(state, key, False) for key in
               ("stop_requested", "safe_stop_requested", "emergency_stop_requested"))


def _incoming_evidence(state):
    """Carry owner evidence with explicit identity checks, never synthesize success."""
    specimen_id = state.current_experiment_spec.get("specimen_id")
    rows = {}
    for key in ("specimen_result", "robot_task_result", "utm_verifications"):
        record = state.run_metadata.get(key)
        if not isinstance(record, dict) or not record:
            continue
        record = dict(record)
        if key == "utm_verifications":
            # Display-only captures are never decision evidence or authority.
            record.pop("previews", None)
        if key == "robot_task_result":
            verified = state.run_metadata.get("utm_verifications") or {}
            first = verified.get("verification_1") or {}
            evidence = first.get("evidence") or {}
            session = record.get("rollout_session_id") or record.get("session_id")
            if (verified.get("run_id") == state.run_id and verified.get("loop_id") == state.loop_count
                    and verified.get("specimen_id") == specimen_id and first.get("confirmed") is True
                    and session and evidence.get("session_id") == session
                    and evidence.get("rollout_stopped") is True and evidence.get("rollout_stop_status") == "STOPPED"):
                record["post_place_interlock"] = deepcopy(evidence.get("post_place_interlock") or {})
                record["execution_evidence"] = deepcopy(evidence.get("rollout_execution") or {})
                record["verified_stop"] = {"session_id": session, "rollout_stopped": True,
                                           "rollout_stop_status": "STOPPED", "source": "verification_1"}
        checks = {"run_id": state.run_id, "specimen_id": specimen_id, "loop_id": state.loop_count}
        def matches(name, actual, expected):
            # Manipulation publishes "loop-0"; Vision publishes integer 0.
            # Both are zero-based. Do not change numbering or accept other loops.
            if name == "loop_id":
                return type(actual) in (str, int) and str(actual) in {str(expected), f"loop-{expected}"}
            return actual == expected
        mismatches = [name for name, expected in checks.items()
                      if record.get(name) is not None and expected is not None and not matches(name, record[name], expected)]
        missing = [name for name, expected in checks.items() if expected is None or record.get(name) is None]
        rows[key] = {"identity_status": "mismatch" if mismatches else "incomplete" if missing else "matched",
                     "mismatched_fields": mismatches, "missing_identity_fields": missing,
                     "evidence": _bounded_evidence(record)}
    return {"run_id": state.run_id, "loop_id": state.loop_count,
            "specimen_id": specimen_id, "records": rows}


def _scope(state):
    return deepcopy([state.run_id, state.loop_count, state.experiment_id, state.stage.value,
        state.mode.value, state.active_goal, state.current_experiment_spec,
        state.active_session_id, state.device_health, state.current_experiment_objective,
        {key: value for key, value in state.run_metadata.items()
         if key.startswith(("operator_", "approval", "equipment_decision_settings", "execution_policy"))
         or key in {"runtime_approvals", "guardian_approval_queue", "vision_operator_intervention"}},
        _incoming_evidence(state)])


def _blocked(code, result=None):
    data = deepcopy(result.data) if result else {}
    # Preserve raw completion facts, but revoke every consumable handoff alias.
    data["verified"] = False
    data["failure_code"] = code
    data["equipment_workflow_failure"] = {"schema": "equipment_workflow_failure.v1",
        "status": "blocked", "failure_code": code}
    for key in ("equipment_handoff", "utm_data_ready", "handoff_packet"):
        if key == "equipment_handoff" or key in data:
            data[key] = {"status": "blocked", "ready_for_analysis": False, "failure_code": code}
    if "handoff_eligibility" in data:
        data["handoff_eligibility"] = {"eligible": False, "failure_code": code}
    report = data.setdefault("equipment_report", {})
    report["decision"] = {"handoff_status": "blocked", "blocking_reasons": [code]}
    return AgentResult(success=False, summary=f"Equipment workflow blocked: {code}", data=data)


def _describe(agent, state, flow):
    root = state.current_experiment_spec.get("equipment_skill_registry_root") or Path(__file__).resolve().parents[2] / "memory/equipment_skills"
    registry = EquipmentSkillRegistry(root)
    skills = []
    for block in flow.get("blocks", []):
        binding = block.get("skill") or {}
        try:
            package = registry.get(binding.get("skill_id", ""), binding.get("skill_version", ""))
            manifest = package["manifest"]
            skills.append({"block_id": block["id"], "binding": binding,
                "lifecycle": manifest.get("lifecycle"), "enabled": manifest.get("enabled"),
                "target_profile": manifest.get("target_profile"),
                "deployment": manifest.get("deployment"),
                "workflow_summary": (package.get("annotations") or {}).get("workflow_summary", {}),
                "workflow_sha256": _digest(package.get("workflow", {})),
                "programs_sha256": _digest(package.get("programs", []))})
        except (ValueError, OSError, KeyError) as exc:
            skills.append({"block_id": block.get("id"), "binding": binding, "error": str(exc)})
    return {"flow": deepcopy(flow), "skills": skills}


def _last_run(result):
    calls = [x for x in result.data.get("tool_results", []) if x.get("tool") == "equipment.pyautogui.run"]
    return calls[-1] if calls else {}


def _safe_resume(agent, result, checkpoint, flow):
    if result.success or int(checkpoint.get("next_index", 0)) >= len(flow.get("blocks", [])):
        return False
    skill = result.data.get("equipment_skill_execution") or {}
    calls = [x for x in result.data.get("tool_results", []) if x.get("tool") == "equipment.pyautogui.run"]
    if not skill.get("execution_id") or skill.get("completed_segments") or len(calls) != 1:
        return False
    raw = calls[0].get("result") or {}
    if raw.get("ok") is not False or raw.get("status") in {"effect_unknown", "running", "executing", "cancelled"}:
        return False
    if raw.get("actuation_performed") is True or raw.get("effects_known") is False or raw.get("effect_unknown") is True:
        return False
    # No coercion of false, malformed or unknown counters into zero.
    if type(raw.get("executed_action_count")) is not int or raw["executed_action_count"] != 0:
        return False
    return agent._skill_segment_retry_is_safe(raw)


def _payload(agent, state, result, execution_id):
    prior = (_last_run(result).get("payload") or {}) if result else {}
    return {"runtime_mode": agent._effective_runtime_mode(state), "run_id": state.run_id,
        "loop_id": state.loop_count, "experiment_id": state.experiment_id,
        "specimen_id": state.current_experiment_spec.get("specimen_id") or (state.run_metadata.get("specimen_result") or {}).get("specimen_id"),
        "workflow_execution_id": execution_id,
        **{k: prior[k] for k in ("bridge_id", "equipment_skill_execution_id", "confirm_execute", "confirm_live_execute") if k in prior}}


async def _capture(agent, state, ctx, result, execution_id):
    payload = _payload(agent, state, result, execution_id)
    if "equipment.pyautogui.screenshot" not in ctx.tools.list_tools():
        return [], {"ok": False, "error": "screenshot tool unavailable"}
    try:
        raw = await agent._call_tool(ctx, "equipment.pyautogui.screenshot", {**payload, "checkpoint": "workflow_terminal"}, state=state)
        if raw.get("ok") is not True:
            raise ValueError("screenshot capture failed")
        if payload["runtime_mode"] == "live" and (raw.get("mode") != "live" or raw.get("simulated") is True):
            raise ValueError("live review requires a live screenshot")
        for key in ("run_id", "loop_id", "specimen_id", "workflow_execution_id"):
            if key in raw and raw[key] != payload[key]:
                raise ValueError("screenshot identity mismatch")
        alias = raw.get("artifact") or {}
        # The bridge downloads output_artifacts to Linux; the singular alias
        # may still contain only the Windows-side metadata. Match its identity
        # rather than treating that truthy alias as a local file.
        artifact = next((a for a in raw.get("output_artifacts", [])
            if str(a.get("content_type", "")).startswith("image/")
            and a.get("local_path")
            and (not alias.get("artifact_id") or a.get("artifact_id") == alias["artifact_id"])), alias)
        if alias.get("sha256") and alias["sha256"] != artifact.get("sha256"):
            raise ValueError("screenshot alias/download digest mismatch")
        filename = artifact.get("local_path") or artifact.get("path")
        if not filename:
            raise ValueError("screenshot local file unavailable")
        path = Path(filename).resolve(strict=True)
        if not path.is_file():
            raise ValueError("screenshot path is not a file")
        with path.open("rb") as stream:
            data = stream.read(MAX_LLM_IMAGE_BYTES + 1)
        if len(data) > MAX_LLM_IMAGE_BYTES or not artifact.get("sha256") or _digest_bytes(data) != artifact["sha256"]:
            raise ValueError("screenshot digest/size mismatch")
        with Image.open(BytesIO(data)) as raster:
            if raster.width * raster.height > 16_000_000:
                raise ValueError("screenshot dimensions exceed limit")
            mime = Image.MIME[raster.format]
            raster.verify()
        evidence = {"ok": True, "path": str(path), "sha256": artifact["sha256"],
            "artifact_id": artifact.get("artifact_id"), "request_identity": payload,
            "identity_binding": "agent_request",
            "response_identity": {key: raw[key] for key in ("run_id", "loop_id", "specimen_id", "workflow_execution_id") if key in raw},
            "mode": raw.get("mode"), "source": "equipment.pyautogui.screenshot"}
        record_tool_artifact("evidence_result", "equipment.workflow_screenshot", evidence)
        return [LLMImageInput(data=data, mime_type=mime, label="Current equipment screen after workflow termination")], evidence
    except (ValueError, KeyError, OSError, RuntimeError, SyntaxError) as exc:
        return [], {"ok": False, "error": str(exc)}


def _digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _focus_action(state, result):
    """Only offer a focus operation already defined by the failed deployed Skill."""
    skill = result.data.get("equipment_skill_execution") or {}
    root = state.current_experiment_spec.get("equipment_skill_registry_root") or Path(__file__).resolve().parents[2] / "memory/equipment_skills"
    try:
        package = EquipmentSkillRegistry(root).get(skill["skill_id"], skill["version"])
        program_id = (_last_run(result).get("payload") or {}).get("program_id")
        for program in package.get("programs", []):
            if program.get("program_id") == program_id:
                for action in program.get("sequence", []):
                    if action.get("action") == "focus_window" and isinstance(action.get("window"), str) and action["window"]:
                        return {"action": "focus_window", "window": action["window"]}
    except (ValueError, KeyError, OSError):
        pass
    return None


async def run_decided_workflow(agent, state, ctx, flow):
    snapshot, frozen_flow = _scope(state), deepcopy(flow)
    description = _describe(agent, state, flow)
    from mcp_tools.source_tools import source_context
    scope_digest = _digest([snapshot, description])
    service = EquipmentRuntimeService(agent._RUNTIME_ROOT / "workflow_decisions")
    specimen = state.current_experiment_spec.get("specimen_id") or (state.run_metadata.get("specimen_result") or {}).get("specimen_id") or "specimen-unresolved"
    sequence_id = f"stacked-loop-{state.loop_count}"
    selection_retry = state.run_metadata.get("equipment_selection_retry") or {}
    if selection_retry:
        from app.equipment_selection_recovery import validate_selection_boundary
        check_state = state.model_copy(deep=True)
        from orchestrator.state import Stage
        check_state.stage, check_state.is_paused = Stage.GUARDIAN, True
        source = service.get(selection_retry["source_execution_id"])
        validate_selection_boundary(check_state, source)
        sequence_id += "-review-" + source["execution_id"]
    record = service.begin(sequence_id=sequence_id, run_id=state.run_id,
        experiment_id=state.experiment_id, specimen_id=specimen, profile_id="stacked_workflow",
        # This is an agent decision record, not a worker execution. Keep its key
        # mode-independent so a mode toggle cannot replay the same delegated work.
        mode="virtual", worker={"worker_id": "equipment-agent"},
        execution_ref={"type": "skill", "skill_id": "stacked_workflow"},
        metadata={"scope_digest": scope_digest, "profile_id": flow.get("profile_id"),
                  "runtime_mode": agent._effective_runtime_mode(state)})
    execution_id = record["execution_id"]
    completed_recheck = record.get("lifecycle") == "COMPLETED"
    def transition(lifecycle, **fields):
        if completed_recheck:
            # A new observation/review never reopens the completed actuation
            # claim. Failed reviews are archived by this invocation; the last
            # accepted execution remains immutable until another acceptance.
            record_tool_artifact("review_transition", "equipment.terminal_revalidation",
                {"execution_id": execution_id, "review_state": lifecycle, "actuation_performed": False})
            if lifecycle != "COMPLETED":
                return
        service.transition(execution_id, lifecycle, **fields)
    retry_result = None
    if record.get("idempotent"):
        stored = record.get("workflow_result")
        if stored and record.get("metadata", {}).get("scope_digest") == scope_digest and not _stopped(state):
            requested = state.run_metadata.pop("equipment_terminal_review_retry", None)
            if requested == execution_id and record.get("lifecycle") in {"ESCALATED", "COMPLETED"}:
                from agents.equipment.recovery import completed_candidate
                try:
                    retry_result = completed_candidate(record, flow, state)
                except (ValueError, OSError, KeyError) as exc:
                    output = _blocked("EQUIPMENT_REVIEW_RETRY_UNSAFE")
                    output.data["recovery_error"] = str(exc)
                    return output
            else:
                output = AgentResult(**deepcopy(stored))
                output.data["equipment_workflow_cached"] = True
                return output
        else:
            return _blocked("EQUIPMENT_WORKFLOW_ALREADY_CLAIMED")

    source_settings = state.run_metadata.get("knowledge_settings", {})
    source_scope = source_settings.get("source_scope", {}) if isinstance(source_settings, dict) else {}
    reference_context = await asyncio.to_thread(source_context, ctx, state.active_goal, scope=source_scope)
    checkpoint = deepcopy(record["checkpoint"]) if retry_result else {"workflow_execution_id": execution_id}
    decisions, diagnostics = [], []
    result = retry_result
    attempts = 0
    def valid():
        return not _stopped(state) and _scope(state) == snapshot and flow == frozen_flow and _describe(agent, state, flow) == description

    async def decide(phase, proposals, images=None):
        refs = ["task:configured"]
        incoming = _incoming_evidence(state)
        refs.extend(f"incoming:{key}" for key in incoming["records"])
        if result is not None:
            refs.append("workflow:terminal")
        if diagnostics:
            refs.append("diagnostics:latest")
        context = {"task": "Review and, only if authorized, execute the configured equipment flow for this specimen; validate its measurement handoff.",
            "research_goal": state.active_goal,
            "experiment_spec": _bounded_evidence(state.current_experiment_spec),
            "experiment_objective": _bounded_evidence(state.current_experiment_objective),
            "incoming_handoff": incoming,
            **_bounded_evidence(description),
            "source_knowledge": reference_context,
            "success": bool(result and result.success), "evidence_refs": refs,
            "execution": _terminal_evidence(result) if result else {}, "diagnostics": _bounded_evidence(diagnostics),
            "completed_blocks": [x["block_id"] for x in checkpoint.get("transitions", []) if x.get("phase") == "skill"],
            "recovery_eligible": bool(result and _safe_resume(agent, result, checkpoint, flow))}
        # The model reads an immutable input, while valid() below checks the live
        # execution/approval/stop authority. Token/UI telemetry can change during
        # inference without invalidating an otherwise identical proposal.
        decision = await decide_equipment(deepcopy(state), ctx, phase=phase, context=context,
            proposals={name: {"proposal_id": _digest([execution_id, phase, len(decisions), context]), **args}
                       for name, args in proposals.items()}, images=images)
        decisions.append(decision)
        if not valid() or decision.get("status") not in {"accepted", "deterministic_test"} or decision.get("scope_valid") is False:
            return "request_operator"
        return (decision.get("request") or {}).get("tool", "request_operator")

    try:
        if any(row["identity_status"] == "mismatch" for row in _incoming_evidence(state)["records"].values()):
            result = _blocked("EQUIPMENT_INCOMING_SCOPE_MISMATCH")
        if valid() and retry_result is None and result is None:
            preflight = await agent._run_equipment_skill_flow(state, ctx, frozen_flow,
                checkpoint=checkpoint, validate_only=True)
            if not preflight.success:
                result = preflight
        if not valid():
            result = _blocked("EQUIPMENT_WORKFLOW_SCOPE_CHANGED")
        elif result is not None and retry_result is None:
            pass  # Preserve the original hard-gate result; no model can override it.
        elif retry_result is None and await decide("select", {"execute_stacked_workflow": {}, "request_operator": {}}) != "execute_stacked_workflow":
            result = _blocked("EQUIPMENT_WORKFLOW_SELECTION_REJECTED")
        else:
            if retry_result is None:
                transition("PREFLIGHT")
                transition("EXECUTING")
                result = await agent._run_equipment_skill_flow(state, ctx, frozen_flow,
                    checkpoint=checkpoint, cancel_requested=lambda: not valid())
                if result.success:
                    transition("VERIFYING", terminal_result={
                        "success": result.success, "summary": result.summary, "data": deepcopy(result.data)})
            else:
                from agents.equipment.recovery import refresh_terminal_observations
                transition("RECOVERING", recovery={"operation": "terminal_review_only", "actuation_performed": False})
                result = await refresh_terminal_observations(agent, state, ctx, frozen_flow, result)
                transition("VERIFYING")
            phase, recovered, observed = "terminal_review", False, False
            before_recovery_images = []
            for _ in range(5):
                if not valid():
                    result = _blocked("EQUIPMENT_WORKFLOW_SCOPE_CHANGED", result)
                    break
                images, capture = await _capture(agent, state, ctx, result, execution_id)
                diagnostics.append({"screenshot": capture})
                safe = _safe_resume(agent, result, checkpoint, flow)
                proposals = {"request_operator": {}}
                if result.success:
                    # TEST may verify contracts without a model/image; real review needs the screen.
                    if images or (state.mode.value == "test" and not getattr(ctx, "force_real_llm_in_test", False)):
                        proposals["accept_workflow_result"] = {}
                elif safe and images:
                    if recovered:
                        proposals["resume_failed_block"] = {}
                    elif attempts == 0:
                        proposals["recover_wait"] = {}
                        if _focus_action(state, result):
                            proposals["recover_focus"] = {}
                if not observed:
                    proposals["observe_workflow"] = {}
                review_images = images
                if phase == "recovery_review" and images:
                    review_images = [LLMImageInput(data=item.data, mime_type=item.mime_type, label=label)
                        for label, group in (("Before bounded recovery", before_recovery_images),
                                             ("After bounded recovery", images)) for item in group]
                choice = await decide(phase, proposals, review_images)
                if choice == "accept_workflow_result":
                    break
                if choice == "observe_workflow":
                    observed = True
                    if "equipment.pyautogui.request_log" in ctx.tools.list_tools():
                        log = await agent._call_tool(ctx, "equipment.pyautogui.request_log", _payload(agent, state, result, execution_id), state=state)
                        diagnostics.append({"request_log": log})
                    phase = "terminal_review"
                    continue
                if choice in {"recover_wait", "recover_focus"} and safe and attempts == 0:
                    attempts += 1
                    before_recovery_images = images
                    operation = "wait" if choice == "recover_wait" else "focus_window"
                    gate = equipment_skill_recovery_gate(state=state, recovery={"operation": operation,
                        "attempt": attempts, "confidence": 1.0}, allowed_operations=[operation], max_attempts=1)
                    if gate_blocks_execution(gate) or not valid():
                        result = _blocked("EQUIPMENT_WORKFLOW_RECOVERY_REJECTED", result)
                        break
                    transition("RECOVERING", checkpoint=checkpoint,
                        recovery={"attempts": attempts, "operation": operation})
                    if choice == "recover_wait":
                        await asyncio.sleep(0 if agent._effective_runtime_mode(state) == "test" else 1)
                        recovery_result = {"ok": True, "operation": "wait", "actuation_performed": False}
                    else:
                        action = _focus_action(state, result)
                        recovery_result = await agent._call_tool(ctx, "equipment.pyautogui.run", {
                            **_payload(agent, state, result, execution_id), "sequence": [action],
                            "sequence_id": f"{execution_id}-recovery-{attempts}"}, state=state)
                    diagnostics.append({"recovery": recovery_result, "guardian": gate})
                    if recovery_result.get("ok") is not True:
                        result = _blocked("EQUIPMENT_WORKFLOW_RECOVERY_FAILED", result)
                        break
                    recovered, phase = True, "recovery_review"
                    continue
                if choice == "resume_failed_block" and recovered and safe and valid():
                    transition("EXECUTING", checkpoint=checkpoint)
                    result = await agent._run_equipment_skill_flow(state, ctx, frozen_flow,
                        checkpoint=checkpoint, cancel_requested=lambda: not valid())
                    recovered, phase = False, "terminal_review"
                    continue
                result = _blocked("EQUIPMENT_WORKFLOW_REVIEW_REQUIRED", result)
                break
            else:
                result = _blocked("EQUIPMENT_WORKFLOW_REVIEW_BUDGET_EXHAUSTED", result)
    except asyncio.CancelledError:
        transition("ESCALATED", failure={"failure_code": "EQUIPMENT_WORKFLOW_CANCELLED"})
        raise
    except Exception as exc:
        result = _blocked("EQUIPMENT_WORKFLOW_REVIEW_REQUIRED" if retry_result is not None
                          else "EQUIPMENT_WORKFLOW_EFFECT_UNKNOWN", result)
        diagnostics.append({"error": f"{type(exc).__name__}: {exc}"})
    if not valid():
        result = _blocked("EQUIPMENT_WORKFLOW_SCOPE_CHANGED", result)
    result.data.update(equipment_decisions=decisions, equipment_workflow_execution_id=execution_id,
        equipment_workflow_recovery={"attempts": attempts, "diagnostics": diagnostics})
    result.data.setdefault("equipment_report", {})["llm_workflow_review"] = {
        "accepted": result.success, "execution_id": execution_id, "decisions": decisions}
    stored = {"success": result.success, "summary": result.summary, "data": result.data}
    if result.success:
        transition("VERIFYING")
    transition("COMPLETED" if result.success else "ESCALATED",
        workflow_result=stored, checkpoint=checkpoint)
    record_tool_artifact("decision_result", "equipment.workflow_review", stored)
    return result
