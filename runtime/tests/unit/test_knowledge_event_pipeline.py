from __future__ import annotations

import json
from pathlib import Path

from knowledge.audit_ledger import AuditLedger
from knowledge.event_normalizer import normalize_knowledge_event
from knowledge.ontology.registry import OntologyRegistry
from knowledge.ontology.validator import OntologyValidator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _payload() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "cycle_id": "cycle-1",
        "source_agent": "analysis_agent",
        "event_type": "specimen.analyzed",
        "occurred_at": "2026-08-08T00:00:00Z",
        "entity_refs": [{"entity_id": "runtime:specimen:s-1", "entity_class": "Specimen"}],
        "payload_summary": {"objective_score": 0.82},
    }


def test_normalizer_is_idempotent_for_same_semantic_event() -> None:
    first = normalize_knowledge_event(_payload(), ontology_version="atr-core-1.0.0")
    second = normalize_knowledge_event(_payload(), ontology_version="atr-core-1.0.0")

    assert first["schema"] == "knowledge_event.v1"
    assert first["event_id"] == second["event_id"]
    assert first["idempotency_key"] == second["idempotency_key"]
    assert first["relationship_intents"] == []
    assert first["artifact_refs"] == []
    assert first["provenance"] == {}


def test_normalized_event_passes_ontology_validation() -> None:
    event = normalize_knowledge_event(_payload(), ontology_version="atr-core-1.0.0")
    validator = OntologyValidator(OntologyRegistry.load_default(PROJECT_ROOT))

    assert validator.validate_event(event).ok


def test_normalizer_rejects_non_mapping_payload() -> None:
    try:
        normalize_knowledge_event([], ontology_version="atr-core-1.0.0")  # type: ignore[arg-type]
    except TypeError as exc:
        assert "mapping" in str(exc)
    else:
        raise AssertionError("non-mapping payload must be rejected")


def test_ledger_appends_json_line_and_returns_hash(tmp_path: Path) -> None:
    event = normalize_knowledge_event(_payload(), ontology_version="atr-core-1.0.0")
    ledger = AuditLedger(tmp_path)

    receipt = ledger.append(event)

    assert receipt.path == tmp_path / "events" / "2026" / "08" / "08" / "events.jsonl"
    assert receipt.path.exists()
    assert len(receipt.sha256) == 64
    assert receipt.line_number == 1
    assert json.loads(receipt.path.read_text(encoding="utf-8"))["event_id"] == event["event_id"]


def test_ledger_preserves_replayed_event_as_second_audit_line(tmp_path: Path) -> None:
    event = normalize_knowledge_event(_payload(), ontology_version="atr-core-1.0.0")
    ledger = AuditLedger(tmp_path)

    first = ledger.append(event)
    second = ledger.append(event)

    lines = second.path.read_text(encoding="utf-8").splitlines()
    assert first.line_number == 1
    assert second.line_number == 2
    assert len(lines) == 2
    assert json.loads(lines[0])["event_id"] == json.loads(lines[1])["event_id"]
