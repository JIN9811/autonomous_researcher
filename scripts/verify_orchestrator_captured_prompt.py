"""Read-only registered Gemma capacity probe for an exact controlled-loop prompt."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def probe(path, backend="vllm", project=False):
    from scripts.orchestrator_verification_guard import VerificationGuard
    with VerificationGuard() as guard:
        from app.bootstrap import _load_configs, _build_backend, _models_cfg_for_backend
        from backends.model_router import ModelRouter
        from backends.prompt_registry import get_system_prompt
        config = _load_configs()
        provider = _build_backend(backend, system_cfg=config["system"]["system"], cfg=config)
        route = ModelRouter(_models_cfg_for_backend(config["models"], backend)).select("orchestrator_plan")
        record = max(json.loads(path.read_text()), key=lambda row: row["utf8_bytes"])
        prompt = record["prompt"]
        original_sha = hashlib.sha256(prompt.encode()).hexdigest()
        if project:
            from orchestrator.handoff_projection import project_handoff_prompt
            prompt = json.dumps(project_handoff_prompt(json.loads(prompt)), ensure_ascii=False)
        run_root = Path(config["system"]["system"].get("run_root", "runs"))
        if not run_root.is_absolute():
            run_root = ROOT / run_root
        output = Path(tempfile.mkdtemp(prefix="validation-orchestrator-capacity-", dir=run_root)) / "capacity.json"
        report = {"schema": "verification_report.v1", "evidence_class": "actual_model_exact_captured_prompt_capacity_only",
            "source_prompt_file": str(path.resolve()), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt_utf8_bytes": len(prompt.encode()), "original_prompt_utf8_bytes": record["utf8_bytes"],
            "original_prompt_sha256": original_sha, "projected": project, "backend": backend,
            "sections": {k: len(json.dumps(v, ensure_ascii=False).encode()) for k,v in json.loads(prompt).items()},
            "requested_model": route.primary, "provider_timeout_s": provider._timeout_s,
            "physical_call_count": 0, "handler_effect": "not_executed", "status": "running"}
        began = time.monotonic()
        try:
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
                guard.allow_endpoint(await provider._base_url_for_model(route.primary))
            guard.discovery_command = None
            response = await provider.complete(model=route.primary, system_prompt=get_system_prompt("orchestrator_plan"),
                user_prompt=prompt, metadata={"task_type": "orchestrator_plan"})
            report.update(status="response_received", served_model=(response.raw or {}).get("model"),
                text=response.text, usage=(response.raw or {}).get("usage"))
            from agents.orchestrator_decision import _json_response, validate_choice, _validate_target
            packet = json.loads(prompt)
            choice = validate_choice(_json_response(response.text), set(packet["tools"]), set(packet["evidence"]))
            _validate_target(choice, packet["context"], packet["evidence"])
            report.update(status="valid_decision_response", choice=choice)
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__)
            response = getattr(exc, "response", None)
            if response is not None:
                report.update(http_status=response.status_code, detail=response.text[:2000])
        finally:
            report.update(latency_s=time.monotonic() - began, denied_attempts=guard.denied)
            rendered = json.dumps(report, indent=2, ensure_ascii=False)
            if provider._api_key and provider._api_key != "EMPTY":
                rendered = rendered.replace(provider._api_key, "[REDACTED]")
            output.write_text(rendered)
        print(json.dumps({"report": str(output), "status": report["status"], "http_status": report.get("http_status")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt_file", type=Path)
    parser.add_argument("--backend", choices=["openai", "vllm"], default="vllm")
    parser.add_argument("--project", action="store_true")
    args = parser.parse_args()
    asyncio.run(probe(args.prompt_file, args.backend, args.project))
