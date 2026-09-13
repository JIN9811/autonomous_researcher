"""Read-only Guardian plan contract over mandatory policy inputs."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from agents.core.plans import owner_plan_evidence, runtime_owner_plan, validate_owner_plan_shape


PLAN_SCHEMA = "ax4lab.owner_plan_snapshot.v1"
CONTRACT_SCHEMA = "ax4lab.owner_plan_contract.v1"
OWNER = "guardian"
VERSION = "1.0.0"
_SETTING_KEYS = {"advisory_evidence_context"}


def guardian_plan_contract() -> dict[str, Any]:
    """Describe queryable Guardian inputs and the non-configurable safety boundary."""
    return deepcopy({
        "schema": CONTRACT_SCHEMA,
        "owner": OWNER,
        "version": VERSION,
        "activation_supported": False,
        "settings": {
            "supported": ["advisory_evidence_context"],
            "default_materialization": False,
        },
        "input_bindings": {
            "operator_stop": ["safe_stop_requested", "stop_requested"],
            "policy_inputs": [
                "current_experiment_spec", "latest_analysis", "latest_observations",
                "device_health", "retry_counters", "guardian_gates", "incident_records",
                "hardware_alerts",
            ],
            "references": "Existing guardian_agent Knowledge reference delivery",
            "advisory_evidence_context": "Optional evidence description; never a gate override",
        },
        "authority_boundaries": [
            "Validation is read-only and does not activate or persist a plan.",
            "Operator stop, deterministic checks, device interlocks, and gate precedence are mandatory.",
            "Threshold overrides, check disabling, readiness fabrication, and permission widening are unsupported.",
        ],
    })


def _inputs(state: Any) -> dict[str, Any]:
    metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
    return deepcopy({
        "operator_stop": {
            "safe_stop_requested": bool(state.safe_stop_requested),
            "stop_requested": bool(state.stop_requested),
        },
        "policy_inputs": {
            "current_experiment_spec": state.current_experiment_spec,
            "latest_analysis": state.latest_analysis,
            "latest_observations": state.latest_observations,
            "device_health": state.device_health,
            "retry_counters": state.retry_counters,
            "guardian_gates": metadata.get("guardian_gates", []),
            "incident_records": metadata.get("incident_records", []),
            "hardware_alerts": metadata.get("hardware_alerts", []),
        },
        "references": {
            "consumer": "guardian_agent",
            "query": state.active_goal or "Guardian policy evidence",
        },
    })


def _validate_settings(settings: Any) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise ValueError("Guardian plan settings must be an object")
    unknown = set(settings) - _SETTING_KEYS
    if unknown:
        raise ValueError(f"Unsupported Guardian setting: {sorted(unknown)}")
    advisory = settings.get("advisory_evidence_context", {})
    if not isinstance(advisory, dict):
        raise ValueError("Guardian advisory evidence context must be an object")
    json.dumps(settings, allow_nan=False)
    return deepcopy(settings)


def resolve_guardian_plan(state: Any) -> dict[str, Any]:
    """Return current mandatory inputs; no plan metadata participates in execution."""
    return {
        "schema": PLAN_SCHEMA,
        "owner": OWNER,
        "version": VERSION,
        "settings": {},
        "inputs": _inputs(state),
    }


def validate_guardian_plan(plan: Any, state: Any) -> dict[str, Any]:
    """Validate optional advisory context while rejecting every policy override."""
    if not isinstance(plan, dict):
        raise ValueError("Guardian plan must be an object")
    allowed = {"schema", "owner", "version", "settings", "inputs"}
    unknown = set(plan) - allowed
    if unknown:
        raise ValueError(f"Unsupported Guardian plan field: {sorted(unknown)}")
    if plan.get("schema", PLAN_SCHEMA) != PLAN_SCHEMA:
        raise ValueError("Unsupported Guardian plan schema")
    if plan.get("owner", OWNER) != OWNER:
        raise ValueError("Unsupported Guardian plan owner")
    if plan.get("version", VERSION) != VERSION:
        raise ValueError("Unsupported Guardian plan version")
    current = resolve_guardian_plan(state)
    if "inputs" in plan and plan["inputs"] != current["inputs"]:
        raise ValueError("Guardian mandatory inputs are read-only")
    return {**current, "settings": _validate_settings(plan.get("settings", {}))}


def validate_guardian_plan_declaration(plan: Any, state: Any) -> dict[str, Any]:
    """Validate one exact portable declaration without weakening mandatory policy."""
    declaration = validate_owner_plan_shape(
        plan,
        expected_owner=OWNER,
        expected_contract_version=VERSION,
    )
    declaration["settings"] = _validate_settings(declaration["settings"])
    return declaration


def resolve_runtime_guardian_plan(state: Any, ctx: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return optional pinned advisory context and its configured evidence record."""
    declaration_value = runtime_owner_plan(ctx, owner=OWNER)
    if declaration_value is None:
        return {}, None
    declaration = validate_guardian_plan_declaration(declaration_value, state)
    settings = deepcopy(declaration["settings"])
    return settings, owner_plan_evidence(declaration, settings)
