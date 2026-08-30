"""
File purpose:
- Async vLLM OpenAI-compatible API client for the shared AgentContext backend switch.

Key classes/functions:
- VLLMBackend

Inputs/outputs:
- Input: model id and prompts
- Output: normalized LLMResponse containing chat completion text

Dependencies:
- httpx.AsyncClient
- backends.llm_backend.BaseLLMBackend

Modification guide:
- Safe places to edit: request payload parameters and response parsing
- Risky places to edit: OpenAI-compatible endpoint contract
- Related files: app/bootstrap.py, agents/base_agent.py
"""

from __future__ import annotations

from typing import Any

import httpx

from backends.llm_backend import BaseLLMBackend, LLMImageInput, LLMResponse, openai_user_content
from backends.nemoclaw_vllm_runtime import NemoClawVLLMRuntime


DEFAULT_MAX_TOKENS_BY_TASK = {
    "orchestrator_plan": 320,
    "design_reasoning": 256,
    "analysis_reasoning": 192,
    "knowledge_query": 256,
    "guardian_reasoning": 256,
    "tool_formatting": 96,
    "gui_helper": 96,
    "module_designer": 1400,
    "equipment_skill_timeline_chunk": 768,
    "equipment_skill_annotation": 1536,
}


class VLLMBackend(BaseLLMBackend):
    """LLM backend backed by a vLLM OpenAI-compatible server."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000/v1",
        timeout_s: float = 300.0,
        api_key: str | None = None,
        model_base_urls: dict[str, str] | None = None,
        nemoclaw_runtime: NemoClawVLLMRuntime | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._api_key = api_key or "EMPTY"
        self._model_base_urls = {
            str(model): str(url).rstrip("/")
            for model, url in (model_base_urls or {}).items()
            if str(model).strip() and str(url).strip()
        }
        self._nemoclaw_runtime = nemoclaw_runtime

    @staticmethod
    def _max_tokens_for_metadata(metadata: dict[str, Any] | None) -> int | None:
        """Keep local vLLM calls bounded so GUI/stage handoffs do not over-generate."""
        if not isinstance(metadata, dict):
            return None
        task_type = str(metadata.get("task_type", "")).strip()
        explicit = metadata.get("max_tokens")
        if explicit is not None:
            try:
                return max(1, int(explicit))
            except (TypeError, ValueError):
                return None
        return DEFAULT_MAX_TOKENS_BY_TASK.get(task_type)

    async def _base_url_for_model(self, model: str) -> str:
        if self._nemoclaw_runtime is not None:
            runtime_url = await self._nemoclaw_runtime.base_url_for_model(model)
            if runtime_url:
                return runtime_url.rstrip("/")
        return self._model_base_urls.get(model, self._base_url)

    async def scale_down_idle_models(self, *, include_persistent: bool = False) -> dict[str, Any]:
        """Scale NemoClaw-hosted vLLM models down to zero replicas."""
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "scaled_down": [], "errors": []}
        return await self._nemoclaw_runtime.scale_down_idle_models(include_persistent=include_persistent)

    async def scale_down_models_except(
        self,
        keep_models: set[str] | None = None,
        *,
        include_persistent: bool = False,
    ) -> dict[str, Any]:
        """Scale non-selected NemoClaw-vLLM models down to zero replicas."""
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "scaled_down": [], "errors": []}
        return await self._nemoclaw_runtime.scale_down_models_except(
            keep_models,
            include_persistent=include_persistent,
        )

    async def prepare_model(self, model: str) -> None:
        """Ensure an on-demand NemoClaw-hosted model is serving before inference timeout starts."""
        if self._nemoclaw_runtime is not None:
            await self._nemoclaw_runtime.ensure_model(model)

    async def load_model(self, model: str) -> dict[str, Any]:
        """Manually load a NemoClaw-hosted vLLM model."""
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "model": model, "loaded": False}
        return await self._nemoclaw_runtime.load_model(model)

    async def unload_model(self, model: str) -> dict[str, Any]:
        """Manually unload a NemoClaw-hosted vLLM model."""
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "model": model, "unloaded": False}
        return await self._nemoclaw_runtime.unload_model(model)

    async def managed_model_statuses(self) -> dict[str, Any]:
        """Return all managed NemoClaw vLLM model statuses."""
        if self._nemoclaw_runtime is None:
            return {"enabled": False, "models": []}
        return await self._nemoclaw_runtime.model_statuses()

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, Any] | None = None,
        images: list[LLMImageInput] | None = None,
    ) -> LLMResponse:
        base_url = await self._base_url_for_model(model)

        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": openai_user_content(user_prompt, images)},
            ],
        }
        max_tokens = self._max_tokens_for_metadata(metadata)
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if metadata:
            payload["metadata"] = metadata

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        content = ""
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                content = str(message.get("content", ""))
        return LLMResponse(text=content, model=model, raw=data)
