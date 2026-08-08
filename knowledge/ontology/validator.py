"""Validation rules for graph-bound ATR Knowledge events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from knowledge.ontology.registry import OntologyRegistry


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    errors: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()


class OntologyValidator:
    def __init__(self, registry: OntologyRegistry) -> None:
        self.registry = registry

    def validate_relationship(self, relationship: dict[str, Any]) -> ValidationReport:
        relation_type = str(relationship.get("relation_type") or "")
        source_class = str(relationship.get("source_class") or "")
        target_class = str(relationship.get("target_class") or "")
        rule = self.registry.relation_rules.get(relation_type)
        if rule is None:
            return ValidationReport(False, (f"unknown relation_type: {relation_type}",))
        errors: list[str] = []
        if source_class not in rule.source_classes:
            errors.append(f"relation {relation_type} domain excludes {source_class}")
        if target_class not in rule.target_classes:
            errors.append(f"relation {relation_type} range excludes {target_class}")
        return ValidationReport(not errors, tuple(errors))

    def validate_transition(self, entity_class: str, old_state: str, new_state: str) -> ValidationReport:
        transitions = self.registry.state_transitions.get(entity_class)
        if transitions is None:
            return ValidationReport(False, (f"no state transition rules for class {entity_class}",))
        allowed = transitions.get(old_state, ())
        if new_state not in allowed:
            return ValidationReport(False, (f"invalid {entity_class} transition: {old_state} -> {new_state}",))
        return ValidationReport(True)

    def validate_event(self, event: dict[str, Any]) -> ValidationReport:
        missing = tuple(field for field in self.registry.required_event_fields if field not in event)
        errors: list[str] = []
        if event.get("schema") != "knowledge_event.v1":
            errors.append("schema must be knowledge_event.v1")
        if event.get("ontology_version") not in {None, self.registry.version_id}:
            errors.append(f"ontology_version must be {self.registry.version_id}")
        event_type = str(event.get("event_type") or "")
        if event_type and event_type not in self.registry.event_families:
            errors.append(f"unknown event_type: {event_type}")
        for field in ("entity_refs", "relationship_intents", "artifact_refs"):
            value = event.get(field)
            if value is not None and not isinstance(value, list):
                errors.append(f"{field} must be a list")
            if isinstance(value, list) and len(value) > self.registry.maxima.get(field, len(value)):
                errors.append(f"{field} exceeds configured maximum")
        summary = event.get("payload_summary")
        if summary is not None and not isinstance(summary, dict):
            errors.append("payload_summary must be an object")
        elif isinstance(summary, dict):
            size = len(json.dumps(summary, ensure_ascii=True, sort_keys=True).encode("utf-8"))
            if size > self.registry.maxima.get("payload_summary_bytes", size):
                errors.append("payload_summary exceeds configured maximum")
        for intent in event.get("relationship_intents", []) if isinstance(event.get("relationship_intents"), list) else []:
            if not isinstance(intent, dict):
                errors.append("relationship intent must be an object")
                continue
            relation_report = self.validate_relationship(intent)
            errors.extend(relation_report.errors)
        all_errors = tuple(f"missing required field: {field}" for field in missing) + tuple(errors)
        return ValidationReport(not all_errors, all_errors, missing)
