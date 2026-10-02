"""
File purpose:
- Deterministic mock LLM backend for test-mode and CI validation.

Key classes/functions:
- MockLLMBackend

Inputs/outputs:
- Input: model id and prompts
- Output: deterministic synthetic response text

Dependencies:
- hashlib
- backends.llm_backend.BaseLLMBackend

Modification guide:
- Safe places to edit: template text and hashing behavior
- Risky places to edit: determinism guarantees used by tests
- Related files: backends/model_router.py, tests/unit/test_rag.py
"""

from __future__ import annotations

import hashlib

from backends.llm_backend import BaseLLMBackend, LLMImageInput, LLMResponse


class MockLLMBackend(BaseLLMBackend):
    """Deterministic backend that never calls external services."""

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, object] | None = None,
        images: list[LLMImageInput] | None = None,
    ) -> LLMResponse:
        image_fingerprints = [hashlib.sha256(image.data).hexdigest() for image in images or []]
        digest = hashlib.sha1(
            f"{model}|{system_prompt}|{user_prompt}|{metadata}|{image_fingerprints}".encode("utf-8")
        ).hexdigest()[:10]
        text = (
            "MOCK_RESPONSE "
            f"model={model} digest={digest} "
            f"prompt_preview={user_prompt[:80].replace(chr(10), ' ')}"
        )
        return LLMResponse(text=text, model=model, raw={"mock": True, "digest": digest})
