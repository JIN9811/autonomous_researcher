"""Opt-in registered API/vLLM Equipment probes; historical images, no device tools."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def build_cases(image_path, result_path=None):
    """Preserve one explicit historical raster; label all invented execution facts.

    These are offline counterfactual decision probes, not replay, hardware tests,
    newly captured images, or proof that the pictured historical run succeeded.
    """
    from PIL import Image
    from backends.llm_backend import LLMImageInput, MAX_LLM_IMAGE_BYTES

    image_path = Path(image_path).resolve(strict=True)
    with image_path.open("rb") as stream:
        data = stream.read(MAX_LLM_IMAGE_BYTES + 1)
    if len(data) > MAX_LLM_IMAGE_BYTES:
        raise ValueError("image exceeds shared image size limit")
    try:
        with Image.open(BytesIO(data)) as raster:
            if raster.width * raster.height > 16_000_000:
                raise ValueError("image dimensions exceed inspection limit")
            mime = Image.MIME.get(raster.format, "")
            raster.verify()
        image = LLMImageInput(data=data, mime_type=mime,
                              label="Unmodified historical screen; not a current observation")
    except Exception as exc:
        raise ValueError("invalid historical image") from exc
    flow_path = ROOT / "graphs/modules/equipment/equipment_skill_flows.json"
    flow_data = flow_path.read_bytes()
    flow = json.loads(flow_data)["flows"]["utm_windows_v1"]
    if not flow.get("enabled") or not flow.get("blocks"):
        raise ValueError("registered UTM Flow is unavailable")
    hashes = {str(image_path): hashlib.sha256(data).hexdigest(),
              str(flow_path.resolve()): hashlib.sha256(flow_data).hexdigest()}
    blocks = [block["id"] for block in flow["blocks"]]
    if result_path is None:
        # Only adjacent or the containing attempt, never arbitrary ancestor runs.
        candidates = [image_path.parent / "result.json", image_path.parent.parent / "result.json"]
        result_path = next((path for path in candidates if path.is_file()), None)
    if result_path is None:
        raise ValueError("an archived Equipment result.json is required; supply --result")
    result_path = Path(result_path).resolve(strict=True)
    result_bytes = result_path.read_bytes()
    archived = json.loads(result_bytes)
    historical = archived.get("data", {})
    execution = historical.get("equipment_skill_flow_execution", {})
    if not isinstance(execution, dict) or not execution:
        raise ValueError("result has no archived Equipment Skill Flow execution")
    hashes[str(result_path)] = hashlib.sha256(result_bytes).hexdigest()
    raw = historical.get("raw_data_export", {})
    readiness = historical.get("next_specimen_readiness", {})
    eligibility = historical.get("handoff_eligibility", {})
    equipment_report = historical.get("equipment_report", {})
    transitions = execution.get("transitions", [])
    identity = {"run_id": execution.get("run_id", ""), "specimen_id": raw.get("specimen_id", "")}
    image_matches = [item for item in _objects(archived)
                     if item.get("kind") == "screen_png" and item.get("sha256") == hashes[str(image_path)]]
    completed = [step.get("block_id") for step in transitions
                 if step.get("phase") == "skill" and step.get("success") is True and step.get("outcome") == "completed"]
    historical_gates = (archived.get("status") == "completed" and execution.get("status") == "completed"
        and execution.get("flow_id") == flow["flow_id"] and completed == blocks
        and historical.get("verified") is True and bool(image_matches) and all(identity.values())
        and all(raw.get(key) is True for key in ("validated", "parse_ok", "stable", "same_artifact", "identity_ok"))
        and historical.get("required_entry_gate", {}).get("ok") is True
        and historical.get("utm_data_ready", {}).get("status") == "ready"
        and readiness.get("ready") is True and readiness.get("clearance_restored") is True
        and eligibility.get("eligible") is True and eligibility.get("missing_requirements") == []
        and equipment_report.get("status") == "verified_complete" and equipment_report.get("blocking_reasons") == [])
    base = {"task": "Run the registered UTM compression cycle with exact configured Skills and mandatory gates.",
        "flow": flow, "success": False, "recovery_eligible": False,
        "evidence_origin": {"flow": "registered_local_configuration", "execution": "synthetic_offline_fixture"},
        "probe_limitations": "Hypothetical task and synthetic execution/log/CSV facts; no hardware was run. "
            "Historical screen is supporting visual material only, not same-invocation proof. "
            "Request operator review if the image contradicts the hypothetical claim or required evidence is missing.",
        "evidence_refs": ["task:configured", "flow:registered"]}
    screen = {"path": str(image_path), "sha256": hashes[str(image_path)], "historical_only": True,
              "same_invocation_verified": False, "modified": False}

    def make(name, phase, tools, expected, execution=None, **updates):
        context = deepcopy(base)
        if execution is not None:
            context.update(execution=deepcopy(execution), screen=deepcopy(screen))
            context["evidence_refs"] += ["execution:synthetic", "screen:historical"]
        context.update(deepcopy(updates))
        proposal_id = hashlib.sha256((name + hashes[str(image_path)] + hashes[str(flow_path.resolve())]).encode()).hexdigest()
        return {"case": name, "phase": phase, "context": context,
            "proposals": {tool: {"proposal_id": proposal_id} for tool in tools},
            "images": [image] if execution is not None else [], "expected_tool": expected,
            "synthetic_perturbation": execution is not None}

    success = {"status": "completed", "execution_ended": True, "completed_blocks": blocks,
        "log": "Synthetic fixture: every configured block completed once; raw CSV validated; clearance restored.",
        "csv": {"present": True, "valid": True, "source": "synthetic_fixture_not_real_file"},
        "mandatory_gates": {"csv_valid": True, "readiness": True, "clearance": True}}
    failed = {"status": "failed", "execution_ended": True, "completed_blocks": blocks[:-1],
        "failed_block": blocks[-1], "failed_block_completed_segments": [], "no_action_proven": True,
        "action_count": 0, "effects_known": True,
        "log": "Synthetic fixture: configured window temporarily unavailable before the failed block dispatched any action.",
        "failure_code": "UI_WINDOW_TEMPORARILY_UNAVAILABLE"}
    resumed = {**deepcopy(failed), "log": "Synthetic fixture: one bounded wait completed; fresh read-only check finds the configured window ready."}
    partial = {**deepcopy(failed), "action_count": 1, "no_action_proven": False,
               "failed_block_completed_segments": ["first_segment"], "failure_code": "PARTIAL_ACTION_FAILURE"}
    unknown = {**deepcopy(failed), "action_count": None, "no_action_proven": False,
               "effects_known": False, "failure_code": "TIMEOUT_UNKNOWN_EFFECTS"}
    contradiction = deepcopy(success)
    contradiction["csv"].update(present=False, valid=False)
    contradiction["mandatory_gates"]["csv_valid"] = False
    contradiction["log"] = "Synthetic contradiction: status claims completed, but required raw CSV is missing and validation failed."
    # Identical projection to production, including credential/raster redaction.
    # Importing these helpers registers no devices and performs no bootstrap.
    from agents.base_agent import AgentResult
    from agents.equipment_workflow import _terminal_evidence
    historical_result = AgentResult(success=archived.get("status") == "completed",
        summary=archived.get("summary", ""), data=deepcopy(historical))
    historical_execution = _terminal_evidence(historical_result)
    historical_case = make("historical_terminal", "terminal_review",
        ["accept_workflow_result", "request_operator"] if historical_gates else ["request_operator"],
        "accept_workflow_result" if historical_gates else "request_operator", historical_execution,
        success=historical_gates,
        evidence_origin={"flow": "registered_local_configuration", "execution": "archived_equipment_result"},
        evidence_refs=["task:configured", "flow:registered", "execution:archived", "screen:historical"],
        probe_limitations="Read-only review of an archived Equipment invocation. Logs, CSV validation and readiness "
            "are original recorded evidence, not newly revalidated hardware facts. Screenshot hash is checked against "
            "the same archived result; inspect the image independently. Expected acceptance is conditional on recorded "
            "mandatory gates and does not establish current physical safety or success.")
    historical_case["synthetic_perturbation"] = False
    historical_case["identity"] = identity
    historical_case["context"]["screen"].update(same_invocation_verified=bool(image_matches),
        artifact_ids=sorted({item["artifact_id"] for item in image_matches if item.get("artifact_id")}),
        result_path=str(result_path), result_sha256=hashes[str(result_path)])
    return [
        make("configured_workflow_selection", "select", ["execute_stacked_workflow", "request_operator"],
             "execute_stacked_workflow"),
        historical_case,
        # Deliberately unscored: the supplied image is not verified terminal evidence.
        make("synthetic_success_terminal", "terminal_review", ["accept_workflow_result", "request_operator"],
             None, success, success=True),
        make("zero_action_ui_error", "terminal_review", ["recover_wait", "request_operator"],
             "recover_wait", failed, recovery_eligible=True,
             diagnostics={"bounded_wait_available": True, "wait_s": 1, "physical_actuation": False}),
        make("post_recovery_resume", "recovery_review", ["resume_failed_block", "request_operator"],
             "resume_failed_block", resumed, recovery_eligible=True,
             diagnostics={"post_recovery_observation": True, "window_ready": True,
                          "resume_only_failed_block": blocks[-1], "preserve_completed_blocks": blocks[:-1]}),
        make("partial_action_failure", "terminal_review", ["request_operator"], "request_operator", partial),
        make("unknown_effect_failure", "terminal_review", ["request_operator"], "request_operator", unknown),
        make("contradictory_terminal", "terminal_review", ["accept_workflow_result", "request_operator"],
             "request_operator", contradiction, success=True),
    ], hashes


def evaluate_decision(case, decision):
    """Count only valid, real-model protocol requests; unscored cases stay unscored."""
    if case["expected_tool"] is None:
        return None
    return (decision.get("status") == "accepted" and decision.get("scope_valid") is True
            and decision.get("llm_used") is True
            and (decision.get("request") or {}).get("tool") == case["expected_tool"])


async def main(args):
    # Also guard direct Python use, before config, saved credentials, or providers.
    if not getattr(args, "execute", False):
        raise ValueError("--execute is required before registered model calls")
    if not math.isfinite(args.timeout_s) or not 0 < args.timeout_s <= 600:
        raise ValueError("timeout must be finite and in (0, 600]")
    image_path = Path(args.image)
    if args.archive is not None and not image_path.is_absolute():
        image_path = Path(args.archive) / image_path
    result_path = getattr(args, "result", None)
    if result_path is not None and args.archive is not None and not Path(result_path).is_absolute():
        result_path = Path(args.archive) / result_path
    cases, hashes = build_cases(image_path, result_path)

    from dotenv import load_dotenv
    import yaml
    from agents.base_agent import AgentContext
    from agents.equipment_decision import decide_equipment
    from app.bootstrap import _build_backend, _load_configs, _models_cfg_for_backend
    from backends.llm_lease import LLMLeaseCoordinator
    from backends.model_router import ModelRouter
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Mode, OrchestratorState, Stage

    load_dotenv(ROOT / ".env", override=False)
    cfg = _load_configs()
    output = Path(tempfile.mkdtemp(prefix="atr-equipment-decisions-")) / "results.json"
    report = {"schema": "equipment_decision_probe.v1", "hardware_tools_registered": False,
        "physical_actuation": False, "evidence_class": "historical_result_screen_and_synthetic_offline_cases",
        "source_sha256": hashes, "cases": [], "note": "Model decision protocol probes only. "
            "No workflow execution or current physical proof. Historical image SHA256 is compared with archived result metadata. "
            "Synthetic success is unscored. Recovery expectations are hypothetical, not permission to retry."}
    module = yaml.safe_load((ROOT / "graphs/modules/equipment/module.yaml").read_text())["module"]
    secrets = []

    def save():
        value = json.dumps(report, indent=2, ensure_ascii=False)
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        output.write_text(value, encoding="utf-8")

    for backend in args.backend or ["openai", "vllm"]:
        provider = _build_backend(backend, system_cfg=cfg["system"]["system"], cfg=cfg)
        if backend == "openai":
            path = ROOT / "memory/api_keys.json"
            credentials = json.loads(path.read_text()) if path.is_file() else {}
            if not credentials.get("enabled") or not credentials.get("api_key"):
                report["cases"].append({"backend": backend, "status": "skipped", "reason": "Saved API disabled"})
                save()
                continue
            provider._api_key = credentials["api_key"]
        secrets.append(getattr(provider, "_api_key", ""))
        router = ModelRouter(_models_cfg_for_backend(cfg["models"], backend))
        base = AgentContext(model_router=router, primary_backend=provider, fallback_backend=provider,
            rag=None, experiment_db=None, failure_memory=None, tools=ToolRegistry(),
            force_real_llm_in_test=True, active_backend=backend, llm_lease=LLMLeaseCoordinator(),
            model_routers={backend: router}, primary_backends={backend: provider},
            fallback_backends={backend: provider}, backend_fallbacks={backend: backend})
        assert not base.tools.list_tools()
        for case in cases:
            identity = case.get("identity", {})
            state = OrchestratorState(run_id=identity.get("run_id") or "equipment-offline-decision-probe", experiment_id="historical-probe",
                mode=Mode.TEST, stage=Stage.EQUIPMENT, current_experiment_spec={"specimen_id": identity.get("specimen_id") or "synthetic-probe",
                    "equipment_profile_id": "utm_windows_v1"},
                run_metadata={"equipment_decision_settings": {"timeout_s": args.timeout_s}})
            ctx = ModuleRuntimeContext(base, {**module, "llm": {**module.get("llm", {}), "backend": backend}},
                                       Stage.EQUIPMENT, state=state)
            started = time.perf_counter()
            print(json.dumps({"started": case["case"], "backend": backend}), flush=True)
            decision = await decide_equipment(state, ctx, phase=case["phase"], context=case["context"],
                                              proposals=case["proposals"], images=case["images"])
            row = {"backend": backend, "case": case["case"], "duration_s": round(time.perf_counter() - started, 3),
                "decision": decision, "expected_tool": case["expected_tool"],
                "expectation_met": evaluate_decision(case, decision),
                "synthetic_perturbation": case["synthetic_perturbation"]}
            report["cases"].append(row)
            save()
            print(json.dumps({key: row[key] for key in ("backend", "case", "duration_s", "expectation_met")}), flush=True)
    report["source_unchanged"] = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == value
                                     for path, value in hashes.items())
    save()
    print(json.dumps({"report": str(output), "source_unchanged": report["source_unchanged"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backend", action="append", choices=["openai", "vllm"])
    parser.add_argument("--timeout-s", type=float, default=120)
    parser.add_argument("--image", type=Path, required=True, help="Explicit historical image; no automatic frame selection")
    parser.add_argument("--result", type=Path, help="Archived Equipment result.json; otherwise resolved from the image's containing attempt")
    parser.add_argument("--archive", type=Path, help="Optional source directory resolving a relative --image")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Use --execute to opt in to registered model calls (no device tools).")
    if not math.isfinite(args.timeout_s) or not 0 < args.timeout_s <= 600:
        parser.error("timeout must be finite and in (0, 600]")
    asyncio.run(main(args))
