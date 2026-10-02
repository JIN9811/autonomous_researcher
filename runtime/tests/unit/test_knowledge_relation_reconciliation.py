from __future__ import annotations

from pathlib import Path

from knowledge.ontology.registry import OntologyRegistry
from knowledge.relation_reconciliation import GraphGapDetector, RelationCandidateGenerator


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _snapshot() -> dict:
    return {
        "nodes": [
            {"id": "run:1", "kind": "Run", "run_id": "run-1", "properties": {"provenance_refs": ["run.json"]}},
            {"id": "cycle:1", "kind": "Cycle", "run_id": "run-1", "properties": {"provenance_refs": ["run.json"]}},
            {"id": "specimen:isolated", "kind": "Specimen", "run_id": "run-1", "created_at": "2026-08-09T00:00:02+00:00", "properties": {"provenance_refs": ["specimen.stl"]}},
            {"id": "observation:best", "kind": "Observation", "run_id": "run-1", "created_at": "2026-08-09T00:00:03+00:00", "properties": {"provenance_refs": ["specimen.stl", "frame.png"]}},
            {"id": "observation:other-run", "kind": "Observation", "run_id": "run-2", "created_at": "2026-08-09T00:00:04+00:00", "properties": {"provenance_refs": ["other.png"]}},
            {"id": "artifact:weak", "kind": "Artifact", "run_id": "run-3", "properties": {"provenance_refs": ["orphan.log"]}},
            {"id": "tool:weak", "kind": "Tool", "run_id": "run-3", "properties": {"provenance_refs": ["orphan.log"]}},
        ],
        "edges": [
            {"id": "run-cycle", "source": "run:1", "target": "cycle:1", "type": "CONTAINS"},
            {"id": "weak-generated", "source": "artifact:weak", "target": "tool:weak", "type": "GENERATED_BY"},
        ],
    }


def test_gap_detector_finds_isolated_and_disconnected_component_nodes() -> None:
    gaps = GraphGapDetector().detect(_snapshot(), limit=20)
    found = {(gap.node_id, gap.gap_type) for gap in gaps}

    assert ("specimen:isolated", "isolated") in found
    assert ("artifact:weak", "disconnected_component") in found
    assert ("tool:weak", "disconnected_component") in found
    assert ("run:1", "disconnected_component") not in found


def test_candidate_ranking_excludes_incompatible_targets_and_explains_score() -> None:
    registry = OntologyRegistry.load_default(PROJECT_ROOT)
    snapshot = _snapshot()
    source = next(node for node in snapshot["nodes"] if node["id"] == "specimen:isolated")

    candidates = RelationCandidateGenerator().rank(
        source,
        snapshot["nodes"],
        snapshot["edges"],
        registry,
        limit=8,
    )

    observed = [candidate for candidate in candidates if candidate.relation_type == "OBSERVED_BY"]
    assert [candidate.target_id for candidate in observed] == ["observation:best", "observation:other-run"]
    assert observed[0].score > observed[1].score
    assert observed[0].score_factors["same_run"] > 0
    assert observed[0].score_factors["shared_provenance"] > 0
    assert all(candidate.target_class in candidate.allowed_target_classes for candidate in candidates)
    assert not any(candidate.target_id == "cycle:1" for candidate in candidates)


def test_gap_detection_is_bounded_and_deterministic() -> None:
    detector = GraphGapDetector()

    first = detector.detect(_snapshot(), limit=2)
    second = detector.detect(_snapshot(), limit=2)

    assert first == second
    assert len(first) == 2

