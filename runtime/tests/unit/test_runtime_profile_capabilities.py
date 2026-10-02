from __future__ import annotations

from app.bootstrap import _build_runtime_profile
from backends.model_router import ModelRouter


def test_runtime_profile_exposes_e4b_vision_role_capability() -> None:
    models_cfg = {
        "models": {"e4b": {"primary": "gemma4:e4b-it-nvfp4"}},
        "task_routes": {"design_reasoning": "e4b"},
        "role_capabilities": {"e4b": {"text": True, "vision": True}},
    }

    profile = _build_runtime_profile(
        backend_name="vllm",
        backend_cfg={"base_url": "http://127.0.0.1:8002/v1"},
        models_cfg=models_cfg,
        router=ModelRouter(models_cfg),
    )

    assert profile["models"]["e4b"]["capabilities"] == {"text": True, "vision": True}
