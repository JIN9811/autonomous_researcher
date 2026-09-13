"""Read-only Knowledge plan contract over the owner's existing inputs."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any

from agents.core.plans import owner_plan_evidence, runtime_owner_plan, validate_owner_plan_shape
from knowledge.markdown_runtime import applicability_for
from knowledge.markdown_memory import MarkdownKnowledgeStore


PLAN_SCHEMA = "ax4lab.owner_plan_snapshot.v1"
CONTRACT_SCHEMA = "ax4lab.owner_plan_contract.v1"
OWNER = "knowledge"
VERSION = "1.0.0"
_SETTING_KEYS = {
    "scope",
    "corpora",
    "source_scope",
    "applicability",
    "decision_call_timeout_s",
    "decision_max_steps",
}
_CORPORA = {"markdown", "project", "sources"}


def knowledge_plan_contract() -> dict[str, Any]:
    """Describe supported bindings without granting storage or execution authority."""
    return deepcopy({
        "schema": CONTRACT_SCHEMA,
        "owner": OWNER,
        "version": VERSION,
        "activation_supported": False,
        "settings": {
            "source": "run_metadata.knowledge_settings",
            "supported": sorted(_SETTING_KEYS),
            "defaults": {
                "corpora": ["markdown", "project", "sources"],
                "decision_call_timeout_s": 300.0,
                "decision_max_steps": 8,
            },
            "default_materialization": False,
        },
        "input_bindings": {
            "scope": "knowledge_settings.scope",
            "corpora": "knowledge_settings.corpora",
            "source_scope": "knowledge_settings.source_scope",
            "applicability": "knowledge_settings applicability plus current objective identity",
            "decision_timeout": "knowledge_settings.decision_call_timeout_s",
            "decision_step_budget": "knowledge_settings.decision_max_steps",
        },
        "authority_boundaries": [
            "Validation is read-only and does not activate or persist a plan.",
            "Existing Knowledge stores and services retain scope and authorization checks.",
            "A plan cannot add corpora, private-memory access, tools, device effects, or ontology authority.",
        ],
    })


def validate_knowledge_settings(settings: Any, state: Any) -> dict[str, Any]:
    """Validate the existing Knowledge settings shape and applicability rules."""
    if not isinstance(settings, dict):
        raise ValueError("Knowledge plan settings must be an object")
    unknown = set(settings) - _SETTING_KEYS
    if unknown:
        raise ValueError(f"Unsupported Knowledge setting: {sorted(unknown)}")
    for key in ("scope", "applicability"):
        if key in settings and not isinstance(settings[key], dict):
            raise ValueError(f"Knowledge {key} must be an object")
    MarkdownKnowledgeStore._normalize_scope(settings.get("scope", {}))
    corpora = settings.get("corpora", ["markdown", "project", "sources"])
    if not isinstance(corpora, list) or any(item not in _CORPORA for item in corpora):
        raise ValueError("Unsupported Knowledge corpus")
    if "sources" in corpora and not isinstance(settings.get("source_scope", {}), dict):
        raise ValueError("Knowledge source_scope must be an object when sources corpus is selected")
    timeout = settings.get("decision_call_timeout_s", 300.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("decision_call_timeout_s must be positive and finite")
    max_steps = settings.get("decision_max_steps", 8)
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 2 <= max_steps <= 16:
        raise ValueError("decision_max_steps must be between 2 and 16")
    json.dumps(settings, allow_nan=False)

    _applicability_for_settings(settings, state)
    return deepcopy(settings)


def _applicability_for_settings(settings: dict[str, Any], state: Any) -> dict[str, Any]:
    detached_state = state.model_copy(deep=True)
    metadata = detached_state.run_metadata if isinstance(detached_state.run_metadata, dict) else {}
    detached_state.run_metadata = {**metadata, "knowledge_settings": deepcopy(settings)}
    return applicability_for(detached_state)


def resolve_knowledge_plan(state: Any) -> dict[str, Any]:
    """Return the current effective Knowledge input snapshot without writing state."""
    raw = state.run_metadata.get("knowledge_settings", {})
    if not isinstance(raw, dict):
        raise ValueError("knowledge_settings must be an object")
    # Current runtime metadata can contain compatibility annotations ignored by
    # the owner. Preserve them in the query snapshot; strictness applies only to
    # a proposed plan and never becomes a new invocation-time rejection path.
    settings = deepcopy(raw)
    supported = {key: deepcopy(value) for key, value in settings.items() if key in _SETTING_KEYS}
    validate_knowledge_settings(supported, state)
    return {
        "schema": PLAN_SCHEMA,
        "owner": OWNER,
        "version": VERSION,
        "settings": settings,
        "inputs": {"applicability": _applicability_for_settings(settings, state)},
    }


def validate_knowledge_plan(plan: Any, state: Any) -> dict[str, Any]:
    """Validate a detached Knowledge proposal without applying it."""
    if not isinstance(plan, dict):
        raise ValueError("Knowledge plan must be an object")
    allowed = {"schema", "owner", "version", "settings", "inputs"}
    unknown = set(plan) - allowed
    if unknown:
        raise ValueError(f"Unsupported Knowledge plan field: {sorted(unknown)}")
    if plan.get("schema", PLAN_SCHEMA) != PLAN_SCHEMA:
        raise ValueError("Unsupported Knowledge plan schema")
    if plan.get("owner", OWNER) != OWNER:
        raise ValueError("Unsupported Knowledge plan owner")
    if plan.get("version", VERSION) != VERSION:
        raise ValueError("Unsupported Knowledge plan version")
    current = resolve_knowledge_plan(state)
    settings = (validate_knowledge_settings(plan["settings"], state)
                if "settings" in plan else deepcopy(current["settings"]))
    inputs = {"applicability": _applicability_for_settings(settings, state)}
    if "inputs" in plan and plan["inputs"] != inputs:
        raise ValueError("Knowledge plan inputs are read-only")
    return {**current, "settings": settings, "inputs": inputs}


def validate_knowledge_plan_declaration(plan: Any, state: Any) -> dict[str, Any]:
    """Validate one exact portable declaration using Knowledge-owned settings rules."""
    declaration = validate_owner_plan_shape(
        plan,
        expected_owner=OWNER,
        expected_contract_version=VERSION,
    )
    declaration["settings"] = validate_knowledge_settings(declaration["settings"], state)
    return declaration


def resolve_runtime_knowledge_plan(state: Any, ctx: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Overlay a pinned declaration on detached legacy settings for this call only."""
    raw = state.run_metadata.get("knowledge_settings", {})
    if not isinstance(raw, dict):
        raise ValueError("knowledge_settings must be an object")
    settings = deepcopy(raw)
    declaration_value = runtime_owner_plan(ctx, owner=OWNER)
    if declaration_value is None:
        return settings, None
    declaration = validate_knowledge_plan_declaration(declaration_value, state)
    settings.update(deepcopy(declaration["settings"]))
    supported = {key: deepcopy(value) for key, value in settings.items() if key in _SETTING_KEYS}
    validate_knowledge_settings(supported, state)
    effective = deepcopy(supported)
    effective.setdefault("corpora", ["markdown", "project", "sources"])
    effective.setdefault("decision_call_timeout_s", 300.0)
    effective.setdefault("decision_max_steps", 8)
    return settings, owner_plan_evidence(declaration, effective)


def applicability_for_knowledge_settings(settings: dict[str, Any], state: Any) -> dict[str, Any]:
    """Resolve applicability against detached effective settings."""
    return _applicability_for_settings(settings, state)
