"""
Unit tests for model router task selection.
"""

from backends.model_router import ModelRouter
from utils.config_loader import load_yaml
from utils.paths import resolve_path


def test_model_router_selects_task_role() -> None:
    cfg = {
        "models": {"orchestrator": {"primary": "a", "fallback": "b"}},
        "task_routes": {"orchestrator_plan": "orchestrator"},
    }
    router = ModelRouter(cfg)
    selection = router.select("orchestrator_plan")
    assert selection.role == "orchestrator"
    assert selection.primary == "a"
    assert selection.fallback == "b"


def test_vllm_orchestrator_defaults_to_e4b() -> None:
    cfg = load_yaml(resolve_path("configs/models.yaml"))
    vllm_cfg = dict(cfg)
    vllm_cfg["models"] = dict(cfg["backend_models"]["vllm"])
    router = ModelRouter(vllm_cfg)

    selection = router.select("orchestrator_plan")

    assert selection.primary == "gemma4:e4b-it-nvfp4"
    assert selection.fallback == "gemma4:31b"
