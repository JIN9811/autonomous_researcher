"""Behavioral contracts for the scoped Wiki and private-memory facade."""
from __future__ import annotations

from pathlib import Path
import json

import pytest


@pytest.mark.parametrize('count', [1, 3])
def test_full_wiki_page_does_not_consume_unreturned_private_match(service, alice, count):
    ids = set()
    for index in range(count):
        row = service.memory.command(alice, action='propose', payload={
            'kind': 'preference', 'content': 'Design Agent', 'source_refs': ['synthetic:paging'],
            'scope': {'kind': 'user'}}, idempotency_key=f'p{index}')
        service.memory.command(alice, action='confirm', target_id=row['record_id'], expected_revision=1,
                               payload={}, idempotency_key=f'c{index}')
        ids.add(row['record_id'])
    cursor, seen = '', []
    for _ in range(30):
        page = service.query(alice, 'Design Agent', consumer='test', limit=1, cursor=cursor,
                             filters={'corpora': ['ax4lab_wiki', 'private_memory']})
        seen.extend(item['record_id'] for item in page['items'])
        cursor = page['next_cursor']
        if not cursor: break
    assert ids <= set(seen)
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize('action', ['propose', 'edit'])
def test_memory_rejects_synthetic_credentials_without_receipt_or_storage(service, alice, action):
    row = service.memory.command(alice, action='propose', payload={
        'kind': 'preference', 'content': 'Safe text', 'source_refs': ['synthetic:guard'],
        'scope': {'kind': 'user'}}, idempotency_key='safe')
    before = service.memory.path.read_bytes()
    secret = 'sk-' + 'syntheticfixture' * 3
    payload = {'content': secret}
    if action == 'propose': payload.update(kind='preference', source_refs=['synthetic:guard'], scope={'kind': 'user'})
    with pytest.raises(ValueError) as error:
        service.memory.command(alice, action=action, payload=payload, target_id=row['record_id'],
                               expected_revision=1, idempotency_key='blocked')
    assert secret not in str(error.value)
    assert service.memory.path.read_bytes() == before


@pytest.fixture
def service(tmp_path: Path):
    from knowledge.context_service import KnowledgeContextService

    return KnowledgeContextService(tmp_path)


@pytest.fixture
def alice():
    from knowledge.context_service import KnowledgePrincipal

    return KnowledgePrincipal("alice", project_ids=frozenset({"project-a"}),
                              session_ids=frozenset({"session-a"}), run_ids=frozenset({"run-a"}))


@pytest.fixture
def bob():
    from knowledge.context_service import KnowledgePrincipal

    return KnowledgePrincipal("bob", project_ids=frozenset({"project-b"}))


def test_wiki_cold_start_answers_korean_platform_query_from_checked_seed(service):
    result = service.wiki.query("플랫폼 에이전트 역할", limit=10)

    assert result["status"] == "ok"
    assert result["items"]
    assert any(item["topic_id"] == "platform-overview" for item in result["items"])
    assert all(item["freshness"] == "fresh" for item in result["items"])


@pytest.mark.parametrize(("query", "topic_id"), [
    ("매니퓰레이션 역할", "manipulation-role"),
    ("놀리지 지식", "knowledge-role"),
    ("Design Agent", "design-role"),
])
def test_wiki_role_aliases_rank_the_requested_role_first(service, query, topic_id):
    result = service.wiki.query(query, limit=3)
    assert result["items"][0]["topic_id"] == topic_id
    assert service.wiki.query("zzqxunknown", limit=3)["items"] == []


@pytest.mark.parametrize(("query", "topic_id"), [
    ("디자인 에이전트의 역할은 무엇인가요?", "design-role"),
    ("스페시먼 에이전트는 무엇을 하나요?", "specimen-role"),
    ("비전 에이전트가 맡은 역할은?", "vision-role"),
    ("매니퓰레이션 에이전트의 역할은?", "manipulation-role"),
    ("장비 에이전트는 무엇을 하나요?", "equipment-role"),
    ("분석 에이전트의 역할은?", "analysis-role"),
    ("가디언 에이전트가 맡은 역할은?", "guardian-role"),
    ("오케스트레이터 에이전트의 역할은?", "orchestrator-role"),
    ("놀리지 에이전트는 무엇을 하나요?", "knowledge-role"),
])
def test_wiki_korean_role_sentences_strip_only_known_alias_particles(service, query, topic_id):
    result = service.wiki.query(query, limit=3)

    assert result["items"]
    assert result["items"][0]["topic_id"] == topic_id
    assert service.wiki.query("zzqxunknown", limit=3)["items"] == []


def test_private_memory_isolated_and_unknown_project_scope_is_rejected(service, alice, bob):
    receipt = service.memory.command(alice, action="propose", payload={
        "kind": "preference", "content": "Use concise explanations", "source_refs": ["synthetic:one"],
        "scope": {"kind": "project", "project_id": "project-a"},
    }, idempotency_key="proposal-1")

    assert service.memory.read(None, receipt["record_id"]) is None
    assert service.memory.read(bob, receipt["record_id"]) is None
    assert service.memory.query(bob, "concise", limit=10)["items"] == []
    with pytest.raises(PermissionError):
        service.memory.command(alice, action="propose", payload={
            "kind": "decision", "content": "wrong scope", "source_refs": ["synthetic:two"],
            "scope": {"kind": "project", "project_id": "project-b"},
        }, idempotency_key="proposal-wrong-scope")


def test_memory_lifecycle_idempotency_conflict_and_forget_erases_private_content(service, alice):
    proposed = service.memory.command(alice, action="propose", payload={
        "kind": "preference", "content": "Remember the cobalt sample", "source_refs": ["synthetic:sample"],
        "scope": {"kind": "user"},
    }, idempotency_key="proposal-2")
    repeated = service.memory.command(alice, action="propose", payload={
        "kind": "preference", "content": "Remember the cobalt sample", "source_refs": ["synthetic:sample"],
        "scope": {"kind": "user"},
    }, idempotency_key="proposal-2")
    assert repeated == proposed and "content" not in proposed
    with pytest.raises(ValueError, match="idempotency"):
        service.memory.command(alice, action="propose", payload={
            "kind": "preference", "content": "different", "source_refs": ["synthetic:sample"],
            "scope": {"kind": "user"},
        }, idempotency_key="proposal-2")

    active = service.memory.command(alice, action="confirm", target_id=proposed["record_id"],
        expected_revision=1, payload={}, idempotency_key="confirm-2")
    with pytest.raises(ValueError, match="revision"):
        service.memory.command(alice, action="edit", target_id=proposed["record_id"],
            expected_revision=1, payload={"content": "outdated edit"}, idempotency_key="edit-stale")
    edited = service.memory.command(alice, action="edit", target_id=proposed["record_id"],
        expected_revision=active["revision"], payload={"content": "Remember cobalt sample only"}, idempotency_key="edit-2")
    expired = service.memory.command(alice, action="expire", target_id=proposed["record_id"],
        expected_revision=edited["revision"], payload={}, idempotency_key="expire-2")
    assert expired["status"] == "expired"
    forgotten = service.memory.command(alice, action="forget", target_id=proposed["record_id"],
        expected_revision=expired["revision"], payload={}, idempotency_key="forget-2")
    assert forgotten["status"] == "deleted"
    assert service.memory.read(alice, proposed["record_id"]) is None
    state = json.loads((service.data_root / "private" / "private_memory_v2.json").read_text(encoding="utf-8"))
    assert "cobalt" not in str(state).lower()
    with pytest.raises(ValueError, match="tombstoned"):
        service.memory.command(alice, action="propose", payload={
            "kind": "preference", "content": "auto reingested cobalt", "source_refs": ["synthetic:sample"],
            "scope": {"kind": "user"}, "automatic": True,
        }, idempotency_key="reingest-2")


def test_delivery_records_retrieved_without_claiming_model_delivery(service, alice):
    pack = service.query(alice, "platform", consumer="orchestrator", limit=4)
    retrieved = service.delivery.record_retrieved(alice, request_id="request-1", consumer_binding="orchestrator",
                                                  context_pack=pack)
    assert retrieved["stage"] == "retrieved"
    assert service.delivery.query(alice, "", limit=10)["items"][0]["stage"] == "retrieved"
    delivered = service.delivery.record_delivered(alice, retrieved["receipt_id"])
    used = service.delivery.record_used(alice, delivered["receipt_id"], citation_ids=[])
    assert used["stage"] == "excluded"


def test_delivery_persists_only_the_citations_that_crossed_the_model_boundary(service, alice):
    pack = {"scope_ref": "scoped:alice", "revision": "fixture", "diagnostics": {"no_match": False},
            "items": [{"citation_id": "wiki:first"}, {"citation_id": "wiki:second"}]}
    retrieved = service.delivery.record_retrieved(alice, request_id="partial-delivery", consumer_binding="orchestrator",
                                                  context_pack=pack)
    presented = [pack["items"][0]["citation_id"]]

    delivered = service.delivery.record_delivered(alice, retrieved["receipt_id"], citation_ids=presented)

    assert delivered["citation_ids"] == [item["citation_id"] for item in pack["items"]]
    assert delivered["delivered_citation_ids"] == presented
    with pytest.raises(ValueError, match="delivered"):
        service.delivery.record_used(alice, delivered["receipt_id"], citation_ids=[pack["items"][-1]["citation_id"]])


def test_delivery_records_trusted_no_match_without_conflating_it_with_exclusion(service, alice):
    pack = service.query(alice, "nonexistenttokenonly", consumer="orchestrator", limit=4)

    receipt = service.delivery.record_retrieved(alice, request_id="no-match", consumer_binding="orchestrator",
                                                context_pack=pack)

    assert pack["diagnostics"]["no_match"] is True
    assert receipt["stage"] == "no_match"
    assert receipt["citation_ids"] == []
    with pytest.raises(ValueError, match="transition"):
        service.delivery.record_delivered(alice, receipt["receipt_id"])


def test_private_cursor_and_context_cannot_leak_deleted_or_out_of_snapshot_records(service, alice):
    first = service.memory.command(alice, action="propose", payload={
        "kind": "decision", "content": "first synthetic decision", "source_refs": ["synthetic:cursor-one"],
        "scope": {"kind": "project", "project_id": "project-a"},
    }, idempotency_key="cursor-one")
    service.memory.command(alice, action="confirm", target_id=first["record_id"], expected_revision=1,
                           payload={}, idempotency_key="cursor-confirm")
    second = service.memory.command(alice, action="propose", payload={
        "kind": "decision", "content": "second synthetic decision", "source_refs": ["synthetic:cursor-two"],
        "scope": {"kind": "project", "project_id": "project-a"},
    }, idempotency_key="cursor-two")
    service.memory.command(alice, action="confirm", target_id=second["record_id"], expected_revision=1,
                           payload={}, idempotency_key="cursor-confirm-two")
    page = service.memory.query(alice, "synthetic", limit=1)
    assert page["next_cursor"]
    from knowledge.context_service import KnowledgePrincipal
    narrower = KnowledgePrincipal("alice")
    with pytest.raises(ValueError, match="cursor"):
        service.memory.query(narrower, "synthetic", cursor=page["next_cursor"], limit=1)
    service.memory.command(alice, action="forget", target_id=first["record_id"], expected_revision=2,
                           payload={}, idempotency_key="cursor-forget")
    service.memory.command(alice, action="forget", target_id=second["record_id"], expected_revision=2,
                           payload={}, idempotency_key="cursor-forget-two")
    assert service.memory.query(alice, "synthetic", limit=10)["items"] == []
    assert service.query(alice, "synthetic", consumer="orchestrator", filters={"corpora": ["private_memory"]})["items"] == []


def test_context_respects_exact_corpora_and_private_model_consent(service, alice):
    assert service.query(alice, "platform", consumer="orchestrator", filters={"corpora": ["private_memory"]})["items"] == []
    service.memory.command(alice, action="propose", payload={
        "kind": "preference", "content": "private model consent check", "source_refs": ["synthetic:consent"],
        "scope": {"kind": "user"},
    }, idempotency_key="consent-proposal")
    state = json.loads((service.data_root / "private" / "private_memory_v2.json").read_text(encoding="utf-8"))
    service.memory.command(alice, action="confirm", target_id=list(state["records"])[0],
                           expected_revision=1, payload={}, idempotency_key="consent-confirm")
    with pytest.raises(PermissionError, match="consent"):
        service.query(alice, "consent", consumer="orchestrator", filters={"corpora": ["private_memory"]}, model_target="remote")


def test_wiki_context_supplies_bounded_content_not_just_catalog_metadata(service):
    pack = service.query(None, "platform", consumer="orchestrator")
    assert pack["items"] and "AX4LAB" in pack["items"][0]["content"]
    assert pack["items"][0]["freshness"] == "fresh"


def test_session_memory_requires_expiry_and_expired_active_records_do_not_enter_context(service, alice):
    with pytest.raises(ValueError, match="expires_at"):
        service.memory.command(alice, action="propose", payload={
            "kind": "instruction", "content": "temporary", "source_refs": ["synthetic:ttl"],
            "scope": {"kind": "session", "session_id": "session-a"},
        }, idempotency_key="ttl-missing")
    receipt = service.memory.command(alice, action="propose", payload={
        "kind": "instruction", "content": "expired temporary", "source_refs": ["synthetic:ttl"],
        "scope": {"kind": "session", "session_id": "session-a"}, "expires_at": "2000-01-01T00:00:00+00:00",
    }, idempotency_key="ttl-expired")
    service.memory.command(alice, action="confirm", target_id=receipt["record_id"], expected_revision=1,
                           payload={}, idempotency_key="ttl-confirm")
    pack = service.query(alice, "expired", consumer="orchestrator", filters={"corpora": ["private_memory"]})
    assert pack["items"] == []


def test_delivery_cursor_is_scope_bound_and_terminal_stage_never_regresses(service, alice):
    pack = service.query(alice, "platform", consumer="orchestrator", limit=1)
    first = service.delivery.record_retrieved(alice, request_id="delivery-one", consumer_binding="orchestrator", context_pack=pack,
                                               run_id="run-a", loop_id="loop-1", attempt_id="attempt-1")
    service.delivery.record_retrieved(alice, request_id="delivery-two", consumer_binding="orchestrator", context_pack=pack)
    page = service.delivery.query(alice, "delivery", limit=1)
    from knowledge.context_service import KnowledgePrincipal
    with pytest.raises(ValueError, match="cursor"):
        service.delivery.query(KnowledgePrincipal("alice"), "delivery", cursor=page["next_cursor"], limit=1)
    delivered = service.delivery.record_delivered(alice, first["receipt_id"])
    terminal = service.delivery.record_used(alice, delivered["receipt_id"], citation_ids=[])
    assert terminal["stage"] == "excluded" and terminal["run_id"] == "run-a"
    with pytest.raises(ValueError, match="transition"):
        service.delivery.record_delivered(alice, first["receipt_id"])


def test_context_rejects_candidate_filter_and_paginates_mixed_corpora_without_repeating(service, alice):
    from knowledge.context_service import KnowledgePrincipal
    model_alice = KnowledgePrincipal("alice", local_model_consent=True)
    candidate = service.memory.command(alice, action="propose", payload={
        "kind": "preference", "content": "candidate must never reach a model", "source_refs": ["synthetic:candidate"],
        "scope": {"kind": "user"},
    }, idempotency_key="candidate-context")
    with pytest.raises(ValueError, match="active"):
        service.query(model_alice, "candidate", consumer="orchestrator", filters={"corpora": ["private_memory"], "memory": {"status": "candidate"}}, model_target="local")
    service.memory.command(alice, action="confirm", target_id=candidate["record_id"], expected_revision=1,
                           payload={}, idempotency_key="candidate-confirm")
    first = service.query(alice, "", consumer="orchestrator", filters={"corpora": ["ax4lab_wiki", "private_memory"]}, limit=1)
    assert first["next_cursor"]
    second = service.query(alice, "", consumer="orchestrator", filters={"corpora": ["ax4lab_wiki", "private_memory"]}, cursor=first["next_cursor"], limit=100)
    assert {item["citation_id"] for item in first["items"]}.isdisjoint({item["citation_id"] for item in second["items"]})
    with pytest.raises(ValueError, match="corpus"):
        service.query(alice, "", consumer="orchestrator", filters={"corpora": []})


def test_delivery_receipt_requires_original_project_and_session_scope(service):
    from knowledge.context_service import KnowledgePrincipal
    project_a = KnowledgePrincipal("alice", project_ids=frozenset({"project-a"}), session_ids=frozenset({"session-a"}))
    project_b = KnowledgePrincipal("alice", project_ids=frozenset({"project-b"}), session_ids=frozenset({"session-b"}))
    receipt = service.delivery.record_retrieved(project_a, request_id="scope-receipt", consumer_binding="orchestrator",
                                                 context_pack={"items": [{"citation_id": "mem-synthetic"}], "scope_ref": "private", "revision": "1"})
    assert service.delivery.read(project_b, receipt["receipt_id"]) is None
    assert service.delivery.query(project_b, "scope-receipt", limit=10)["items"] == []


def test_wiki_revision_changes_with_source_freshness_and_long_pages_remain_queryable(tmp_path):
    from knowledge.wiki import WikiCatalog
    source = tmp_path / "source.md"; source.write_text("reference one", encoding="utf-8")
    wiki_root = tmp_path / "docs" / "knowledge" / "wiki"; wiki_root.mkdir(parents=True)
    digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    page = wiki_root / "long.md"
    page.write_text("---\n" + json.dumps({"topic_id": "long-page", "owner": "test", "source_refs": ["source.md"],
        "source_revision": {"source.md": digest}, "verified_at": "2026-01-01T00:00:00+00:00", "applicability": "test", "status": "reviewed"}) +
        "\n---\n# Long page\n" + "usefulterm " + ("filler " * 1_000), encoding="utf-8")
    wiki = WikiCatalog(tmp_path)
    before = wiki.query("usefulterm")
    assert before["items"] and before["items"][0]["freshness"] == "fresh"
    source.write_text("reference two", encoding="utf-8")
    after = wiki.query("usefulterm")
    assert after["revision"] != before["revision"] and after["items"][0]["freshness"] == "stale"


def test_private_context_cursor_reaches_more_than_one_thousand_records_without_collecting_all(service, alice):
    root = service.data_root / "private"
    root.mkdir(parents=True, exist_ok=True)
    records = {}
    for index in range(1_001):
        record_id = f"mem-{index:032x}"
        records[record_id] = {"record_id": record_id, "kind": "preference", "subject_id": "alice", "scope": {"kind": "user"},
                              "content": f"bulk-token {index}", "source_refs": ["synthetic:bulk"], "confirmation": "confirmed",
                              "status": "active", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
                              "expires_at": "", "revision": 1, "history": []}
    (root / "private_memory_v2.json").write_text(json.dumps({"records": records, "idempotency": {}, "tombstones": {}}), encoding="utf-8")
    cursor = ""; seen = set()
    for _ in range(11):
        page = service.query(alice, "bulk-token", consumer="orchestrator", filters={"corpora": ["private_memory"]}, cursor=cursor, limit=100)
        seen.update(item["record_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 1_001 and cursor == ""
