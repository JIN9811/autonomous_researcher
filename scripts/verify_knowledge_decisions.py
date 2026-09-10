"""Opt-in registered API/vLLM Knowledge probes; no device or model-startup tools."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def verify(args):
    from dotenv import load_dotenv
    from agents.base_agent import AgentContext
    from agents.knowledge_decision import run_knowledge_decision
    from app.bootstrap import _build_backend, _load_configs, _models_cfg_for_backend
    from backends.model_router import ModelRouter
    from knowledge.markdown_runtime import store_for
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.state import Mode, OrchestratorState, Stage

    load_dotenv(ROOT / ".env", override=False)
    cfg = _load_configs()
    output = Path(tempfile.mkdtemp(prefix="atr-knowledge-decisions-")) / "results.json"
    report = {"schema": "knowledge_decision_probe.v1", "physical_actuation": False,
              "service_startup": False, "evidence_class": "synthetic_software_verification", "cases": []}
    secrets = []

    def save():
        payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        for secret in secrets:
            if secret:
                payload = payload.replace(secret, "[REDACTED]")
        output.write_text(payload, encoding="utf-8")

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
        for case in args.case or ["classified_note", "scoped_retrieval", "insufficient_evidence"]:
            root = output.parent / backend / case
            store = store_for(project_root=root)
            ctx = AgentContext(model_router=router, primary_backend=provider, fallback_backend=provider,
                rag=None, experiment_db=None, failure_memory=None, tools=ToolRegistry(),
                force_real_llm_in_test=True, allow_mock_fallback=False, active_backend=backend,
                model_routers={backend: router}, primary_backends={backend: provider},
                fallback_backends={backend: provider}, backend_fallbacks={backend: backend},
                artifact_run_root=str(root / "runs"))
            responses = []
            class CapturingContext:
                def __init__(self, wrapped):
                    self.wrapped = wrapped

                def __getattr__(self, name):
                    return getattr(self.wrapped, name)

                async def complete(self, *positional, **keywords):
                    response = await self.wrapped.complete(*positional, **keywords)
                    responses.append(response.text[:8000])
                    return response

            ctx = CapturingContext(ctx)
            run_id = f"knowledge-probe-{backend}-{case.replace('_', '-')}"
            source = root / "runs" / run_id / "analysis.json"
            source.parent.mkdir(parents=True, exist_ok=True)
            evidence = [{"id": "current-analysis", "source_ref": str(source), "content": {
                "fixture": True, "not_measured": True, "export_valid": True,
                "objective_score": 1.25, "observation": "Export completed after schema validation."}}]
            scope = {"run_id": run_id}
            expected_id = None
            goal = "Curate the supplied software-verification observation as reusable, source-backed knowledge. Do not claim a physical experiment."
            if case == "scoped_retrieval":
                note = dict(run_id=run_id, cycle_id="loop-000001", agent_id="equipment_agent",
                    event_id="earlier-export", ontology_type="Observation", title="Export validation",
                    body="In this software fixture the export completed after schema validation; this establishes no physical measurement.",
                    source_refs=[str(source)], evidence_kind="observed", fidelity="virtual", tags=["export"])
                expected_id = store.write_note(note)["record_id"]
                store.write_note({**note, "run_id": "unrelated-run", "event_id": "unrelated-export",
                                  "body": "An unrelated run reported a different export schema. Not applicable to this run."})
                goal = "Find and read the existing export-validation knowledge for this run, reuse its citation in context, and avoid a duplicate note."
            elif case == "insufficient_evidence":
                evidence = []
                goal = "Determine the cause of an export failure. No observations or logs have been supplied. Publish the evidence gap without inventing a cause or reusable factual note."
            source.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            before = deepcopy(evidence)
            state = OrchestratorState(run_id=run_id, experiment_id="synthetic-knowledge-probe",
                mode=Mode.TEST, stage=Stage.KNOWLEDGE, active_goal=goal)
            print(json.dumps({"started": case, "backend": backend}), flush=True)
            decision = await run_knowledge_decision(state, ctx, store=store, evidence=evidence, scope=scope,
                settings={"corpora": ["markdown"], "decision_call_timeout_s": args.timeout_s})
            actions = [item["tool"] for item in decision["trace"]]
            accepted = decision["status"] == "accepted" and decision["llm_used"] and before == evidence
            if case == "classified_note":
                accepted = accepted and bool(decision["note_receipts"]) and bool(decision["citations"])
            elif case == "scoped_retrieval":
                accepted = accepted and not decision["note_receipts"] and any(
                    item["source_id"] == expected_id for item in decision["citations"])
                accepted = accepted and all(item.get("run_id") == run_id for item in decision["selected_knowledge"])
            else:
                accepted = accepted and not decision["note_receipts"] and bool(decision["no_knowledge_reason"])
            row = {"backend": backend, "case": case, "expectation_met": bool(accepted),
                "duration_s": decision["duration_s"], "model": decision.get("model"), "tools": actions,
                "evidence_unchanged": before == evidence, "decision": decision,
                "model_responses": responses}
            report["cases"].append(row)
            save()
            print(json.dumps({key: row[key] for key in ("backend", "case", "expectation_met", "duration_s", "model", "tools")}), flush=True)
    save()
    print(json.dumps({"report": str(output), "physical_actuation": False}), flush=True)
    return bool(report["cases"]) and all(item.get("expectation_met", False) for item in report["cases"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backend", action="append", choices=["openai", "vllm"])
    parser.add_argument("--case", action="append", choices=["classified_note", "scoped_retrieval", "insufficient_evidence"])
    parser.add_argument("--timeout-s", type=float, default=300)
    options = parser.parse_args()
    if not options.execute:
        parser.error("Use --execute to opt in to registered model calls; no device or model startup.")
    raise SystemExit(0 if asyncio.run(verify(options)) else 1)
