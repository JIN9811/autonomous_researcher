"""Opt-in registered-provider Orchestrator verification; never starts services/devices."""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from collections import Counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CASES_PATH = Path(__file__).with_name("orchestrator_prompt_cases.json")
DECISIONS = ["ready", "busy", "unknown_stale", "supported_proposal", "unsupported_setup", "completed_defer_resume"]


def fixtures():
    return json.loads(CASES_PATH.read_text())


def _ids_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def case_selection(shard_index=0, shard_count=1):
    """Partition fully expanded cases, not source prompts; never parallelize shared attempts."""
    if (type(shard_index) is not int or type(shard_count) is not int or shard_count not in (1, 2)
            or not 0 <= shard_index < shard_count):
        raise ValueError("Require shard-count 1 or 2 and 0 <= shard-index < shard-count")
    ids = []
    for case in fixtures():
        variants = ["N", "P", "B", "I", "R", "V", "S", "M", "specimen"] if case["id"] in {"I09", "I10", "I19"} else [None]
        ids.extend(case["id"] + ("-" + variant if variant else "") for variant in variants)
    ids.extend(DECISIONS)
    selected = ids[shard_index::shard_count]
    return {"schema": "verification_selection.v1", "shard_index": shard_index, "shard_count": shard_count,
            "expected_case_ids": ids, "selected_case_ids": selected,
            "expected_case_ids_sha256": _ids_digest(ids), "selected_case_ids_sha256": _ids_digest(selected)}


def aggregate_reports(reports):
    """Fail closed on missing, duplicated, mixed-epoch, or unsuccessful shard evidence."""
    errors, providers, epochs = [], {}, []
    expected = case_selection()["expected_case_ids"]
    for index, report in enumerate(reports):
        label = f"report {index}"
        selection = report.get("selection", {})
        try:
            prescribed = case_selection(selection.get("shard_index"), selection.get("shard_count"))
        except ValueError:
            errors.append(f"{label}: invalid selection")
            continue
        if selection != prescribed:
            errors.append(f"{label}: selection metadata mismatch")
        if report.get("schema") != "verification_report.v1" or report.get("run_status") != "complete":
            errors.append(f"{label}: incomplete report")
        if report.get("physical_call_count") != 0 or report.get("denied_attempts") != []:
            errors.append(f"{label}: guard evidence is not clean")
        epoch = {key: report.get(key) for key in ("fixture_sha256", "code_sha256", "prompt_sha256", "source_sha256")}
        if any(not value for value in epoch.values()):
            errors.append(f"{label}: missing epoch")
        epochs.append(epoch)
        rows_by_provider = {}
        for row in report.get("cases", []):
            rows_by_provider.setdefault(row.get("backend"), []).append(row)
            if row.get("case") not in DECISIONS:
                status = intake_case_status(intent_ok=(row.get("classification") or {}).get("intent") in row.get("allowed_intents", []),
                    transport_blocked=False, effect=row.get("effect", {}), raw_attempts=row.get("raw_attempts", []))
            else:
                status = decision_case_status(outcome=row, raw_attempts=row.get("raw_attempts", []), transport_blocked=False)
            if (row.get("status") != "passed" or status != "passed" or not row.get("served_model")
                    or row.get("physical_call_count") != 0):
                errors.append(f"{label}: unsuccessful case {row.get('backend')}/{row.get('case')}")
        if not rows_by_provider:
            errors.append(f"{label}: no provider cases")
        for backend, rows in rows_by_provider.items():
            if backend not in {"openai", "vllm"}:
                errors.append(f"{label}: unknown provider")
            if Counter(row.get("case") for row in rows) != Counter(prescribed["selected_case_ids"]):
                errors.append(f"{label}: missing, duplicate, or unknown cases for {backend}")
            group = providers.setdefault(backend, {"case_count": 0, "shards": [], "cases": [], "served_models": []})
            group["case_count"] += len(rows)
            group["shards"].append((selection["shard_index"], selection["shard_count"]))
            group["cases"].extend(row.get("case") for row in rows)
            group["served_models"].extend(row.get("served_model") for row in rows if row.get("served_model"))
    if not reports:
        errors.append("No reports supplied")
    if epochs and any(epoch != epochs[0] for epoch in epochs[1:]):
        errors.append("Mixed code, fixture, prompt, or production-source epochs")
    for backend, group in providers.items():
        counts = {count for _, count in group["shards"]}
        if len(counts) != 1 or Counter(index for index, _ in group["shards"]) != Counter(range(next(iter(counts)))):
            errors.append(f"{backend}: missing or duplicate shards")
        if Counter(group["cases"]) != Counter(expected):
            errors.append(f"{backend}: full unique coverage is missing")
        group["served_models"] = sorted(set(group["served_models"]))
    return {"schema": "verification_aggregate.v1", "status": "failed" if errors else "passed",
            "providers": providers, "errors": errors,
            "limitations": ["Complete fixture coverage is not a model-driven whole-cycle or hardware claim."]}


def decision_case_status(*, outcome, raw_attempts, transport_blocked):
    unavailable = {"ConnectionError", "ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout",
        "PoolTimeout", "NetworkError", "ReadError", "WriteError", "HTTPStatusError"}
    if transport_blocked or outcome.get("execution_status") == "blocked" or outcome.get("error_type") in unavailable:
        return "blocked"
    if outcome.get("error_type") or outcome.get("execution_status") == "failed":
        return "failed"
    if not raw_attempts:
        return "blocked"
    last = raw_attempts[-1]
    if "text" not in last:
        return "blocked" if last.get("error_type") in unavailable else "failed"
    if not last.get("served_model"):
        return "blocked"
    decisions = [outcome.get("decision", {})] + [phase.get("decision", {}) for phase in outcome.get("phases", [])]
    if outcome.get("containment_only") or any(decision.get("status") == "failed" for decision in decisions):
        return "failed"
    return "passed" if outcome.get("expectation_met") else "failed"


def intake_case_status(*, intent_ok, transport_blocked, effect, raw_attempts):
    return decision_case_status(outcome={**effect,
        "expectation_met": intent_ok and effect.get("expectation_met", False),
        "decision": (effect.get("response") or {}).get("decision", {})},
        raw_attempts=raw_attempts, transport_blocked=transport_blocked)


def controller_for(ctx, root, *, lifecycle_requests=None):
    from app.controller import MainController, ControllerDeps
    from agents.registry import AgentRegistry
    from agents.bo_agent import BOAgent
    from agents.orchestrator_agent import OrchestratorAgent
    registry = AgentRegistry()
    registry.register(BOAgent())
    registry.register(OrchestratorAgent())
    controller = MainController(ControllerDeps(agent_registry=registry, orchestrator_agent_name="orchestrator_agent",
        agent_context=ctx, run_root=root / "runs", logging_config={}, system_config={}, runtime_profile={}))
    if lifecycle_requests is not None:
        async def simulated_scale_down(*, include_persistent=False, keep_models=None):
            lifecycle_requests.append({"boundary": "model_lifecycle.scale_down_idle_models",
                "run_id": controller._state.run_id, "include_persistent": include_persistent,
                "keep_models": deepcopy(keep_models), "actual_effect": False})
            return {"enabled": False, "scaled_down": [], "errors": [], "status": "simulated", "simulated": True}
        # Only this explicit verifier-owned boundary is simulated. The global
        # guard still rejects every real provider lifecycle or device operation.
        controller._scale_down_idle_vllm_models = simulated_scale_down
    return controller


async def settle_verification_controller(controller):
    """Join fixture-owned background cleanup before closing its case/guard."""
    task = controller._vllm_transition_task
    if task is not None:
        try:
            await task
        finally:
            if controller._vllm_transition_task is task:
                controller._vllm_transition_task = None


def intake_context(controller, case, variant=None):
    """Create authentic SetupStore IDs and current server pending metadata."""
    from orchestrator.orchestrator_checkpoint import handoff_checkpoint
    setup = controller.planning_snapshot()["state"]["setup"]
    store = controller._setup_store()
    mode = variant or case["context"].split(":")[0].split(";")[0]
    by_field = {b["topic_key"]: b for b in setup["blocks"]}
    def propose(field, value):
        b = by_field[field]
        return store.propose(b["block_id"], b["revision"], {field: value}, str(uuid4()))
    if mode in {"P", "M"}:
        propose("research.goal", "강성 대비 질량 최적화")
    if mode in {"B", "M"}:
        space = deepcopy(by_field["bo.parameter_space"]["draft_values"]["bo.parameter_space"])
        space.update(cell_size_mm=[7, 8], relative_density=[.3, .4])
        propose("bo.parameter_space", space)
    meta = controller._state.run_metadata
    if mode == "I":
        meta["orchestrator_planning_boundary"] = {"status": "deferred", "task_id": str(uuid4()),
            "key": str(uuid4()), "goal": controller._state.active_goal, "constraints": {}}
    if mode in {"R", "V"}:
        key = "completed-owner-" + str(uuid4())
        handoff_checkpoint(meta, key, action="prepare", payload={"result_data": {"owner_completed": True}})
        handoff_checkpoint(meta, key, action="defer", payload={"condition": "Explicit review required"})
        meta["orchestrator_pending_handoff"] = key
        if mode == "V":
            meta["orchestrator_observation_refresh"] = {"status": "waiting", "held_checkpoint": key}
    if mode == "specimen":
        meta["pending_specimen_input"] = {"type": "printer_test_path_choice", "specimen_id": "fixture",
            "input_request": {"choices": ["virtual_bridge", "installed_printer", "physical_print"]}}
    pending = controller._planning_pending_request()
    request = {"pending": pending, "setup": controller._planning_setup_projection(),
        "instruction": "Current server context only. Setup changes are next-new-run proposals, not execution authority."}
    if mode == "E":
        field = case["context"].split(":", 1)[1].strip()
        request["setup_context"] = by_field[field]
    if mode == "S":
        request["client_reference"] = "An obsolete prior-session proposal; no current server pending request."
    if mode == "M":
        request["clarification"] = "Two drafts, no uniquely selected proposal."
    return pending, request


async def verify(args):
    selection = case_selection(getattr(args, "shard_index", 0), getattr(args, "shard_count", 1))
    selected = set(selection["selected_case_ids"])
    from scripts.orchestrator_verification_guard import VerificationGuard
    with VerificationGuard() as guard:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        from app.bootstrap import _load_configs, _build_backend, _models_cfg_for_backend
        from backends.model_router import ModelRouter
        from agents.base_agent import AgentContext
        from mcp_tools.tool_registry import ToolRegistry
        from agents.orchestrator_decision import classify_chat_request
        from scripts.orchestrator_decision_fixtures import (run_case, exercise_intake_effect,
            registered_planning_settings, INTAKE_CLEANUP_TIMEOUT_S, HANDLER_CLEANUP_TIMEOUT_S)
        cfg = _load_configs()
        if args.output:
            output = Path(args.output).resolve()
            if output.exists():
                raise FileExistsError("Refusing to overwrite an existing verification report")
            output.parent.mkdir(parents=True, exist_ok=True)
        else:
            run_root = Path(cfg["system"]["system"].get("run_root", "runs"))
            if not run_root.is_absolute():
                run_root = ROOT / run_root
            run_root.mkdir(parents=True, exist_ok=True)
            output = Path(tempfile.mkdtemp(prefix="validation-orchestrator-setup-", dir=run_root)) / "orchestrator_setup_verification.json"
        report = {"schema": "verification_report.v1", "run_status": "running", "selection": selection,
            "verification_scope": "provider_shard" if selection["shard_count"] > 1 else "full_provider",
            "cases": [], "physical_call_count": 0, "simulated_lifecycle_requests": [],
            "verification_limits": {"module_settings": "unchanged graph-linked settings; timeout_s null inherits provider",
                "provider_timeout_s": {}, "intake_cleanup_timeout_s": INTAKE_CLEANUP_TIMEOUT_S,
                "handler_cleanup_timeout_s": HANDLER_CLEANUP_TIMEOUT_S,
                "cleanup_rationale": "Beyond 300s primary+fallback per call and four decision steps; cleanup only"},
            "service_startup": False, "fixture_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "prompt_sha256": hashlib.sha256((ROOT / "backends/prompt_registry.py").read_bytes()).hexdigest(),
            "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [ROOT / name for name in ("app/controller.py", "app/planning_setup.py", "agents/equipment_agent.py", "agents/orchestrator_decision.py",
                    "agents/orchestrator_capabilities.py", "scripts/orchestrator_decision_fixtures.py",
                    "scripts/orchestrator_verification_guard.py", "orchestrator/handoff_boundary.py",
                    "orchestrator/handoff_projection.py", "graphs/modules/equipment/module.yaml",
                    "orchestrator/setup_application.py", "orchestrator/experimental_setup.py", "agents/bo_agent.py")]},
            "limitations": ["Intake effects replay the just-captured real classification through the same-scope controller.",
                "Decision owner evidence is explicitly supplied; completed-result retention is not a measured owner cycle.",
                "No physical execution or live readiness discovery is claimed."]}
        secrets = []
        def save():
            rendered = json.dumps(report, indent=2, ensure_ascii=False, default=str)
            for secret in secrets:
                if secret:
                    rendered = rendered.replace(secret, "[REDACTED]")
            output.write_text(rendered)
        save()
        print(json.dumps({"report": str(output)}), flush=True)
        for backend in args.backend or ["openai", "vllm"]:
            provider = _build_backend(backend, system_cfg=cfg["system"]["system"], cfg=cfg)
            report["verification_limits"]["provider_timeout_s"][backend] = provider._timeout_s
            router = ModelRouter(_models_cfg_for_backend(cfg["models"], backend))
            selection = router.select("orchestrator_plan")
            try:
                if backend == "openai":
                    path = ROOT / "memory/api_keys.json"
                    credentials = json.loads(path.read_text()) if path.is_file() else {}
                    if not credentials.get("enabled") or not credentials.get("api_key"):
                        raise RuntimeError("Saved API disabled or missing")
                    provider._api_key = credentials["api_key"]
                    secrets.append(provider._api_key)
                    guard.allow_endpoint(provider._base_url)
                else:
                    runtime = provider._nemoclaw_runtime
                    if runtime is not None:
                        guard.discovery_command = ["docker", "inspect", "-f",
                            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", runtime._cluster_container]
                    for model in {selection.primary, selection.fallback} - {None}:
                        guard.allow_endpoint(await asyncio.wait_for(provider._base_url_for_model(model), timeout=25))
                    guard.discovery_command = None
                    if provider._api_key != "EMPTY":
                        secrets.append(provider._api_key)
            except Exception as exc:
                report["cases"].append({"backend": backend, "model": selection.primary, "status": "blocked",
                    "case": "provider_configuration", "reason": type(exc).__name__, "physical_call_count": 0,
                    "evidence_class": "provider_preflight"})
                save()
                continue
            attempts = []
            original_complete = provider.complete
            async def observed(_original=original_complete, **kwargs):
                began = time.monotonic()
                try:
                    request = json.loads(kwargs["user_prompt"])
                except (ValueError, TypeError):
                    request = {"operation": "read_only_followup", "prompt": kwargs["user_prompt"]}
                row = {"requested_model": kwargs["model"], "request": request}
                attempts.append(row)
                try:
                    response = await _original(**kwargs)
                    raw = response.raw or {}
                    row.update(served_model=raw.get("model"), text=response.text,
                        finish_reason=(raw.get("choices") or [{}])[0].get("finish_reason"), usage=raw.get("usage"))
                    return response
                except BaseException as exc:
                    row["error_type"] = type(exc).__name__
                    error_response = getattr(exc, "response", None)
                    if error_response is not None:
                        row["http_status"] = error_response.status_code
                        row["http_error_detail"] = error_response.text[:2000]
                    raise
                finally:
                    row["latency_s"] = time.monotonic() - began
            provider.complete = observed
            def context(root):
                return AgentContext(model_router=router, primary_backend=provider, fallback_backend=provider,
                    rag=None, experiment_db=None, failure_memory=None, tools=ToolRegistry(),
                    force_real_llm_in_test=True, allow_mock_fallback=False, active_backend=backend,
                    model_routers={backend: router}, primary_backends={backend: provider},
                    fallback_backends={backend: provider}, backend_fallbacks={backend: backend}, artifact_run_root=str(root))
            transport_blocked = False
            for case in fixtures():
                variants = [None]
                if case["id"] in {"I09", "I10", "I19"}:
                    variants = ["N", "P", "B", "I", "R", "V", "S", "M", "specimen"]
                for variant in variants:
                    name = case["id"] + ("-" + variant if variant else "")
                    if name not in selected:
                        continue
                    root = output.parent / backend / name
                    ctx = context(root)
                    lifecycle_start = len(report["simulated_lifecycle_requests"])
                    controller = controller_for(ctx, root, lifecycle_requests=report["simulated_lifecycle_requests"])
                    pending, request = intake_context(controller, case, variant)
                    start_index = len(attempts)
                    started = time.monotonic()
                    value = None
                    if not transport_blocked:
                        try:
                            value = await asyncio.wait_for(classify_chat_request(controller._state, ctx,
                                message=case["message"], pending_id=pending["pending_id"] if pending else None,
                                context={"request": request, "settings": registered_planning_settings(controller)}),
                                timeout=INTAKE_CLEANUP_TIMEOUT_S)
                        except TimeoutError:
                            pass
                    raw_attempts = deepcopy(attempts[start_index:])
                    responses = [a for a in raw_attempts if "text" in a]
                    transport_blocked = transport_blocked or (bool(raw_attempts) and not responses)
                    intent_ok = bool(value and value["intent"] in case["allowed_intents"])
                    effect = {"expectation_met": False, "effect": "unverified", "tool_trace": [], "handoff_ids": []}
                    if responses and value:
                        effect = await exercise_intake_effect(controller, case, value, request)
                        raw_attempts = deepcopy(attempts[start_index:])
                    await settle_verification_controller(controller)
                    served = responses[-1].get("served_model") if responses else None
                    row = {"backend": backend, "model": selection.primary, "served_model": served,
                        "requested_models": [a["requested_model"] for a in raw_attempts],
                        "served_models": [a["served_model"] for a in raw_attempts if a.get("served_model")],
                        "fallback_attempted": any(a["requested_model"] != selection.primary for a in raw_attempts),
                        "scope": {"run_id": controller._state.run_id, "pending": pending}, "case": name,
                        "status": intake_case_status(intent_ok=intent_ok, transport_blocked=transport_blocked,
                            effect=effect, raw_attempts=raw_attempts),
                        "classification": value, "allowed_intents": case["allowed_intents"], "allowed_effects": case["allowed_effects"],
                        "latency_s": time.monotonic() - started, "tool_trace": effect["tool_trace"], "effect": effect,
                        "setup_revision": controller._setup_store().snapshot()["revision"], "handoff_ids": effect["handoff_ids"],
                        "physical_call_count": guard.physical_call_count, "evidence_class": "actual_model_intake_and_controller_adapter",
                        "raw_attempts": raw_attempts, "holdout": case["holdout"],
                        "simulated_lifecycle_requests": deepcopy(report["simulated_lifecycle_requests"][lifecycle_start:]),
                        "model_identity_status": "exact_match" if served == selection.primary else "observed_provider_alias_resolution" if served else "unknown"}
                    report["cases"].append(row)
                    save()
                    print(json.dumps({"backend": backend, "case": name, "status": row["status"],
                        "latency_s": round(row["latency_s"], 2)}), flush=True)
            for name in DECISIONS:
                if name not in selected:
                    continue
                start_index = len(attempts)
                started = time.monotonic()
                root = output.parent / backend / name
                lifecycle_start = len(report["simulated_lifecycle_requests"])
                controller = controller_for(context(root), root, lifecycle_requests=report["simulated_lifecycle_requests"])
                outcome = {"expectation_met": False, "tool_trace": [], "handoff_ids": []}
                if not transport_blocked:
                    try:
                        outcome = await run_case(controller, name)
                    except Exception as exc:
                        outcome["error_type"] = type(exc).__name__
                await settle_verification_controller(controller)
                raw = deepcopy(attempts[start_index:])
                row = {"backend": backend, "model": selection.primary, "case": name,
                    "status": decision_case_status(outcome=outcome, raw_attempts=raw, transport_blocked=transport_blocked),
                    "evidence_class": "actual_model_real_local_handler_supplied_owner_evidence",
                    "physical_call_count": 0, "latency_s": time.monotonic() - started,
                    "served_model": next((a.get("served_model") for a in reversed(raw) if a.get("served_model")), None),
                    "raw_attempts": raw, "requested_models": [a["requested_model"] for a in raw],
                    "served_models": [a["served_model"] for a in raw if a.get("served_model")],
                    "simulated_lifecycle_requests": deepcopy(report["simulated_lifecycle_requests"][lifecycle_start:]),
                    "fallback_attempted": any(a["requested_model"] != selection.primary for a in raw), **outcome}
                report["cases"].append(row)
                save()
                print(json.dumps({"backend": backend, "case": name, "status": row["status"]}), flush=True)
            save()
        report["denied_attempts"] = guard.denied
        report["run_status"] = "complete"
        save()
        coverage = all(Counter(row["case"] for row in report["cases"] if row["backend"] == backend)
                       == Counter(selected) for backend in args.backend or ["openai", "vllm"])
        return coverage and all(row.get("status") == "passed" for row in report["cases"]) and not guard.denied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", action="append", choices=["openai", "vllm"])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--aggregate", action="append", metavar="REPORT", help="Validate complete independent reports without inference")
    args = parser.parse_args()
    try:
        selection = case_selection(args.shard_index, args.shard_count)
    except ValueError as error:
        parser.error(str(error))
    if args.aggregate:
        if args.execute:
            parser.error("Aggregation never executes providers")
        paths = [Path(name).resolve() for name in args.aggregate]
        result = aggregate_reports([json.loads(path.read_text()) for path in paths])
        result["reports"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with Path(args.output).open("x", encoding="utf-8") as target:
                target.write(rendered)
        print(rendered)
        return 0 if result["status"] == "passed" else 1
    if not args.execute:
        print(json.dumps({"fixtures": fixtures(), "decision_cases": DECISIONS, "selection": selection,
            "denied_boundaries": ["unlisted ToolRegistry calls", "hardware sockets", "native camera/serial SDK startup",
                "subprocesses except exact configured read-only Docker inspect", "services and model lifecycle"],
            "execution": False}, ensure_ascii=False, indent=2))
        return 0
    return 0 if asyncio.run(verify(args)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
