from __future__ import annotations

from knowledge.relation_reconciliation import GraphEditDraft, RelationDecision, RelationProposal
from knowledge.relation_store import RelationStore


def _proposal(*, proposal_id: str = "proposal-1", confidence: float = 0.82) -> RelationProposal:
    return RelationProposal(
        proposal_id=proposal_id,
        version=1,
        work_id="work-1",
        source_id="specimen:1",
        source_class="Specimen",
        target_id="observation:1",
        target_class="Observation",
        relation_type="OBSERVED_BY",
        confidence=confidence,
        evidence_score=0.76,
        rationale="The observation and specimen share a run and artifact reference.",
        provenance_refs=("artifact:frame-1",),
        model_snapshot={"backend": "vllm", "model": "gemma4:e4b-it-nvfp4"},
        ontology_version="atr-core-1.0.0",
        graph_revision="rev-1",
        graph_context_hash="ctx-1",
    )


def test_relation_store_deduplicates_pending_work_by_graph_and_evidence_revision(tmp_path) -> None:
    store = RelationStore(tmp_path)

    first = store.enqueue_node("specimen:1", graph_revision="rev-1", evidence_hash="ev-1")
    duplicate = store.enqueue_node("specimen:1", graph_revision="rev-1", evidence_hash="ev-1")
    changed = store.enqueue_node("specimen:1", graph_revision="rev-2", evidence_hash="ev-1")

    assert duplicate.work_id == first.work_id
    assert changed.work_id != first.work_id
    assert store.stats()["pending_work"] == 2


def test_relation_store_claims_work_once_and_records_proposal_resolution(tmp_path) -> None:
    store = RelationStore(tmp_path)
    queued = store.enqueue_node("specimen:1", graph_revision="rev-1", evidence_hash="ev-1")

    claimed = store.claim_pending(limit=10)
    second_claim = store.claim_pending(limit=10)
    stored = store.append_proposal(_proposal())
    decision = store.append_decision(
        RelationDecision(
            decision_id="decision-1",
            proposal_id=stored.proposal_id,
            proposal_version=stored.version,
            decision="approved",
            decision_source="operator",
            operator="jin",
            rationale="Evidence verified.",
            accepted_relation=stored.relationship(),
        )
    )

    assert [item.work_id for item in claimed] == [queued.work_id]
    assert second_claim == []
    assert decision.proposal_id == "proposal-1"
    assert store.get_proposal("proposal-1").status == "approved"
    assert store.stats()["approved"] == 1


def test_relation_store_keeps_original_proposal_when_re_evaluated(tmp_path) -> None:
    store = RelationStore(tmp_path)
    original = store.append_proposal(_proposal())
    replacement = store.append_proposal(
        RelationProposal(
            **{
                **_proposal(proposal_id="proposal-2", confidence=0.88).as_dict(),
                "supersedes": original.proposal_id,
                "version": 2,
            }
        )
    )

    assert store.get_proposal(original.proposal_id).status == "superseded"
    assert store.get_proposal(replacement.proposal_id).status == "pending"
    assert [item.proposal_id for item in store.list_proposals()] == ["proposal-2", "proposal-1"]


def test_relation_store_round_trips_graph_edit_draft(tmp_path) -> None:
    store = RelationStore(tmp_path)
    draft = GraphEditDraft(
        draft_id="draft-1",
        graph_revision="rev-1",
        operator="jin",
        changes=(
            {
                "operation": "revise_relation",
                "edge_id": "edge-1",
                "source_id": "specimen:1",
                "source_class": "Specimen",
                "target_id": "observation:1",
                "target_class": "Observation",
                "relation_type": "OBSERVED_BY",
            },
        ),
    )

    store.save_edit_draft(draft)

    loaded = store.get_edit_draft("draft-1")
    assert loaded is not None
    assert loaded.graph_revision == "rev-1"
    assert loaded.changes[0]["operation"] == "revise_relation"
