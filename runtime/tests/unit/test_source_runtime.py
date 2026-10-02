"""Source ingestion stays independent from experiment execution and device tools."""
import asyncio
import json
from types import SimpleNamespace

import pytest


def make_service(tmp_path, context):
    from knowledge.source_library import SourceLibrary
    from knowledge.source_runtime import SourceIngestionService
    inbox = tmp_path / "inputs"
    inbox.mkdir()
    (inbox / "source.md").write_text("# Evidence\nOnly a reference; duration 42 seconds.")
    return SourceIngestionService(SourceLibrary(tmp_path / "library", inbox), lambda: context)


@pytest.mark.asyncio
async def test_disabled_worker_does_not_ingest_existing_inputs(tmp_path):
    service = make_service(tmp_path, None)
    await service.tick()
    assert service.status()["enabled"] is False
    assert service.library.status()["sources"] == []


@pytest.mark.asyncio
async def test_unavailable_model_waits_without_calls_and_setting_persists(tmp_path):
    class Context:
        async def selected_model_loaded(self, task):
            return False
        async def complete(self, *args, **kwargs):
            pytest.fail("An unavailable model must not be invoked or started")
    service = make_service(tmp_path, Context())
    service.configure(enabled=True)
    await service.tick()
    await service.tick()
    assert service.status()["state"] == "waiting_for_model"
    from knowledge.source_runtime import SourceIngestionService
    restored = SourceIngestionService(service.library, lambda: Context())
    assert restored.status()["enabled"] is True
    service.configure(enabled=False)


@pytest.mark.asyncio
async def test_background_wait_does_not_block_other_async_work(tmp_path):
    service = make_service(tmp_path, None)
    await service.start()
    try:
        event = asyncio.Event()
        asyncio.get_running_loop().call_soon(event.set)
        await asyncio.wait_for(event.wait(), timeout=1)
        assert service.status()["running"] is True
    finally:
        await service.shutdown()
    assert service.status()["running"] is False


def test_retry_rejects_unknown_identity_and_nonboolean_settings(tmp_path):
    service = make_service(tmp_path, SimpleNamespace())
    with pytest.raises((KeyError, ValueError)):
        service.retry("source-unknown")
    with pytest.raises(ValueError):
        service.configure(enabled="false")


def test_curation_freezes_existing_api_priority_without_changing_shared_context():
    from agents.base_agent import AgentContext
    from backends.model_router import ModelRouter
    from knowledge.source_runtime import curation_context
    local, api = object(), object()
    local_router = ModelRouter({"models": {"e4b": {"primary": "registered-local", "fallback": "unloaded"}}})
    api_router = ModelRouter({"models": {"e4b": {"primary": "registered-api"}}})
    ctx = AgentContext(local_router, local, api, None, None, None, None, active_backend="vllm",
        model_routers={"vllm": local_router, "openai": api_router},
        primary_backends={"vllm": local, "openai": api}, fallback_backends={"vllm": api},
        backend_fallbacks={"vllm": "openai"})
    owned = curation_context(ctx)
    assert owned.active_backend == "openai"
    assert owned.model_router.select("knowledge_query").primary == "registered-api"
    assert owned.model_router.select("knowledge_query").fallback is None
    assert ctx.active_backend == "vllm" and ctx.backend_fallbacks["vllm"] == "openai"


@pytest.mark.asyncio
async def test_worker_runs_full_discovery_to_model_publication_once(tmp_path):
    class Context:
        active_backend = "fixture"
        calls = 0
        async def selected_model_loaded(self, task):
            return True
        async def complete(self, task, prompt, **kwargs):
            self.calls += 1
            envelope = json.loads(prompt)
            if not envelope["observations"]:
                request = {"tool": "inspect_source", "arguments": {"offset": 0, "limit": 8}}
            else:
                blocks = envelope["observations"][0]["observation"]["blocks"]
                request = {"tool": "publish_knowledge", "arguments": {"notes": [{
                    "title": "Reference duration", "body": "Reference only: duration 42 seconds.",
                    "category": "reference", "ontology_type": "KnowledgeClaim", "tags": [],
                    "applicability": {}, "source_block_ids": [b["block_id"] for b in blocks]}]}}
            return SimpleNamespace(text=json.dumps(request), model="fixture", raw={})
    ctx = Context()
    service = make_service(tmp_path, ctx)
    service.configure(enabled=True)
    await service.tick()
    await service.tick()
    assert service.library.search("duration")["hits"]
    assert ctx.calls == 2
    await service.tick()
    assert ctx.calls == 2
