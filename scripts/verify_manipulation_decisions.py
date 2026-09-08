"""Opt-in registered API/vLLM decisions over historical evidence; no robot tools."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_cases(archive):
    archive = Path(archive)
    transfer = json.loads((archive / "manipulation_agent/attempt-000001/result.json").read_text())["data"]["manipulation"]
    vision = json.loads((archive / "vision_agent/attempt-000012/result.json").read_text())["data"]
    capture = deepcopy(vision["observation"]["vision_manipulation_completion"])
    execution = {**vision["rollout_stop"], "transfer_task": transfer["transfer_task"],
        "execution_evidence": capture["rollout_execution"], "post_place_interlock": capture["post_place_interlock"]}
    task = {**transfer["transfer_task"], "session_id": capture["session_id"]}
    contradictory = {**capture, "detected": False}
    return [
        {"case": "configured_transfer", "tool": "lerobot.rollout.start", "payload": task,
         "expected_tool": "lerobot.rollout.start"},
        {"case": "configured_clearance", "tool": "lerobot.replay.start", "payload": {
            "task_id": "clear_utm_to_disposal", "source_location": "utm_fixture", "target_location": "discard_bin",
            "dataset_repo_id": "jin/utm_clear", "replay_episode": 0}, "synthetic_perturbation": True,
         "expected_tool": "lerobot.replay.start"},
        {"case": "historical_placement", "payload": execution, "capture": capture, "expected_tool": "accept_task_result"},
        {"case": "contradictory_placement", "payload": execution, "capture": contradictory,
         "synthetic_perturbation": True, "expected_tool": "return_to_owner"},
    ]


async def main(args):
    from dotenv import load_dotenv
    import yaml
    from agents.base_agent import AgentContext
    from agents.manipulation_decision import select_manipulation_tool, review_manipulation_result
    from app.bootstrap import _build_backend, _load_configs, _models_cfg_for_backend
    from backends.llm_lease import LLMLeaseCoordinator
    from backends.model_router import ModelRouter
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.langgraph_runtime import ModuleRuntimeContext
    from orchestrator.state import Mode, OrchestratorState, Stage

    load_dotenv(ROOT / ".env", override=False)
    cfg = _load_configs()
    cases = load_cases(args.archive)
    source_paths = [Path(args.archive) / path for path in (
        "manipulation_agent/attempt-000001/result.json", "vision_agent/attempt-000012/result.json")]
    hashes = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    output = Path(tempfile.mkdtemp(prefix="atr-manipulation-decisions-")) / "results.json"
    report = {"schema": "manipulation_decision_probe.v1", "hardware_tools_registered": False,
        "physical_actuation": False, "evidence_class": "historical_offline_development_cases",
        "source_sha256": hashes, "cases": [], "note": "Historical stop/Vision gates are assumed for task-review probes; no new image validation or physical proof."}
    module = yaml.safe_load((ROOT / "graphs/modules/manipulation/module.yaml").read_text())["module"]
    secrets = []
    def save():
        value = json.dumps(report, indent=2, default=str, ensure_ascii=False)
        for secret in secrets:
            if secret: value = value.replace(secret, "[REDACTED]")
        output.write_text(value)
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
        for case in cases:
            source = cases[2]["capture"]
            state = OrchestratorState(run_id=source["run_id"], experiment_id="historical-probe",
                loop_count=source["loop_id"], mode=Mode.TEST, stage=Stage.MANIPULATION,
                current_experiment_spec={"specimen_id": source["specimen_id"]},
                run_metadata={"manipulation_decision_settings": {"timeout_s": args.timeout_s}})
            ctx = ModuleRuntimeContext(base, {**module, "llm": {**module.get("llm", {}), "backend": backend}},
                Stage.MANIPULATION, state=state)
            assert not base.tools.list_tools()
            started = time.perf_counter()
            print(json.dumps({"started": case["case"], "backend": backend}), flush=True)
            if "capture" in case:
                decision = await review_manipulation_result(state, ctx, "transfer_to_utm", case["payload"], case["capture"],
                    execution_ended=True, vision_accepted=True)
            else:
                decision = await select_manipulation_tool(state, ctx, case["tool"], case["payload"])
            actual = (decision.get("request") or {}).get("tool")
            row = {"backend": backend, "case": case["case"], "duration_s": round(time.perf_counter() - started, 3),
                "decision": decision, "expected_tool": case["expected_tool"],
                "expectation_met": actual == case["expected_tool"], "synthetic_perturbation": case.get("synthetic_perturbation", False)}
            report["cases"].append(row)
            save()
            print(json.dumps({k: row[k] for k in ("backend", "case", "duration_s", "expectation_met")}), flush=True)
    report["source_unchanged"] = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == value for path, value in hashes.items())
    save()
    print(json.dumps({"report": str(output), "source_unchanged": report["source_unchanged"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backend", action="append", choices=["openai", "vllm"])
    parser.add_argument("--timeout-s", type=float, default=120)
    parser.add_argument("--archive", type=Path, default=ROOT / "runs/run-20260906T122533Z-c0effd/runtime/loops/loop-000001")
    args = parser.parse_args()
    if not args.execute: parser.error("Use --execute to opt in to registered model calls (no device tools).")
    asyncio.run(main(args))
