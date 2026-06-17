"""Unit tests for the OpenAI API backend token policy."""

from __future__ import annotations

from backends.openai_client import OpenAIBackend


def test_openai_orchestrator_plan_uses_reasoning_safe_completion_budget() -> None:
    """Reasoning models need more completion budget than local vLLM defaults."""

    assert OpenAIBackend._max_tokens_for_metadata({"task_type": "orchestrator_plan"}) >= 1600


def test_openai_explicit_completion_budget_still_wins() -> None:
    """Explicit call metadata must override task defaults."""

    assert OpenAIBackend._max_tokens_for_metadata({"task_type": "orchestrator_plan", "max_completion_tokens": 512}) == 512
