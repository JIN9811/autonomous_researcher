"""Bounded, read-only evidence decisions for the Guardian agent."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import math
from time import monotonic
from typing import Any, Callable

from orchestrator.state import Mode
from utils.agent_artifact_archive import record_tool_artifact


_EVIDENCE_REFS = {
    "identity": "identity:current",
    "baseline": "baseline:action",
    "design": "validation:design",
    "health": "validation:health",
    "graph_gates": "validation:graph_gates",
    "consistency": "validation:consistency",
    "observations": "observations:current",
    "retries": "retry:pressure",
}
_TOOLS = {
    "guardian.evidence.read",
    "guardian.failures.read",
    "device.health",
    "experiment.queue.status",
    "guardian.decision.submit",
}
_ACTIONS = {"continue", "review", "safe_stop"}
_SUBSTANTIVE_CONTINUE_REFS = {
    "baseline:action",
    "validation:design",
    "validation:health",
    "validation:graph_gates",
    "validation:consistency",
    "observations:current",
    "retry:pressure",
    "health:fresh",
    "queue:current",
    "queue:shared_runtime_status",
}


class _StopRequested(Exception):
    pass


def _stopped(state: Any) -> bool:
    return any(
        bool(getattr(state, field, False))
        for field in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")
    )


def _identity(state: Any) -> dict[str, Any]:
    spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
    return {
        "run_id": str(state.run_id),
        "experiment_id": str(state.experiment_id),
        "loop_count": int(state.loop_count),
        "stage": str(state.stage.value),
        "specimen_id": str(spec.get("specimen_id") or ""),
    }


def _scope(state: Any) -> list[Any]:
    metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
    guarded_metadata = {
        key: deepcopy(metadata.get(key))
        for key in ("guardian_gates", "incident_records", "hardware_alerts")
        if key in metadata
    }
    return deepcopy(
        [
            _identity(state),
            state.mode.value,
            state.current_experiment_spec,
            state.current_experiment_objective,
            state.device_health,
            state.latest_observations,
            state.latest_analysis,
            state.retry_counters,
            guarded_metadata,
        ]
    )


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, default=str)


def _parse_request(text: Any) -> tuple[str, dict[str, Any]]:
    raw = str(text or "").strip()
    if len(raw) > 16_000 or not raw:
        raise ValueError("empty or oversized decision response")
    lines = raw.splitlines()
    if len(lines) >= 3 and lines[0] in {"```json", "```"} and lines[-1] == "```":
        raw = "\n".join(lines[1:-1])
    request = json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant)
    if not isinstance(request, dict) or set(request) != {"tool", "arguments"}:
        raise ValueError("decision request must contain only tool and arguments")
    tool, arguments = request["tool"], request["arguments"]
    if not isinstance(tool, str) or tool not in _TOOLS or not isinstance(arguments, dict):
        raise ValueError("unsupported Guardian tool request")
    _json(arguments)
    return tool, arguments


async def _cancel_task(task: asyncio.Task[Any]) -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        pass


async def _complete_while_current(
    state: Any,
    ctx: Any,
    prompt: str,
    *,
    timeout_s: float,
) -> Any:
    task = asyncio.create_task(ctx.complete("guardian_reasoning", prompt, timeout_s=timeout_s))
    deadline = monotonic() + timeout_s
    try:
        while True:
            if _stopped(state):
                await _cancel_task(task)
                raise _StopRequested("stop requested")
            remaining = deadline - monotonic()
            if remaining <= 0:
                await _cancel_task(task)
                raise TimeoutError("Guardian model call timed out")
            done, _pending = await asyncio.wait({task}, timeout=min(0.025, remaining))
            if done:
                return task.result()
    except asyncio.CancelledError:
        await _cancel_task(task)
        raise


async def _call_readonly_while_current(
    state: Any,
    callback: Callable[[], Any],
    *,
    timeout_s: float,
) -> Any:
    """Keep synchronous registry/validator work off the event loop and bounded."""
    task = asyncio.create_task(asyncio.to_thread(callback))
    deadline = monotonic() + timeout_s
    try:
        while True:
            if _stopped(state):
                await _cancel_task(task)
                raise _StopRequested("stop requested")
            remaining = deadline - monotonic()
            if remaining <= 0:
                await _cancel_task(task)
                raise TimeoutError("Guardian read-only tool timed out")
            done, _pending = await asyncio.wait({task}, timeout=min(0.025, remaining))
            if done:
                return task.result()
    except asyncio.CancelledError:
        await _cancel_task(task)
        raise


async def read_guardian_health(
    state: Any,
    read_health: Callable[[], dict[str, Any]],
    *,
    timeout_s: float = 120.0,
) -> dict[str, Any] | None:
    """Run the existing route-bound health validator off-loop and stop-aware."""
    if _stopped(state):
        return None
    try:
        value = await _call_readonly_while_current(state, read_health, timeout_s=timeout_s)
        return value if isinstance(value, dict) else {
            "status": "unknown", "snapshot": {}, "unhealthy_devices": [],
            "active_hardware_alerts": [], "query_status": "unavailable", "query_error": "InvalidResult",
        }
    except _StopRequested:
        return None
    except TimeoutError:
        return {
            "status": "unknown", "snapshot": {}, "unhealthy_devices": [],
            "active_hardware_alerts": [], "query_status": "unavailable", "query_error": "TimeoutError",
        }


def _review(result: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
    result.update(status="review_required", action="review", reason=reason, failure_code=code)
    return result


def _validate_settings(state: Any) -> tuple[int, int, float, float]:
    metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
    settings = metadata.get("guardian_settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("guardian_settings must be an object")
    max_turns = settings.get("max_turns", 6)
    max_duplicates = settings.get("max_duplicate_requests", 1)
    call_timeout = settings.get("call_timeout_s", 120.0)
    total_timeout = settings.get("total_timeout_s", 300.0)
    if (
        type(max_turns) is not int
        or not 1 <= max_turns <= 12
        or type(max_duplicates) is not int
        or not 0 <= max_duplicates <= 12
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 < float(value) <= 600
            for value in (call_timeout, total_timeout)
        )
    ):
        raise ValueError("invalid Guardian decision budget")
    return max_turns, max_duplicates, float(call_timeout), float(total_timeout)


def _foreign_queue_identity(payload: dict[str, Any], identity: dict[str, Any]) -> bool:
    for key in ("run_id", "experiment_id", "loop_count", "specimen_id"):
        if key in payload and payload[key] != identity[key]:
            return True
    if "loop_id" in payload and payload["loop_id"] != identity["loop_count"]:
        return True
    return False


def _queue_identity_matches(payload: dict[str, Any], identity: dict[str, Any]) -> bool:
    checks = {
        "run_id": identity["run_id"],
        "experiment_id": identity["experiment_id"],
        "specimen_id": identity["specimen_id"],
    }
    return all(key in payload and payload[key] == value for key, value in checks.items()) and (
        payload.get("loop_count", payload.get("loop_id")) == identity["loop_count"]
    )


async def run_guardian_decision(
    state: Any,
    ctx: Any,
    *,
    evidence: dict[str, Any],
    read_health: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Run a finite Guardian-local tool loop without granting safety authority."""
    identity = _identity(state)
    result: dict[str, Any] = {
        "schema": "guardian_evidence_decision.v1",
        "status": "review_required",
        "action": "review",
        "reason": "Guardian evidence review is required.",
        "evidence_refs": [],
        "llm_used": False,
        "trace": [],
        "identity": identity,
    }
    baseline = evidence.get("baseline") if isinstance(evidence, dict) else None
    if not isinstance(baseline, dict) or evidence.get("identity") != identity:
        return _review(result, "GUARDIAN_IDENTITY_INVALID", "Guardian evidence identity is not current.")
    if _stopped(state) or baseline.get("action") == "safe_stop":
        result.update(
            status="skipped",
            action="safe_stop",
            reason=str(baseline.get("reason") or "A mandatory stop is already active."),
            evidence_refs=["baseline:action"],
        )
        return result

    try:
        max_turns, max_duplicates, call_timeout, total_timeout = _validate_settings(state)
    except (TypeError, ValueError):
        return _review(result, "GUARDIAN_SETTINGS_INVALID", "Guardian decision settings are invalid.")

    if state.mode == Mode.TEST and not bool(getattr(ctx, "force_real_llm_in_test", True)):
        result.update(
            status="deterministic_test",
            action="continue",
            reason="Explicit non-LLM TEST path retained the code-owned baseline.",
            evidence_refs=["baseline:action"],
            evidence_class="simulated",
            trace=[{"turn": 0, "tool": "guardian.evidence.read", "status": "simulated"}],
        )
        return result

    frozen_evidence = deepcopy(evidence)
    frozen_scope = _scope(state)
    try:
        _json(frozen_evidence)
    except (TypeError, ValueError):
        return _review(result, "GUARDIAN_EVIDENCE_INVALID", "Guardian evidence is not valid finite JSON.")
    observed_refs: set[str] = set()
    signatures: dict[str, int] = {}
    duplicate_count = 0
    failed_observation = False
    deadline = monotonic() + total_timeout
    tool_schemas = {
        "guardian.evidence.read": {"section": sorted(_EVIDENCE_REFS)},
        "guardian.failures.read": {"limit": "integer 1..10"},
        "device.health": {},
        "experiment.queue.status": {},
        "guardian.decision.submit": {
            "action": ["continue", "review", "safe_stop"],
            "reason": "nonempty concise string",
            "evidence_refs": "nonempty observed IDs",
        },
    }
    instructions = (
        "Review Guardian evidence through the listed read-only local tools. Inspect at least one evidence source "
        "before submitting. Code owns identity, hard gates, stop state, routes and device parameters. Historical "
        "failures are unresolved context, not current faults. Never invent evidence or clear a gate. Return exactly "
        "one compact JSON object with EXACTLY TWO top-level keys: tool and arguments. Never add top-level reason, "
        "rationale, evidence_refs, commentary, or other keys. Evidence-read arguments contain only the declared read "
        "fields. Put a concise observable reason and evidence_refs only inside guardian.decision.submit arguments. "
        "Once current evidence is sufficient, submit a disposition instead of reading more. On the final available "
        "turn submit a supported disposition; choose review when evidence remains insufficient, never force continue."
    )

    try:
        for turn in range(1, max_turns + 1):
            if _stopped(state):
                raise _StopRequested("stop requested")
            remaining = min(call_timeout, deadline - monotonic())
            if remaining <= 0:
                return _review(result, "GUARDIAN_DECISION_TIMEOUT", "Guardian decision time budget expired.")
            prompt = instructions + "\n" + _json(
                {
                    "identity": identity,
                    "baseline_action": baseline.get("action"),
                    "turns_remaining": max_turns - turn + 1,
                    "current_summary": {
                        "design_status": (frozen_evidence.get("design") or {}).get("status"),
                        "health_status": (frozen_evidence.get("health") or {}).get("status"),
                        "graph_gate_status": (frozen_evidence.get("graph_gates") or {}).get("status"),
                        "consistency_status": (frozen_evidence.get("consistency") or {}).get("status"),
                        "observations": frozen_evidence.get("observations"),
                        "retries": frozen_evidence.get("retries"),
                    },
                    "tools": tool_schemas,
                    "observed_evidence_refs": sorted(observed_refs),
                    "request_examples": [
                        {"tool": "guardian.evidence.read", "arguments": {"section": "baseline"}},
                        {"tool": "device.health", "arguments": {}},
                        {"tool": "guardian.decision.submit", "arguments": {
                            "action": "continue", "reason": "Current checks support continuation.",
                            "evidence_refs": ["baseline:action"],
                        }},
                    ],
                    "observations": result["trace"],
                }
            )
            try:
                response = await _complete_while_current(state, ctx, prompt, timeout_s=remaining)
            except _StopRequested:
                raise
            except TimeoutError:
                return _review(result, "GUARDIAN_DECISION_TIMEOUT", "Guardian model call timed out.")
            except Exception:
                return _review(result, "GUARDIAN_PROVIDER_ERROR", "Guardian model provider failed.")
            if (getattr(response, "raw", None) or {}).get("mock"):
                return _review(result, "GUARDIAN_PROVIDER_ERROR", "Mock output cannot establish Guardian judgment.")
            result["llm_used"] = True
            result["model"] = str(getattr(response, "model", "unknown"))
            try:
                tool, arguments = _parse_request(getattr(response, "text", ""))
            except (TypeError, ValueError, json.JSONDecodeError):
                return _review(result, "GUARDIAN_REQUEST_INVALID", "Guardian model request is invalid.")

            signature = _json({"tool": tool, "arguments": arguments})
            signatures[signature] = signatures.get(signature, 0) + 1
            if signatures[signature] > 1:
                duplicate_count += 1
                if duplicate_count > max_duplicates:
                    return _review(result, "GUARDIAN_DUPLICATE_BUDGET", "Guardian duplicate request budget was exceeded.")

            entry: dict[str, Any] = {"turn": turn, "tool": tool, "arguments": deepcopy(arguments)}
            result["trace"].append(entry)
            record_tool_artifact("tool_started", tool, arguments)
            try:
                if tool == "guardian.evidence.read":
                    if set(arguments) != {"section"} or arguments["section"] not in _EVIDENCE_REFS:
                        raise ValueError("unsupported evidence section")
                    section = arguments["section"]
                    if section not in frozen_evidence:
                        raise ValueError("evidence section unavailable")
                    ref = _EVIDENCE_REFS[section]
                    observation = {"section": section, "evidence_ref": ref, "value": deepcopy(frozen_evidence[section])}
                    observed_refs.add(ref)
                elif tool == "guardian.failures.read":
                    if set(arguments) != {"limit"} or type(arguments["limit"]) is not int or not 1 <= arguments["limit"] <= 10:
                        raise ValueError("failure limit must be 1..10")
                    failures = frozen_evidence.get("failures")
                    if not isinstance(failures, list):
                        raise ValueError("failure evidence unavailable")
                    observation = {
                        "historical": True,
                        "resolved": False,
                        "failures": deepcopy(failures[-arguments["limit"] :]),
                        "evidence_ref": "failures:historical",
                    }
                    observed_refs.add("failures:historical")
                elif tool == "device.health":
                    if arguments:
                        raise ValueError("device.health accepts no model arguments")
                    tool_remaining = min(call_timeout, deadline - monotonic())
                    if tool_remaining <= 0:
                        raise TimeoutError("Guardian decision time budget expired")
                    health = await _call_readonly_while_current(state, read_health, timeout_s=tool_remaining)
                    if not isinstance(health, dict) or health.get("status") not in {"pass", "fail", "unknown"}:
                        raise ValueError("health validator returned invalid evidence")
                    observation = {"evidence_ref": "health:fresh", "validation": deepcopy(health)}
                    observed_refs.add("health:fresh")
                    result["fresh_health"] = deepcopy(health)
                    if health.get("status") == "unknown":
                        failed_observation = True
                elif tool == "experiment.queue.status":
                    if arguments:
                        raise ValueError("queue status accepts no model arguments")
                    payload = {
                        "run_id": identity["run_id"],
                        "experiment_id": identity["experiment_id"],
                        "loop_count": identity["loop_count"],
                        "loop_id": identity["loop_count"],
                        "specimen_id": identity["specimen_id"],
                    }
                    tool_remaining = min(call_timeout, deadline - monotonic())
                    if tool_remaining <= 0:
                        raise TimeoutError("Guardian decision time budget expired")
                    queue = await _call_readonly_while_current(
                        state,
                        lambda: ctx.tools.call("experiment.queue.status", payload),
                        timeout_s=tool_remaining,
                    )
                    queue_status = str(queue.get("status") or "").strip().lower() if isinstance(queue, dict) else ""
                    if (
                        not isinstance(queue, dict)
                        or queue.get("ok") is False
                        or queue_status in {"error", "failed", "failure", "unavailable", "unknown"}
                        or _foreign_queue_identity(queue, identity)
                    ):
                        raise ValueError("queue result identity is not current")
                    _json(queue)
                    identity_match = _queue_identity_matches(queue, identity)
                    ref = "queue:current" if identity_match else "queue:shared_runtime_status"
                    observation = {
                        "evidence_ref": ref,
                        "scope": "current_identity" if identity_match else "shared_runtime_status",
                        "identity_match": identity_match,
                        "requested_identity": identity,
                        "queue": deepcopy(queue),
                    }
                    observed_refs.add(ref)
                else:
                    if set(arguments) != {"action", "reason", "evidence_refs"}:
                        raise ValueError("invalid decision submission fields")
                    action, reason, refs = arguments["action"], arguments["reason"], arguments["evidence_refs"]
                    if (
                        action not in _ACTIONS
                        or not isinstance(reason, str)
                        or not 0 < len(reason.strip()) <= 1_000
                        or not isinstance(refs, list)
                        or not refs
                        or len(set(refs)) != len(refs)
                        or any(not isinstance(ref, str) or ref not in observed_refs for ref in refs)
                    ):
                        raise ValueError("invalid decision submission")
                    if failed_observation and action == "continue":
                        raise ValueError("failed evidence query cannot support continue")
                    if action == "continue" and not set(refs).intersection(_SUBSTANTIVE_CONTINUE_REFS):
                        raise ValueError("continue requires substantive current evidence")
                    if _stopped(state):
                        raise _StopRequested("stop requested")
                    if _scope(state) != frozen_scope or evidence != frozen_evidence:
                        observation = {"error": "Guardian evidence changed during review."}
                        entry.update(status="failed", observation=observation)
                        record_tool_artifact("tool_failed", tool, observation)
                        return _review(result, "GUARDIAN_SCOPE_CHANGED", "Guardian evidence changed during review.")
                    observation = {"accepted": True, "action": action, "evidence_refs": list(refs)}
                    entry.update(status="accepted", observation=observation)
                    record_tool_artifact("tool_result", tool, observation)
                    result.update(
                        status="accepted",
                        action=action,
                        reason=reason.strip(),
                        evidence_refs=list(refs),
                    )
                    return result
                entry.update(status="ok", observation=observation)
                record_tool_artifact("tool_result", tool, observation)
            except _StopRequested:
                record_tool_artifact("tool_failed", tool, {"error_type": "StopRequested"})
                raise
            except Exception as exc:
                failed_observation = True
                observation = {"error": "tool observation unavailable", "error_type": type(exc).__name__}
                entry.update(status="failed", observation=observation)
                record_tool_artifact("tool_failed", tool, observation)
                if tool in {"guardian.decision.submit", "guardian.evidence.read", "guardian.failures.read", "device.health"}:
                    return _review(result, "GUARDIAN_TOOL_INVALID", "Guardian tool request could not be validated.")
        return _review(result, "GUARDIAN_DECISION_BUDGET", "Guardian decision turn budget was exhausted.")
    except _StopRequested:
        result.update(
            status="interrupted",
            action="safe_stop",
            reason="A stop was requested during Guardian review.",
            evidence_refs=["identity:current"],
            failure_code="GUARDIAN_STOP_REQUESTED",
        )
        return result
    except asyncio.CancelledError:
        raise
