import json
import multiprocessing
from pathlib import Path

import fcntl

import pytest

import orchestrator.experimental_setup as experimental_setup
from orchestrator.experimental_setup import SetupConflict, SetupStore, SetupValidationError


def _ensure_block_in_separate_process(root: str, queue) -> None:
    store = SetupStore(Path(root), session_id="session-a")
    store.ensure_block("research.goal", "owner-a", {"goal": "baseline"})
    queue.put("written")


def test_edit_keeps_identity_replays_same_request_and_rejects_stale_writer(tmp_path):
    """Removing per-block revision checks would permit a stale edit to overwrite a draft."""
    store = SetupStore(tmp_path, session_id="session-a")
    block = store.ensure_block("research.goal", "orchestrator_agent", {"goal": "baseline"})

    proposed = store.propose(block["block_id"], block["revision"], {"goal": "compare"}, "req-a")

    assert proposed["block_id"] == block["block_id"]
    assert store.propose(block["block_id"], block["revision"], {"goal": "compare"}, "req-a") == proposed
    with pytest.raises(SetupConflict):
        store.propose(block["block_id"], block["revision"], {"goal": "other"}, "req-b")

    restored = SetupStore(tmp_path, session_id="session-a")
    assert restored.snapshot() == store.snapshot()


def test_request_id_cannot_be_reused_for_a_different_payload(tmp_path):
    """Dropping the request fingerprint would make retries able to change a proposal."""
    store = SetupStore(tmp_path, session_id="session-a")
    block = store.ensure_block("research.goal", "orchestrator_agent", {"goal": "baseline"})

    store.propose(block["block_id"], block["revision"], {"goal": "compare"}, "req-a")

    with pytest.raises(SetupConflict):
        store.propose(block["block_id"], block["revision"], {"goal": "different"}, "req-a")


def test_normalized_confirmation_atomically_persists_successor_validation_and_original_request(tmp_path, monkeypatch):
    store = SetupStore(tmp_path, "session-a")
    block = store.ensure_block("research.goal", "orchestrator_agent", {"research.goal": "baseline"})
    p = store.propose(block["block_id"], block["block_revision"], {"research.goal": " new "}, "p")
    before = store.snapshot()
    before_bytes = (tmp_path / "experimental_setup.json").read_bytes()
    persist = experimental_setup.atomic_write_json
    def fail_write(*args, **kwargs):
        raise OSError("simulated atomic write failure")
    monkeypatch.setattr(experimental_setup, "atomic_write_json", fail_write)
    with pytest.raises(OSError):
        store.confirm_normalized(p["proposal_id"], p["block_revision"], "c", {"research.goal": "new"},
            {"status": "requires_confirmation"}, expected_store_revision=before["revision"])
    assert (tmp_path / "experimental_setup.json").read_bytes() == before_bytes
    assert store.snapshot() == before
    assert "validation" not in store.proposal(p["proposal_id"])
    monkeypatch.setattr(experimental_setup, "atomic_write_json", persist)
    result = store.confirm_normalized(p["proposal_id"], p["block_revision"], "c", {"research.goal": "new"},
        {"status": "requires_confirmation"}, expected_store_revision=before["revision"])
    reloaded = SetupStore(tmp_path, "session-a")
    assert reloaded.confirmation_result(p["proposal_id"], p["block_revision"], "c") == result
    assert result["requires_confirmation"] is True
    assert result["proposal_id"] != p["proposal_id"]
    assert result["blocks"][0]["confirmed_values"] is None
    assert len(result["blocks"][0]["proposal_ids"]) == 2
    assert reloaded.proposal(p["proposal_id"])["validation"]["status"] == "requires_confirmation"
    with pytest.raises(SetupConflict):
        reloaded.confirmation_result(result["proposal_id"], result["block_revision"], "c")


def test_second_store_instance_checks_the_persisted_revision_before_writing(tmp_path):
    """Using a stale instance's memory would let a second tab overwrite a newer proposal."""
    writer = SetupStore(tmp_path, session_id="session-a")
    block = writer.ensure_block("research.goal", "orchestrator_agent", {"goal": "baseline"})
    stale_view = SetupStore(tmp_path, session_id="session-a")

    writer.propose(block["block_id"], block["revision"], {"goal": "writer"}, "writer-request")

    with pytest.raises(SetupConflict):
        stale_view.propose(block["block_id"], block["revision"], {"goal": "stale"}, "stale-request")


def test_separate_process_writer_honors_the_store_lock_before_mutating(tmp_path):
    """Ignoring the durable lock lets a second process race the load-and-replace transaction."""
    SetupStore(tmp_path, session_id="session-a")
    lock_path = tmp_path / ".experimental_setup.lock"
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        process = context.Process(target=_ensure_block_in_separate_process, args=(str(tmp_path), queue))
        process.start()
        process.join(timeout=0.75)
        try:
            assert process.is_alive()
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    process.join(timeout=5)
    assert process.exitcode == 0
    assert queue.get(timeout=1) == "written"


def test_existing_topic_returns_its_block_revision_separately_from_snapshot_revision(tmp_path):
    """Returning the global revision as an existing block's base revision causes false stale writes."""
    store = SetupStore(tmp_path, session_id="session-a")
    goal = store.ensure_block("research.goal", "orchestrator_agent", {"goal": "baseline"})
    store.ensure_block("bo.acquisition", "bo_agent", {"acquisition": "ei"})

    existing = store.ensure_block("research.goal", "other-owner", {"goal": "ignored"})

    assert existing["block_id"] == goal["block_id"]
    assert existing["block_revision"] == 1
    assert existing["revision"] == 2


def test_historical_confirmed_proposal_cannot_receive_a_delayed_receipt_after_new_confirmation(tmp_path):
    """Accepting A's delayed receipt after B is confirmed corrupts B's receipt and effective state."""
    store = SetupStore(tmp_path, session_id="session-a")
    block = store.ensure_block("research.goal", "owner-a", {"goal": "baseline"})
    proposal_a = store.propose(block["block_id"], block["revision"], {"goal": "a"}, "proposal-a")
    confirmed_a = store.confirm(proposal_a["proposal_id"], proposal_a["revision"], "confirm-a", "next_run")
    proposal_b = store.propose(block["block_id"], confirmed_a["block_revision"], {"goal": "b"}, "proposal-b")
    store.confirm(proposal_b["proposal_id"], proposal_b["revision"], "confirm-b", "next_run")

    with pytest.raises(SetupConflict):
        store.record_application(proposal_a["proposal_id"], "owner-a", {"status": "applied", "readback": {"goal": "a"}})

    saved = store.snapshot()["blocks"][0]
    assert saved["confirmed_proposal_id"] == proposal_b["proposal_id"]
    assert saved["effective_values"] == {}


def test_only_the_current_draft_can_be_confirmed_or_discarded(tmp_path):
    """Allowing an older draft to act at a newer revision replaces the user's current draft."""
    store = SetupStore(tmp_path, session_id="session-a")
    block = store.ensure_block("research.goal", "owner-a", {"goal": "baseline"})
    first = store.propose(block["block_id"], block["revision"], {"goal": "first"}, "proposal-a")
    second = store.propose(block["block_id"], first["revision"], {"goal": "second"}, "proposal-b")

    with pytest.raises(SetupConflict):
        store.confirm(first["proposal_id"], second["revision"], "confirm-a", "next_run")
    with pytest.raises(SetupConflict):
        store.discard(first["proposal_id"], second["revision"], "discard-a")

    assert store.proposal(second["proposal_id"])["status"] == "draft"
    assert store.snapshot()["blocks"][0]["draft_values"] == {"goal": "second"}


def test_nested_malformed_state_raises_validation_error_at_restore(tmp_path):
    """A schema-valid outer object with malformed blocks must not later fail as a KeyError."""
    path = tmp_path / "experimental_setup.json"
    path.write_text(
        json.dumps({"session_id": "session-a", "revision": 1, "event_seq": 1, "blocks": [{}], "proposals": {}, "requests": {}, "events": []}),
        encoding="utf-8",
    )

    with pytest.raises(SetupValidationError):
        SetupStore(tmp_path, session_id="session-a")


def test_draft_does_not_replace_effective_values_until_owner_receipts_arrive(tmp_path):
    """Copying a draft into effective values would falsely show unapplied configuration as applied."""
    store = SetupStore(tmp_path, session_id="session-a")
    block = store.ensure_block("research.goal", ["orchestrator_agent", "bo_agent"], {"goal": "baseline"})
    proposal = store.propose(block["block_id"], block["revision"], {"goal": "compare"}, "proposal-a")

    before_confirmation = store.snapshot()["blocks"][0]
    assert before_confirmation["draft_values"] == {"goal": "compare"}
    assert before_confirmation["effective_values"] == {}

    confirmed = store.confirm(proposal["proposal_id"], proposal["revision"], "confirm-a", "next_run")
    after_confirmation = confirmed["blocks"][0]
    assert after_confirmation["confirmed_values"] == {"goal": "compare"}
    assert after_confirmation["effective_values"] == {}
    assert after_confirmation["application_status"] == "scheduled"

    partial = store.record_application(proposal["proposal_id"], "orchestrator_agent", {"status": "applied", "readback": {"goal": "compare"}})
    assert partial["blocks"][0]["application_status"] == "partial"
    assert partial["blocks"][0]["receipts"] == {
        "orchestrator_agent": {"status": "applied", "readback": {"goal": "compare"}}
    }
    assert partial["blocks"][0]["effective_values"] == {"goal": "compare"}


def test_new_draft_preserves_the_prior_confirmed_and_effective_values(tmp_path):
    """Replacing confirmed state while drafting would hide the values an owner is still using."""
    store = SetupStore(tmp_path, session_id="session-a")
    block = store.ensure_block("research.goal", "owner-a", {"goal": "baseline"})
    first = store.propose(block["block_id"], block["revision"], {"goal": "baseline"}, "proposal-a")
    store.confirm(first["proposal_id"], first["revision"], "confirm-a", "next_run")
    applied = store.record_application(first["proposal_id"], "owner-a", {"status": "applied", "readback": {"goal": "baseline"}})

    store.propose(block["block_id"], applied["block_revision"], {"goal": "compare"}, "proposal-b")

    saved = store.snapshot()["blocks"][0]
    assert saved["draft_values"] == {"goal": "compare"}
    assert saved["confirmed_values"] == {"goal": "baseline"}
    assert saved["effective_values"] == {"goal": "baseline"}
    assert saved["application_status"] == "applied"


def test_receipts_for_each_owner_are_retained_across_a_partial_application(tmp_path):
    """Replacing receipts instead of mapping them by owner would erase partial-application evidence."""
    store = SetupStore(tmp_path, session_id="session-a")
    block = store.ensure_block("research.goal", ["owner-a", "owner-b"], {"goal": "baseline"})
    proposal = store.propose(block["block_id"], block["revision"], {"goal": "compare"}, "proposal-a")
    confirmed = store.confirm(proposal["proposal_id"], proposal["revision"], "confirm-a", "next_run")

    store.record_application(proposal["proposal_id"], "owner-a", {"status": "applied"})
    result = store.record_application(proposal["proposal_id"], "owner-b", {"status": "rejected", "reason": "busy"})

    saved = result["blocks"][0]
    assert saved["application_status"] == "partial"
    assert saved["receipts"] == {
        "owner-a": {"status": "applied"},
        "owner-b": {"status": "rejected", "reason": "busy"},
    }
    assert store.proposal(proposal["proposal_id"])["history"][-1]["event"] == "application_recorded"
    assert confirmed["event_seq"] < result["event_seq"]


def test_restoring_applying_state_never_changes_it_or_applies_anything(tmp_path):
    """Constructor-side recovery must not resume an unfinished owner application."""
    store = SetupStore(tmp_path, session_id="session-a")
    block = store.ensure_block("research.goal", "owner-a", {"goal": "baseline"})
    proposal = store.propose(block["block_id"], block["revision"], {"goal": "compare"}, "proposal-a")
    store.confirm(proposal["proposal_id"], proposal["revision"], "confirm-a", "next_run")
    store.record_application(proposal["proposal_id"], "owner-a", {"status": "applying"})

    restored = SetupStore(tmp_path, session_id="session-a")

    assert restored.snapshot() == store.snapshot()
    assert restored.snapshot()["blocks"][0]["application_status"] == "applying"


def test_corrupt_store_is_not_overwritten_and_failed_write_keeps_memory(tmp_path, monkeypatch):
    """Treating corrupt persistence as empty or committing before a failed write loses durable state."""
    path = tmp_path / "experimental_setup.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(SetupValidationError):
        SetupStore(tmp_path, session_id="session-a")
    assert path.read_text(encoding="utf-8") == "not json"

    path.unlink()
    store = SetupStore(tmp_path, session_id="session-a")
    baseline = store.snapshot()
    persisted_baseline = json.loads(path.read_text(encoding="utf-8"))

    def fail_write(_path, _payload):
        raise OSError("disk full")

    monkeypatch.setattr(experimental_setup, "atomic_write_json", fail_write)
    with pytest.raises(OSError, match="disk full"):
        store.ensure_block("research.goal", "owner-a", {"goal": "baseline"})

    assert store.snapshot() == baseline
    assert json.loads(path.read_text(encoding="utf-8")) == persisted_baseline


def test_activation_claim_requires_same_run_and_stable_owner_request_ids(tmp_path):
    store = SetupStore(tmp_path, "session")
    block = store.ensure_block("goal", ["a", "b"], {})
    p = store.propose(block["block_id"], block["block_revision"], {"goal": "compare"}, "p")
    store.confirm(p["proposal_id"], p["block_revision"], "c", "next_run")
    with pytest.raises(SetupValidationError):
        store.claim_activation(p["proposal_id"], {"a": {"status": "applying"}, "b": {"status": "applying"}})
    receipts = {o: {"status": "applying", "run_id": "new", "request_id": f"{p['proposal_id']}:{o}:new"}
                for o in ("a", "b")}
    receipts["b"]["run_id"] = "different"
    with pytest.raises(SetupValidationError):
        store.claim_activation(p["proposal_id"], receipts)
    assert store.snapshot()["blocks"][0]["receipts"] == {}


def test_inflight_activation_blocks_superseding_confirmation_not_drafts(tmp_path):
    store = SetupStore(tmp_path, "session")
    block = store.ensure_block("goal", "a", {})
    p = store.propose(block["block_id"], block["block_revision"], {"goal": "compare"}, "p")
    store.confirm(p["proposal_id"], p["block_revision"], "c", "next_run")
    claim = store.claim_activation(p["proposal_id"], {"a": {"status": "applying", "run_id": "new",
                                  "request_id": f"{p['proposal_id']}:a:new"}})
    newer = store.propose(block["block_id"], claim["block_revision"], {"goal": "other"}, "p2")
    with pytest.raises(SetupConflict):
        store.confirm(newer["proposal_id"], newer["block_revision"], "c2", "next_run")
    assert store.proposal(newer["proposal_id"])["status"] == "draft"
