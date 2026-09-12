"""Setup confirmation cannot mutate running experiments or claim unread effects."""
from copy import deepcopy
import socket
import subprocess
import asyncio

import pytest

from agents.bo_agent import BOAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.orchestrator_capabilities import OwnerCatalog
from agents.registry import AgentRegistry
from graphs.schema import load_graph_config
from orchestrator.experimental_setup import SetupStore, SetupConflict
from orchestrator.state import OrchestratorState, Stage, Mode
from orchestrator import setup_application as application


@pytest.fixture(autouse=True)
def deny_external(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No external effects in setup coordinator tests")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)


def fixture(tmp_path):
    registry = AgentRegistry()
    registry.register(BOAgent())
    registry.register(OrchestratorAgent())
    owners = OwnerCatalog(registry, load_graph_config("graphs/configs/atr_closed_loop.yaml"))
    store = SetupStore(tmp_path, "session")
    return store, owners


def proposal(store, values=None, owners=None, topic="experiment"):
    values = values or {"research.goal": "compare", "bo.acquisition": "upper_confidence_bound"}
    block = store.ensure_block(topic, owners or ["orchestrator_agent", "bo_agent"], {})
    return store.propose(block["block_id"], block["block_revision"], values, "propose-" + topic)


def state(run_id="old", mode=Mode.TEST):
    return OrchestratorState(run_id=run_id, experiment_id="exp", mode=mode,
        active_goal="baseline", run_metadata={"physical_policy": {"printer": False},
            "profile": "original", "bo_settings": {"acquisition": "expected_improvement", "random_seed": 73}})


def test_missing_readback_is_not_applied():
    assert application.receipt_status({"goal": "compare"}, None) == "unknown"
    assert application.receipt_status({"goal": "compare"}, {"goal": "compare"}) == "applied"
    assert application.receipt_status({"goal": "compare"}, {"goal": "baseline"}) == "rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(Mode))
async def test_confirm_only_changes_next_new_run_and_preserves_original_mode(tmp_path, mode):
    store, owners = fixture(tmp_path)
    p = proposal(store)
    app = application.SetupApplication(store, owners)
    old = state(mode=mode)
    before = old.model_dump()
    result = await app.confirm(p["proposal_id"], p["block_revision"], "confirm", old)
    assert result["proposal"]["target"] == "next_run"
    assert old.model_dump() == before
    with pytest.raises(SetupConflict):
        await app.activate_for_new_run(old)
    new = state("new", mode)
    snapshot = await app.activate_for_new_run(new)
    assert new.active_goal == "compare"
    assert new.run_metadata["bo_settings"]["acquisition"] == "upper_confidence_bound"
    assert new.mode == mode
    assert new.run_metadata["physical_policy"] == before["run_metadata"]["physical_policy"]
    assert new.run_metadata["profile"] == "original"
    assert new.run_metadata["bo_settings"]["random_seed"] == 73
    assert snapshot["blocks"][0]["application_status"] == "applied"
    new.stage = Stage.DESIGN
    assert await app.activate_for_new_run(new) == snapshot
    snapshot["blocks"].clear()
    assert new.run_metadata["experimental_setup_snapshot"]["blocks"]
    assert old.model_dump() == before


@pytest.mark.asyncio
async def test_unregistered_setting_and_wrong_owner_are_not_confirmed(tmp_path):
    store, owners = fixture(tmp_path)
    p = proposal(store, {"mode": "live"})
    app = application.SetupApplication(store, owners)
    with pytest.raises(ValueError):
        await app.confirm(p["proposal_id"], p["block_revision"], "c", state())
    assert store.proposal(p["proposal_id"])["status"] == "draft"
    p = proposal(store, {"research.goal": "compare"}, ["bo_agent"], "wrong")
    with pytest.raises(ValueError):
        await app.confirm(p["proposal_id"], p["block_revision"], "c2", state())


@pytest.mark.asyncio
async def test_normalized_difference_requires_new_visible_proposal(tmp_path):
    store, owners = fixture(tmp_path)
    p = proposal(store, {"research.goal": " compare "}, ["orchestrator_agent"])
    result = await application.SetupApplication(store, owners).confirm(
        p["proposal_id"], p["block_revision"], "c", state())
    assert result["requires_confirmation"] is True
    assert result["normalized_values"] == {"research.goal": "compare"}
    assert store.proposal(p["proposal_id"])["status"] == "draft"


@pytest.mark.asyncio
async def test_normalized_confirmation_reloads_original_request_before_owner_validation(tmp_path, monkeypatch):
    store, owners = fixture(tmp_path)
    p = proposal(store, {"research.goal": " compare "}, ["orchestrator_agent"])
    original_state = state()
    first = await application.SetupApplication(store, owners).confirm(p["proposal_id"], p["block_revision"], "confirmation", original_state)
    snapshot = store.snapshot()
    restored = SetupStore(tmp_path, "session")
    def forbidden(*args, **kwargs):
        pytest.fail("An identical committed retry re-entered owner validation")
    monkeypatch.setattr(owners, "validate", forbidden)
    assert await application.SetupApplication(restored, owners).confirm(
        p["proposal_id"], p["block_revision"], "confirmation", original_state) == first
    assert restored.snapshot() == snapshot
    assert original_state.active_goal == "baseline"


@pytest.mark.asyncio
async def test_partial_and_lost_response_never_retries_and_reconcile_is_read_only(tmp_path, monkeypatch):
    store, owners = fixture(tmp_path)
    p = proposal(store)
    app = application.SetupApplication(store, owners)
    await app.confirm(p["proposal_id"], p["block_revision"], "c", state())
    bo = owners.registry.get("bo_agent")
    original_apply = bo.apply_setup
    calls = []
    def lost(changes, new, request_id):
        receipt = store.snapshot()["blocks"][0]["receipts"]["bo_agent"]
        assert receipt["status"] == "applying"
        calls.append(request_id)
        original_apply(changes, new, request_id)
        raise TimeoutError("response lost")
    original_read = bo.read_setup
    monkeypatch.setattr(bo, "apply_setup", lost)
    # Validation uses readback only indirectly for BO, so loss is scoped to receipt reads.
    monkeypatch.setattr(bo, "read_setup", lambda new: None)
    new = state("new")
    result = await app.activate_for_new_run(new)
    assert result["blocks"][0]["application_status"] == "partial"
    assert calls == [f"{p['proposal_id']}:bo_agent:new"]
    restored = application.SetupApplication(SetupStore(tmp_path, "session"), owners)
    await restored.activate_for_new_run(state("another"))
    assert len(calls) == 1
    monkeypatch.setattr(bo, "read_setup", original_read)
    frozen = deepcopy(new.run_metadata["experimental_setup_snapshot"])
    await restored.reconcile(p["proposal_id"], new)
    assert store.snapshot()["blocks"][0]["application_status"] == "applied"
    assert new.run_metadata["experimental_setup_snapshot"] == frozen
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_revision_change_during_validation_prevents_confirmation(tmp_path, monkeypatch):
    store, owners = fixture(tmp_path)
    p = proposal(store)
    original = owners.validate
    def raced(owner, changes, current):
        if owner == "bo_agent":
            store.propose(p["block_id"], p["block_revision"], {"research.goal": "changed"}, "race")
        return original(owner, changes, current)
    monkeypatch.setattr(owners, "validate", raced)
    with pytest.raises(SetupConflict):
        await application.SetupApplication(store, owners).confirm(p["proposal_id"], p["block_revision"], "c", state())
    assert store.proposal(p["proposal_id"])["status"] == "draft"


@pytest.mark.asyncio
async def test_concurrent_activators_reserve_before_any_effect(tmp_path, monkeypatch):
    store, owners = fixture(tmp_path)
    p = proposal(store)
    app = application.SetupApplication(store, owners)
    await app.confirm(p["proposal_id"], p["block_revision"], "c", state())
    original = owners.apply
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def delayed(owner, changes, new, request_id):
        calls.append(request_id)
        entered.set()
        await release.wait()
        return await original(owner, changes, new, request_id)
    monkeypatch.setattr(owners, "apply", delayed)
    first = asyncio.create_task(app.activate_for_new_run(state("first")))
    await entered.wait()
    second = application.SetupApplication(SetupStore(tmp_path, "session"), owners)
    await second.activate_for_new_run(state("second"))
    release.set()
    await first
    assert sorted(calls) == [f"{p['proposal_id']}:bo_agent:first", f"{p['proposal_id']}:orchestrator_agent:first"]


def test_validation_metadata_and_activation_claim_are_atomic(tmp_path):
    store, _ = fixture(tmp_path)
    p = proposal(store)
    result = store.record_validation(p["proposal_id"], p["block_revision"],
        {"status": "valid", "origin_run_id": "old"}, expected_store_revision=p["revision"])
    assert result["block_revision"] == p["block_revision"]
    assert result["revision"] > p["revision"]
    with pytest.raises(SetupConflict):
        store.confirm(p["proposal_id"], p["block_revision"], "c", "next_run", expected_store_revision=p["revision"])
    store.confirm(p["proposal_id"], p["block_revision"], "c", "next_run", expected_store_revision=result["revision"])
    receipts = {owner: {"status": "applying", "run_id": "new", "request_id": f"{p['proposal_id']}:{owner}:new"}
                for owner in ("bo_agent", "orchestrator_agent")}
    assert store.claim_activation(p["proposal_id"], receipts)["claimed"] is True
    other = SetupStore(tmp_path, "session")
    assert other.claim_activation(p["proposal_id"], receipts)["claimed"] is False
    assert store.snapshot()["blocks"][0]["application_status"] == "applying"


@pytest.mark.asyncio
async def test_owner_revision_change_marks_stale_and_preserves_values(tmp_path, monkeypatch):
    store, owners = fixture(tmp_path)
    p = proposal(store)
    app = application.SetupApplication(store, owners)
    await app.confirm(p["proposal_id"], p["block_revision"], "c", state())
    original = owners.describe
    def changed(current, ctx):
        rows = original(current, ctx)
        for row in rows:
            if row["owner"] == "bo_agent":
                row["contract_version"] = "changed"
        return rows
    monkeypatch.setattr(owners, "describe", changed)
    new = state("new")
    result = await app.activate_for_new_run(new)
    assert result["blocks"][0]["validation_status"] == "stale"
    assert result["blocks"][0]["confirmed_values"] == {"research.goal": "compare", "bo.acquisition": "upper_confidence_bound"}
    assert new.active_goal == "baseline"


@pytest.mark.asyncio
async def test_prior_run_receipts_never_claim_effective_in_later_run(tmp_path):
    store, owners = fixture(tmp_path)
    p = proposal(store)
    app = application.SetupApplication(store, owners)
    await app.confirm(p["proposal_id"], p["block_revision"], "c", state())
    await app.activate_for_new_run(state("first"))
    next_state = state("second")
    result = await app.activate_for_new_run(next_state)
    assert next_state.active_goal == "baseline"
    assert result["blocks"][0]["application_status"] == "not_applied"
    assert result["blocks"][0]["effective_values"] == {}
    with pytest.raises(SetupConflict):
        await app.reconcile(p["proposal_id"], next_state)


@pytest.mark.asyncio
async def test_success_reply_without_effect_is_rejected_and_confirm_replays(tmp_path, monkeypatch):
    store, owners = fixture(tmp_path)
    p = proposal(store)
    app = application.SetupApplication(store, owners)
    first = await app.confirm(p["proposal_id"], p["block_revision"], "c", state())
    assert await app.confirm(p["proposal_id"], p["block_revision"], "c", state()) == first
    monkeypatch.setattr(owners.registry.get("bo_agent"), "apply_setup",
        lambda changes, new, request_id: {"status": "applied", "values": changes})
    result = await app.activate_for_new_run(state("new"))
    receipts = result["blocks"][0]["receipts"]
    assert receipts["bo_agent"]["status"] == "rejected"
    assert receipts["orchestrator_agent"]["status"] == "applied"


@pytest.mark.asyncio
async def test_dependent_block_revision_change_requires_revalidation(tmp_path):
    store, owners = fixture(tmp_path)
    dependency = store.ensure_block("dependency", "bo_agent", {})
    p = proposal(store)
    app = application.SetupApplication(store, owners)
    await app.confirm(p["proposal_id"], p["block_revision"], "c", state())
    store.propose(dependency["block_id"], dependency["block_revision"], {"bo.acquisition": "exploration"}, "dep")
    new = state("new")
    result = await app.activate_for_new_run(new)
    block = next(b for b in result["blocks"] if b["block_id"] == p["block_id"])
    assert block["validation_status"] == "stale"
    assert not block["receipts"]
    assert new.active_goal == "baseline"


@pytest.mark.asyncio
async def test_failed_new_proposal_snapshot_excludes_previous_effective_values(tmp_path, monkeypatch):
    store, owners = fixture(tmp_path)
    p = proposal(store, {"research.goal": "compare"}, ["orchestrator_agent"])
    app = application.SetupApplication(store, owners)
    await app.confirm(p["proposal_id"], p["block_revision"], "c", state())
    await app.activate_for_new_run(state("first"))
    block = store.snapshot()["blocks"][0]
    p2 = store.propose(block["block_id"], block["revision"], {"research.goal": "another"}, "p2")
    await app.confirm(p2["proposal_id"], p2["block_revision"], "c2", state("first"))
    monkeypatch.setattr(owners.registry.get("orchestrator_agent"), "apply_setup",
                        lambda *args: {"status": "applied"})
    result = await app.activate_for_new_run(state("second"))
    assert result["blocks"][0]["application_status"] == "rejected"
    assert result["blocks"][0]["effective_values"] == {}
