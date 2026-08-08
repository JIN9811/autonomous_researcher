"""
Unit tests for model router task selection.
"""

from backends.model_router import ModelRouter
from backends.llm_lease import LLMLeaseCoordinator
from utils.config_loader import load_yaml
from utils.paths import resolve_path


def test_model_router_selects_task_role() -> None:
    cfg = {
        "models": {"orchestrator": {"primary": "a", "fallback": "b"}},
        "task_routes": {"orchestrator_plan": "orchestrator"},
    }
    router = ModelRouter(cfg)
    selection = router.select("orchestrator_plan")
    assert selection.role == "orchestrator"
    assert selection.primary == "a"
    assert selection.fallback == "b"


def test_vllm_orchestrator_defaults_to_31b() -> None:
    cfg = load_yaml(resolve_path("configs/models.yaml"))
    vllm_cfg = dict(cfg)
    vllm_cfg["models"] = dict(cfg["backend_models"]["vllm"])
    router = ModelRouter(vllm_cfg)

    selection = router.select("orchestrator_plan")

    assert selection.primary == "gemma4:31b"
    assert selection.fallback == "gemma4:e4b-it-nvfp4"


def test_backend_fallback_defaults_to_openai() -> None:
    cfg = load_yaml(resolve_path("configs/models.yaml"))

    assert cfg["backend"]["default"] == "vllm"
    assert cfg["backend"]["fallback"] == "openai"
    assert cfg["backend_models"]["openai"]["orchestrator"]["primary"] == "gpt-5.5"

import pytest

from agents.base_agent import AgentContext
from backends.llm_backend import BaseLLMBackend, LLMResponse
from knowledge.experiment_db import ExperimentDB
from knowledge.failure_memory import FailureMemory
from knowledge.rag import HybridRAG
from mcp_tools.tool_registry import ToolRegistry


class _OrderBackend(BaseLLMBackend):
    def __init__(self, name: str, calls: list[tuple[str, str]], *, fail: bool = False) -> None:
        self.name = name
        self.calls = calls
        self.fail = fail

    async def complete(self, *, model: str, system_prompt: str, user_prompt: str, metadata=None) -> LLMResponse:
        self.calls.append((self.name, model))
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        return LLMResponse(text=f"ok:{self.name}:{model}", model=model, raw={})


class _ModelBehaviorBackend(BaseLLMBackend):
    def __init__(self, name: str, calls: list[tuple[str, str]], behavior: dict[str, object]) -> None:
        self.name = name
        self.calls = calls
        self.behavior = behavior

    async def complete(self, *, model: str, system_prompt: str, user_prompt: str, metadata=None) -> LLMResponse:
        self.calls.append((self.name, model))
        value = self.behavior.get(model, f"ok:{self.name}:{model}")
        if isinstance(value, Exception):
            raise value
        return LLMResponse(text=str(value), model=model, raw={})


class _ManagedStatusBackend(_OrderBackend):
    def __init__(self, name: str, calls: list[tuple[str, str]], *, loaded: bool) -> None:
        super().__init__(name, calls)
        self.loaded = loaded
        self.status_calls = 0
        self.prepare_calls = 0

    async def managed_model_statuses(self):
        self.status_calls += 1
        return {"enabled": True, "models": [{"model": "local-primary", "loaded": self.loaded}]}

    async def prepare_model(self, model: str) -> None:
        self.prepare_calls += 1


@pytest.mark.asyncio
async def test_openai_api_key_loading_uses_api_before_local_primary() -> None:
    calls: list[tuple[str, str]] = []
    vllm = _OrderBackend("vllm", calls, fail=False)
    openai = _OrderBackend("openai", calls, fail=False)
    vllm_router = ModelRouter(
        {
            "models": {"orchestrator": {"primary": "local-primary", "fallback": "local-fallback"}},
            "task_routes": {"orchestrator_plan": "orchestrator"},
        }
    )
    openai_router = ModelRouter(
        {
            "models": {"orchestrator": {"primary": "api-primary"}},
            "task_routes": {"orchestrator_plan": "orchestrator"},
        }
    )
    ctx = AgentContext(
        model_router=vllm_router,
        primary_backend=vllm,
        fallback_backend=openai,
        rag=HybridRAG(local_index=None, web_retriever=None),
        experiment_db=ExperimentDB(),
        failure_memory=FailureMemory(),
        tools=ToolRegistry(),
        active_backend="vllm",
        model_routers={"vllm": vllm_router, "openai": openai_router},
        primary_backends={"vllm": vllm, "openai": openai},
        fallback_backends={"vllm": openai},
        backend_fallbacks={"vllm": "openai"},
    )

    response = await ctx.complete("orchestrator_plan", "hello")

    assert response.text == "ok:openai:api-primary"
    assert calls == [("openai", "api-primary")]


@pytest.mark.asyncio
async def test_empty_openai_api_fallback_response_continues_to_local_model_fallback() -> None:
    calls: list[tuple[str, str]] = []
    vllm = _ModelBehaviorBackend(
        "vllm",
        calls,
        {
            "local-primary": RuntimeError("local primary failed"),
            "local-fallback": "ok:vllm:local-fallback",
        },
    )
    openai = _ModelBehaviorBackend("openai", calls, {"api-primary": ""})
    vllm_router = ModelRouter(
        {
            "models": {"orchestrator": {"primary": "local-primary", "fallback": "local-fallback"}},
            "task_routes": {"orchestrator_plan": "orchestrator"},
        }
    )
    openai_router = ModelRouter(
        {
            "models": {"orchestrator": {"primary": "api-primary"}},
            "task_routes": {"orchestrator_plan": "orchestrator"},
        }
    )
    ctx = AgentContext(
        model_router=vllm_router,
        primary_backend=vllm,
        fallback_backend=openai,
        rag=HybridRAG(local_index=None, web_retriever=None),
        experiment_db=ExperimentDB(),
        failure_memory=FailureMemory(),
        tools=ToolRegistry(),
        active_backend="vllm",
        model_routers={"vllm": vllm_router, "openai": openai_router},
        primary_backends={"vllm": vllm, "openai": openai},
        fallback_backends={"vllm": openai},
        backend_fallbacks={"vllm": "openai"},
    )

    response = await ctx.complete("orchestrator_plan", "hello")

    assert response.text == "ok:vllm:local-fallback"
    assert calls == [("openai", "api-primary"), ("vllm", "local-primary"), ("vllm", "local-fallback")]


@pytest.mark.asyncio
async def test_agent_context_uses_shared_lease_without_changing_existing_complete_contract() -> None:
    calls: list[tuple[str, str]] = []
    backend = _OrderBackend("vllm", calls)
    router = ModelRouter(
        {
            "models": {"orchestrator": {"primary": "local-primary"}},
            "task_routes": {"orchestrator_plan": "orchestrator"},
        }
    )
    lease = LLMLeaseCoordinator()
    ctx = AgentContext(
        model_router=router,
        primary_backend=backend,
        fallback_backend=backend,
        rag=HybridRAG(local_index=None, web_retriever=None),
        experiment_db=ExperimentDB(),
        failure_memory=FailureMemory(),
        tools=ToolRegistry(),
        llm_lease=lease,
    )

    response = await ctx.complete("orchestrator_plan", "hello", priority=10, owner="workflow:test")

    assert response.text == "ok:vllm:local-primary"
    assert lease.status()["last_owner"] == "workflow:test"


@pytest.mark.asyncio
async def test_selected_model_loaded_does_not_prepare_or_load_model() -> None:
    calls: list[tuple[str, str]] = []
    backend = _ManagedStatusBackend("vllm", calls, loaded=False)
    router = ModelRouter(
        {
            "models": {"e4b": {"primary": "local-primary"}},
            "task_routes": {"knowledge_relation": "e4b"},
        }
    )
    ctx = AgentContext(
        model_router=router,
        primary_backend=backend,
        fallback_backend=backend,
        rag=HybridRAG(local_index=None, web_retriever=None),
        experiment_db=ExperimentDB(),
        failure_memory=FailureMemory(),
        tools=ToolRegistry(),
    )

    loaded = await ctx.selected_model_loaded("knowledge_relation")

    assert loaded is False
    assert backend.status_calls == 1
    assert backend.prepare_calls == 0
