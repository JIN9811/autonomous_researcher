"""Strict portable shape shared by core owners; owner policy stays owner-local."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from packages.portability import portable_value


Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,95}$")]
ExactVersion = Annotated[
    str,
    StringConstraints(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"),
]


class OwnerPlanDeclaration(BaseModel):
    """Portable definition identity and detached settings, never runtime inputs."""

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    schema_: Literal["ax4lab.owner_plan.v1"] = Field(alias="schema", serialization_alias="schema")
    id: Identifier
    owner: Identifier
    version: ExactVersion
    contract_version: ExactVersion
    settings: dict[str, Any]


def validate_owner_plan_shape(
    value: Any,
    *,
    expected_owner: str,
    expected_contract_version: str,
) -> dict[str, Any]:
    """Return a detached exact declaration before an owner applies policy rules."""
    try:
        declaration = OwnerPlanDeclaration.model_validate(value)
    except ValidationError as exc:
        raise ValueError(f"Invalid owner plan declaration fields/schema/version: {exc}") from exc
    if declaration.owner != expected_owner:
        raise ValueError(f"Owner plan owner must match module owner: {expected_owner}")
    if declaration.contract_version != expected_contract_version:
        raise ValueError(f"Unsupported {expected_owner} owner plan contract version")
    payload = declaration.model_dump(mode="json", by_alias=True)
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Owner plan declaration must contain finite JSON data") from exc
    return deepcopy(portable_value(payload, exporting=True, owner_plan=True))


def runtime_owner_plan(ctx: Any, *, owner: str) -> Any | None:
    """Read one detached pinned declaration only from its matching owner module."""
    accessor = getattr(ctx, "runtime_module_config", None)
    if not callable(accessor):
        return None
    module = accessor()
    if not isinstance(module, dict) or str(module.get("id") or "") != owner:
        return None
    return deepcopy(module.get("owner_plan")) if "owner_plan" in module else None


def owner_plan_evidence(declaration: dict[str, Any], effective_settings: dict[str, Any]) -> dict[str, Any]:
    """Record configured identity plus owner-approved effective settings."""
    return {
        key: deepcopy(declaration[key])
        for key in ("schema", "id", "owner", "version", "contract_version")
    } | {"effective_settings": deepcopy(effective_settings)}
