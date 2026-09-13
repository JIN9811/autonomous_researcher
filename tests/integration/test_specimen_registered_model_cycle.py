"""Opt-in current-graph cycle: real registered models, no device actuation.

Run with AX4LAB_VERIFY_REGISTERED_MODEL_CYCLE=1. Credentials are read only;
all controller state is isolated by the existing guarded cycle fixture.
"""
import json
import os
import time
from pathlib import Path

import pytest

from test_orchestrator_setup_loop import actual_controller  # noqa: F401
from test_orchestrator_setup_loop import (
    test_confirmed_setup_enters_original_initial_lhs_and_real_design as run_existing_cycle,
)


@pytest.mark.skipif(os.getenv("AX4LAB_VERIFY_REGISTERED_MODEL_CYCLE") != "1",
                    reason="Explicit opt-in required for real model requests")
@pytest.mark.parametrize("actual_controller", ["registered_models"], indirect=True)
@pytest.mark.asyncio
async def test_current_cycle_uses_registered_models_without_actuation(actual_controller, monkeypatch, tmp_path):
    """A skipped owner, deterministic replacement or failed model route cannot pass."""
    controller, guard = actual_controller
    ctx = controller._deps.agent_context
    ctx.force_real_llm_in_test = True
    ctx.allow_mock_fallback = False
    # Exercise the existing configurable wait budget, not a replacement decision.
    # Image API latency can exceed the 45-second default. Freshness admission is
    # unchanged and may still reject evidence that expires during a completion.
    from agents.vision.agent import VisionAgent
    original_vision_run = VisionAgent.run

    async def configured_vision_run(self, state, context):
        state.run_metadata["vision_decision_settings"] = {"timeout_s": 90.0}
        return await original_vision_run(self, state, context)

    monkeypatch.setattr(VisionAgent, "run", configured_vision_run)
    root = Path(__file__).resolve().parents[2]
    credentials = json.loads((root / "memory/api_keys.json").read_text())
    assert credentials.get("enabled") and credentials.get("api_key"), "Saved API route is unavailable"
    # apply_openai_api_key is the production saved-route mechanism. Restore its
    # process-local environment effect; never change the saved key or live server.
    monkeypatch.setenv("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    await controller.apply_openai_api_key(credentials["api_key"], enabled=True, emit_event=False)
    guard.allow_endpoint(ctx.primary_backends["openai"]._base_url)
    attempts = []
    seen = set()
    for backend_name, provider in ctx.primary_backends.items():
        if id(provider) in seen:
            continue
        seen.add(id(provider))
        original = provider.complete

        async def observed(*args, _original=original, _backend=backend_name, **kwargs):
            metadata = kwargs.get("metadata") or {}
            entry = {"backend": _backend, "requested_model": kwargs.get("model"),
                     "task_type": metadata.get("task_type"),
                     "requested_task_type": metadata.get("requested_task_type"),
                     "module_id": metadata.get("module_id"), "status": "running"}
            attempts.append(entry)
            started = time.perf_counter()
            try:
                response = await _original(*args, **kwargs)
                raw = response.raw if isinstance(response.raw, dict) else {}
                entry.update(status="completed", served_model=raw.get("model") or response.model,
                             usage=raw.get("usage"))
                return response
            except BaseException as exc:
                entry.update(status="failed", error_type=type(exc).__name__)
                raise
            finally:
                entry["elapsed_s"] = round(time.perf_counter() - started, 3)
                # No prompts, responses, credentials or user memory in this log.
                (tmp_path / "registered-model-attempts.json").write_text(json.dumps(attempts, indent=2))
                print(json.dumps(entry), flush=True)

        monkeypatch.setattr(provider, "complete", observed)
    started = time.perf_counter()
    completed = False
    try:
        await run_existing_cycle(actual_controller, monkeypatch, tmp_path,
                                 "next_design", "virtual_bridge", cycle_timeout_s=900)
        completed = True
        assert attempts and all(a["status"] == "completed" for a in attempts), attempts
        assert all(a.get("served_model") and a["backend"] != "mock" for a in attempts)
        required_model_owners = {"orchestrator", "design", "specimen", "vision", "manipulation",
                                 "equipment", "analysis", "knowledge", "bo", "guardian"}
        assert required_model_owners <= {a.get("module_id") for a in attempts}, (
            "Completed virtual nodes must not bypass their LLM decision layers", attempts)
        assert guard.physical_call_count == 0 and not guard.denied
    finally:
        (tmp_path / "registered-model-cycle.json").write_text(json.dumps({
            "completed_current_cycle": completed, "elapsed_s": round(time.perf_counter() - started, 3),
            "model_attempts": attempts, "physical_call_count": guard.physical_call_count,
            "denied_effects": guard.denied,
            "test_configuration": {"vision_decision_timeout_s": 90.0,
                                   "production_default_modified": False,
                                   "evidence_freshness_modified": False},
            "completed_nodes": [e.get("node_id") for e in controller.recent_events()
                                if e.get("type") == "node.completed"],
            "limitations": ["Device boundaries and experiment data are synthetic.",
                            "Background FEM is not executed.",
                            "Model coverage is reported by observed calls, not inferred from completed nodes."]}, indent=2))
