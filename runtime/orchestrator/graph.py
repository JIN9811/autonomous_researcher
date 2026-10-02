"""
File purpose:
- Backward-compatible transition wrapper retained for old imports only.
- Runtime execution now uses graphs/configs/*.yaml through LangGraphRunLoop.

Key classes/functions:
- OrchestrationGraph

Inputs/outputs:
- Input: stage and guardian decision
- Output: next stage

Dependencies:
- orchestrator.transitions.default_next_stage

Modification guide:
- Do not add new runtime behavior here. Update graphs/configs/*.yaml and module configs instead.
- Related files: graphs/configs/*.yaml, orchestrator/langgraph_runtime.py
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.state import Stage
from orchestrator.transitions import default_next_stage


class OrchestrationGraph:
    """Compatibility shim; it delegates to graph-config-derived transitions."""

    def __init__(self, graph_config_path: str | Path | None = None) -> None:
        self.graph_config_path = graph_config_path

    def next_stage(self, current: Stage, guardian_decision: str = "continue") -> Stage:
        """Compute next stage through the configured graph transition table."""
        return default_next_stage(
            current=current,
            guardian_decision=guardian_decision,
            graph_config_path=self.graph_config_path,
        )
