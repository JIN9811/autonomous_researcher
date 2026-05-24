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
from dataclasses import dataclass, field
from typing import Any


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
    ) -> LLMResponse:
        """Return one model completion."""
        raise NotImplementedError
