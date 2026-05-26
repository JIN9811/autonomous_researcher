"""
File purpose:
- Compile validated ATR graph configs into executable LangGraph graphs.

Key classes/functions:
- ATRLangGraphCompiler

Inputs/outputs:
- Input: GraphConfig and HandlerRegistry
- Output: compiled LangGraph app

Dependencies:
- langgraph
- graphs.schema
- graphs.registry

Modification guide:
- Safe places to edit: compiler metadata and supported condition types
- Risky places to edit: fallback behavior when LangGraph is unavailable
- Related files: orchestrator/langgraph_runtime.py
"""

from __future__ import annotations

from typing import Any

from graphs.registry import HandlerRegistry
from graphs.schema import GraphConfig
from graphs.validator import validate_graph_config


class ATRLangGraphCompiler:
    """Compile config-driven ATR graph definitions with allowlisted handlers."""

    def __init__(self, config: GraphConfig, handlers: HandlerRegistry, *, module_ids: set[str] | None = None) -> None:
        self.config = config
        self.handlers = handlers
        self.module_ids = set(module_ids) if module_ids is not None else None

    def validate(self) -> list[str]:
        """Return validation errors before compile/run."""
        errors = validate_graph_config(
            self.config,
            registered_handlers=set(self.handlers.names()),
            registered_modules=self.module_ids,
        )
        handler_errors = self.handlers.validation_errors(self.config.handler_ids)
        for handler_id in sorted(self.config.handler_ids):
            for issue in handler_errors.get(handler_id, []):
                errors.append(f"handler={handler_id} invalid runtime signature: {issue}")
        return sorted(dict.fromkeys(errors))

    def summary(self) -> dict[str, Any]:
        """Return the executable graph shape that was compile-checked."""
        registered_handlers = set(self.handlers.names())
        executable_edges = [
            {
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition,
                "label": edge.label,
            }
            for edge in self.config.edges
            if edge.metadata.get("runtime_edge") != "logical_transition"
        ]
        logical_edges = [
            {
                "source": edge.source,
                "target": edge.target,
                "from_stage": edge.metadata.get("from_stage", ""),
                "to_stage": edge.metadata.get("to_stage", ""),
                "label": edge.label,
                "condition": edge.condition or edge.metadata.get("condition") or edge.metadata.get("transition_condition"),
                "default": str(edge.metadata.get("to_stage", "")) == self.config.transitions.get(str(edge.metadata.get("from_stage", "")), "")
                and (
                    bool(edge.metadata.get("default_transition"))
                    or str(edge.condition or edge.metadata.get("condition") or edge.metadata.get("transition_condition") or "").strip()
                    in {"", "default", "continue", "always"}
                ),
                "metadata": dict(edge.metadata),
            }
            for edge in self.config.edges
            if edge.metadata.get("runtime_edge") == "logical_transition"
        ]
        return {
            "graph_id": self.config.id,
            "version": self.config.version,
            "entry_node": self.config.entry_node,
            "finish_nodes": list(self.config.finish_nodes),
            "node_count": len(self.config.nodes),
            "edge_count": len(executable_edges),
            "logical_edge_count": len(logical_edges),
            "nodes": [
                {
                    "id": node.id,
                    "label": node.label,
                    "handler": node.handler,
                    "handler_signature": self.handlers.metadata(node.handler).get("signature", "") if node.handler in registered_handlers else "",
                    "handler_async": self.handlers.metadata(node.handler).get("is_async", False) if node.handler in registered_handlers else False,
                    "handler_accepts_runtime_state": self.handlers.metadata(node.handler).get("accepts_runtime_state", False) if node.handler in registered_handlers else False,
                    "stage": node.stage,
                    "module_id": node.module_id,
                    "kind": node.kind,
                }
                for node in self.config.nodes
            ],
            "executable_edges": executable_edges,
            "logical_edges": logical_edges,
            "stage_dispatch": dict(self.config.stage_dispatch),
            "transitions": dict(self.config.transitions),
            "transition_candidates": {stage: self.config.transition_candidates(stage) for stage in self.config.stage_dispatch},
        }

    def compile(self) -> Any:
        """Compile the configured graph into a LangGraph executable."""
        errors = self.validate()
        if errors:
            raise ValueError("Invalid LangGraph config: " + "; ".join(errors))
        try:
            from langgraph.graph import END, StateGraph
        except ImportError as exc:  # pragma: no cover - exercised when dependency is absent.
            raise RuntimeError(
                "LangGraph dependency is required for ATR runtime. "
                "Install project requirements or run `pip install langgraph`."
            ) from exc

        builder = StateGraph(dict)
        for node in self.config.nodes:
            builder.add_node(node.id, self.handlers.get(node.handler))

        builder.set_entry_point(self.config.entry_node)

        conditional_by_source: dict[str, dict[str, str]] = {}
        for edge in self.config.edges:
            if edge.metadata.get("runtime_edge") == "logical_transition":
                continue
            if edge.condition:
                conditional_by_source.setdefault(edge.source, {})[edge.condition] = edge.target
                continue
            target = END if edge.target in self.config.finish_nodes else edge.target
            builder.add_edge(edge.source, target)

        for source, route_map in conditional_by_source.items():
            builder.add_conditional_edges(source, _stage_router, route_map)

        return builder.compile()


def _stage_router(runtime_state: dict[str, Any]) -> str:
    """Route dispatch edges from the current OrchestratorState stage."""
    state = runtime_state.get("state")
    stage = getattr(state, "stage", None)
    value = getattr(stage, "value", stage)
    return str(value or "error")
