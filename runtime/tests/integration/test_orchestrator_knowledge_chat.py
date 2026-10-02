"""Read-only ORC knowledge path exercised through the real planning entrypoint."""
import json
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest_plugins = ("test_orchestrator_setup_loop",)


@pytest.mark.asyncio
async def test_credential_memory_chat_refused_before_any_model_or_transcript(actual_controller, monkeypatch):
    controller, guard = actual_controller
    prompts = _install_question_transport(monkeypatch)
    secret = 'sk-' + 'syntheticfixture' * 3
    result = await controller.planning_message(message='Remember my API key is ' + secret,
                                               session_id=controller._planning_session_id)
    assert result['ok'] is False
    assert prompts == []
    assert secret not in str(result)
    assert secret not in str(controller._planning_messages)
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
async def test_public_chat_memory_read_edit_forget_are_exact_confirmed_and_non_actuating(actual_controller, monkeypatch, tmp_path):
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal
    controller, guard = actual_controller
    service = KnowledgeContextService(tmp_path)
    principal = KnowledgePrincipal('synthetic-management')
    controller._deps.agent_context.knowledge_service = service
    controller._deps.agent_context.knowledge_principal = principal
    prompts = _install_question_transport(monkeypatch)
    controller._bind_planning_session(controller._planning_session_id)
    controller._ensure_planning_intro(); controller.planning_snapshot()
    before = controller._setup_store().snapshot()
    import app.bootstrap
    monkeypatch.setattr(app.bootstrap, 'load_runtime', lambda: controller)
    api = importlib.import_module('app.main'); monkeypatch.setattr(api, 'controller', controller)
    async def chat(message):
        return await api.post_planning_message(api.PlanningMessageRequest(message=message, session_id=controller._planning_session_id))
    row = service.memory.command(principal, action='propose', payload={'kind': 'preference',
        'content': 'Original', 'source_refs': ['synthetic:management'], 'scope': {'kind': 'user'}}, idempotency_key='original')
    rid = row['record_id']
    read = await chat(f'Read memory {rid}')
    assert read['memory_records'][0]['content'] == 'Original'
    assert (await chat('Show memories'))['memory_records'][0]['record_id'] == rid
    edited = await chat(f'Edit memory {rid} revision 1: Revised')
    assert edited['memory_pending_command']['expected_revision'] == 1
    assert service.memory.read(principal, rid)['content'] == 'Original'
    assert (await chat(f'Confirm edit memory {rid} revision 2'))['ok'] is False
    assert (await chat(f'Confirm edit memory {rid} revision 1'))['memory_receipt']['revision'] == 2
    forgotten = await chat(f'Forget memory {rid} revision 2')
    assert forgotten['memory_pending_command']['action'] == 'forget'
    assert service.memory.read(principal, rid)['status'] != 'deleted'
    assert (await chat(f'Confirm forget memory {rid} revision 2'))['memory_receipt']['status'] == 'deleted'
    assert prompts == []
    assert controller._setup_store().snapshot() == before
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', ['this session', 'this project'])
async def test_unresolvable_narrow_memory_scope_asks_without_user_scope_candidate(actual_controller, monkeypatch, tmp_path, scope):
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal
    controller, guard = actual_controller
    service = KnowledgeContextService(tmp_path)
    principal = KnowledgePrincipal('synthetic-scope')
    controller._deps.agent_context.knowledge_service = service
    controller._deps.agent_context.knowledge_principal = principal
    _install_question_transport(monkeypatch)
    result = await controller.planning_message(message=f'Remember for {scope}: concise replies', session_id=controller._planning_session_id)
    assert service.memory.count(principal) == 0
    assert result['memory_receipt']['status'] == 'clarification_required'
    assert 'scope' in result['answer'].lower()
    assert guard.physical_call_count == 0


def _install_question_transport(monkeypatch, *, answer="The Design Agent evaluates candidate suitability.", owner_only=False,
                                on_answer=None):
    prompts = []
    async def complete(self, task_type, prompt, **kwargs):
        prompts.append((task_type, prompt))
        packet = json.loads(prompt)
        if packet.get("operation") == "classify_chat_request":
            return SimpleNamespace(text=json.dumps({"intent": "question", "reason": "read-only question", "pending_id": None}), model="synthetic", raw={})
        if packet.get("operation") == "answer_grounded_question":
            if on_answer is not None:
                on_answer()
            citations = [] if owner_only else [item["citation_id"] for item in packet["reference_only"]["items"][:1]]
            owners = [packet["owner_readbacks"][0]["owner"]] if owner_only and packet["owner_readbacks"] else []
            return SimpleNamespace(text=json.dumps({"answer": answer, "citation_ids": citations, "owner_readback_owners": owners}), model="synthetic", raw={})
        raise AssertionError(f"unexpected model decision: {task_type}")
    from agents.base_agent import AgentContext
    monkeypatch.setattr(AgentContext, "complete", complete)
    return prompts


@pytest.mark.asyncio
async def test_question_returns_wiki_sources_without_changing_setup_or_starting_devices(actual_controller, monkeypatch):
    """Would fail if a question were routed into legacy setup/run planning instead of the read-only branch."""
    controller, guard = actual_controller
    prompts = _install_question_transport(monkeypatch)
    # Normal planning-session bootstrap is outside the question branch.
    controller._bind_planning_session(controller._planning_session_id)
    controller._ensure_planning_intro()
    setup_before = controller._setup_store().snapshot()
    controller.planning_snapshot()  # materializes existing read-only setup display blocks
    setup_before = controller._setup_store().snapshot()
    before = controller._planning_intake_scope()
    result = await controller.planning_message(message="What does the Design Agent do?", session_id=controller._planning_session_id)

    assert result["ok"] is True
    assert result.get("sources"), result
    assert result["citation_metadata"]["authority"] == "reference_only"
    assert result["knowledge_delivery"]["status"] == "inline_unpersisted"
    assert controller._planning_intake_scope() == before
    assert controller._setup_store().snapshot() == setup_before
    assert guard.physical_call_count == 0
    assert [kind for kind, _ in prompts] == ["orchestrator_plan", "orchestrator_plan"]
    assert [source["citation_id"] for source in result["sources"]] == result["knowledge_delivery"]["used_citation_ids"]
    assert result["sources"][0]["title"]
    assert result["sources"][0]["revision"]
    assert isinstance(result['sources'][0]['revision'], (str, int))
    visible = result["session"]["messages"][-1]
    assert result["sources"][0]["citation_id"] in visible["knowledge_delivery"]["citation_ids"]
    assert visible["citation_metadata"]["revision"]
    assert visible["sources"][0]["title"] == result["sources"][0]["title"]
    compact = next(event["payload"]["latest"] for event in reversed(controller.recent_events())
                   if event.get("payload", {}).get("latest", {}).get("message_id") == visible["message_id"])
    assert "knowledge_delivery" in controller._planning_messages[-1], controller._planning_messages[-1]
    assert "knowledge_delivery" in compact, compact
    assert compact["knowledge_delivery"]["citation_ids"]
    # The compact event path must retain the same bound marker for a user
    # question, so browser persistence policy need not fetch the full transcript.
    private_user = {"role": "operator", "content": "private question", "knowledge_request": True,
                    "citation_metadata": {"authority": "reference_only", "scope_ref": "private:fixture", "revision": "7"}}
    user_event = controller._compact_event_payload_for_display({"latest": private_user})["latest"]
    assert user_event["knowledge_request"] is True
    assert user_event["citation_metadata"]["scope_ref"] == "private:fixture"
    assert "content" not in compact["sources"][0]


def test_knowledge_bound_event_buffer_omits_private_content_but_keeps_ordinary_event_summary(actual_controller):
    """Would fail if SSE/recent-event caching retained a question or answer's private text."""
    controller, _ = actual_controller
    private_user = {"role": "operator", "content": "PRIVATE_USER_REQUEST", "knowledge_request": True,
                    "citation_metadata": {"authority": "reference_only", "scope_ref": "private:fixture", "revision": "7"}}
    private_answer = {"role": "orchestrator", "content": "PRIVATE_DERIVED_ANSWER",
                      "knowledge_delivery": {"status": "used", "stage": "used", "citation_ids": ["private:one"]},
                      "memory_receipt": {"status": "candidate", "record_id": "memory-one", "revision": 1}}

    user_latest = controller._compact_event_for_buffer({"type": "user_reply", "payload": {"latest": private_user}})["payload"]["latest"]
    answer_latest = controller._compact_event_for_buffer({"type": "agent_reply", "payload": {"latest": private_answer}})["payload"]["latest"]
    ordinary_latest = controller._compact_event_for_buffer({"type": "agent_reply", "payload": {
        "latest": {"role": "orchestrator", "content": "ordinary event summary"}}})["payload"]["latest"]

    assert "content" not in user_latest and "PRIVATE_USER_REQUEST" not in str(user_latest)
    assert "content" not in answer_latest and "PRIVATE_DERIVED_ANSWER" not in str(answer_latest)
    assert user_latest["knowledge_request"] is True
    assert answer_latest["memory_receipt"]["record_id"] == "memory-one"
    assert ordinary_latest["content"] == "ordinary event summary"


@pytest.mark.asyncio
async def test_question_scope_switch_does_not_append_private_question_to_new_transcript(actual_controller, monkeypatch):
    """A session change during the answer await must leave the new transcript untouched."""
    controller, guard = actual_controller
    old_session = controller._planning_session_id
    _install_question_transport(monkeypatch, on_answer=controller._reset_planning_transcript)

    result = await controller.planning_message(message="What does the Design Agent do?", session_id=old_session)

    assert result["ok"] is False
    assert controller._planning_session_id != old_session
    assert controller.planning_snapshot()["messages"] == []
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
async def test_no_match_still_reaches_grounded_question_transport(actual_controller, monkeypatch, tmp_path):
    """Would fail if no-match skipped the actual ORC answer boundary."""
    controller, guard = actual_controller
    from knowledge.context_service import KnowledgeContextService
    controller._deps.agent_context.knowledge_service = KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path)
    prompts = _install_question_transport(monkeypatch, answer="No reviewed reference matches this term.")
    controller._bind_planning_session(controller._planning_session_id); controller._ensure_planning_intro(); controller.planning_snapshot()
    result = await controller.planning_message(message="nonexistenttokenonly", session_id=controller._planning_session_id)
    packet = json.loads(prompts[-1][1])
    assert packet["operation"] == "answer_grounded_question"
    assert packet["reference_only"]["diagnostics"]["no_match"] is True
    assert result["sources"] == [] and result["knowledge_delivery"]["stage"] == "no_match"
    assert result["answer"].startswith("I can’t provide a grounded answer")
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
async def test_current_state_answer_accepts_only_valid_owner_readback_basis(actual_controller, monkeypatch):
    """Would fail if an empty citation list could authorize an answer without a listed owner readback."""
    controller, guard = actual_controller
    _install_question_transport(monkeypatch, answer="Current owner configuration is available.", owner_only=True)
    controller._bind_planning_session(controller._planning_session_id); controller._ensure_planning_intro(); controller.planning_snapshot()
    result = await controller.planning_message(message="What is the current status?", session_id=controller._planning_session_id)
    assert result["answer"] == "Current owner configuration is available."
    assert result["sources"] == []
    assert guard.physical_call_count == 0


@pytest.mark.asyncio
async def test_korean_explicit_memory_is_pending_then_confirmed_memory_enters_trusted_orc_context(actual_controller, monkeypatch, tmp_path):
    """Would fail if Korean memory intent were setup/run intent, or confirmed private memory were omitted."""
    controller, _ = actual_controller
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal
    service = KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path)
    principal = KnowledgePrincipal(subject_id="synthetic-user", local_model_consent=True, remote_model_consent=True)
    controller._deps.agent_context.knowledge_service = service
    controller._deps.agent_context.knowledge_principal = principal
    prompts = _install_question_transport(monkeypatch, answer="I will use the confirmed preference.")
    controller._bind_planning_session(controller._planning_session_id); controller._ensure_planning_intro(); controller.planning_snapshot()
    proposed = await controller.planning_message(message="기억해 간결하게 설명해", session_id=controller._planning_session_id)
    assert proposed["memory_receipt"]["status"] == "candidate"
    assert proposed["memory_pending_command"]["action"] == "confirm"
    visible_candidate = proposed["session"]["messages"][-1]
    assert visible_candidate["memory_receipt"] == {key: proposed["memory_receipt"][key]
                                                    for key in ("status", "record_id", "revision", "kind")
                                                    if key in proposed["memory_receipt"]}
    assert visible_candidate["memory_pending_command"] == {key: proposed["memory_pending_command"][key]
                                                             for key in ("action", "target_id", "expected_revision", "endpoint")}
    receipt = proposed["memory_receipt"]
    service.memory.command(principal, action="confirm", target_id=receipt["record_id"], expected_revision=receipt["revision"], payload={}, idempotency_key="confirm-synthetic")
    result = await controller.planning_message(message="간결하게 설명해줘", session_id=controller._planning_session_id)
    packets = [json.loads(prompt) for _, prompt in prompts if json.loads(prompt).get("operation") == "answer_grounded_question"]
    assert any(item.get("corpus") == "private_memory" for item in packets[-1]["reference_only"]["items"])
    assert result["memory_receipt"] is None


@pytest.mark.asyncio
async def test_confirmed_private_memory_is_not_starved_by_multiple_wiki_hits_in_actual_orc_prompt(actual_controller, monkeypatch, tmp_path):
    """Would fail if Wiki-first limit three dropped a matching confirmed private record."""
    controller, _ = actual_controller
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal
    service = KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path)
    principal = KnowledgePrincipal(subject_id="synthetic-user", local_model_consent=True, remote_model_consent=True)
    controller._deps.agent_context.knowledge_service = service; controller._deps.agent_context.knowledge_principal = principal
    receipt = service.memory.command(principal, action="propose", payload={"kind": "preference", "content": "Agent concise preference",
        "source_refs": ["synthetic:memory"], "scope": {"kind": "user"}, "explicit": True}, idempotency_key="starve-propose")
    service.memory.command(principal, action="confirm", target_id=receipt["record_id"], expected_revision=receipt["revision"], payload={}, idempotency_key="starve-confirm")
    prompts = _install_question_transport(monkeypatch)
    controller._bind_planning_session(controller._planning_session_id); controller._ensure_planning_intro(); controller.planning_snapshot()
    await controller.planning_message(message="Agent", session_id=controller._planning_session_id)
    packet = [json.loads(prompt) for _, prompt in prompts if json.loads(prompt).get("operation") == "answer_grounded_question"][-1]
    assert sum(item.get("corpus") == "ax4lab_wiki" for item in packet["reference_only"]["items"]) == 2
    assert any(item.get("record_id") == receipt["record_id"] for item in packet["reference_only"]["items"])


@pytest.mark.asyncio
async def test_public_planning_route_and_workspace_confirm_share_memory_then_recall_without_setup_effects(actual_controller, monkeypatch, tmp_path):
    """The API planning path and v2 confirmation share injected memory, never setup authority."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal
    from knowledge.workspace_api import install_workspace_routes, trusted_local_profile_resolver

    controller, guard = actual_controller
    service = KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path / "knowledge")
    principal = KnowledgePrincipal(subject_id="workspace-synthetic", local_model_consent=True, remote_model_consent=True)
    controller._deps.agent_context.knowledge_service = service
    controller._deps.agent_context.knowledge_principal = principal
    prompts = _install_question_transport(monkeypatch, answer="I will use the confirmed preference.")
    controller._bind_planning_session(controller._planning_session_id)
    controller._ensure_planning_intro()
    controller.planning_snapshot()  # materialize the pre-existing read-only setup projection
    before_scope = controller._planning_intake_scope()
    before_setup = controller._setup_store().snapshot()

    import app.bootstrap
    monkeypatch.setattr(app.bootstrap, "load_runtime", lambda: controller)
    api = importlib.import_module("app.main")
    monkeypatch.setattr(api, "controller", controller)
    proposed = await api.post_planning_message(api.PlanningMessageRequest(
        message="기억해 간결하게 설명해", session_id=controller._planning_session_id))
    assert proposed["memory_receipt"]["status"] == "candidate"
    live_page = await api.get_planning_messages(session_id=controller._planning_session_id)
    live_snapshot = await api.get_planning_session(session_id=controller._planning_session_id)
    live_candidate = next(message for message in reversed(live_page["messages"])
                          if message.get("memory_receipt"))
    snapshot_candidate = next(message for message in reversed(live_snapshot["messages"])
                              if message.get("memory_receipt"))
    assert live_candidate["memory_receipt"] == snapshot_candidate["memory_receipt"]
    assert live_candidate["memory_pending_command"] == snapshot_candidate["memory_pending_command"]

    workspace = FastAPI()
    install_workspace_routes(workspace, service_factory=lambda: service,
                             principal_resolver=trusted_local_profile_resolver(principal),
                             private_mutation_origins=frozenset({"https://workspace.test"}))
    with TestClient(workspace) as client:
        candidate_read = client.post("/api/knowledge/memory/read", json={
            "record_id": live_candidate["memory_receipt"]["record_id"]})
        assert candidate_read.status_code == 200
        assert candidate_read.json()["items"][0]["record_id"] == live_candidate["memory_receipt"]["record_id"]
        assert candidate_read.json()["revision"] == str(live_candidate["memory_receipt"]["revision"])
        confirmed = client.post("/api/knowledge/memory/commands", headers={"Origin": "https://workspace.test"}, json={
            "action": "confirm", "target_id": live_candidate["memory_receipt"]["record_id"],
            "expected_revision": live_candidate["memory_receipt"]["revision"],
            "idempotency_key": "workspace-confirm", "payload": {},
        })
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "active"
        readback = client.post("/api/knowledge/memory/read", json={"record_id": live_candidate["memory_receipt"]["record_id"]})
        assert readback.status_code == 200
        assert readback.json()["revision"] == str(confirmed.json()["revision"])
        assert readback.json()["items"][0]["status"] == "active"

    recalled = await api.post_planning_message(api.PlanningMessageRequest(
        message="간결하게 설명해줘", session_id=controller._planning_session_id))
    packets = [json.loads(prompt) for _, prompt in prompts if json.loads(prompt).get("operation") == "answer_grounded_question"]
    assert any(item.get("record_id") == proposed["memory_receipt"]["record_id"]
               for item in packets[-1]["reference_only"]["items"])
    assert recalled["ok"] is True
    assert controller._planning_intake_scope() == before_scope
    assert controller._setup_store().snapshot() == before_setup
    assert guard.physical_call_count == 0
