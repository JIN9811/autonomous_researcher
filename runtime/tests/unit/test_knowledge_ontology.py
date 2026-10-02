from __future__ import annotations

from pathlib import Path

from knowledge.ontology.registry import OntologyRegistry
from knowledge.ontology.validator import OntologyValidator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_default_registry_exposes_versioned_core_classes() -> None:
    registry = OntologyRegistry.load_default(PROJECT_ROOT)

    assert registry.version_id == "atr-core-1.0.0"
    assert {"Run", "Specimen", "GuardianGate", "KnowledgeClaim"} <= registry.class_names
    assert registry.relation_rules["CONTAINS"].source_classes == ("Run",)
    assert registry.relation_rules["CONTAINS"].target_classes == ("Cycle",)


def test_validator_accepts_declared_relation_domain_and_range() -> None:
    validator = OntologyValidator(OntologyRegistry.load_default(PROJECT_ROOT))

    report = validator.validate_relationship(
        {"relation_type": "CONTAINS", "source_class": "Run", "target_class": "Cycle"}
    )

    assert report.ok
    assert report.errors == ()


def test_validator_rejects_relation_outside_declared_domain() -> None:
    validator = OntologyValidator(OntologyRegistry.load_default(PROJECT_ROOT))

    report = validator.validate_relationship(
        {"relation_type": "CONTAINS", "source_class": "Specimen", "target_class": "Cycle"}
    )

    assert not report.ok
    assert any("domain" in error for error in report.errors)


def test_validator_rejects_invalid_specimen_state_transition() -> None:
    validator = OntologyValidator(OntologyRegistry.load_default(PROJECT_ROOT))

    valid = validator.validate_transition("Specimen", "validated", "sliced")
    invalid = validator.validate_transition("Specimen", "designed", "manufactured")

    assert valid.ok
    assert not invalid.ok
    assert any("transition" in error for error in invalid.errors)


def test_validator_requires_knowledge_event_contract_fields() -> None:
    validator = OntologyValidator(OntologyRegistry.load_default(PROJECT_ROOT))

    report = validator.validate_event(
        {
            "schema": "knowledge_event.v1",
            "event_id": "event:1",
            "event_type": "run.created",
        }
    )

    assert not report.ok
    assert "run_id" in report.missing_fields
    assert "occurred_at" in report.missing_fields


def test_validator_rejects_unknown_event_family() -> None:
    validator = OntologyValidator(OntologyRegistry.load_default(PROJECT_ROOT))
    event = {
        "schema": "knowledge_event.v1",
        "event_id": "event:1",
        "idempotency_key": "sha256:abc",
        "run_id": "run-1",
        "cycle_id": "cycle-1",
        "source_agent": "knowledge_agent",
        "event_type": "unknown.action",
        "occurred_at": "2026-08-08T00:00:00Z",
        "entity_refs": [],
        "relationship_intents": [],
        "artifact_refs": [],
        "payload_summary": {},
        "ontology_version": "atr-core-1.0.0",
        "provenance": {},
    }

    report = validator.validate_event(event)

    assert not report.ok
    assert any("event_type" in error for error in report.errors)
