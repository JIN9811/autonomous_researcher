from __future__ import annotations

import base64
import asyncio

import pytest

from backends import ollama_client, openai_client, vllm_client
from backends.llm_backend import LLMImageInput, openai_user_content, ollama_user_message
from backends.ollama_client import OllamaBackend
from backends.openai_client import OpenAIBackend
from backends.vllm_client import VLLMBackend


PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


def test_shared_image_input_builds_openai_compatible_content() -> None:
    image = LLMImageInput(data=PNG, mime_type="image/png", label="pre-click frame", detail="high")

    content = openai_user_content("Locate the control", [image])

    assert content[0] == {"type": "text", "text": "Locate the control"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
    )
    assert content[1]["image_url"]["detail"] == "high"
    assert set(content[1]["image_url"]) == {"url", "detail"}


def test_shared_image_input_builds_ollama_message_without_data_url_prefix() -> None:
    image = LLMImageInput(data=PNG, mime_type="image/png", label="pre-click frame")

    message = ollama_user_message("Locate the control", [image])

    assert message == {
        "role": "user",
        "content": "Locate the control\n\nImage 1: pre-click frame",
        "images": [base64.b64encode(PNG).decode("ascii")],
    }


@pytest.mark.parametrize("mime_type", ["text/plain", "image/svg+xml", "application/octet-stream"])
def test_shared_image_input_rejects_non_raster_content(mime_type: str) -> None:
    with pytest.raises(ValueError, match="unsupported image MIME type"):
        LLMImageInput(data=PNG, mime_type=mime_type)


def test_shared_image_input_rejects_oversized_payload() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        LLMImageInput(data=b"x" * (8 * 1024 * 1024 + 1), mime_type="image/png")


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "ok"}}], "message": {"content": "ok"}}


class _Client:
    def __init__(self, captured: list[dict], **_kwargs) -> None:
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, url: str, *, json: dict, headers: dict | None = None) -> _Response:
        self.captured.append({"url": url, "json": json, "headers": headers})
        return _Response()


@pytest.mark.parametrize(
    ("module", "backend"),
    [
        (openai_client, OpenAIBackend(api_key="test")),
        (vllm_client, VLLMBackend()),
    ],
)
def test_openai_compatible_backends_use_shared_multimodal_content(
    monkeypatch: pytest.MonkeyPatch,
    module,
    backend,
) -> None:
    captured: list[dict] = []
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: _Client(captured, **kwargs))

    asyncio.run(
        backend.complete(
            model="vision-model",
            system_prompt="system",
            user_prompt="inspect",
            images=[LLMImageInput(PNG, "image/png", "pre-click")],
        )
    )

    user_content = captured[0]["json"]["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": "inspect"}
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_ollama_backend_uses_shared_multimodal_images(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", lambda **kwargs: _Client(captured, **kwargs))

    asyncio.run(
        OllamaBackend().complete(
            model="vision-model",
            system_prompt="system",
            user_prompt="inspect",
            images=[LLMImageInput(PNG, "image/png", "pre-click")],
        )
    )

    user_message = captured[0]["json"]["messages"][1]
    assert user_message["content"] == "inspect\n\nImage 1: pre-click"
    assert user_message["images"] == [base64.b64encode(PNG).decode("ascii")]


def test_vllm_equipment_skill_tasks_have_explicit_completion_budgets() -> None:
    assert VLLMBackend._max_tokens_for_metadata(
        {"task_type": "equipment_skill_timeline_chunk"}
    ) == 768
    assert VLLMBackend._max_tokens_for_metadata(
        {"task_type": "equipment_skill_annotation"}
    ) == 1536
