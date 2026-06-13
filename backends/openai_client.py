"""
File purpose:
- Async OpenAI Chat Completions client for API-key based ATR deployments.

Key classes/functions:
- OpenAIBackend

Inputs/outputs:
- Input: model id and prompts
- Output: normalized LLMResponse containing chat completion text

Dependencies:
- httpx.AsyncClient
- backends.llm_backend.BaseLLMBackend

Modification guide:
- Safe places to edit: request payload parameters and response parsing
- Risky places to edit: OpenAI API endpoint contract
- Related files: app/bootstrap.py, configs/models.yaml, .env.example
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from backends.llm_backend import BaseLLMBackend, LLMResponse
from backends.vllm_client import DEFAULT_MAX_TOKENS_BY_TASK


class OpenAIBackend(BaseLLMBackend):
    """LLM backend backed by OpenAI's API using an API key."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 300.0,
        api_key: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._organization = organization or os.getenv("OPENAI_ORG_ID", "")
        self._project = project or os.getenv("OPENAI_PROJECT_ID", "")
        self._reasoning_effort = (reasoning_effort or os.getenv("OPENAI_REASONING_EFFORT", "")).strip()
        self._temperature = os.getenv("OPENAI_TEMPERATURE", "").strip()

    @staticmethod
    def _max_tokens_for_metadata(metadata: dict[str, Any] | None) -> int | None:
        if not isinstance(metadata, dict):
            return None
        explicit = metadata.get("max_completion_tokens", metadata.get("max_tokens"))
        if explicit is not None:
            try:
                return max(1, int(explicit))
            except (TypeError, ValueError):
                return None
        task_type = str(metadata.get("task_type", "")).strip()
        return DEFAULT_MAX_TOKENS_BY_TASK.get(task_type)

    @staticmethod
    def _message_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        return str(value or "")

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the openai backend.")

        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "developer", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        max_tokens = self._max_tokens_for_metadata(metadata)
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        if self._temperature:
            try:
                payload["temperature"] = float(self._temperature)
            except ValueError:
                raise RuntimeError("OPENAI_TEMPERATURE must be a number when set.")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._organization:
            headers["OpenAI-Organization"] = self._organization
        if self._project:
            headers["OpenAI-Project"] = self._project

        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
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
                content = self._message_text(message.get("content", ""))
        return LLMResponse(text=content, model=model, raw=data)
