"""
File purpose:
- Backward-compatible stage-to-agent resolver.
- Canonical runtime handler selection lives in graph/module YAML config.

Key classes/functions:
- stage_to_agent

Inputs/outputs:
- Input: current stage
- Output: target agent name or None

Dependencies:
- graphs.schema.load_graph_config
- orchestrator.state.Stage
- yaml for module config compatibility lookup

Modification guide:
- Do not add new hard-coded stage-agent maps here.
- Update graphs/configs/*.yaml or graphs/modules/*/module.yaml and validate through Runtime IDE/API instead.
- Related files: orchestrator/langgraph_runtime.py, graphs/configs/*.yaml, graphs/modules/*/module.yaml
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from graphs import GraphConfig, load_graph_config
from orchestrator.state import Stage

_DEFAULT_GRAPH_PATH = Path(__file__).resolve().parent.parent / "graphs" / "configs" / "atr_closed_loop.yaml"
_MODULE_ROOT = Path(__file__).resolve().parent.parent / "graphs" / "modules"


@lru_cache(maxsize=8)
def _load_router_config(path_text: str) -> GraphConfig:
    """Load graph config for compatibility router helpers with small cache."""
    return load_graph_config(path_text)


def _graph_config(graph_config_path: str | Path | None = None) -> GraphConfig:
    """Return graph config used by compatibility routing."""
    path = Path(graph_config_path) if graph_config_path is not None else _DEFAULT_GRAPH_PATH
    return _load_router_config(str(path.resolve()))


@lru_cache(maxsize=64)
def _load_module_handler(module_id: str) -> str:
    """Return module.handler for a graph module reference, if available."""
    safe_module = str(module_id).strip().rstrip("/").split("/")[-1]
    if not safe_module:
        return ""
    module_path = _MODULE_ROOT / safe_module / "module.yaml"
    try:
        raw = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    module = raw.get("module", raw) if isinstance(raw, dict) else {}
    if not isinstance(module, dict):
        return ""
    handler = module.get("handler")
    return str(handler).strip() if handler else ""


def _agent_name_from_handler(handler: str) -> str | None:
    """Convert allowlisted handler id to old AgentRegistry name."""
    clean = str(handler or "").strip()
    if not clean.startswith("agent."):
        return None
    agent_name = clean.removeprefix("agent.").strip()
    return agent_name or None


def stage_to_agent(stage: Stage, *, graph_config_path: str | Path | None = None) -> str | None:
    """Return the configured agent name for a stage or None when no agent is bound."""
    config = _graph_config(graph_config_path)
    for node in config.nodes:
        if node.stage != stage.value:
            continue
        module_handler = _load_module_handler(node.module_id or "") if node.module_id else ""
        return _agent_name_from_handler(module_handler or node.handler)
    return None
