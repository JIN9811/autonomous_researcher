"""
Integration tests for GPU clear control behavior.
"""

import pytest

from app.bootstrap import load_runtime


@pytest.mark.asyncio
async def test_gpu_clear_unloads_loaded_ollama_models(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_runtime()
    calls: list[tuple[str, str, dict | None]] = []

    class _FakeResponse:
        def __init__(self, payload: dict | None = None) -> None:
            self._payload = payload or {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.calls = calls

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def get(self, url: str) -> _FakeResponse:
            self.calls.append(("GET", url, None))
            return _FakeResponse(
                {
                    "models": [
                        {"name": "gemma4:31b"},
                        {"model": "gemma4:e4b-it-bf16"},
                    ]
                }
            )

        async def post(self, url: str, json: dict) -> _FakeResponse:
            self.calls.append(("POST", url, json))
            return _FakeResponse({})

    monkeypatch.setattr("app.controller.httpx.AsyncClient", _FakeAsyncClient)

    async def fake_vllm_clear(*, include_persistent: bool = False) -> dict:
        return {"enabled": True, "scaled_down": [], "errors": []}

    monkeypatch.setattr(controller, "_scale_down_idle_vllm_models", fake_vllm_clear)

    result = await controller.clear_gpu()
    assert result["ok"] is True
    assert result["errors"] == []
    assert set(result["unloaded_models"]) == {"gemma4:31b", "gemma4:e4b-it-bf16"}

    post_payloads = [payload for method, _, payload in calls if method == "POST"]
    assert len(post_payloads) == 2
    assert all(payload is not None and payload.get("keep_alive") == 0 for payload in post_payloads)
