"""Normalize heterogeneous runtime payloads into the Knowledge event contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def normalize_knowledge_event(payload: Mapping[str, Any], *, ontology_version: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("knowledge event payload must be a mapping")
    event = deepcopy(dict(payload))
    event.pop("event_id", None)
    event.pop("idempotency_key", None)
    event.update(
        {
            "schema": "knowledge_event.v1",
            "entity_refs": _list_of_dicts(event.get("entity_refs")),
            "relationship_intents": _list_of_dicts(event.get("relationship_intents")),
            "artifact_refs": _list_of_dicts(event.get("artifact_refs")),
            "payload_summary": dict(event.get("payload_summary") or {}),
            "ontology_version": ontology_version,
            "provenance": dict(event.get("provenance") or {}),
        }
    )
    canonical = json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    event["event_id"] = f"event:{digest[:32]}"
    event["idempotency_key"] = f"sha256:{digest}"
    return event


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("knowledge event reference collections must be lists")
    if not all(isinstance(item, dict) for item in value):
        raise TypeError("knowledge event reference collections must contain mappings")
    return [deepcopy(item) for item in value]
