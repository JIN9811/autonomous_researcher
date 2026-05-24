"""
File purpose:
- Bootstrap runtime dependencies for the autonomous researcher application.

Key classes/functions:
- load_runtime

Inputs/outputs:
- Input: environment variables + YAML configs
- Output: initialized MainController

Dependencies:
- python-dotenv
- utils.config_loader
- app.controller.MainController

Modification guide:
- Safe places to edit: default backend and startup registration
- Risky places to edit: dependency wiring for orchestrator
- Related files: app/main.py, app/controller.py
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agents.analysis_agent import AnalysisAgent
from agents.base_agent import AgentContext
from agents.design_agent import DesignAgent
from agents.equipment_agent import LabEquipmentAgent
from agents.guardian_agent import GuardianAgent
from agents.knowledge_agent import KnowledgeAgent
from agents.manipulation_agent import ManipulationAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.registry import AgentRegistry
from agents.specimen_agent import SpecimenMakingAgent
from agents.vision_agent import VisionAgent
from app.controller import ControllerDeps, MainController
from backends.mock_llm import MockLLMBackend
from backends.model_router import ModelRouter
from backends.nemoclaw_client import NemoClawBackend
from backends.nemoclaw_vllm_runtime import NemoClawVLLMRuntime
from backends.ollama_client import OllamaBackend
from backends.vllm_client import VLLMBackend
from knowledge.experiment_db import ExperimentDB
from knowledge.failure_memory import FailureMemory
from knowledge.rag import HybridRAG, LocalRAGIndex, WebRetriever
from mcp_tools.equipment_tools import register_equipment_tools
from mcp_tools.lerobot_tools import register_lerobot_tools
from mcp_tools.mock_tools import register_mock_tools
from mcp_tools.printer_tools import register_printer_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.graph import OrchestrationGraph
from utils.config_loader import load_all_configs
from utils.paths import resolve_path


def _load_configs() -> dict[str, Any]:
    root = resolve_path(".")
    cfg = load_all_configs(root / "configs")
    return cfg


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


SUPPORTED_BACKENDS = ("nemoclaw", "ollama", "vllm")


def _normalize_backend_name(value: str | None, default: str = "vllm") -> str:
    backend_name = str(value or default).strip().lower()
    if backend_name == "openai":
        backend_name = "vllm"
    return backend_name if backend_name in SUPPORTED_BACKENDS else default


def _apply_model_env_overrides(models_cfg: dict[str, Any], *, backend_name: str = "") -> dict[str, Any]:
    cfg = dict(models_cfg)
    models = dict(cfg.get("models", {}))
    for role in ("orchestrator", "e4b", "e2b"):
        models[role] = dict(models.get(role, {}))

    prefix = f"AUTONOMOUS_{backend_name.upper()}_" if backend_name else ""
    override_map = {
        "orchestrator": os.getenv(f"{prefix}ORCHESTRATOR_MODEL") or os.getenv("AUTONOMOUS_ORCHESTRATOR_MODEL"),
        "e4b": os.getenv(f"{prefix}E4B_MODEL") or os.getenv("AUTONOMOUS_E4B_MODEL"),
        "e2b": os.getenv(f"{prefix}E2B_MODEL") or os.getenv("AUTONOMOUS_E2B_MODEL"),
    }
    for role, value in override_map.items():
        if value:
            models[role]["primary"] = value
    cfg["models"] = models
    return cfg


def _models_cfg_for_backend(models_cfg: dict[str, Any], backend_name: str) -> dict[str, Any]:
    """Build a model-router config for one inference backend branch."""
    cfg = dict(models_cfg)
    backend_models = dict(models_cfg.get("backend_models", {}))
    if backend_name in backend_models:
        cfg["models"] = dict(backend_models[backend_name])
    return _apply_model_env_overrides(cfg, backend_name=backend_name)


def _build_backend(
    backend_name: str,
    *,
    system_cfg: dict[str, Any],
    cfg: dict[str, Any],
) -> OllamaBackend | NemoClawBackend | VLLMBackend:
    if backend_name == "nemoclaw":
        nemoclaw_cfg = cfg.get("system", {}).get("nemoclaw", cfg.get("nemoclaw", {}))
        return NemoClawBackend(
            base_url=str(os.getenv("NEMOCLAW_PROXY_URL", nemoclaw_cfg.get("proxy_url", "http://127.0.0.1:11435"))),
            timeout_s=float(os.getenv("NEMOCLAW_TIMEOUT_S", nemoclaw_cfg.get("timeout_seconds", 60))),
            token_file=str(os.getenv("NEMOCLAW_TOKEN_FILE", nemoclaw_cfg.get("token_file", "~/.nemoclaw/ollama-proxy-token"))),
            auto_start_proxy=_env_flag("NEMOCLAW_AUTO_START_PROXY", bool(nemoclaw_cfg.get("auto_start_proxy", True))),
            proxy_script=str(os.getenv("NEMOCLAW_PROXY_SCRIPT", nemoclaw_cfg.get("proxy_script", "~/.nemoclaw/source/scripts/ollama-auth-proxy.js"))),
            proxy_port=int(os.getenv("NEMOCLAW_PROXY_PORT", str(nemoclaw_cfg.get("proxy_port", 11435)))),
            backend_port=int(os.getenv("NEMOCLAW_BACKEND_PORT", str(nemoclaw_cfg.get("backend_port", 11434)))),
            keep_alive=os.getenv("NEMOCLAW_KEEP_ALIVE", str(nemoclaw_cfg.get("keep_alive", "0"))),
        )
    if backend_name == "vllm":
        vllm_cfg = cfg.get("system", {}).get("vllm", cfg.get("vllm", {}))
        return VLLMBackend(
            base_url=str(os.getenv("VLLM_BASE_URL", vllm_cfg.get("base_url", "http://127.0.0.1:8000/v1"))),
            timeout_s=float(os.getenv("VLLM_TIMEOUT_S", vllm_cfg.get("timeout_seconds", 300))),
            api_key=str(os.getenv("VLLM_API_KEY", vllm_cfg.get("api_key", "EMPTY"))),
            model_base_urls=dict(vllm_cfg.get("model_base_urls", {})),
            nemoclaw_runtime=NemoClawVLLMRuntime.from_config(vllm_cfg.get("nemoclaw_k8s", {})),
        )
    ollama_cfg = cfg.get("system", {}).get("ollama", cfg.get("ollama", {}))
    ollama_timeout_s = float(os.getenv("OLLAMA_TIMEOUT_S", ollama_cfg.get("timeout_seconds", 300)))
    return OllamaBackend(
        base_url=os.getenv("OLLAMA_BASE_URL", str(ollama_cfg.get("base_url", "http://localhost:11434"))),
        timeout_s=ollama_timeout_s,
        keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", str(ollama_cfg.get("keep_alive", "0"))),
    )


def _build_runtime_profile(
    *,
    backend_name: str,
    backend_cfg: dict[str, Any],
    models_cfg: dict[str, Any],
    router: ModelRouter,
) -> dict[str, Any]:
    """Assemble backend/model metadata for GUI status panels."""
    labels = {
        "nemoclaw": "Ollama / NemoClaw",
        "ollama": "Ollama",
        "vllm": "NemoClaw / vLLM",
    }
    role_routes = {
        "orchestrator": "orchestrator_plan",
        "e4b": "design_reasoning",
        "e2b": "tool_formatting",
    }
    selected_models: dict[str, dict[str, str | None]] = {}
    for role, task_type in role_routes.items():
        selection = router.select(task_type)
        selected_models[role] = {
            "task_type": task_type,
            "primary": selection.primary,
            "fallback": selection.fallback,
        }

    return {
        "backend": {
            "name": backend_name,
            "label": labels.get(backend_name, backend_name),
            "active": True,
            "proxy_url": (
                backend_cfg.get("proxy_url")
                or backend_cfg.get("base_url")
                or "http://127.0.0.1:11435"
            ),
            "model_base_urls": dict(backend_cfg.get("model_base_urls", {})),
        },
        "models": selected_models,
        "task_routes": dict(models_cfg.get("task_routes", {})),
    }


def load_runtime() -> MainController:
    """Create fully initialized runtime controller."""
    load_dotenv(resolve_path(".env"), override=False)
    cfg = _load_configs()
    system_cfg = cfg.get("system", {}).get("system", {})
    base_models_cfg = cfg.get("models", {})
    logging_cfg = cfg.get("logging", {})

    guide_path = resolve_path(system_cfg.get("guide_path", "./docs/project/Project_guide.txt"))
    local_index = LocalRAGIndex.from_file(guide_path)
    web_retriever = WebRetriever(
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
        serper_api_key=os.getenv("SERPER_API_KEY"),
    )
    rag = HybridRAG(local_index=local_index, web_retriever=web_retriever)

    backend_name = _normalize_backend_name(os.getenv("AUTONOMOUS_BACKEND"), str(system_cfg.get("inference_backend", "vllm")))
    backend_registry = {
        name: _build_backend(name, system_cfg=system_cfg, cfg=cfg)
        for name in SUPPORTED_BACKENDS
    }
    allow_mock_fallback = _env_flag(
        "AUTONOMOUS_ALLOW_MOCK_FALLBACK",
        bool(system_cfg.get("allow_mock_fallback", False)),
    )
    fallback_registry = {
        name: MockLLMBackend() if allow_mock_fallback else backend
        for name, backend in backend_registry.items()
    }
    force_real_llm_in_test = _env_flag(
        "AUTONOMOUS_USE_REAL_LLM_IN_TEST",
        bool(system_cfg.get("force_real_llm_in_test", True)),
    )
    models_by_backend = {name: _models_cfg_for_backend(base_models_cfg, name) for name in SUPPORTED_BACKENDS}
    router_registry = {name: ModelRouter(models_by_backend[name]) for name in SUPPORTED_BACKENDS}
    router = router_registry[backend_name]
    backend_cfg_by_name = {
        "nemoclaw": cfg.get("system", {}).get("nemoclaw", cfg.get("nemoclaw", {})),
        "ollama": cfg.get("system", {}).get("ollama", cfg.get("ollama", {})),
        "vllm": cfg.get("system", {}).get("vllm", cfg.get("vllm", {})),
    }
    runtime_profiles = {
        name: _build_runtime_profile(
            backend_name=name,
            backend_cfg=backend_cfg_by_name.get(name, {}),
            models_cfg=models_by_backend[name],
            router=router_registry[name],
        )
        for name in SUPPORTED_BACKENDS
    }
    runtime_profile = dict(runtime_profiles[backend_name])

    tools = ToolRegistry()
    register_mock_tools(tools)
    register_printer_tools(tools, cfg.get("devices", {}), repo_root=resolve_path("."))
    register_equipment_tools(tools, cfg.get("devices", {}), repo_root=resolve_path("."))
    register_lerobot_tools(tools, cfg.get("lerobot", {}), repo_root=resolve_path("."))

    agent_context = AgentContext(
        model_router=router,
        primary_backend=backend_registry[backend_name],
        fallback_backend=fallback_registry[backend_name],
        rag=rag,
        experiment_db=ExperimentDB(),
        failure_memory=FailureMemory(),
        tools=tools,
        force_real_llm_in_test=force_real_llm_in_test,
        allow_mock_fallback=allow_mock_fallback,
        active_backend=backend_name,
        model_routers=router_registry,
        primary_backends=backend_registry,
        fallback_backends=fallback_registry,
        runtime_profiles=runtime_profiles,
    )

    agent_registry = AgentRegistry()
    agent_registry.register(OrchestratorAgent())
    agent_registry.register(DesignAgent())
    agent_registry.register(SpecimenMakingAgent())
    agent_registry.register(VisionAgent())
    agent_registry.register(ManipulationAgent())
    agent_registry.register(LabEquipmentAgent())
    agent_registry.register(AnalysisAgent())
    agent_registry.register(KnowledgeAgent())
    agent_registry.register(GuardianAgent())

    run_root = resolve_path(system_cfg.get("run_root", "./runs"))
    deps = ControllerDeps(
        agent_registry=agent_registry,
        orchestrator_agent_name="orchestrator_agent",
        agent_context=agent_context,
        graph=OrchestrationGraph(),
        run_root=Path(run_root),
        logging_config=logging_cfg,
        system_config=system_cfg,
        runtime_profile=runtime_profile,
    )
    return MainController(deps)
