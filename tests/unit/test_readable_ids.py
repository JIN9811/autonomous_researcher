"""Human-readable identities without changing execution or archive ownership."""
from datetime import datetime, timezone
import importlib
import json
import re
from types import SimpleNamespace

import pytest

from utils import ids


@pytest.fixture
def clock(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 12, 23, 30, 25, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(ids, "datetime", FixedDateTime)


def test_new_identifiers_show_korean_date_rollover_and_purpose(clock):
    assert re.fullmatch(r"20260913_083025_KST_planning_[0-9a-f]{8}", ids.make_run_id())
    assert re.fullmatch(r"20260913_083025_KST_Experiment_[0-9a-f]{8}", ids.make_experiment_id())
    assert re.fullmatch(r"20260913_083025_KST_planning_[0-9a-f]{8}", ids.make_planning_session_id())


@pytest.mark.parametrize("mode,profile,want", [
    ("live", "", "Experiment"), ("live", "virtual_bridge", "Experiment"),
    ("test", "", "test"), ("test", "virtual_bridge", "test_virtual"),
    ("test", "installed_printer", "test_real_printer"),
    ("test", "physical_print", "test_physical_print"),
    ("test", "unknown-profile", "test"), ("replay", "physical_print", "replay"),
    ("fault-injection", "", "fault_injection"), ("", "", "planning"),
])
def test_purpose_uses_mode_and_only_an_explicit_test_profile(mode, profile, want, clock):
    purpose = ids.run_purpose(mode, profile)
    assert purpose == want
    assert ids.make_run_id(purpose).startswith(f"20260913_083025_KST_{want}_")


def test_same_second_ids_remain_distinct_and_events_keep_legacy_transport_format(clock):
    generated = [ids.make_run_id() for _ in range(100)]
    assert len(set(generated)) == 100
    assert all(name.startswith("20260913_083025_KST_planning_") for name in generated)
    assert re.fullmatch(r"evt-20260912T233025Z-[0-9a-f]{4}", ids.make_event_id())


@pytest.mark.parametrize("purpose", ["../escape", "", "test/virtual", "a b", "experiment:foo"])
def test_unrecognized_purpose_cannot_enter_a_directory_name(purpose):
    with pytest.raises(ValueError):
        ids.make_run_id(purpose)


@pytest.fixture
def controller(tmp_path, handoff_no_external):
    from scripts.verify_orchestrator_setup import controller_for
    async def complete(*args, **kwargs):
        pytest.fail("Naming must not invoke a model")
    return controller_for(SimpleNamespace(complete=complete, active_backend="controlled"), tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,purpose", [("live", "Experiment"), ("test", "test"),
    ("replay", "replay"), ("fault-injection", "fault_injection")])
async def test_new_run_and_resume_preserve_existing_session_and_log_paths(controller, monkeypatch, mode, purpose):
    from orchestrator.state import Mode
    controller.planning_snapshot()
    session = controller._planning_session_id
    store = controller._setup_store()
    old_dir = controller._logger_bundle.run_dir
    controller._record_planning_message({"role": "user", "content": "retained history"})
    old_path = controller._planning_transcript_path()
    before = old_path.read_bytes()
    reached = []
    async def stopped_at_runtime_boundary():
        reached.append(controller._state.run_id)
    monkeypatch.setattr(controller, "_run_live_or_test", stopped_at_runtime_boundary)
    monkeypatch.setattr(controller, "_run_replay", stopped_at_runtime_boundary)
    result = await controller.start(mode=Mode(mode))
    assert result["ok"]
    await controller._run_task
    run_id = result["run_id"]
    assert re.fullmatch(rf"\d{{8}}_\d{{6}}_KST_{purpose}_[0-9a-f]{{8}}", run_id)
    assert reached == [run_id]
    assert controller._logger_bundle.run_dir.name == controller._state.active_session_id == run_id
    await controller.pause()
    await controller.resume()
    assert controller._state.run_id == run_id
    assert controller._planning_session_id == session
    assert controller._setup_store() is store
    assert old_dir.is_dir() and old_path.read_bytes() == before


def test_reset_planning_session_keeps_old_transcript(controller):
    controller._record_planning_message({"role": "user", "content": "original"})
    old_path = controller._planning_transcript_path()
    before = old_path.read_bytes()
    run_id = controller._state.run_id
    controller._reset_planning_transcript()
    session = controller._planning_session_id
    assert re.fullmatch(r"\d{8}_\d{6}_KST_planning_[0-9a-f]{8}", session)
    controller._record_planning_message({"role": "user", "content": "new"})
    assert controller._planning_transcript_path().parent.name == session
    assert controller._state.run_id == run_id
    assert old_path.read_bytes() == before


@pytest.mark.asyncio
async def test_readable_run_keeps_numbered_loop_and_attempt_archives(controller):
    from utils.agent_artifact_archive import AgentArtifactExecution, list_executions
    current = controller._state
    run_id = current.run_id
    root = controller._deps.run_root
    for loop in (0, 1, 1):
        current.loop_count = loop
        execution = AgentArtifactExecution(root, current, "analysis_agent")
        execution.finish("completed", {"loop": loop})
    entries = list_executions(root / run_id)
    assert [(e["loop_number"], e["attempt_index"]) for e in entries] == [(1, 1), (2, 1), (2, 2)]
    first = root / run_id / "runtime/loops/loop-000001/analysis_agent/attempt-000001/manifest.json"
    assert json.loads(first.read_text())["run_id"] == run_id
    assert current.run_id == run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("profile,purpose", [("virtual_bridge", "test_virtual"),
    ("installed_printer", "test_real_printer"), ("physical_print", "test_physical_print")])
@pytest.mark.parametrize("source", ["constraints", "retained_profile"])
async def test_confirmed_new_series_uses_known_profile_but_continuation_keeps_id(controller, monkeypatch, profile, purpose, source):
    from orchestrator.setup_application import SetupApplication
    controller.planning_snapshot()
    store = controller._setup_store()
    block = next(b for b in store.snapshot()["blocks"] if b["topic_key"] == "research.goal")
    proposal = store.propose(block["block_id"], block["revision"], {"research.goal": "naming check"}, "propose")
    await SetupApplication(store, controller._planning_setup_catalog()).confirm(
        proposal["proposal_id"], proposal["block_revision"], "confirm", controller._state)
    constraints = {"printer_test_path": profile} if source == "constraints" else {}
    if source == "retained_profile":
        controller._state.run_metadata["test_mode_profile"] = {"profile_id": profile}
    async def deferred_review(**kwargs):
        return {"status": "deferred"}
    monkeypatch.setattr(importlib.import_module("app.controller"), "review_handoff", deferred_review)
    old_run = controller._state.run_id
    await controller._handoff_planning_to_design(goal=None, constraints=constraints, new_series=True)
    run_id = controller._state.run_id
    assert run_id != old_run
    assert re.fullmatch(rf"\d{{8}}_\d{{6}}_KST_{purpose}_[0-9a-f]{{8}}", run_id)
    assert controller._state.active_goal == "naming check"
    assert controller._setup_store() is store
    await controller._handoff_planning_to_design(goal=None, constraints={}, new_series=False)
    assert controller._state.run_id == run_id


@pytest.mark.parametrize("run_id", ["run-20260912T000000Z-abcdef", "20260912_090000_KST_test_virtual_1234abcd"])
@pytest.mark.parametrize("separator", ["::", ":", "/"])
def test_artifact_reference_accepts_old_and_new_run_ids(controller, monkeypatch, run_id, separator):
    import app.bootstrap
    monkeypatch.setattr(app.bootstrap, "load_runtime", lambda: controller)
    api = importlib.import_module("app.main")
    monkeypatch.setattr(api, "controller", controller)
    assert api._parse_artifact_id(f"{run_id}{separator}runtime/loops/loop-000001/result.json", "fallback") == (
        run_id, "runtime/loops/loop-000001/result.json")
    assert api._parse_artifact_id("runtime/loops/loop-000001/result.json", "fallback") == (
        "fallback", "runtime/loops/loop-000001/result.json")


@pytest.mark.asyncio
@pytest.mark.parametrize("message,purpose", [
    ("테스트 모드, 가상 브릿지", "test_virtual"),
    ("테스트 모드, 실제 프린터", "test_real_printer"),
    ("테스트 모드, 실제 출력", "test_physical_print"),
    ("테스트 모드", "test"),
])
async def test_live_gui_test_request_names_run_without_changing_live_execution_mode(controller, monkeypatch, message, purpose):
    from orchestrator.state import Mode
    from orchestrator.setup_application import SetupApplication
    controller.prepare_live_gui()
    assert controller._state.mode == Mode.LIVE
    store = controller._setup_store()
    block = next(b for b in store.snapshot()["blocks"] if b["topic_key"] == "research.goal")
    proposal = store.propose(block["block_id"], block["revision"], {"research.goal": "GUI naming"}, "gui-proposal")
    await SetupApplication(store, controller._planning_setup_catalog()).confirm(
        proposal["proposal_id"], proposal["block_revision"], "gui-confirm", controller._state)
    async def completion(**kwargs):
        return SimpleNamespace(text=json.dumps({"goal": "GUI naming", "constraints": {}}),
            model="controlled-naming", raw={}), "controlled response"
    async def review(**kwargs):
        return {"status": "deferred"}
    monkeypatch.setattr(controller, "_complete_live_planning_prompt", completion)
    monkeypatch.setattr(importlib.import_module("app.controller"), "review_handoff", review)
    await controller._run_test_mode_planning(goal=None, constraints={}, operator_message=message)
    task = controller._planning_handoff_task
    if task is not None:
        await task
    assert re.fullmatch(rf"\d{{8}}_\d{{6}}_KST_{purpose}_[0-9a-f]{{8}}", controller._state.run_id)
    assert controller._state.mode == Mode.LIVE
    assert controller._setup_store() is store
