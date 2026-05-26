"""
File purpose:
- Backward-compatible default stage transition helper.
- Canonical runtime transitions live in graphs/configs/*.yaml.

Key classes/functions:
- default_next_stage
- ordered_stages

Inputs/outputs:
- Input: current stage and guardian decision
- Output: next stage enum

Dependencies:
- graphs.schema.load_graph_config
- orchestrator.state.Stage

Modification guide:
- Do not use this file as the source of truth for runtime order.
- Update graphs/configs/*.yaml and validate/compile through Runtime IDE/API instead.
- Related files: graphs/configs/*.yaml, orchestrator/langgraph_runtime.py
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from graphs import GraphConfig, load_graph_config
from orchestrator.state import Stage

_DEFAULT_GRAPH_PATH = Path(__file__).resolve().parent.parent / "graphs" / "configs" / "atr_closed_loop.yaml"


def _coerce_stage(value: str, fallback: Stage = Stage.COMPLETE) -> Stage:
    """Convert graph-config stage strings to Stage values with a safe compatibility fallback."""
    try:
        return Stage(value)
    except ValueError:
        return fallback


@lru_cache(maxsize=8)
def _load_transition_config(path_text: str) -> GraphConfig:
    """Load graph config for compatibility helpers with small cache."""
    return load_graph_config(path_text)


def _graph_config(graph_config_path: str | Path | None = None) -> GraphConfig:
    """Return the active/default graph config used by compatibility transition helpers."""
    path = Path(graph_config_path) if graph_config_path is not None else _DEFAULT_GRAPH_PATH
    return _load_transition_config(str(path.resolve()))


def _ordered_stages_from_config(config: GraphConfig) -> list[Stage]:
    """Derive a bounded default ordered stage list from graph transitions."""
    stages: list[Stage] = []
    current = _coerce_stage(config.next_stage(Stage.IDLE.value), fallback=Stage.DESIGN)
    visited: set[tuple[str, str]] = set()
    for _ in range(max(1, len(config.transitions) + 2)):
        if current in {Stage.COMPLETE, Stage.ERROR}:
            break
        stages.append(current)
        next_stage = _coerce_stage(config.next_stage(current.value), fallback=Stage.COMPLETE)
        edge = (current.value, next_stage.value)
        if edge in visited or next_stage in stages:
            break
        visited.add(edge)
        current = next_stage
    return stages


ordered_stages: list[Stage] = _ordered_stages_from_config(_graph_config())


def default_next_stage(
    current: Stage,
    guardian_decision: str = "continue",
    *,
    graph_config_path: str | Path | None = None,
) -> Stage:
    """Return the next stage from the active graph config.

    This compatibility helper intentionally mirrors `GraphConfig.next_stage(...)` instead
    of carrying its own stage list. Runtime execution itself uses `LangGraphRunLoop`.
    """
    config = _graph_config(graph_config_path)
    next_stage = config.next_stage(current.value, guardian_decision=guardian_decision)
    return _coerce_stage(next_stage, fallback=Stage.COMPLETE)
