"""
File purpose:
- Async Ollama API client used as the default local-first inference backend.

Key classes/functions:
- OllamaBackend

Inputs/outputs:
- Input: model id and prompts
- Output: normalized LLMResponse containing Ollama message text

Dependencies:
- httpx.AsyncClient
- backends.llm_backend.BaseLLMBackend

Modification guide:
- Safe places to edit: request timeout and API payload metadata
- Risky places to edit: endpoint contract with Ollama /api/chat
- Related files: configs/models.yaml, backends/model_router.py
"""

from __future__ import annotations

from typing import Any

import httpx

from backends.llm_backend import BaseLLMBackend, LLMImageInput, LLMResponse, ollama_user_message


class OllamaBackend(BaseLLMBackend):
    """LLM backend backed by local Ollama server."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout_s: float = 90.0,
        keep_alive: str | int | None = "0",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._keep_alive = keep_alive

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, Any] | None = None,
        images: list[LLMImageInput] | None = None,
    ) -> LLMResponse:
        payload = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                ollama_user_message(user_prompt, images),
            ],
            "options": {"temperature": 0.2},
        }
        if self._keep_alive is not None:
            payload["keep_alive"] = self._keep_alive
        if metadata:
            payload["metadata"] = metadata

        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.post(f"{self._base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        content = ""
        message = data.get("message")
        if isinstance(message, dict):
            content = str(message.get("content", ""))
        if not content:
            content = str(data.get("response", ""))
        return LLMResponse(text=content, model=model, raw=data)
