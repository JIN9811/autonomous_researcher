"""
File purpose:
- Define backend interfaces for model inference used by all agents.

Key classes/functions:
- LLMResponse
- BaseLLMBackend

Inputs/outputs:
- Input: model id, prompts, optional metadata
- Output: normalized LLMResponse

Dependencies:
- abc.ABC
- dataclasses.dataclass

Modification guide:
- Safe places to edit: response metadata and helper fields
- Risky places to edit: abstract method signature expected by callers
- Related files: backends/mock_llm.py, backends/ollama_client.py
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import base64
from dataclasses import dataclass, field
from typing import Any


SUPPORTED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
MAX_LLM_IMAGE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LLMImageInput:
    """Validated raster image shared by local and remote multimodal backends."""

    data: bytes
    mime_type: str
    label: str = ""
    detail: str = "high"

    def __post_init__(self) -> None:
        if self.mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
            raise ValueError(f"unsupported image MIME type: {self.mime_type}")
        if not self.data:
            raise ValueError("image payload is empty")
        if len(self.data) > MAX_LLM_IMAGE_BYTES:
            raise ValueError(f"image payload exceeds {MAX_LLM_IMAGE_BYTES} bytes")
        if self.detail not in {"auto", "low", "high"}:
            raise ValueError(f"unsupported image detail: {self.detail}")

    def base64_data(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64_data()}"


def openai_user_content(user_prompt: str, images: list[LLMImageInput] | None = None) -> str | list[dict[str, Any]]:
    """Build one OpenAI-compatible user content value for API and vLLM."""
    if not images:
        return user_prompt
    content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": image.data_url(), "detail": image.detail},
        }
        for image in images
    )
    return content


def ollama_user_message(user_prompt: str, images: list[LLMImageInput] | None = None) -> dict[str, Any]:
    """Build Ollama's equivalent user message from the shared image contract."""
    if not images:
        return {"role": "user", "content": user_prompt}
    labels = "\n".join(
        f"Image {index}: {image.label or 'visual evidence'}"
        for index, image in enumerate(images, start=1)
    )
    return {
        "role": "user",
        "content": f"{user_prompt}\n\n{labels}",
        "images": [image.base64_data() for image in images],
    }


@dataclass(slots=True)
class LLMResponse:
    """Normalized response object returned by every backend."""

    text: str
    model: str
    raw: dict[str, Any] = field(default_factory=dict)


class BaseLLMBackend(ABC):
    """Abstract base class for swappable model backends."""

    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        metadata: dict[str, Any] | None = None,
        images: list[LLMImageInput] | None = None,
    ) -> LLMResponse:
        """Return one model completion."""
        raise NotImplementedError
