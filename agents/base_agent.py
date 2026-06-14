"""
File purpose:
- Provide base abstractions and shared runtime context for all agents.

Key classes/functions:
- AgentResult
- AgentContext
- BaseAgent

Inputs/outputs:
- Input: orchestrator state + agent context
- Output: normalized AgentResult

Dependencies:
- abc.ABC
- dataclasses
- orchestrator.state.OrchestratorState

Modification guide:
- Safe places to edit: context fields and helper methods
- Risky places to edit: abstract run contract used by orchestrator
- Related files: agents/*.py, orchestrator/run_loop.py
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from backends.llm_backend import BaseLLMBackend, LLMResponse
from backends.model_router import ModelRouter
from backends.prompt_registry import get_system_prompt
from knowledge.experiment_db import ExperimentDB
from knowledge.failure_memory import FailureMemory
from knowledge.rag import HybridRAG
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import OrchestratorState


@dataclass(slots=True)
class AgentResult:
    """Normalized output returned by every agent."""

    success: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    next_hint: str | None = None


@dataclass(slots=True)
class AgentContext:
    """Shared dependencies injected into every agent call."""

    model_router: ModelRouter
    primary_backend: BaseLLMBackend
    fallback_backend: BaseLLMBackend
    rag: HybridRAG
    experiment_db: ExperimentDB
    failure_memory: FailureMemory
    tools: ToolRegistry
    force_real_llm_in_test: bool = True
    allow_mock_fallback: bool = False
    active_backend: str = "vllm"
    on_model_call: Callable[..., Awaitable[None] | None] | None = None
    on_tool_event: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None
    model_routers: dict[str, ModelRouter] = field(default_factory=dict)
    primary_backends: dict[str, BaseLLMBackend] = field(default_factory=dict)
    fallback_backends: dict[str, BaseLLMBackend] = field(default_factory=dict)
    backend_fallbacks: dict[str, str] = field(default_factory=dict)
    runtime_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)

    def set_active_backend(self, backend_name: str) -> dict[str, Any]:
        """Switch the shared inference backend for all agents."""
        normalized = backend_name.strip().lower()
        if normalized not in self.primary_backends:
            allowed = ", ".join(sorted(self.primary_backends)) or self.active_backend
            raise ValueError(f"Unsupported inference backend: {backend_name}. allowed={allowed}")
        self.active_backend = normalized
        return self.runtime_profile()

    def runtime_profile(self) -> dict[str, Any]:
        """Return metadata for the currently selected backend branch."""
        profile = dict(self.runtime_profiles.get(self.active_backend, {}))
        available = []
        for name, item in sorted(self.runtime_profiles.items()):
            backend = dict(item.get("backend", {})) if isinstance(item, dict) else {}
            available.append(
                {
                    "name": name,
                    "label": backend.get("label", name),
                    "selected": name == self.active_backend,
                }
            )
        profile["available_backends"] = available
        profile["backend_fallback"] = self.backend_fallbacks.get(self.active_backend, "")
        return profile

    async def complete(
        self,
        task_type: str,
        user_prompt: str,
        *,
        timeout_s: float | None = None,
    ) -> LLMResponse:
        """Call selected model with fallback backend on failure."""
        router = self.model_routers.get(self.active_backend, self.model_router)
        primary_backend = self.primary_backends.get(self.active_backend, self.primary_backend)
        selection = router.select(task_type)
        system_prompt = get_system_prompt(task_type)

        async def _call_backend(backend: BaseLLMBackend, model: str, role: str) -> LLMResponse:
            coro = backend.complete(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                metadata={"task_type": task_type, "role": role},
            )
            if timeout_s is not None and timeout_s > 0:
                return await asyncio.wait_for(coro, timeout=timeout_s)
            return await coro

        errors: list[Exception] = []
        attempts: list[tuple[str, BaseLLMBackend, str, str]] = []

        fallback_backend_name = self.backend_fallbacks.get(self.active_backend, "")
        fallback_backend = self.fallback_backends.get(self.active_backend, self.fallback_backend)
        backend_fallback_attempt: tuple[str, BaseLLMBackend, str, str] | None = None
        if fallback_backend_name and fallback_backend_name != self.active_backend:
            fallback_router = self.model_routers.get(fallback_backend_name, router)
            fallback_selection = fallback_router.select(task_type)
            backend_fallback_attempt = (
                fallback_backend_name,
                fallback_backend,
                fallback_selection.primary,
                f"{fallback_selection.role}:backend_fallback",
            )

        api_key_primary = fallback_backend_name == "openai" and backend_fallback_attempt is not None
        if api_key_primary:
            attempts.append(backend_fallback_attempt)

        attempts.append((self.active_backend, primary_backend, selection.primary, selection.role))

        if selection.fallback and selection.fallback != selection.primary:
            attempts.append(
                (
                    self.active_backend,
                    primary_backend,
                    selection.fallback,
                    f"{selection.role}:model_fallback",
                )
            )

        if backend_fallback_attempt is not None and not api_key_primary:
            attempts.append(backend_fallback_attempt)
        elif backend_fallback_attempt is None and fallback_backend is not primary_backend:
            fallback_model = selection.fallback or selection.primary
            attempts.append(
                (
                    self.active_backend,
                    fallback_backend,
                    fallback_model,
                    f"{selection.role}:fallback",
                )
            )

        seen: set[tuple[int, str, str]] = set()
        for backend_name, backend, model, role in attempts:
            key = (id(backend), model, role)
            if key in seen:
                continue
            seen.add(key)
            try:
                response = await _call_backend(backend, model, role)
                if not str(response.text or "").strip():
                    raise RuntimeError(f"empty LLM response from backend={backend_name} model={model}")
                await self._notify_model_call(
                    task_type=task_type,
                    model=model,
                    role=role,
                    backend=backend_name,
                )
                return response
            except Exception as exc:
                errors.append(exc)

        detail = "; ".join(f"{type(exc).__name__}: {exc}" for exc in errors[-3:])
        raise RuntimeError(
            f"LLM call failed task={task_type} active_backend={self.active_backend} "
            f"fallback_backend={fallback_backend_name or self.active_backend}: {detail}"
        )

    async def _notify_model_call(self, task_type: str, model: str, role: str, backend: str) -> None:
        """Notify controller hooks that one model was successfully used for a task."""
        callback = self.on_model_call
        if callback is None:
            return
        try:
            result = callback(task_type=task_type, model=model, role=role, backend=backend)
            if inspect.isawaitable(result):
                await result
        except Exception:
            # Avoid model-call path coupling with callback failures.
            return


class BaseAgent(ABC):
    """Base class for all pluggable agents."""

    name: str = "base_agent"

    @abstractmethod
    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        """Execute one agent step."""
        raise NotImplementedError

    @staticmethod
    def now_iso() -> str:
        """Current UTC timestamp used for status fields."""
        return datetime.now(timezone.utc).isoformat()
