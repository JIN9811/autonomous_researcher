"""Unit tests for vLLM startup-path performance guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agents.base_agent import AgentContext
from backends.llm_backend import BaseLLMBackend, LLMResponse
from backends.model_router import ModelRouter
from backends.nemoclaw_vllm_runtime import ManagedVLLMModel, NemoClawVLLMRuntime
from backends.vllm_client import VLLMBackend
from knowledge.experiment_db import ExperimentDB
from knowledge.failure_memory import FailureMemory
from knowledge.rag import HybridRAG, LocalRAGIndex, WebRetriever
from mcp_tools.tool_registry import ToolRegistry


class _PreparedBackend(BaseLLMBackend):
    """Backend that exposes prepare_model so AgentContext can prove it does not duplicate work."""

    def __init__(self) -> None:
        self.prepare_calls = 0
        self.complete_calls = 0

    async def prepare_model(self, model: str) -> None:
        self.prepare_calls += 1

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.complete_calls += 1
        return LLMResponse(text="ok", model=model, raw={"metadata": metadata or {}})


class _FailingBackend(BaseLLMBackend):
    """Backend that records attempted models before failing."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(model)
        raise RuntimeError(f"{model} unavailable")


class _RecordingBackend(BaseLLMBackend):
    """Backend that records the model used for a successful fallback."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(model)
        return LLMResponse(text="openai-ok", model=model, raw={"metadata": metadata or {}})


def _router() -> ModelRouter:
    return ModelRouter(
        {
            "models": {"e4b": {"primary": "gemma4:e4b-it-nvfp4", "fallback": None}},
            "task_routes": {"tool_formatting": "e4b"},
        }
    )


def _rag() -> HybridRAG:
    return HybridRAG(
        local_index=LocalRAGIndex(chunks=[]),
        web_retriever=WebRetriever(tavily_api_key=None, serper_api_key=None),
    )


@pytest.mark.asyncio
async def test_agent_context_does_not_duplicate_backend_prepare() -> None:
    backend = _PreparedBackend()
    ctx = AgentContext(
        model_router=_router(),
        primary_backend=backend,
        fallback_backend=backend,
        rag=_rag(),
        experiment_db=ExperimentDB(),
        failure_memory=FailureMemory(),
        tools=ToolRegistry(),
        active_backend="test",
        primary_backends={"test": backend},
        fallback_backends={"test": backend},
        model_routers={"test": _router()},
    )

    response = await ctx.complete("tool_formatting", "format this")

    assert response.text == "ok"
    assert backend.complete_calls == 1
    assert backend.prepare_calls == 0


@pytest.mark.asyncio
async def test_agent_context_uses_openai_backend_as_last_fallback() -> None:
    local_backend = _FailingBackend()
    openai_backend = _RecordingBackend()
    local_router = ModelRouter(
        {
            "models": {"orchestrator": {"primary": "local-primary", "fallback": "local-fallback"}},
            "task_routes": {"orchestrator_plan": "orchestrator"},
        }
    )
    openai_router = ModelRouter(
        {
            "models": {"orchestrator": {"primary": "gpt-5.5"}},
            "task_routes": {"orchestrator_plan": "orchestrator"},
        }
    )
    model_events: list[dict[str, str]] = []

    async def on_model_call(*, task_type: str, model: str, role: str, backend: str) -> None:
        model_events.append(
            {
                "task_type": task_type,
                "model": model,
                "role": role,
                "backend": backend,
            }
        )

    ctx = AgentContext(
        model_router=local_router,
        primary_backend=local_backend,
        fallback_backend=openai_backend,
        rag=_rag(),
        experiment_db=ExperimentDB(),
        failure_memory=FailureMemory(),
        tools=ToolRegistry(),
        active_backend="vllm",
        primary_backends={"vllm": local_backend, "openai": openai_backend},
        fallback_backends={"vllm": openai_backend, "openai": openai_backend},
        backend_fallbacks={"vllm": "openai", "openai": "openai"},
        model_routers={"vllm": local_router, "openai": openai_router},
        on_model_call=on_model_call,
    )

    response = await ctx.complete("orchestrator_plan", "plan this")

    assert response.text == "openai-ok"
    assert local_backend.calls == ["local-primary", "local-fallback"]
    assert openai_backend.calls == ["gpt-5.5"]
    assert model_events == [
        {
            "task_type": "orchestrator_plan",
            "model": "gpt-5.5",
            "role": "orchestrator:backend_fallback",
            "backend": "openai",
        }
    ]


@pytest.mark.asyncio
async def test_nemoclaw_vllm_runtime_caches_recent_model_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = NemoClawVLLMRuntime(
        enabled=True,
        cluster_container="cluster",
        namespace="ns",
        readiness_cache_s=30,
        models={
            "gemma4:e4b-it-nvfp4": ManagedVLLMModel(
                deployment="vllm-gemma4-e4b",
                node_port=31002,
            )
        },
    )
    calls = {"available": 0}

    async def available(_deployment: str) -> bool:
        calls["available"] += 1
        return True

    monkeypatch.setattr(runtime, "_deployment_available", available)

    await runtime.ensure_model("gemma4:e4b-it-nvfp4")
    await runtime.ensure_model("gemma4:e4b-it-nvfp4")

    assert calls == {"available": 1}


@pytest.mark.asyncio
async def test_nemoclaw_vllm_runtime_reports_model_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = NemoClawVLLMRuntime(
        enabled=True,
        cluster_container="cluster",
        namespace="ns",
        readiness_cache_s=0,
        models={
            "gemma4:e4b-it-nvfp4": ManagedVLLMModel(
                deployment="vllm-gemma4-e4b",
                node_port=31002,
                persistent=True,
            ),
        },
    )

    async def deployment_status(deployment: str) -> dict[str, int]:
        if deployment == "vllm-gemma4-e4b":
            return {"desired_replicas": 1, "available_replicas": 1, "ready_replicas": 1}
        return {"desired_replicas": 1, "available_replicas": 0, "ready_replicas": 0}

    monkeypatch.setattr(runtime, "_deployment_status", deployment_status)

    result = await runtime.model_statuses()

    by_model = {item["model"]: item for item in result["models"]}
    assert by_model["gemma4:e4b-it-nvfp4"]["state"] == "loaded"


@pytest.mark.asyncio
async def test_nemoclaw_vllm_runtime_scales_down_other_worker_before_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = NemoClawVLLMRuntime(
        enabled=True,
        cluster_container="cluster",
        namespace="ns",
        readiness_cache_s=0,
        models={
            "gemma4:31b": ManagedVLLMModel(
                deployment="vllm-gemma4-31b",
                node_port=31001,
                persistent=True,
            ),
            "gemma4:e4b-it-nvfp4": ManagedVLLMModel(
                deployment="vllm-gemma4-e4b",
                node_port=31002,
                depends_on=("gemma4:31b",),
            ),
        },
    )
    scaled_down: list[str] = []

    async def available(deployment: str) -> bool:
        return deployment in {"vllm-gemma4-31b", "vllm-gemma4-e4b"}

    async def scale_down_model(model: str, managed: ManagedVLLMModel) -> None:
        scaled_down.append(f"{model}:{managed.deployment}")

    async def ensure_model(_model: str, *, seen: set[str]) -> None:
        return None

    monkeypatch.setattr(runtime, "_deployment_available", available)
    monkeypatch.setattr(runtime, "_scale_down_model", scale_down_model)
    monkeypatch.setattr(runtime, "_ensure_model", ensure_model)

    await runtime.ensure_model("gemma4:e4b-it-nvfp4")

    assert scaled_down == []


def test_vllm_backend_bounds_common_task_tokens() -> None:
    assert VLLMBackend._max_tokens_for_metadata({"task_type": "orchestrator_plan"}) == 320
    assert VLLMBackend._max_tokens_for_metadata({"task_type": "tool_formatting"}) == 96
    assert VLLMBackend._max_tokens_for_metadata({"task_type": "tool_formatting", "max_tokens": 12}) == 12


def test_vllm_backend_requests_json_object_for_structured_completion() -> None:
    assert VLLMBackend._response_format_for_metadata({"response_format": "json_object"}) == {
        "type": "json_object"
    }
    assert VLLMBackend._response_format_for_metadata({"response_format": "text"}) is None


def test_nemoclaw_vllm_deployment_memory_profile_allows_resident_gemma4_models() -> None:
    deploy_path = Path(__file__).resolve().parents[2] / "deploy" / "nemoclaw-vllm.yaml"
    docs = [doc for doc in yaml.safe_load_all(deploy_path.read_text(encoding="utf-8")) if isinstance(doc, dict)]

    memory_profile: dict[str, str] = {}
    for doc in docs:
        if doc.get("kind") != "Deployment":
            continue
        name = doc.get("metadata", {}).get("name", "")
        container = doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [{}])[0]
        args = container.get("args", [])
        if "--gpu-memory-utilization" in args:
            memory_profile[name] = args[args.index("--gpu-memory-utilization") + 1]

    assert memory_profile == {
        "vllm-gemma4-31b": "0.55",
        "vllm-gemma4-e4b": "0.14",
    }
