"""Opt-in real registered-model intake verification; no execution/tool access."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = [
    ("virtual", "테스트 모드, 가상 브릿지", "start_run"),
    ("installed", "테스트 모드, 실제 프린터", "start_run"),
    ("physical", "테스트 모드, 실제 출력", "start_run"),
    ("installed_alias", "테스트 모드, 설치 프린터", "start_run"),
    ("bare", "테스트 모드", "start_run"),
    ("experiment", "실험 수행", "start_run"),
    ("experiment_with_inputs", "PLA gyroid 시편 30x30x30 mm로 에너지 흡수 최적화 실험 수행", "start_run"),
    ("experiment_question", "실험 수행하면 어떤 순서로 진행돼?", "question"),
    ("experiment_negative", "지금 실험 수행하지 마", "non_execution"),
    ("virtual_question", "테스트 모드, 가상 브릿지가 뭐야?", "question"),
    ("installed_question", "테스트 모드, 실제 프린터에서는 출력을 생략해?", "question"),
    ("physical_question", "테스트 모드, 실제 출력 경로를 설명해줘", "question"),
    ("negative", "테스트 모드, 실제 프린터 실행하지 마", "non_execution"),
    ("quoted", "'테스트 모드, 실제 출력'이라는 문구의 뜻을 알려줘", "question"),
    ("hypothetical", "테스트 모드, 실제 프린터라고 입력하면 어떻게 돼?", "question"),
    ("setup_only", "실행하지 말고 다음 실험 목표 설정만 에너지 흡수 최적화로 수정해줘", "change_setup"),
    ("automatic", '[Automatic test input] 테스트 모드, installed_printer. 아래 시나리오로 실험 수행.\n'
     '{"goal":"Compare energy absorption","constraints":{"material":"PLA","specimen_size_mm":[30,30,30]}}', "start_run"),
]


async def controller_cases(ctx, root, backend):
    """Compatibility CLI flag; verify the current dialogue admission contract."""
    return await dialogue_cases(ctx, root, backend)


async def dialogue_cases(ctx, root, backend, selected_cases=None):
    """Real models, ordinary dialogue + Setup; execution intercepted before Design."""
    from scripts.verify_orchestrator_setup import controller_for, settle_verification_controller
    from agents.module_discovery import discover_agent_modules
    from app.planning_dialogue import dialogue_for, plain_message
    from orchestrator.state import Mode
    from copy import deepcopy
    rows = []
    cases = [("virtual", "테스트 모드, 가상 브릿지", "virtual_bridge"),
             ("installed", "테스트 모드, 실제 프린터", "installed_printer"),
             ("physical", "테스트 모드, 실제 출력", "physical_print"),
             ("human_ko", None, None), ("human_en", None, None)]
    for name, trigger, path in cases:
        if selected_cases and name not in selected_cases:
            continue
        c = controller_for(ctx, root / backend / ("dialogue_" + name), lifecycle_requests=[])
        for module in discover_agent_modules():
            if module.agent_name not in c._deps.agent_registry.names():
                c._deps.agent_registry.register_module(module)
        c._state.mode = Mode.LIVE
        c._bind_planning_session(None)
        admitted, turns = [], []
        async def stop_before_design(*, goal, constraints, **kwargs):
            admitted.append({"goal": goal, "constraints": deepcopy(constraints),
                "spec": c._build_planning_spec(base_spec={}, constraints=constraints)})
            return {"ok": True, "verification_boundary": "before_design_dispatch"}
        c._handoff_planning_to_design = stop_before_design
        began = time.monotonic()
        try:
            result = await c.bootstrap_live_orchestrator()
            assert result["ok"], result.get("message")
            if trigger:
                result = await c.planning_message(message=trigger)
                await asyncio.wait_for(c._test_scenario.task, 600)
                if c._planning_handoff_task:
                    await c._planning_handoff_task
            else:
                messages = (["현재 가능한 실험 패키지는 뭐야?", "좋아요. 조건을 정해보죠.",
                    "에너지 흡수를 개선하고 싶고 재료는 PLA로 할게요.", "그런데 AX4LAB에서 에이전트와 브릿지는 어떻게 달라?",
                    "시편은 gyroid 구조로 가로 세로 높이 각각 30 mm로 해주세요.",
                    "재료는 PETG로 변경할게요. 아직 시작하지는 마세요.", "네, 이 조건으로 실험을 시작해 주세요."]
                    if name == "human_ko" else ["Which experiment packages are available?", "Yes, let's plan one.",
                    "I want to improve energy absorption, using PLA.", "By the way, how do agents differ from device bridges in AX4LAB?",
                    "Use a gyroid specimen measuring 30 by 30 by 30 mm.", "Change the material to PETG, but don't start yet.",
                    "Yes, start the experiment with these conditions."])
                for i, message in enumerate(messages):
                    before = deepcopy(dialogue_for(c).values())
                    result = await c.planning_message(message=message, session_id=c._planning_session_id)
                    values = dialogue_for(c).values()
                    assert result["ok"], result.get("message")
                    if i == 3:
                        assert values == before, "Question changed accepted research values"
                    if i < len(messages)-1:
                        assert not admitted, "Premature execution"
                    if i == 5:
                        assert values.get("material") == "PETG", values
                    turns.append({"message": message, "values": values, "setup_revision": c._setup_store().snapshot()["revision"]})
                # A model may explicitly re-review the revised material before
                # accepting execution. Supply a real confirmation, not a bypass.
                if not admitted and (dialogue_for(c).pending or {}).get("purpose") == "run_review":
                    confirmation = "네, 방금 검토한 조건으로 실험 실행을 승인합니다." if name == "human_ko" else "Yes, I approve starting the experiment with the conditions you just reviewed."
                    result = await c.planning_message(message=confirmation, session_id=c._planning_session_id)
                    assert result["ok"], result.get("message")
                    turns.append({"message": confirmation, "values": dialogue_for(c).values(),
                        "setup_revision": c._setup_store().snapshot()["revision"]})
            assert len(admitted) == 1, {"admitted": len(admitted), "driver": c._test_scenario.status, "last": c._planning_messages[-1:]}
            actual = admitted[0]
            assert actual["constraints"].get("printer_test_path") == path
            if path:
                assert actual["spec"]["print"]["use_ejection_only_project_file"] == (path == "installed_printer")
            else:
                assert actual["constraints"]["material"] == "PETG"
                assert actual["spec"]["print"]["start_immediately"] is True
            for m in c._planning_messages:
                if m.get("role") in {"operator", "orchestrator"}:
                    plain_message(m["content"])
            row = {"passed": True}
        except Exception as exc:
            row = {"passed": False, "error": str(exc), "error_type": type(exc).__name__,
                   "dialogue_diagnostic": getattr(dialogue_for(c), "last_error", None)}
        finally:
            c._test_scenario.cancel()
            if c._test_scenario.task:
                await asyncio.gather(c._test_scenario.task, return_exceptions=True)
            await settle_verification_controller(c)
        row.update(backend=backend, case="dialogue_" + name, latency_s=round(time.monotonic()-began, 3),
            admitted=admitted, turns=turns, setup=c._planning_setup_projection(),
            messages=[{k: m.get(k) for k in ("role", "content", "input_source")} for m in c._planning_messages])
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("backend", "case", "passed", "latency_s", "error")}, ensure_ascii=False), flush=True)
        (root / (backend + "-dialogue-progress.json")).write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    return rows


async def verify(args):
    from scripts.orchestrator_verification_guard import VerificationGuard
    output = Path(tempfile.mkdtemp(prefix="validation-test-intake-", dir=ROOT / "runs")) / "report.json"
    report = {"scope": "registered model dialogue before Design dispatch" if args.dialogue or args.controller else "actual registered model chat classification only", "cases": [],
              "physical_calls": 0, "execution_started": False}
    print(json.dumps({"report": str(output)}), flush=True)
    with VerificationGuard() as guard:
        from app.bootstrap import _load_configs, _build_backend, _models_cfg_for_backend
        from backends.model_router import ModelRouter
        from agents.base_agent import AgentContext
        from agents.core.orchestrator.decision import classify_chat_request
        from mcp_tools.tool_registry import ToolRegistry
        from orchestrator.state import OrchestratorState, Mode, Stage
        cfg = _load_configs()
        for backend in args.backend or ["openai", "vllm"]:
            provider = _build_backend(backend, system_cfg=cfg["system"]["system"], cfg=cfg)
            router = ModelRouter(_models_cfg_for_backend(cfg["models"], backend))
            route = router.select("orchestrator_plan")
            if backend == "openai":
                credentials = json.loads((ROOT / "memory/api_keys.json").read_text())
                if not credentials.get("enabled") or not credentials.get("api_key"):
                    raise RuntimeError("Saved API disabled or missing")
                provider._api_key = credentials["api_key"]
                guard.allow_endpoint(provider._base_url)
            else:
                runtime = provider._nemoclaw_runtime
                if runtime:
                    guard.discovery_command = ["docker", "inspect", "-f",
                        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", runtime._cluster_container]
                for model in {route.primary, route.fallback} - {None}:
                    guard.allow_endpoint(await provider._base_url_for_model(model))
                guard.discovery_command = None
            observed = []
            original = provider.complete
            async def record(_original=original, **kwargs):
                try:
                    response = await _original(**kwargs)
                except Exception as exc:
                    detail = getattr(getattr(exc, "response", None), "text", "")
                    print(json.dumps({"backend": backend, "provider_error": type(exc).__name__, "detail": detail[:1200]}, ensure_ascii=False), flush=True)
                    raise
                observed.append({"model": (response.raw or {}).get("model"), "response": response.text})
                return response
            provider.complete = record
            ctx = AgentContext(model_router=router, primary_backend=provider, fallback_backend=provider,
                rag=None, experiment_db=None, failure_memory=None, tools=ToolRegistry(),
                force_real_llm_in_test=True, allow_mock_fallback=False, active_backend=backend)
            state = OrchestratorState(run_id="validation-test-intake", experiment_id="validation",
                                      mode=Mode.LIVE, stage=Stage.IDLE)
            if args.controller or args.dialogue:
                rows = await dialogue_cases(ctx, output.parent, backend, args.dialogue_case) if args.dialogue else await controller_cases(ctx, output.parent, backend)
                models = sorted({r["model"] for r in observed if r.get("model")})
                for row in rows:
                    row["served_models"] = models
                    row["passed"] = row["passed"] and bool(models)
                report["cases"].extend(rows)
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                continue
            for iteration in range(args.repeat):
                for name, message, expected in CASES[:5] if args.starts_only else CASES:
                    observed.clear()
                    began = time.monotonic()
                    result = await classify_chat_request(state, ctx, message=message,
                        context={"request": {"pending_request": None, "setup_context": None,
                            "instruction": "A setup context is editing/discussion only, never run approval. For observation refresh, confirm_pending requires an explicit request for a fresh observation, not yes or ordinary continue."}})
                    accepted = result["intent"] not in {"start_run", "confirm_pending", "change_setup"} if expected == "non_execution" else result["intent"] == expected
                    row = {"backend": backend, "case": name, "iteration": iteration + 1,
                           "message": message, "expected": expected, "result": result,
                           "latency_s": round(time.monotonic() - began, 3),
                           "model_responses": list(observed), "passed": bool(observed) and accepted}
                    report["cases"].append(row)
                    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({k: row[k] for k in ("backend", "case", "iteration", "passed", "result", "latency_s")}, ensure_ascii=False), flush=True)
        report["denied_attempts"] = guard.denied
        report["passed"] = not guard.denied and all(r["passed"] for r in report["cases"])
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backend", action="append", choices=["openai", "vllm"])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--starts-only", action="store_true")
    parser.add_argument("--controller", action="store_true")
    parser.add_argument("--dialogue", action="store_true")
    parser.add_argument("--dialogue-case", action="append", choices=["virtual", "installed", "physical", "human_ko", "human_en"])
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"execution": False, "cases": CASES}, ensure_ascii=False))
    else:
        raise SystemExit(asyncio.run(verify(args)))
