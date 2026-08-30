"""
File purpose:
- NemoClaw/OpenClaw-native backend via authenticated Ollama proxy.

Key classes/functions:
- NemoClawBackend

Inputs/outputs:
- Input: model id, prompts, proxy/token settings
- Output: normalized LLMResponse from /api/chat

Dependencies:
- httpx.AsyncClient
- subprocess (optional proxy auto-start)

Modification guide:
- Safe places to edit: timeout/proxy bootstrap behavior
- Risky places to edit: auth header and Ollama payload schema
- Related files: app/bootstrap.py, backends/ollama_client.py
"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
from typing import Any

import httpx

from backends.llm_backend import BaseLLMBackend, LLMImageInput, LLMResponse, ollama_user_message


class NemoClawBackend(BaseLLMBackend):
    """Authenticated backend that routes inference through NemoClaw proxy."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11435",
        timeout_s: float = 60.0,
        token_file: str = "~/.nemoclaw/ollama-proxy-token",
        auto_start_proxy: bool = True,
        proxy_script: str = "~/.nemoclaw/source/scripts/ollama-auth-proxy.js",
        proxy_port: int = 11435,
        backend_port: int = 11434,
        keep_alive: str | int | None = "0",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._token_file = Path(token_file).expanduser()
        self._auto_start_proxy = auto_start_proxy
        self._proxy_script = Path(proxy_script).expanduser()
        self._proxy_port = int(proxy_port)
        self._backend_port = int(backend_port)
        self._keep_alive = keep_alive
        self._proxy_checked = False

    def _load_token(self) -> str:
        if not self._token_file.exists():
            raise RuntimeError(f"NemoClaw token file not found: {self._token_file}")
        token = self._token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(f"NemoClaw token file is empty: {self._token_file}")
        return token

    def _start_proxy_if_needed(self, token: str) -> None:
        if not self._auto_start_proxy:
            return
        if not self._proxy_script.exists():
            raise RuntimeError(f"NemoClaw proxy script not found: {self._proxy_script}")

        env = os.environ.copy()
        env["OLLAMA_PROXY_TOKEN"] = token
        env["OLLAMA_PROXY_PORT"] = str(self._proxy_port)
        env["OLLAMA_BACKEND_PORT"] = str(self._backend_port)
        subprocess.Popen(
            ["node", str(self._proxy_script)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    async def _ensure_proxy(self, token: str) -> None:
        if self._proxy_checked:
            return
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self._base_url}/api/tags", headers=headers)
                if response.status_code == 200:
                    self._proxy_checked = True
                    return
        except Exception:
            pass

        self._start_proxy_if_needed(token)

        # Re-check once after attempting startup.
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{self._base_url}/api/tags", headers=headers)
            response.raise_for_status()
        self._proxy_checked = True

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, Any] | None = None,
        images: list[LLMImageInput] | None = None,
    ) -> LLMResponse:
        token = self._load_token()
        await self._ensure_proxy(token)

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

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.post(f"{self._base_url}/api/chat", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        content = ""
        message = data.get("message")
        if isinstance(message, dict):
            content = str(message.get("content", ""))
        if not content:
            content = str(data.get("response", ""))
        return LLMResponse(text=content, model=model, raw=data)
