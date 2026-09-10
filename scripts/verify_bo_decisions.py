"""Opt-in BO Agent/API/local inference probes with real numerics and no device tools."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def verify(args):
    from dotenv import load_dotenv
    from agents.base_agent import AgentContext
    from agents.bo_agent import BOAgent
    from app.bootstrap import _build_backend, _load_configs, _models_cfg_for_backend
    from backends.model_router import ModelRouter
    from learning.bo_parameter_space import BOParameterSpace
    from mcp_tools.experiment_tools import register_experiment_tools
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.state import Mode, OrchestratorState, Stage

    load_dotenv(ROOT / ".env", override=False)
    cfg = _load_configs()
    output = Path(tempfile.mkdtemp(prefix="atr-bo-decisions-")) / "results.json"
    report = {"schema": "bo_decision_probe.v1", "physical_actuation": False,
        "service_startup": False, "evidence_class": "synthetic_software_verification", "cases": []}
    secrets = []

    def save():
        text = json.dumps(report, indent=2, ensure_ascii=False, default=str)
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        output.write_text(text, encoding="utf-8")

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
        # Direct AgentContext inference uses registered routes without model prepare/load calls.
        for phase in args.phase or ["initial_design", "acquisition"]:
            count = 0
            registry = ToolRegistry()
            register_experiment_tools(registry)
            tools = ToolRegistry()

            def benchmark(payload):
                nonlocal count
                assert payload["sequential_only"] is True
                assert payload["request"]["execution"] == {"mode": "virtual", "bridge": "virtual", "dry_run": True}
                count += 1
                assert count == 1, "BO repeated a successful numerical invocation"
                return registry.call("experiment.benchmark", payload)

            tools.register("experiment.benchmark", benchmark)
            ctx = AgentContext(model_router=router, primary_backend=provider, fallback_backend=provider,
                rag=None, experiment_db=None, failure_memory=None, tools=tools,
                force_real_llm_in_test=True, allow_mock_fallback=False, active_backend=backend,
                model_routers={backend: router}, primary_backends={backend: provider},
                fallback_backends={backend: provider}, backend_fallbacks={backend: backend},
                artifact_run_root=str(output.parent / "runs"))
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            state = OrchestratorState(run_id=f"bo-probe-{backend}-{phase}-{stamp}",
                experiment_id="synthetic-bo-probe", mode=Mode.TEST, stage=Stage.BO,
                active_goal="Software-only BO verification with synthetic observations. No hardware or research-target attainment claim.")
            settings = {"strategy_control": "configured", "budget": 1,
                "parameter_space": {"cell_size_mm": [6.2, 9.1], "relative_density": [.24, .44]},
                "decision_call_timeout_s": args.timeout_s, "decision_total_timeout_s": 300,
                "num_restarts": 3, "raw_samples": 32}
            if phase == "acquisition":
                normalized, _ = BOAgent.normalize_settings(settings)
                space = BOParameterSpace.from_mapping(normalized["parameter_space"])
                for index, parameters in enumerate(space.lhs_points(8, seed=7)):
                    score = 1.0 - (parameters["cell_size_mm"] - 7.6) ** 2 / 10 - (parameters["relative_density"] - .35) ** 2
                    state.experiment_evaluations.append({"evaluation_id": f"synthetic-{index}",
                        "candidate_id": f"synthetic-{index}", "source": "analysis_agent",
                        "fidelity": "synthetic", "objective_score": score,
                        "metrics": {"energy_density_50pct_MJ_per_m3": score},
                        "metadata": {"fixture": True, "not_measured": True},
                        "objective": {"metric_name": "energy_density_50pct_MJ_per_m3", "constraints": parameters}})
            started = time.monotonic()
            print(json.dumps({"started": phase, "backend": backend}), flush=True)
            result = await BOAgent().run_with_settings(state, ctx, settings)
            bo = result.data.get("bo_result", {})
            decision = bo.get("decision", {})
            row = {"backend": backend, "case": phase, "duration_s": round(time.monotonic() - started, 3),
                "success": result.success, "optimizer_calls": count, "decision": decision,
                "phase": bo.get("optimization_phase"), "backend_active": bo.get("backend_active"),
                "recommendation": bo.get("recommendation"), "artifacts": bo.get("artifacts"),
                "run_id": state.run_id}
            row["expectation_met"] = bool(result.success and count == 1 and decision.get("llm_used")
                and decision.get("status") == "accepted" and row["phase"] == phase)
            report["cases"].append(row)
            save()
            print(json.dumps({key: row[key] for key in ("backend", "case", "duration_s", "expectation_met", "optimizer_calls")}), flush=True)
    save()
    print(json.dumps({"report": str(output), "physical_actuation": False}), flush=True)
    return all(case.get("expectation_met", False) for case in report["cases"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backend", action="append", choices=["openai", "vllm"])
    parser.add_argument("--phase", action="append", choices=["initial_design", "acquisition"])
    parser.add_argument("--timeout-s", type=float, default=120)
    args = parser.parse_args()
    if not args.execute:
        parser.error("Use --execute to opt in to registered model calls; no devices or model startup.")
    raise SystemExit(0 if asyncio.run(verify(args)) else 1)
