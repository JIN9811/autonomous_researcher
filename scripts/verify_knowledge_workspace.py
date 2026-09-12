"""Opt-in real registered-provider probes of non-actuating agent decision inputs.

Reports delivery, responses and citation text separately; these are not evidence
of scientific benefit, physical operation or acceptance of every proposed tool.
Only public Wiki and synthetic fixtures are sent to providers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def classify_response(pack: dict, output: str) -> dict:
    from agents.knowledge_context import _REFERENCE_TOKEN
    tokens = set(_REFERENCE_TOKEN.findall(output[:16_000]))
    return {"responded": bool(output.strip()), "cited_ids": [
        item["citation_id"] for item in pack.get("items", [])
        if item.get("citation_id") and item["citation_id"] in tokens]}


def delivery_outcome(receipt: dict) -> str:
    """Check actual validated-boundary evidence, never infer use from transport."""
    cited = receipt.get('used_citation_ids', [])
    delivered = receipt.get('delivered_citation_ids', [])
    if not set(cited) <= set(delivered): raise ValueError('used citation was not delivered')
    status = receipt.get('use_status') or 'unknown'
    if status == 'used' and not cited: raise ValueError('used without citation')
    if status == 'excluded' and not receipt.get('non_use_reason'): raise ValueError('exclusion without reason')
    if status == 'unknown' and cited: raise ValueError('unknown cannot claim citations')
    return status


async def question_probe(ctx, query: str) -> dict:
    """Run the real question method with transcript-only synthetic persistence.

    Classifier/Setup isolation is separately covered by the controller integration
    tests; this harness has no graph runner, catalog or device methods.
    """
    from types import SimpleNamespace
    from app.controller import MainController

    class QuestionHarness:
        _explicit_memory_text = staticmethod(MainController._explicit_memory_text)
        def __init__(self):
            self._deps = SimpleNamespace(agent_context=ctx)
            self._state = SimpleNamespace(run_id="synthetic-question", loop_count=0)
            self.messages = []
        def _planning_intake_scope(self):
            return {"session_id": "synthetic-question", "running": False}
        def planning_snapshot(self, **kwargs):
            return {"messages": self.messages}
        def _record_planning_message(self, entry):
            self.messages.append(entry)
            return entry
        async def _append_planning_message(self, entry):
            self.messages.append(entry)

    harness = QuestionHarness()
    return await MainController._planning_knowledge_question(harness, message=query,
        session_id="synthetic-question", intake_scope=harness._planning_intake_scope())


async def verify(args) -> bool:
    from dotenv import load_dotenv
    from agents.base_agent import AgentContext
    from app.bootstrap import _build_backend, _load_configs, _models_cfg_for_backend
    from backends.model_router import ModelRouter
    from tests import knowledge_delivery_fixtures as fixtures
    from tests.unit.test_agent_knowledge_delivery import (
        test_every_active_owner_actual_decision_prompt_carries_relevant_or_no_match_reference_only as invoke_owner,
    )

    load_dotenv(ROOT / ".env", override=False)
    cfg = _load_configs()
    directory = ROOT / "runs" / ("validation-knowledge-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    directory.mkdir(parents=True)
    report = {"schema": "knowledge_provider_delivery_verification.v1", "physical_actuation": False,
              "service_startup": False, "input_class": "public_wiki_and_synthetic_fixture", "cases": []}
    secrets = []

    def save():
        content = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        for secret in secrets:
            if secret:
                content = content.replace(secret, "[REDACTED]")
        (directory / "results.json").write_text(content, encoding="utf-8")

    original_transport = fixtures.KnowledgeDeliveryTransport
    for backend in args.backend or ["openai", "vllm"]:
        provider = _build_backend(backend, system_cfg=cfg["system"]["system"], cfg=cfg)
        if backend == "openai":
            credentials_path = ROOT / "memory/api_keys.json"
            credentials = json.loads(credentials_path.read_text()) if credentials_path.is_file() else {}
            if not credentials.get("enabled") or not credentials.get("api_key"):
                report["cases"].append({"backend": backend, "status": "unavailable", "reason": "Saved API disabled"})
                save()
                continue
            provider._api_key = credentials["api_key"]
        secrets.append(getattr(provider, "_api_key", ""))
        router = ModelRouter(_models_cfg_for_backend(cfg["models"], backend))
        owners = [] if args.questions_only else args.owner or ["orchestrator", "design", "specimen", "vision", "manipulation", "equipment", "analysis", "bo", "knowledge", "guardian"]
        for owner in owners:
            for case, query, match in [("relevant", "Design Agent", True), ("no_match", "nonexistenttokenonly", False)]:
                responses = []
                contexts = []
                case_root = directory / backend / owner / case
                real = AgentContext(model_router=router, primary_backend=provider, fallback_backend=provider,
                    rag=None, experiment_db=None, failure_memory=None, tools=None,
                    force_real_llm_in_test=True, allow_mock_fallback=False, active_backend=backend,
                    model_routers={backend: router}, primary_backends={backend: provider},
                    fallback_backends={backend: provider}, backend_fallbacks={backend: backend},
                    artifact_run_root=str(case_root / "runs"))

                class RegisteredTransport(original_transport):
                    def __init__(self, service, *, query_case):
                        super().__init__(service, query_case=query_case)
                        self.active_backend = backend
                        self.backend_fallbacks = {backend: backend}
                        from knowledge.context_service import KnowledgePrincipal
                        self.knowledge_principal = KnowledgePrincipal('synthetic-provider', run_ids=frozenset({'knowledge-matrix'}))
                        contexts.append(self)

                    async def complete(self, task_type, prompt, **kwargs):
                        self.prompts.append((task_type, prompt, kwargs))
                        pack = fixtures.reference_pack_from_prompt(task_type, prompt)
                        started = time.monotonic()
                        result = await real.complete(task_type, prompt, **kwargs)
                        responses.append({"task_type": task_type, "model": result.model,
                            "duration_s": round(time.monotonic() - started, 3),
                            "pack": pack, "response": result.text, **classify_response(pack, result.text)})
                        return result

                fixtures.KnowledgeDeliveryTransport = RegisteredTransport
                row = {"backend": backend, "owner": owner, "case": case, "responses": responses}
                print(json.dumps({"started": owner, "backend": backend, "case": case}), flush=True)
                started = time.monotonic()
                try:
                    await asyncio.wait_for(invoke_owner(case_root, owner, query, match), timeout=args.timeout_s)
                    receipts = [receipt for transport in contexts for receipt in transport.knowledge_service.delivery.query(transport.knowledge_principal, '')['items']]
                    row['validated_boundary_receipts'] = receipts
                    row['reference_use_outcomes'] = [delivery_outcome(receipt) for receipt in receipts]
                    row['use_claim'] = 'validated_explanatory_citation' if 'used' in row['reference_use_outcomes'] else 'no_validated_use_claim'
                    row["expectation_met"] = bool(responses) and all(item["responded"] for item in responses)
                    row["status"] = "response_verified" if row["expectation_met"] else "no_response"
                except Exception as exc:
                    row.update(expectation_met=False, status="failed", error_type=type(exc).__name__)
                finally:
                    fixtures.KnowledgeDeliveryTransport = original_transport
                row["duration_s"] = round(time.monotonic() - started, 3)
                report["cases"].append(row)
                save()
                print(json.dumps({key: row[key] for key in ("backend", "owner", "case", "status", "duration_s")}), flush=True)
        if args.questions_only:
            from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal
            service = KnowledgeContextService(ROOT, data_root=directory / backend / "memory")
            principal = KnowledgePrincipal(subject_id="synthetic-validation", run_ids=frozenset({"synthetic-question"}),
                local_model_consent=True, remote_model_consent=True)
            ctx = AgentContext(model_router=router, primary_backend=provider, fallback_backend=provider,
                rag=None, experiment_db=None, failure_memory=None, tools=None,
                force_real_llm_in_test=True, allow_mock_fallback=False, active_backend=backend,
                model_routers={backend: router}, primary_backends={backend: provider},
                fallback_backends={backend: provider}, backend_fallbacks={backend: backend},
                knowledge_service=service, knowledge_principal=principal)
            for case, query in [("question", "What does the Design Agent do?"),
                                ("korean", "디자인 에이전트의 역할은 무엇인가요?"),
                                ("unknown", "nonexistenttokenonly"),
                                ("memory_candidate", "Remember zephyrsynthetic concise explanations")]:
                started = time.monotonic()
                result = await asyncio.wait_for(question_probe(ctx, query), timeout=args.timeout_s)
                accepted = bool(result.get("sources")) if case in {"question", "korean"} else (
                    result.get("answer", "").startswith("I can’t provide a grounded answer") if case == "unknown" else
                    result.get("memory_receipt", {}).get("status") == "candidate")
                row = {"backend": backend, "case": case, "expectation_met": accepted,
                    "duration_s": round(time.monotonic() - started, 3), "result": result}
                report["cases"].append(row); save()
                print(json.dumps({key: row[key] for key in ("backend", "case", "expectation_met", "duration_s")}), flush=True)
                if case == "memory_candidate":
                    candidate = result["memory_receipt"]
                    active = service.memory.command(principal, action="confirm", target_id=candidate["record_id"],
                        expected_revision=candidate["revision"], payload={}, idempotency_key="synthetic-confirm")
                    recalled = await asyncio.wait_for(question_probe(ctx, "zephyrsynthetic"), timeout=args.timeout_s)
                    used = any(source["record_id"] == candidate["record_id"] for source in recalled["sources"])
                    service.memory.command(principal, action="forget", target_id=active["record_id"],
                        expected_revision=active["revision"], payload={}, idempotency_key="synthetic-forget")
                    forgotten = await asyncio.wait_for(question_probe(ctx, "zephyrsynthetic"), timeout=args.timeout_s)
                    report["cases"].append({"backend": backend, "case": "confirmed_memory_recall_and_forget",
                        "expectation_met": used and not forgotten["sources"], "recall": recalled, "forgotten": forgotten})
                    save()
    save()
    print(json.dumps({"report": str(directory / "results.json")}), flush=True)
    return bool(report["cases"]) and all(row.get("expectation_met", False) for row in report["cases"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--questions-only", action="store_true", help="Probe actual ORC question method and synthetic private-memory lifecycle only")
    parser.add_argument("--backend", action="append", choices=["openai", "vllm"])
    parser.add_argument("--owner", action="append", choices=["orchestrator", "design", "specimen", "vision", "manipulation", "equipment", "analysis", "bo", "knowledge", "guardian"])
    parser.add_argument("--timeout-s", type=float, default=600)
    options = parser.parse_args()
    if not options.execute:
        parser.error("Use --execute for existing registered providers; no hardware or service startup.")
    raise SystemExit(0 if asyncio.run(verify(options)) else 1)
