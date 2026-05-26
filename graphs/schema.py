"""
File purpose:
- Define graph configuration schemas used by the ATR LangGraph runtime.

Key classes/functions:
- GraphConfig
- load_graph_config

Inputs/outputs:
- Input: YAML graph definitions
- Output: validated graph metadata consumed by compiler/runtime

Dependencies:
- pydantic
- pyyaml

Modification guide:
- Safe places to edit: additive metadata fields
- Risky places to edit: node id, handler id, and transition semantics
- Related files: graphs/compiler.py, orchestrator/langgraph_runtime.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class GraphNode(BaseModel):
    """One graph node bound to a registered runtime handler."""

    id: str
    label: str
    handler: str
    stage: str | None = None
    kind: str = "agent"
    description: str = ""
    module_id: str | None = None
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "handler")
    @classmethod
    def _required_id(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("graph node id/handler cannot be empty")
        return clean


class GraphEdge(BaseModel):
    """Inspectable edge metadata for GUI/runtime validation."""

    source: str
    target: str
    condition: str | None = None
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModuleLLMConfig(BaseModel):
    """Editable LLM routing hints for one module."""

    model_config = ConfigDict(extra="allow")

    backend: str | None = None
    model: str | None = None
    primary: str | None = None
    fallback: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None


class ModuleRetryConfig(BaseModel):
    """Per-module retry policy override."""

    model_config = ConfigDict(extra="allow")

    max_attempts: int | None = None
    backoff_s: float | None = None


class ModuleSafetyConfig(BaseModel):
    """Per-module safety and dry-run policy flags."""

    model_config = ConfigDict(extra="allow")

    live_requires_validation: bool = True
    dry_run_supported: bool = True
    requires_human_approval: bool = False


class ModulePromptConfig(BaseModel):
    """Prompt override metadata for one module."""

    model_config = ConfigDict(extra="allow")

    path: str | None = None
    system: str | None = None
    developer: str | None = None
    user_template: str | None = None


class ModuleStep(BaseModel):
    """One editable pre-execution or internal module graph step."""

    model_config = ConfigDict(extra="allow")

    id: str
    label: str = ""
    kind: str = "internal_step"
    handler: str | None = None
    output_key: str | None = None
    event_type: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _required_step_id(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("module step id cannot be empty")
        return clean


class ModuleConfig(BaseModel):
    """Versioned editable module definition consumed by Runtime IDE and runtime binding."""

    model_config = ConfigDict(extra="allow")

    id: str
    label: str = ""
    handler: str
    llm_role: str = ""
    editable: bool = True
    safety: ModuleSafetyConfig = Field(default_factory=ModuleSafetyConfig)
    tools: list[str] = Field(default_factory=list)
    pre_execution: list[ModuleStep] = Field(default_factory=list)
    internal_graph: list[ModuleStep] = Field(default_factory=list)
    llm: ModuleLLMConfig | None = None
    prompt: ModulePromptConfig | str | None = None
    timeout_s: float | None = None
    retry: ModuleRetryConfig | None = None
    io_contract: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""

    @field_validator("id", "handler")
    @classmethod
    def _required_module_value(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("module id/handler cannot be empty")
        return clean

    @field_validator("tools")
    @classmethod
    def _tools_must_be_non_empty_strings(cls, value: list[str]) -> list[str]:
        clean_tools: list[str] = []
        for index, tool in enumerate(value, start=1):
            clean = str(tool).strip()
            if not clean:
                raise ValueError(f"tools[{index}] must be a non-empty string")
            clean_tools.append(clean)
        return clean_tools




class GraphConfig(BaseModel):
    """Versioned executable graph definition."""

    id: str
    name: str
    version: str = "0.1.0"
    entry_node: str
    finish_nodes: list[str] = Field(default_factory=lambda: ["step_complete"])
    nodes: list[GraphNode]
    edges: list[GraphEdge] = Field(default_factory=list)
    stage_dispatch: dict[str, str] = Field(default_factory=dict)
    transitions: dict[str, str] = Field(default_factory=dict)
    terminal_stages: list[str] = Field(default_factory=lambda: ["complete", "error"])
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def node_ids(self) -> set[str]:
        """Return all configured node ids."""
        return {node.id for node in self.nodes}

    @property
    def handler_ids(self) -> set[str]:
        """Return all configured handler ids."""
        return {node.handler for node in self.nodes}

    def node_for_stage(self, stage: str) -> str | None:
        """Return configured node id for a runtime stage."""
        return self.stage_dispatch.get(stage)

    def transition_candidates(self, stage: str) -> list[dict[str, Any]]:
        """Return logical transition candidates for one runtime stage.

        `transitions` remains the backward-compatible default path, while
        `edges[*].metadata.runtime_edge=logical_transition` can express multiple
        possible LangGraph-style links from one stage.
        """
        candidates: list[dict[str, Any]] = []
        default_target = self.transitions.get(stage, "")
        for index, edge in enumerate(self.edges):
            if edge.metadata.get("runtime_edge") != "logical_transition":
                continue
            source_stage = str(edge.metadata.get("from_stage") or edge.source)
            if source_stage != stage:
                continue
            target_stage = str(edge.metadata.get("to_stage") or edge.target)
            condition = str(
                edge.metadata.get("condition")
                or edge.metadata.get("transition_condition")
                or edge.condition
                or ""
            ).strip()
            metadata_default = bool(edge.metadata.get("default_transition"))
            is_default = bool(default_target) and target_stage == default_target and (
                metadata_default or condition in {"", "default", "continue", "always"}
            )
            candidates.append(
                {
                    "index": index,
                    "source": edge.source,
                    "target": edge.target,
                    "from_stage": source_stage,
                    "to_stage": target_stage,
                    "condition": condition or ("default" if is_default else "candidate"),
                    "label": edge.label,
                    "metadata": dict(edge.metadata),
                    "default": is_default,
                }
            )
        if default_target and not any(str(candidate.get("to_stage")) == default_target for candidate in candidates):
            candidates.append(
                {
                    "index": -1,
                    "source": self.stage_dispatch.get(stage, stage),
                    "target": self.stage_dispatch.get(default_target, default_target),
                    "from_stage": stage,
                    "to_stage": default_target,
                    "condition": "default",
                    "label": f"configured transition: {stage} -> {default_target}",
                    "metadata": {"runtime_edge": "logical_transition", "from_stage": stage, "to_stage": default_target},
                    "default": True,
                }
            )
        return candidates

    @staticmethod
    def _transition_context_value(state_metadata: dict[str, Any] | None, key: str) -> Any:
        """Read a shallow or dotted key from transition context metadata."""
        if not isinstance(state_metadata, dict) or not key:
            return None
        current: Any = state_metadata
        for part in key.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _candidate_matches(
        self,
        candidate: dict[str, Any],
        *,
        guardian_decision: str,
        state_metadata: dict[str, Any] | None,
        requested_next_stage: str,
        requested_decision: str,
    ) -> bool:
        """Return whether one logical transition candidate matches runtime context."""
        target = str(candidate.get("to_stage") or "")
        condition = str(candidate.get("condition") or "").strip().lower()
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        condition_key = str(metadata.get("condition_key") or "").strip()
        if condition_key:
            observed = self._transition_context_value(state_metadata, condition_key)
            expected = metadata.get("condition_value", True)
            return observed == expected
        if requested_next_stage and requested_next_stage == target:
            return True
        tokens = {str(token).strip().lower() for token in (guardian_decision, requested_decision) if token}
        if condition in {"default", "continue", "always", ""}:
            return False
        if condition in tokens:
            return True
        for token in tokens:
            if condition in {f"decision:{token}", f"guardian:{token}", f"guardian_decision:{token}"}:
                return True
        if condition.startswith("next_stage:") and condition.split(":", 1)[1] == requested_next_stage:
            return True
        return False

    def next_stage(
        self,
        stage: str,
        *,
        guardian_decision: str = "continue",
        state_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Return the next configured stage using logical edge candidates when present."""
        context = state_metadata if isinstance(state_metadata, dict) else {}
        agent_result = context.get("agent_result") if isinstance(context.get("agent_result"), dict) else {}
        requested_next_stage = str(
            context.get("next_stage")
            or context.get("requested_next_stage")
            or context.get("transition_next_stage")
            or agent_result.get("next_stage")
            or agent_result.get("requested_next_stage")
            or ""
        ).strip()
        requested_decision = str(
            context.get("transition_decision")
            or context.get("routing_decision")
            or agent_result.get("transition_decision")
            or agent_result.get("routing_decision")
            or ""
        ).strip().lower()

        candidates = self.transition_candidates(stage)
        for candidate in candidates:
            if self._candidate_matches(
                candidate,
                guardian_decision=guardian_decision,
                state_metadata=context,
                requested_next_stage=requested_next_stage,
                requested_decision=requested_decision,
            ):
                return str(candidate.get("to_stage") or "complete")

        if stage == "guardian":
            if guardian_decision == "stop":
                return "complete"
            if guardian_decision == "error":
                return "error"

        default_edges = [candidate for candidate in candidates if bool(candidate.get("default"))]
        if default_edges:
            return str(default_edges[0].get("to_stage") or "complete")
        if candidates:
            return str(candidates[0].get("to_stage") or "complete")
        return self.transitions.get(stage, "complete")


def load_graph_config(path: str | Path) -> GraphConfig:
    """Load and validate a YAML graph configuration."""
    graph_path = Path(path)
    raw = yaml.safe_load(graph_path.read_text(encoding="utf-8")) or {}
    graph = raw.get("graph", raw)
    return GraphConfig.model_validate(graph)


def load_module_config(path: str | Path) -> ModuleConfig:
    """Load and validate a YAML module configuration."""
    module_path = Path(path)
    raw = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
    module = raw.get("module", raw) if isinstance(raw, dict) else raw
    return ModuleConfig.model_validate(module)
