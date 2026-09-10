"""BO-owned bounded strategy/evidence/result-review decisions.

The model can select a supported numeric strategy, inspect code-owned evidence,
and accept the exact solver candidate.  Candidate coordinates, objective,
search space, budget, and the LHS phase remain owned by numerical code.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import inspect
import json
import math
from time import monotonic
from typing import Any, Awaitable, Callable, Mapping, Sequence

from utils.agent_artifact_archive import record_tool_artifact


SUPPORTED_ACQUISITIONS = {
    "expected_improvement",
    "upper_confidence_bound",
    "probability_of_improvement",
    "uncertainty_sampling",
    "exploitation",
    "exploration",
}
_STRATEGY_KEYS = {"acquisition", "kappa", "xi", "exploration_weight", "exploitation_weight"}


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _diagnostics(context: Mapping[str, Any], optimizer_result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    observations = context.get("observations")
    observations = observations if isinstance(observations, (list, tuple)) else []
    parameter_space = context.get("parameter_space")
    parameter_space = parameter_space if isinstance(parameter_space, Mapping) else {}
    finite = [item for item in observations if isinstance(item, Mapping) and _finite_number(item.get("score"))]
    failed = [item for item in observations if isinstance(item, Mapping) and item.get("ok_for_bo") is False]
    signatures: list[str] = []
    for item in finite:
        parameters = item.get("parameters")
        if isinstance(parameters, Mapping):
            signatures.append(json.dumps(dict(parameters), sort_keys=True, ensure_ascii=True, default=str))

    coverages: list[float] = []
    dimension_coverage: dict[str, float] = {}
    for name, domain in parameter_space.items():
        if not isinstance(domain, (list, tuple)) or len(domain) != 2 or not all(_finite_number(v) for v in domain):
            continue
        low, high = (float(domain[0]), float(domain[1]))
        if high <= low:
            continue
        values = []
        for item in finite:
            parameters = item.get("parameters")
            value = parameters.get(name) if isinstance(parameters, Mapping) else None
            if _finite_number(value) and low <= float(value) <= high:
                values.append(float(value))
        coverage = (max(values) - min(values)) / (high - low) if len(values) >= 2 else 0.0
        dimension_coverage[str(name)] = round(max(0.0, min(coverage, 1.0)), 6)
        coverages.append(coverage)

    result_finite = None
    if optimizer_result is not None:
        numeric = optimizer_result.get("numeric")
        numeric = numeric if isinstance(numeric, Mapping) else {}
        supplied = [value for value in numeric.values() if isinstance(value, (int, float)) and not isinstance(value, bool)]
        result_finite = all(math.isfinite(float(value)) for value in supplied) if supplied else None
    return {
        "schema": "bo_diagnostics.v1",
        "observation_count": len(observations),
        "finite_observation_count": len(finite),
        "failed_count": len(failed),
        "duplicate_count": len(signatures) - len(set(signatures)),
        "domain_coverage": round(sum(coverages) / len(coverages), 6) if coverages else 0.0,
        "dimension_coverage": dimension_coverage,
        "optimizer_result_finite": result_finite,
    }


def _configured_strategy(settings: Mapping[str, Any]) -> dict[str, Any]:
    configured = {key: deepcopy(settings[key]) for key in _STRATEGY_KEYS if key in settings}
    acquisition = configured.get("acquisition")
    if acquisition is not None and (not isinstance(acquisition, str) or acquisition not in SUPPORTED_ACQUISITIONS):
        raise ValueError("unsupported configured acquisition")
    for key in _STRATEGY_KEYS - {"acquisition"}:
        if key in configured and not _finite_number(configured[key]):
            raise ValueError(f"configured {key} must be finite")
    return configured


def _adaptive_strategy(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if not set(arguments).issubset(_STRATEGY_KEYS):
        raise ValueError("optimizer arguments can contain only bounded strategy settings")
    if not arguments:
        return {}
    strategy = dict(arguments)
    acquisition = strategy.get("acquisition")
    if acquisition is not None and (not isinstance(acquisition, str) or acquisition not in SUPPORTED_ACQUISITIONS):
        raise ValueError("unsupported acquisition")
    bounds = {
        "kappa": (0.0, 20.0),
        "xi": (0.0, 1.0),
        "exploration_weight": (0.0, 1.0),
        "exploitation_weight": (0.0, 1.0),
    }
    for key, (low, high) in bounds.items():
        if key in strategy and (not _finite_number(strategy[key]) or not low <= float(strategy[key]) <= high):
            raise ValueError(f"invalid adaptive {key}")
    return strategy


def _validate_candidate(result: Mapping[str, Any], parameter_space: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if result.get("ok") is not True:
        raise ValueError("optimizer did not return a successful numeric result")
    candidate_id = result.get("candidate_id")
    parameters = result.get("parameters")
    if not isinstance(candidate_id, str) or not candidate_id.strip() or not isinstance(parameters, Mapping):
        raise ValueError("optimizer result is missing candidate identity or parameters")
    checked = dict(parameters)
    unknown = set(checked) - set(parameter_space)
    if unknown:
        raise ValueError("optimizer candidate contains undeclared parameter keys")
    for name, domain in parameter_space.items():
        values = list(domain) if isinstance(domain, (list, tuple)) else [domain]
        if not values or name not in checked:
            raise ValueError(f"optimizer candidate is missing {name}")
        actual = checked[name]
        if len(values) == 2 and all(_finite_number(value) for value in values):
            if not _finite_number(actual) or not float(values[0]) <= float(actual) <= float(values[1]):
                raise ValueError(f"optimizer candidate is outside {name} bounds")
        elif len(values) == 1 and actual != values[0]:
            raise ValueError(f"optimizer candidate changed fixed {name}")
        elif len(values) > 1 and actual not in values:
            raise ValueError(f"optimizer candidate is outside {name} domain")
    for value in checked.values():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(float(value)):
            raise ValueError("optimizer candidate contains non-finite coordinates")
    numeric = result.get("numeric")
    if numeric is not None and not isinstance(numeric, Mapping):
        raise ValueError("optimizer numeric diagnostics must be an object")
    if isinstance(numeric, Mapping) and any(
        isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(float(value))
        for value in numeric.values()
    ):
        raise ValueError("optimizer numeric diagnostics contain non-finite values")
    return candidate_id, checked


def _parse_request(text: Any, evidence: set[str], tools: set[str]) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```json") and raw.endswith("```"):
        raw = raw[7:-3].strip()
    if not raw or len(raw) > 16000:
        raise ValueError("empty or oversized decision response")
    request = json.loads(raw)
    if not isinstance(request, dict) or set(request) != {"tool", "arguments", "reason", "evidence_refs"}:
        raise ValueError("invalid decision request fields")
    tool = request["tool"]
    arguments = request["arguments"]
    reason = request["reason"]
    refs = request["evidence_refs"]
    if (
        not isinstance(tool, str)
        or tool not in tools
        or not isinstance(arguments, dict)
        or not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 2000
        or not isinstance(refs, list)
        or not refs
        or any(not isinstance(ref, str) or ref not in evidence for ref in refs)
    ):
        raise ValueError("invalid decision tool, reason, or evidence")
    return request


async def _invoke_bounded(callback: Callable[..., Any], *args: Any, timeout_s: float) -> Any:
    """Invoke async callbacks directly and sync callbacks off the event loop."""
    started = monotonic()
    if inspect.iscoroutinefunction(callback):
        value = callback(*args)
    else:
        # Cancellation cannot terminate native work already running in a thread;
        # the backend's existing optimizer timeout remains independently in effect.
        value = await asyncio.wait_for(asyncio.to_thread(callback, *args), timeout=timeout_s)
    if inspect.isawaitable(value):
        remaining = timeout_s - (monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("BO callback budget expired")
        return await asyncio.wait_for(value, timeout=remaining)
    return value


def _virtual_request(step: int, candidate_id: str | None) -> dict[str, Any]:
    if step == 0:
        return {
            "tool": "inspect_diagnostics", "arguments": {},
            "reason": "Inspect code-owned observation diagnostics before numerical optimization.",
            "evidence_refs": ["context:observations"],
        }
    if candidate_id is None:
        return {
            "tool": "run_optimizer", "arguments": {},
            "reason": "Run the configured numerical policy after diagnostics.",
            "evidence_refs": ["context:request", "diagnostics:current"],
        }
    return {
        "tool": "accept_recommendation", "arguments": {"candidate_id": candidate_id},
        "reason": "Accept the unchanged solver candidate after code-owned checks.",
        "evidence_refs": [f"candidate:{candidate_id}"],
    }


async def run_bo_decision(
    *,
    context: Mapping[str, Any],
    ctx: Any,
    settings: Mapping[str, Any],
    run_optimizer: Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]] | Mapping[str, Any]],
    retrieve_knowledge: Callable[[str, int], Awaitable[Sequence[Mapping[str, Any]]] | Sequence[Mapping[str, Any]]] | None = None,
    virtual_test: bool = False,
) -> dict[str, Any]:
    """Run the finite BO-local tool protocol and return its trace/result."""
    frozen = deepcopy(dict(context))
    result: dict[str, Any] = {
        "schema": "bo_decision.v1", "status": "failed", "provenance": "virtual_test" if virtual_test else "llm",
        "llm_used": False, "trace": [], "optimizer_result": None, "knowledge": [],
    }
    try:
        control = settings.get("strategy_control", "configured")
        if control not in {"configured", "adaptive"}:
            raise ValueError("strategy_control must be configured or adaptive")
        max_calls = settings.get("decision_max_calls", 6)
        call_timeout = settings.get("decision_call_timeout_s", 45.0)
        total_timeout = settings.get("decision_total_timeout_s", 120.0)
        if (
            type(max_calls) is not int or not 1 <= max_calls <= 12
            or not _finite_number(call_timeout) or not 0 < float(call_timeout) <= 300
            or not _finite_number(total_timeout) or not 0 < float(total_timeout) <= 300
        ):
            raise ValueError("invalid BO decision budget")
        parameter_space = frozen.get("parameter_space")
        if not isinstance(parameter_space, Mapping):
            raise ValueError("missing parameter space")
        evidence = {"context:request", "context:observations", "context:knowledge"}
        tools = {"inspect_diagnostics", "retrieve_knowledge", "run_optimizer", "return_to_owner"}
        optimizer_result: dict[str, Any] | None = None
        candidate_id: str | None = None
        inspected = False
        deadline = monotonic() + float(total_timeout)

        instructions = (
            "You own a bounded BO strategy/evidence/result-review decision. Use only the supplied agent-local tools. "
            "On the normal path inspect diagnostics, optionally retrieve relevant local knowledge, run the optimizer once, "
            "then accept the exact solver candidate or return to the owner. Never create or edit coordinates, objective, "
            "bounds, budget, initial LHS size/seed/phase, or device actions. Output exactly one JSON object containing only "
            "tool, arguments, reason, evidence_refs. Cite only supplied evidence IDs."
        )
        for index in range(max_calls):
            remaining = min(float(call_timeout), deadline - monotonic())
            if remaining <= 0:
                raise TimeoutError("BO decision budget expired")
            available_tools = set(tools)
            tool_schemas: dict[str, Any] = {
                "inspect_diagnostics": {"arguments": {}, "effect": "return code-owned counts, duplicates, domain coverage, and finite-result diagnostics"},
                "retrieve_knowledge": {"arguments": {"query": "nonempty string <= 500 chars", "top_k": "integer 1..8"}, "effect": "search only the local index; returned source IDs become evidence"},
                "return_to_owner": {"arguments": {}, "effect": "hold without a Design-ready handoff"},
            }
            if "run_optimizer" in available_tools:
                tool_schemas["run_optimizer"] = {
                    "arguments": {} if control == "configured" else {
                        "acquisition": sorted(SUPPORTED_ACQUISITIONS),
                        "kappa": "optional finite number 0..20",
                        "xi": "optional finite number 0..1",
                        "exploration_weight": "optional finite number 0..1",
                        "exploitation_weight": "optional finite number 0..1",
                    },
                    "effect": "run the existing numerical optimizer once; no objective/bounds/budget/LHS arguments",
                    "example": {"tool": "run_optimizer", "arguments": {}, "reason": "Run after diagnostics.", "evidence_refs": ["context:request", "diagnostics:current"]},
                }
            if "accept_recommendation" in available_tools:
                tool_schemas["accept_recommendation"] = {
                    "arguments": {"candidate_id": candidate_id},
                    "effect": "accept only this exact solver candidate with unchanged coordinates",
                    "example": {"tool": "accept_recommendation", "arguments": {"candidate_id": candidate_id}, "reason": "Accept checked numeric result.", "evidence_refs": [f"candidate:{candidate_id}"]},
                }
            prompt = instructions + "\n" + json.dumps(
                {"context": frozen, "tools": {name: tool_schemas[name] for name in sorted(available_tools)}, "evidence_refs": sorted(evidence), "trace": result["trace"]},
                ensure_ascii=False, allow_nan=False, default=str,
            )
            response_entry: dict[str, Any] = {"step": index + 1}
            try:
                if virtual_test:
                    request = _virtual_request(index, candidate_id)
                    response_entry["model"] = "virtual_test"
                    response_entry["response"] = json.dumps(request)
                else:
                    if not hasattr(ctx, "complete"):
                        raise ValueError("registered bo_policy inference is unavailable")
                    response = await asyncio.wait_for(
                        ctx.complete("bo_policy", prompt, timeout_s=remaining), timeout=remaining,
                    )
                    if getattr(response, "raw", {}).get("mock"):
                        raise ValueError("mock fallback is not a BO decision")
                    result["llm_used"] = True
                    result["model"] = str(getattr(response, "model", "unknown"))
                    response_entry["model"] = result["model"]
                    response_entry["response"] = str(getattr(response, "text", ""))[:16000]
                    request = _parse_request(getattr(response, "text", ""), evidence, available_tools)
                if virtual_test:
                    request = _parse_request(response_entry["response"], evidence, available_tools)
                response_entry["request"] = deepcopy(request)
                record_tool_artifact("decision_response", "bo.decision", response_entry)
                tool = request["tool"]
                arguments = request["arguments"]
                if tool in {"inspect_diagnostics", "return_to_owner"} and arguments:
                    raise ValueError(f"{tool} takes no arguments")
                if tool == "inspect_diagnostics":
                    diagnostics = _diagnostics(frozen, optimizer_result)
                    inspected = True
                    evidence.add("diagnostics:current")
                    response_entry["result"] = diagnostics
                    result["diagnostics"] = diagnostics
                elif tool == "retrieve_knowledge":
                    if set(arguments) != {"query", "top_k"}:
                        raise ValueError("retrieve_knowledge requires query and top_k")
                    query, top_k = arguments["query"], arguments["top_k"]
                    if not isinstance(query, str) or not query.strip() or len(query) > 500 or type(top_k) is not int or not 1 <= top_k <= 8:
                        raise ValueError("invalid local knowledge request")
                    if retrieve_knowledge is None:
                        chunks = []
                    else:
                        remaining_callback = min(float(call_timeout), deadline - monotonic())
                        if remaining_callback <= 0:
                            raise TimeoutError("BO decision budget expired")
                        chunks = await _invoke_bounded(
                            retrieve_knowledge, query.strip(), top_k, timeout_s=remaining_callback,
                        )
                    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes)):
                        raise ValueError("invalid local knowledge result")
                    stored = []
                    for item in chunks[:top_k]:
                        if not isinstance(item, Mapping):
                            raise ValueError("invalid local knowledge entry")
                        source_id = item.get("source_id") or item.get("chunk_id")
                        if not isinstance(source_id, str) or not source_id.strip():
                            raise ValueError("local knowledge entry requires a source ID")
                        entry = {"source_id": source_id, "source": str(item.get("source") or "local_index"), "text": str(item.get("text") or "")[:2000]}
                        stored.append(entry)
                        evidence.add(f"knowledge:{source_id}")
                    result["knowledge"].extend(stored)
                    response_entry["result"] = stored
                elif tool == "run_optimizer":
                    if optimizer_result is not None:
                        raise ValueError("optimizer can run at most once")
                    if not inspected:
                        raise ValueError("diagnostics must be inspected before optimization")
                    if control == "configured":
                        if arguments:
                            raise ValueError("configured strategy cannot be changed by the model")
                        strategy = _configured_strategy(settings)
                    else:
                        strategy = _adaptive_strategy(arguments)
                        if not strategy:
                            strategy = _configured_strategy(settings)
                    remaining_callback = min(float(call_timeout), deadline - monotonic())
                    if remaining_callback <= 0:
                        raise TimeoutError("BO decision budget expired")
                    raw_result = await _invoke_bounded(
                        run_optimizer, strategy, timeout_s=remaining_callback,
                    )
                    if not isinstance(raw_result, Mapping):
                        raise ValueError("invalid optimizer result")
                    optimizer_result = deepcopy(dict(raw_result))
                    result["optimizer_result"] = optimizer_result
                    response_entry["result"] = {
                        "status": "completed",
                        "candidate_id": optimizer_result.get("candidate_id"),
                        "parameters": deepcopy(optimizer_result.get("parameters")),
                        "numeric": deepcopy(optimizer_result.get("numeric")),
                        "phase": optimizer_result.get("phase"),
                        "backend_active": optimizer_result.get("backend_active"),
                    }
                    candidate_id, _parameters = _validate_candidate(optimizer_result, parameter_space)
                    evidence.add(f"candidate:{candidate_id}")
                    tools = {"inspect_diagnostics", "retrieve_knowledge", "accept_recommendation", "return_to_owner"}
                    result["strategy"] = strategy
                    result["diagnostics"] = _diagnostics(frozen, optimizer_result)
                    response_entry["result"]["diagnostics"] = result["diagnostics"]
                elif tool == "accept_recommendation":
                    if set(arguments) != {"candidate_id"} or candidate_id is None or arguments.get("candidate_id") != candidate_id:
                        raise ValueError("only the exact solver candidate ID can be accepted")
                    if f"candidate:{candidate_id}" not in request["evidence_refs"]:
                        raise ValueError("accepted candidate must be cited")
                    result.update(status="accepted", candidate_id=candidate_id, reason=request["reason"], evidence_refs=request["evidence_refs"])
                    response_entry["result"] = {"status": "accepted", "candidate_id": candidate_id}
                    response_entry["status"] = "valid"
                    result["trace"].append(response_entry)
                    record_tool_artifact("evidence_result", "bo.accept_recommendation", response_entry)
                    return result
                else:
                    result.update(status="returned", reason=request["reason"], evidence_refs=request["evidence_refs"])
                    response_entry["result"] = {"status": "returned"}
                    response_entry["status"] = "valid"
                    result["trace"].append(response_entry)
                    record_tool_artifact("evidence_result", "bo.return_to_owner", response_entry)
                    return result
                response_entry["status"] = "valid"
                result["trace"].append(response_entry)
                record_tool_artifact("evidence_result", f"bo.{tool}", response_entry)
            except asyncio.CancelledError:
                raise
            except Exception:
                response_entry["status"] = "invalid"
                response_entry["error_type"] = "BO_DECISION_INVALID_REQUEST"
                result["trace"].append(response_entry)
                record_tool_artifact("decision_response", "bo.invalid", response_entry)
                raise
        result["failure_code"] = "BO_DECISION_BUDGET_EXHAUSTED"
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        result["failure_code"] = "BO_DECISION_TIMEOUT"
    except Exception as exc:
        result["failure_code"] = "BO_DECISION_INVALID"
        result["error_type"] = type(exc).__name__
    return result
