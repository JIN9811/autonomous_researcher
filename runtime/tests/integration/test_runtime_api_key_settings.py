"""
Integration tests for runtime API key settings used by the Main GUI.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module


def test_runtime_api_key_settings_import_env_and_toggle_usage(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "memory" / "api_keys.json"
    monkeypatch.setattr(main_module, "API_KEY_SETTINGS_PATH", settings_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-runtime-key-123456")

    client = TestClient(main_module.app)

    imported = client.get("/api/runtime/api-key").json()
    assert imported["ok"] is True
    assert imported["provider"] == "openai"
    assert imported["has_key"] is True
    assert imported["enabled"] is True
    assert imported["source"] == "env"
    assert imported["key_status"] == "registered"
    assert "masked_key" not in imported
    assert settings_path.exists()
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["api_key"] == "sk-test-runtime-key-123456"
    assert stored["enabled"] is True

    active_backend = main_module.controller._deps.agent_context.active_backend
    assert imported["primary_backend"] == "openai"
    assert imported["fallback_backend"] == "openai"
    assert main_module.controller._deps.agent_context.backend_fallbacks[active_backend] == "openai"

    unloaded = client.post("/api/runtime/api-key/unload", json={}).json()
    assert unloaded["ok"] is True
    assert unloaded["enabled"] is False
    assert unloaded["has_key"] is True
    assert unloaded["primary_backend"] == active_backend
    assert unloaded["fallback_backend"] == active_backend
    assert main_module.controller._deps.agent_context.backend_fallbacks[active_backend] == active_backend
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["enabled"] is False
    assert stored["api_key"] == "sk-test-runtime-key-123456"

    saved = client.post(
        "/api/runtime/api-key",
        json={"api_key": "sk-new-runtime-key-abcdef", "enabled": True},
    ).json()
    assert saved["ok"] is True
    assert saved["enabled"] is True
    assert saved["source"] == "user"
    assert saved["key_status"] == "registered"
    assert "masked_key" not in saved
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["api_key"] == "sk-new-runtime-key-abcdef"
    assert stored["source"] == "user"

    loaded = client.post("/api/runtime/api-key/load", json={}).json()
    assert loaded["ok"] is True
    assert loaded["enabled"] is True
    assert loaded["primary_backend"] == "openai"
    assert loaded["fallback_backend"] == "openai"
    openai_backend = main_module.controller._deps.agent_context.primary_backends["openai"]
    assert openai_backend._api_key == "sk-new-runtime-key-abcdef"
    assert main_module.controller._deps.agent_context.backend_fallbacks[active_backend] == "openai"
    assert main_module.controller._deps.agent_context.fallback_backends[active_backend] is openai_backend


def test_runtime_api_key_settings_import_root_env_file(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "memory" / "api_keys.json"
    root_env_path = tmp_path / "env"
    root_env_path.write_text("OPENAI_API_KEY=sk-root-env-file-123456\n", encoding="utf-8")
    original_resolve_path = main_module.resolve_path

    def fake_resolve_path(path: str) -> Path:
        if path == ".env":
            return tmp_path / ".env"
        if path == "env":
            return root_env_path
        return original_resolve_path(path)

    monkeypatch.setattr(main_module, "API_KEY_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(main_module, "resolve_path", fake_resolve_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    imported = main_module._read_api_key_settings(import_env=True)

    assert imported["api_key"] == "sk-root-env-file-123456"
    assert imported["enabled"] is True
    assert imported["source"] == "env"
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["api_key"] == "sk-root-env-file-123456"


def test_runtime_api_key_status_get_does_not_emit_load_events(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "memory" / "api_keys.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "schema": "api_key.v1",
                "provider": "openai",
                "api_key": "sk-existing-runtime-key-123456",
                "enabled": True,
                "source": "user",
                "updated_at": "2026-06-13T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    events: list[tuple[str, str]] = []

    async def fake_emit_control_event(event_type: str, message: str, **kwargs) -> None:
        events.append((event_type, message))

    monkeypatch.setattr(main_module, "API_KEY_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(main_module.controller, "_emit_control_event", fake_emit_control_event)

    client = TestClient(main_module.app)
    first = client.get("/api/runtime/api-key").json()
    second = client.get("/api/runtime/api-key").json()

    assert first["ok"] is True
    assert second["ok"] is True
    assert events == []


def test_startup_applies_saved_api_key_before_first_status_request(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "memory" / "api_keys.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "schema": "api_key.v1",
                "provider": "openai",
                "api_key": "sk-startup-runtime-key-123456",
                "enabled": True,
                "source": "user",
                "updated_at": "2026-06-13T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    events: list[tuple[str, str]] = []

    async def fake_emit_control_event(event_type: str, message: str, **kwargs) -> None:
        events.append((event_type, message))

    ctx = main_module.controller._deps.agent_context
    active_backend = ctx.active_backend
    openai_backend = ctx.primary_backends["openai"]
    primary_backend = ctx.primary_backends[active_backend]
    monkeypatch.setattr(main_module, "API_KEY_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(main_module.controller, "_emit_control_event", fake_emit_control_event)
    monkeypatch.setattr(openai_backend, "_api_key", "")
    monkeypatch.setattr(ctx, "backend_fallbacks", dict(ctx.backend_fallbacks))
    monkeypatch.setattr(ctx, "fallback_backends", dict(ctx.fallback_backends))
    ctx.backend_fallbacks[active_backend] = active_backend
    ctx.fallback_backends[active_backend] = primary_backend

    asyncio.run(main_module.keep_startup_side_effect_free())

    assert openai_backend._api_key == "sk-startup-runtime-key-123456"
    assert ctx.backend_fallbacks[active_backend] == "openai"
    assert ctx.fallback_backends[active_backend] is openai_backend
    assert events == []


def test_main_gui_exposes_api_key_controls() -> None:
    client = TestClient(main_module.app)
    page = client.get("/")
    assert page.status_code == 200
    assert "api key" in page.text.lower()
    assert "api-key-load-btn" in page.text
    assert "api-key-unload-btn" in page.text
    assert "api-key-dialog" in page.text
