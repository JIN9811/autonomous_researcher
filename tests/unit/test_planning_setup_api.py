"""Chat authorization and next-run setup; external transports are disabled first."""
import asyncio
import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("handoff_no_external")


@pytest.fixture
def controller(tmp_path, handoff_no_external):
    from app.controller import MainController, ControllerDeps
    from agents.registry import AgentRegistry
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.bo_agent import BOAgent
    registry = AgentRegistry()
    registry.register(OrchestratorAgent())
    registry.register(BOAgent())
    async def complete(task, prompt, **kwargs):
        return SimpleNamespace(model="controlled", raw={}, text=json.dumps(
            {"intent": "question", "reason": "Question", "pending_id": None}))
    return MainController(ControllerDeps(agent_registry=registry,
        orchestrator_agent_name="orchestrator_agent",
        agent_context=SimpleNamespace(complete=complete, active_backend="controlled"),
        run_root=tmp_path / "runs", logging_config={}, system_config={}, runtime_profile={}))


@pytest.fixture
def api(controller, monkeypatch, handoff_no_external):
    import app.bootstrap
    monkeypatch.setattr(app.bootstrap, "load_runtime", lambda: controller)
    module = importlib.import_module("app.main")
    monkeypatch.setattr(module, "controller", controller)
    return module


def model(controller, intent, *, mutate=None):
    async def complete(task, prompt, **kwargs):
        try:
            packet = json.loads(prompt)
        except ValueError:
            packet = {}
        if packet.get("operation") == "classify_chat_request":
            if mutate:
                mutate()
            return SimpleNamespace(model="controlled", raw={}, text=json.dumps({
                "intent": intent, "reason": "semantic fixture",
                "pending_id": packet["pending_id"] if intent == "confirm_pending" else None}))
        return SimpleNamespace(model="controlled", raw={}, text="Explanation only.")
    controller._deps.agent_context.complete = complete


def test_chat_context_is_optional_and_explicit(api):
    assert api.PlanningMessageRequest(message="Explain this result").setup_context is None
    edit = api.PlanningMessageRequest(message="Revise the next design", setup_context={"block_id": "b1", "revision": 2})
    assert edit.setup_context == {"block_id": "b1", "revision": 2}


def goal_block(controller):
    setup = controller.planning_snapshot()["state"]["setup"]
    return next(b for b in setup["blocks"] if "research.goal" in b["draft_values"])


def action(controller, block, proposal, **overrides):
    return {"action": "confirm", "proposal_id": proposal["proposal_id"],
        "expected_revision": proposal["block_revision"], "request_id": "confirm-1",
        "session_id": controller._planning_session_id, "target": "next_run", **overrides}


def test_projection_is_canonical_and_click_does_not_execute(controller):
    original = controller._state.active_goal
    first = controller.planning_snapshot(session_id="untrusted-tab")
    second = controller.planning_snapshot(session_id="other-tab")
    assert first["planning_session_id"] == controller._state.active_session_id
    assert second["planning_session_id"] == first["planning_session_id"]
    setup = second["state"]["setup"]
    assert setup["session_id"] == first["planning_session_id"]
    assert setup["projection_id"]
    assert setup["owners"] and all(r["availability"]["status"] == "unknown" for r in setup["owners"])
    assert controller._state.active_goal == original
    assert controller._run_task is None


def test_confirm_stages_next_run_only_and_rejects_stale_or_foreign_scope(controller):
    from orchestrator.experimental_setup import SetupConflict
    block = goal_block(controller)
    store = controller._setup_store()
    proposal = store.propose(block["block_id"], block["revision"], {"research.goal": "next goal"}, "proposal-1")
    original = controller._state.active_goal
    async def run():
        with pytest.raises(PermissionError):
            await controller.planning_setup_action(action(controller, block, proposal, session_id="foreign"))
        with pytest.raises(SetupConflict):
            await controller.planning_setup_action(action(controller, block, proposal, expected_revision=1))
        result = await controller.planning_setup_action(action(controller, block, proposal))
        assert result["ok"] is True
        assert result["setup"]["blocks"][0]["agreement_status"] == "confirmed"
        assert controller._state.active_goal == original
        assert controller._run_task is None
    asyncio.run(run())


@pytest.mark.parametrize("intent,message", [("question", "Should we start design?"),
    ("question", "Do not start design"), ("question", 'Explain "start design"'),
    ("out_of_scope", "Tell me a joke"), ("unclear", "yes")])
@pytest.mark.parametrize("locked", [False, True])
def test_non_actions_never_resume_or_queue(controller, monkeypatch, intent, message, locked):
    model(controller, intent)
    boundary = {"status": "deferred", "task_id": "task-one", "key": "boundary-one", "goal": "goal", "constraints": {}}
    controller._state.run_metadata["orchestrator_planning_boundary"] = deepcopy(boundary)
    async def forbidden(**kwargs):
        pytest.fail("Non-action reached an execution branch")
    monkeypatch.setattr(controller, "_handoff_planning_to_design", forbidden)
    monkeypatch.setattr(controller, "_run_test_mode_planning", forbidden)
    async def run():
        if locked:
            await controller._planning_request_lock.acquire()
        try:
            await controller.planning_message(message=message, constraints={"live_is_running": True,
                "live_runtime_followup_queue_only": True, "orchestrator_action": {"action": "refresh_observation"}})
        finally:
            if locked:
                controller._planning_request_lock.release()
        assert controller._state.run_metadata["orchestrator_planning_boundary"] == boundary
        assert not controller._state.run_metadata.get("operator_followup_queue")
    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["run", "pending", "specimen", "goal"])
def test_delayed_intake_cannot_authorize_replacement_scope(controller, monkeypatch, mutation):
    controller._state.run_metadata["orchestrator_planning_boundary"] = {
        "status": "deferred", "task_id": "one", "key": "one", "goal": "goal", "constraints": {}}
    def change():
        if mutation == "run":
            controller._state.run_id = "replacement"
        elif mutation == "specimen":
            controller._state.current_experiment_spec = {"specimen_id": "replacement"}
        elif mutation == "goal":
            controller._state.active_goal = "replacement goal"
        else:
            controller._state.run_metadata["orchestrator_planning_boundary"]["task_id"] = "two"
    model(controller, "confirm_pending", mutate=change)
    async def forbidden(**kwargs):
        pytest.fail("Stale classification resumed a replacement task")
    monkeypatch.setattr(controller, "_handoff_planning_to_design", forbidden)
    result = asyncio.run(controller.planning_message(message="Please continue"))
    assert result["ok"] is False
    assert not controller._state.run_metadata.get("operator_followup_queue")


def test_setup_edit_uses_real_bounded_proposal_without_design(controller, monkeypatch):
    block = goal_block(controller)
    original = controller._state.active_goal
    async def complete(task, prompt, **kwargs):
        packet = json.loads(prompt)
        if packet["operation"] == "classify_chat_request":
            return SimpleNamespace(model="controlled", raw={}, text=json.dumps({"intent": "change_setup", "reason": "edit", "pending_id": None}))
        assert packet["operation"] == "decide_orchestration"
        return SimpleNamespace(model="controlled", raw={}, text=json.dumps({"tool": "propose_setup_change",
            "arguments": {"block_id": block["block_id"], "revision": block["revision"], "changes": {"research.goal": "new design goal"}},
            "reason": "Requested next-run edit", "evidence_refs": ["chat:request"]}))
    controller._deps.agent_context.complete = complete
    async def forbidden(**kwargs):
        pytest.fail("Setup edit ran Design")
    monkeypatch.setattr(controller, "_handoff_planning_to_design", forbidden)
    result = asyncio.run(controller.planning_message(message="Change next design goal", session_id=controller._planning_session_id,
        setup_context={"block_id": block["block_id"], "revision": block["revision"]}))
    assert result["ok"] is True
    assert result["decision"]["status"] == "proposed"
    changed = controller._setup_store().snapshot()["blocks"][0]
    assert changed["draft_values"] == {"research.goal": "new design goal"}
    assert changed["current_draft_proposal_id"]
    assert changed["confirmed_values"] is None
    assert controller._state.active_goal == original


def test_api_action_http_contract(api, controller):
    import httpx
    block = goal_block(controller)
    proposal = controller._setup_store().propose(block["block_id"], block["revision"], {"research.goal": "next"}, "p")
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
            for overrides, status in [({"session_id": "foreign"}, 403), ({"expected_revision": 1}, 409),
                ({"target": "current_run"}, 422), ({"action": "execute"}, 422), ({"expected_revision": True}, 422)]:
                response = await client.post("/api/planning/setup/actions", json=action(controller, block, proposal, **overrides))
                assert response.status_code == status, response.text
            response = await client.post("/api/planning/setup/actions", json=action(controller, block, proposal))
            assert response.status_code == 200
            assert set(response.json()) == {"ok", "setup", "message"}
    asyncio.run(run())


def test_normalized_owner_values_require_a_second_visible_confirmation(controller):
    block = goal_block(controller)
    store = controller._setup_store()
    proposal = store.propose(block["block_id"], block["revision"], {"research.goal": "  normalized goal  "}, "p")
    async def run():
        first = await controller.planning_setup_action(action(controller, block, proposal))
        changed = first["setup"]["blocks"][0]
        assert changed["draft_values"] == {"research.goal": "normalized goal"}
        assert changed["confirmed_values"] is None
        assert changed["current_draft_proposal_id"] != proposal["proposal_id"]
        second = await controller.planning_setup_action(action(controller, block, {
            "proposal_id": changed["current_draft_proposal_id"], "block_revision": changed["revision"]}, request_id="second-confirm"))
        assert second["setup"]["blocks"][0]["confirmed_values"] == {"research.goal": "normalized goal"}
        assert controller._state.active_goal != "normalized goal"
    asyncio.run(run())


def test_client_running_false_cannot_start_a_parallel_run(controller, monkeypatch):
    model(controller, "start_run")
    async def forbidden(**kwargs):
        pytest.fail("A client display flag started a second run")
    monkeypatch.setattr(controller, "_run_test_mode_planning", forbidden)
    async def run():
        controller._run_task = asyncio.create_task(asyncio.Event().wait())
        try:
            result = await controller.planning_message(message="Start test design", constraints={"live_is_running": False})
            assert result["ok"] is False
        finally:
            controller._run_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await controller._run_task
    asyncio.run(run())


def test_stop_flag_change_during_intake_invalidates_start(controller, monkeypatch):
    model(controller, "start_run", mutate=lambda: setattr(controller._state, "stop_requested", True))
    async def forbidden(**kwargs):
        pytest.fail("Delayed classification ran after STOP")
    monkeypatch.setattr(controller, "_run_test_mode_planning", forbidden)
    result = asyncio.run(controller.planning_message(message="Start test design"))
    assert result["ok"] is False


def test_fresh_gui_session_preserves_old_store_without_reloading_it(controller):
    block = goal_block(controller)
    old_path = controller._planning_transcript_path().parent / "experimental_setup.json"
    old_session = controller._planning_session_id
    old_bytes = old_path.read_bytes()
    snapshot = controller.prepare_live_gui(reset=True)
    assert snapshot["planning_session_id"] != old_session
    assert controller._planning_transcript_path().parent / "experimental_setup.json" != old_path
    assert old_path.read_bytes() == old_bytes
    assert all(b["block_id"] != block["block_id"] for b in snapshot["state"]["setup"]["blocks"])


def test_projection_tracks_graph_removal_without_erasing_history(controller, tmp_path):
    import yaml
    from graphs import load_graph_config
    snapshot = controller.planning_snapshot()["state"]["setup"]
    graph = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    # Existing BO owner node is an overlay; removing its module binding should
    # immediately retire editing while retaining the immutable store history.
    for node in graph.nodes:
        if node.handler == "agent.bo_agent" or node.id == "bo":
            node.handler = "agent.unknown_owner"
            node.module_id = None
    path = tmp_path / "graph.yaml"
    # pytest's tmp_path is test-owned; apply_patch is not required for fixture data.
    path.write_text(yaml.safe_dump(graph.model_dump(mode="json")))
    controller._active_graph_config_path = path
    updated = controller.planning_snapshot()["state"]["setup"]
    assert updated["revision"] == snapshot["revision"]
    assert updated["projection_id"] != snapshot["projection_id"]
    old_bo = next(b for b in snapshot["blocks"] if b["topic_key"] == "bo.acquisition")
    retired = next(b for b in updated["blocks"] if b["block_id"] == old_bo["block_id"])
    assert retired["active"] is False
    assert retired["editable"] is False


def test_refresh_request_is_bound_by_server_not_injected_constraints(controller):
    model(controller, "confirm_pending")
    controller._state.current_experiment_spec = {"specimen_id": "specimen-one"}
    marker = {"status": "waiting", "held_checkpoint": "held", "scope": {
        "run_id": controller._state.run_id, "loop": 0, "specimen_id": "specimen-one"}, "action": "refresh_observation"}
    controller._state.run_metadata["orchestrator_observation_refresh"] = marker
    result = asyncio.run(controller.planning_message(message="Request a fresh observation for this checkpoint", constraints={
        "orchestrator_action": {"action": "refresh_observation", "held_checkpoint": "injected"}}))
    assert result["ok"] is True
    queued = controller._state.run_metadata["operator_followup_queue"]
    assert len(queued) == 1
    assert queued[0]["orchestrator_action"] == {"action": "refresh_observation", "held_checkpoint": "held", **marker["scope"]}


def test_context_rejects_stale_before_model_and_changed_block_after_model(controller):
    from orchestrator.experimental_setup import SetupConflict
    block = goal_block(controller)
    store = controller._setup_store()
    model(controller, "change_setup", mutate=lambda: store.propose(block["block_id"], block["revision"], {"research.goal": "concurrent"}, "concurrent"))
    result = asyncio.run(controller.planning_message(message="Change design goal", session_id=controller._planning_session_id,
        setup_context={"block_id": block["block_id"], "revision": block["revision"]}))
    assert result["ok"] is False
    assert len(store.snapshot()["blocks"][0]["proposal_ids"]) == 1
    with pytest.raises(SetupConflict):
        asyncio.run(controller.planning_message(message="Change goal", session_id=controller._planning_session_id,
            setup_context={"block_id": block["block_id"], "revision": block["revision"]}))


def test_deferred_initial_confirmation_retains_task_and_next_run_setup(controller, monkeypatch):
    model(controller, "confirm_pending")
    controller._state.run_metadata["orchestrator_planning_boundary"] = {
        "status": "deferred", "task_id": "task", "key": "held", "goal": "original", "constraints": {"size": 7}}
    entries = []
    async def boundary(**kwargs):
        entries.append(kwargs)
        return {"ok": True}
    monkeypatch.setattr(controller, "_handoff_planning_to_design", boundary)
    asyncio.run(controller.planning_message(message="Please continue this review"))
    assert entries == [{"goal": "original", "constraints": {"size": 7}, "new_series": False}]
    assert controller._state.run_metadata["orchestrator_review_revision"] == 1


def test_stop_chat_bypasses_a_busy_classifier_and_planning_lock(controller, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("STOP waited for model classification")
    controller._deps.agent_context.complete = forbidden
    # Existing stop manages replay transports; no managed replay exists here.
    monkeypatch.setattr(controller, "_stop_managed_replay", lambda **kwargs: {"ok": True})
    async def run():
        await controller._planning_request_lock.acquire()
        try:
            response = await controller.planning_message(message="STOP")
            assert response["ok"] is True
            assert controller._state.stop_requested is True
        finally:
            controller._planning_request_lock.release()
    asyncio.run(run())


def test_refresh_scope_is_rechecked_after_queue_event_await(controller, monkeypatch):
    model(controller, "confirm_pending")
    controller._state.current_experiment_spec = {"specimen_id": "one"}
    marker = {"status": "waiting", "held_checkpoint": "held", "scope": {
        "run_id": controller._state.run_id, "loop": 0, "specimen_id": "one"}, "action": "refresh_observation"}
    controller._state.run_metadata["orchestrator_observation_refresh"] = marker
    original = controller.emit_runtime_event
    async def emit(**kwargs):
        if kwargs.get("event_type") == "user_reply":
            controller._state.run_metadata["orchestrator_observation_refresh"]["held_checkpoint"] = "replacement"
        return await original(**kwargs)
    monkeypatch.setattr(controller, "emit_runtime_event", emit)
    result = asyncio.run(controller.planning_message(message="Request a fresh observation"))
    assert result["ok"] is False
    assert not controller._state.run_metadata.get("operator_followup_queue")


def test_setup_restart_reloads_same_store_and_never_resumes(controller):
    block = goal_block(controller)
    path = controller._planning_transcript_path()
    store = controller._setup_store()
    proposal = store.propose(block["block_id"], block["revision"], {"research.goal": "persistent"}, "p")
    controller._experimental_setup_store = None
    # A reconstructed cache must find the same session-local durable evidence.
    assert controller._setup_store().proposal(proposal["proposal_id"])["values"] == {"research.goal": "persistent"}
    assert controller._planning_transcript_path() == path
    assert controller._run_task is None


def test_delayed_proposal_rejects_graph_change_and_uses_module_budget(controller, monkeypatch):
    block = goal_block(controller)
    from graphs import load_graph_config
    from agents.orchestrator_capabilities import OwnerCatalog
    graph = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    catalogs = [OwnerCatalog(controller._deps.agent_registry, graph)]
    monkeypatch.setattr(controller, "_planning_setup_catalog", lambda: catalogs[0])
    calls = []
    async def complete(task, prompt, **kwargs):
        packet = json.loads(prompt)
        calls.append(kwargs)
        if packet["operation"] == "classify_chat_request":
            return SimpleNamespace(model="controlled", text=json.dumps({"intent": "change_setup", "pending_id": None, "reason": "edit"}))
        changed = deepcopy(graph)
        for node in changed.nodes:
            if node.handler == "agent.orchestrator_agent":
                node.handler = "agent.unknown_owner"
                node.module_id = None
        catalogs[0] = OwnerCatalog(controller._deps.agent_registry, changed)
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "propose_setup_change", "arguments": {
            "block_id": block["block_id"], "revision": block["revision"], "changes": {"research.goal": "stale graph"}},
            "reason": "edit", "evidence_refs": ["chat:request"]}))
    controller._deps.agent_context.complete = complete
    result = asyncio.run(controller.planning_message(message="Change goal", setup_context={"block_id": block["block_id"], "revision": block["revision"]}, session_id=controller._planning_session_id))
    assert result["ok"] is False
    assert not controller._setup_store().snapshot()["blocks"][0]["proposal_ids"]
    # Timeout belongs to the graph module / existing model route, never a new30s override.
    assert all(call.get("timeout_s") != 30 for call in calls)


def test_question_cannot_restore_lost_printer_marker_or_resume(controller, monkeypatch):
    model(controller, "question")
    spec = {"candidate_id": "one", "specimen_id": "one", "test_mode_llm_generated": True}
    controller._state.current_experiment_spec = deepcopy(spec)
    async def forbidden(**kwargs):
        pytest.fail("A question resumed a printer task")
    monkeypatch.setattr(controller, "_handle_pending_specimen_operator_input", forbidden)
    asyncio.run(controller.planning_message(message="What does installed printer mean?"))
    assert "pending_specimen_input" not in controller._state.run_metadata
    assert not controller._state.run_metadata.get("operator_followup_queue")
    assert controller._state.current_experiment_spec == spec


def test_discard_is_idempotent_and_cannot_apply_values(controller):
    block = goal_block(controller)
    store = controller._setup_store()
    proposal = store.propose(block["block_id"], block["revision"], {"research.goal": "discarded"}, "p")
    request = action(controller, block, proposal, action="discard")
    async def run():
        await controller.planning_setup_action(request)
        again = await controller.planning_setup_action(request)
        assert again["ok"] is True
        assert store.proposal(proposal["proposal_id"])["status"] == "discarded"
        assert not store.snapshot()["blocks"][0]["current_draft_proposal_id"]
        assert controller._state.active_goal != "discarded"
    asyncio.run(run())


def test_plain_chat_setup_proposal_uses_same_tool_and_confirmation_action(controller):
    block = goal_block(controller)
    packets = []
    async def complete(task, prompt, **kwargs):
        packet = json.loads(prompt)
        packets.append(packet)
        if packet["operation"] == "classify_chat_request":
            intent = "confirm_pending" if packet["message"] == "Confirm the proposed goal" else "change_setup"
            return SimpleNamespace(model="controlled", text=json.dumps({"intent": intent, "reason": "operator request",
                "pending_id": packet["pending_id"] if intent == "confirm_pending" else None}))
        return SimpleNamespace(model="controlled", text=json.dumps({"tool": "propose_setup_change", "arguments": {
            "block_id": block["block_id"], "revision": block["revision"], "changes": {"research.goal": "next plain goal"}},
            "reason": "requested", "evidence_refs": ["chat:request"]}))
    controller._deps.agent_context.complete = complete
    async def run():
        proposed = await controller.planning_message(message="Set the next run goal to next plain goal", session_id=controller._planning_session_id)
        assert proposed["decision"]["status"] == "proposed"
        assert controller._setup_store().snapshot()["blocks"][0]["confirmed_values"] is None
        confirmed = await controller.planning_message(message="Confirm the proposed goal", session_id=controller._planning_session_id)
        assert confirmed["ok"] is True
        assert confirmed["setup"]["blocks"][0]["confirmed_values"] == {"research.goal": "next plain goal"}
        assert controller._run_task is None
        assert controller._state.active_goal != "next plain goal"
    asyncio.run(run())


def test_api_setup_context_validation_is_scoped(api, controller):
    import httpx
    block = goal_block(controller)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
            for context, session, status in [({"block_id": "absent", "revision": 1}, controller._planning_session_id, 422),
                ({"block_id": block["block_id"], "revision": 0}, controller._planning_session_id, 409),
                ({"block_id": block["block_id"], "revision": True}, controller._planning_session_id, 422),
                ({"block_id": block["block_id"], "revision": block["revision"]}, "tab-local", 403)]:
                response = await client.post("/api/planning/message", json={"message": "Revise design", "session_id": session, "setup_context": context})
                assert response.status_code == status, response.text
    asyncio.run(run())


@pytest.mark.parametrize("pointer", ["orchestrator_pending_handoff", "orchestrator_waiting_entry"])
def test_runtime_review_confirmation_queues_only_bound_server_checkpoint(controller, pointer):
    model(controller, "confirm_pending")
    controller._state.run_metadata[pointer] = "checkpoint-one"
    controller._state.run_metadata["orchestrator_checkpoints"] = {"checkpoint-one": {
        "status": "deferred", "payload": {"stage": "design", "reason": "Operator review needed"}}}
    async def run():
        await controller._planning_request_lock.acquire()
        try:
            response = await controller.planning_message(message="Continue this pending review")
        finally:
            controller._planning_request_lock.release()
        assert response["ok"] is True
        queue = controller._state.run_metadata["operator_followup_queue"]
        assert len(queue) == 1
        assert queue[0]["orchestrator_action"] is None
        assert controller._state.run_metadata[pointer] == "checkpoint-one"
    asyncio.run(run())


@pytest.mark.parametrize("session", [None, "foreign-session", "new-tab-local-id"])
@pytest.mark.parametrize("intent", ["change_setup", "confirm_pending"])
def test_general_chat_setup_effects_require_canonical_scope(controller, session, intent):
    block = goal_block(controller)
    store = controller._setup_store()
    if intent == "confirm_pending":
        store.propose(block["block_id"], block["revision"], {"research.goal": "draft"}, "p")
    before = store.snapshot()
    model(controller, intent)
    with pytest.raises(PermissionError):
        asyncio.run(controller.planning_message(message="Change or confirm next-run goal", session_id=session))
    assert store.snapshot() == before
    assert controller._run_task is None


def test_rejected_general_setup_api_returns_canonical_session(api, controller):
    import httpx
    model(controller, "change_setup")
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
            response = await client.post("/api/planning/message", json={"message": "Change next-run goal", "session_id": "local-tab"})
            assert response.status_code == 403
            assert response.json()["detail"]["planning_session_id"] == controller._planning_session_id
    asyncio.run(run())


@pytest.mark.parametrize("operation", ["_planning_setup_projection", "_planning_intake_scope"])
def test_each_setup_resolution_reads_each_linked_module_once_and_refreshes_next_call(controller, monkeypatch, operation):
    """No quadratic owner rereads and no stale cross-request catalog cache."""
    from collections import Counter
    from pathlib import Path
    from graphs import load_graph_config
    graph = load_graph_config("graphs/configs/atr_closed_loop.yaml")
    linked_modules = {node.module_id for node in graph.nodes if node.module_id}
    graph_root = Path("graphs").resolve()
    expected = {str(graph_root / module_id / "module.yaml"): 1 for module_id in linked_modules}
    original = Path.read_text
    reads = Counter()
    def read(path, *args, **kwargs):
        if path.name == "module.yaml":
            reads[str(path.resolve())] += 1
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    for _ in range(2):
        reads.clear()
        getattr(controller, operation)()
        assert dict(reads) == expected


@pytest.mark.parametrize("reload_store", [False, True])
def test_normalized_confirmation_http_retry_replays_without_another_draft(api, controller, reload_store):
    import httpx
    block = goal_block(controller)
    store = controller._setup_store()
    proposal = store.propose(block["block_id"], block["revision"], {"research.goal": "  retry goal  "}, "proposal")
    request = action(controller, block, proposal)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
            first = await client.post("/api/planning/setup/actions", json=request)
            assert first.status_code == 200, first.text
            saved = store.snapshot()
            if reload_store:
                controller._experimental_setup_store = None
            replay = await client.post("/api/planning/setup/actions", json=request)
            assert replay.status_code == 200, replay.text
            assert replay.json() == first.json()
            assert controller._setup_store().snapshot() == saved
            changed = replay.json()["setup"]["blocks"][0]
            assert len(changed["proposal_ids"]) == 2
            assert changed["confirmed_values"] is None
            # A distinct explicit approval is still required to accept Q.
            second_request = {**request, "proposal_id": changed["current_draft_proposal_id"],
                "expected_revision": changed["revision"], "request_id": "second-explicit-confirmation"}
            confirmed = await client.post("/api/planning/setup/actions", json=second_request)
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.json()["setup"]["blocks"][0]["confirmed_values"] == {"research.goal": "retry goal"}
            assert controller._state.active_goal != "retry goal"
    asyncio.run(run())


@pytest.mark.parametrize("changed_action", ["confirm", "discard"])
def test_normalization_original_request_id_cannot_authorize_successor_payload(api, controller, changed_action):
    import httpx
    block = goal_block(controller)
    store = controller._setup_store()
    proposal = store.propose(block["block_id"], block["revision"], {"research.goal": "  retry goal  "}, "proposal")
    request = action(controller, block, proposal)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
            first = await client.post("/api/planning/setup/actions", json=request)
            assert first.status_code == 200
            changed = first.json()["setup"]["blocks"][0]
            saved = store.snapshot()
            controller._experimental_setup_store = None
            altered = {**request, "action": changed_action, "proposal_id": changed["current_draft_proposal_id"],
                "expected_revision": changed["revision"]}
            rejected = await client.post("/api/planning/setup/actions", json=altered)
            assert rejected.status_code == 409, rejected.text
            assert controller._setup_store().snapshot() == saved
    asyncio.run(run())
