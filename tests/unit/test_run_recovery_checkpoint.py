import hashlib
import json

import pytest


@pytest.mark.parametrize('case', ['fresh_server', 'unpaused', 'later_specimen', 'later_cycle', 'matching'])
def test_tail_request_only_routes_its_current_paused_boundary(tmp_path, monkeypatch, case):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app import run_recovery, equipment_tail_recovery
    from orchestrator.state import OrchestratorState, Stage
    state = OrchestratorState(run_id='saved-run', experiment_id='e', stage=Stage.ERROR,
        is_paused=True, current_experiment_spec={'specimen_id': 's1'})
    request = {'loop_id': 0, 'experiment_spec': {'specimen_id': 's1'}}
    if case == 'fresh_server':
        state.run_id, state.stage = 'startup-run', Stage.IDLE
    elif case == 'unpaused':
        state.is_paused = False
    elif case == 'later_specimen':
        state.current_experiment_spec = {'specimen_id': 's2'}
    elif case == 'later_cycle':
        state.loop_count = 2
    folder = tmp_path / 'saved-run/recovery'
    folder.mkdir(parents=True)
    (folder / 'equipment_tail_request.json').write_text('{}')
    controller = SimpleNamespace(_state=state, _deps=SimpleNamespace(run_root=tmp_path),
        snapshot=lambda: {'is_running': False}, _active_safety_sources=lambda: [])
    class OrdinaryCheckpointBoundary(Exception):
        pass
    def read_checkpoint(*args):
        raise OrdinaryCheckpointBoundary  # Existing validation still owns restore.
    tail_restore = Mock(return_value={'ok': True, 'status': 'tail'})
    monkeypatch.setattr(run_recovery, 'read_checkpoint', read_checkpoint)
    monkeypatch.setattr(equipment_tail_recovery, 'read_request', lambda *args: request)
    monkeypatch.setattr(equipment_tail_recovery, 'restore', tail_restore)
    if case == 'matching':
        assert run_recovery.restore_checkpoint(controller, 'saved-run')['status'] == 'tail'
        tail_restore.assert_called_once_with(controller, 'saved-run')
    else:
        with pytest.raises(OrdinaryCheckpointBoundary):
            run_recovery.restore_checkpoint(controller, 'saved-run')
        tail_restore.assert_not_called()
    assert controller._state is state


def historical_fixture(tmp_path):
    from PIL import Image
    from app import run_recovery
    state, path = clearance_review_fixture(tmp_path)
    raw = path.parent / "raw.png"
    Image.new("RGB", (640, 480), (120, 120, 120)).save(raw)
    record = json.loads(path.read_text())
    evidence = record["data"]["utm_verification_2"]["record"]["evidence"]
    evidence.update(run_id=state.run_id, loop_id=0, specimen_id="s1", session_id="clear-test",
        raw_frame_path=str(raw), frame_timestamp=101, after_timestamp=100,
        frame_id="original", topic="/camera/image_raw", camera_profile_id="camera_utm_primary",
        material="high_chroma_red", vision_decision={"images": [{"label": "raw frame",
            "path": str(raw), "sha256": run_recovery._hash(raw)}]})
    path.write_text(json.dumps(record))
    state = run_recovery.prepare_clearance_review_retry(state, tmp_path)
    request = {"run_id": state.run_id, "loop_id": 0, "specimen_id": "s1", "session_id": "clear-test",
        "requested_by": "operator", "source_sha256": run_recovery._hash(path),
        "stop_after_cycle": 2}
    return state, path, raw, request


def test_archived_clearance_preserves_capture_time_and_provenance(tmp_path):
    from app.run_recovery import archived_clearance_capture
    state, _, _, request = historical_fixture(tmp_path)
    capture = archived_clearance_capture(state, request, tmp_path / "review")
    assert capture["clear_confirmed"] is True
    assert capture["frame_timestamp"] == 101
    assert capture["historical_review"] is True and capture["current_physical_clearance"] is False
    assert capture["source_sha256"] == request["source_sha256"]
    assert "registered" not in capture and "unknown_reason" not in capture


@pytest.mark.parametrize("change", ["image", "archive", "scope", "before_removal", "no_operator"])
def test_archived_clearance_rejects_modified_or_unscoped_evidence(tmp_path, change):
    from app.run_recovery import archived_clearance_capture, _hash
    state, path, raw, request = historical_fixture(tmp_path)
    if change == "image": raw.write_bytes(b"changed")
    elif change == "archive": path.write_text("{}")
    elif change == "scope": request["session_id"] = "other"
    elif change == "no_operator": request["requested_by"] = "model"
    else:
        record = json.loads(path.read_text())
        record["data"]["utm_verification_2"]["record"]["evidence"]["frame_timestamp"] = 99
        path.write_text(json.dumps(record))
        request["source_sha256"] = _hash(path)
        state.run_metadata["clearance_review_recovery"]["source_sha256"] = _hash(path)
    with pytest.raises(ValueError):
        archived_clearance_capture(state, request, tmp_path / "review")


def test_postprocessing_tool_guard_never_dispatches_hardware():
    from app.run_recovery import PostprocessingTools
    from types import SimpleNamespace
    calls = []
    tools = PostprocessingTools(SimpleNamespace(call=lambda name, payload: calls.append(name)))
    for name in ("lerobot.replay.start", "printer.print", "plc.reset", "vision.utm_specimen_presence.capture"):
        with pytest.raises(ValueError): tools.call(name, {})
    assert calls == []
    tools.call("geometry.generate_metamaterial_stl", {})
    assert calls == ["geometry.generate_metamaterial_stl"]


def clearance_review_fixture(tmp_path):
    from orchestrator.state import OrchestratorState, Stage
    state = OrchestratorState(run_id="run-test", experiment_id="experiment-test", stage=Stage.COMPLETE)
    state.current_experiment_spec = {"specimen_id": "s1"}
    execution = {"run_id": "run-test", "loop_id": 0, "specimen_id": "s1",
        "session_id": "clear-test", "task_id": "clear_utm_to_disposal",
        "state": "error", "success": False, "failure_code": "VISION_REVIEW_REQUIRED",
        "replay_completed_at": 100, "replay_execution_verified": True,
        "pending_deadline_at": 120, "pending_timeout_s": 132,
        "replay_evidence": {"ok": True, "replay_execution_verified": True, "follower_closed": True,
            "session_id": "clear-test", "evidence_token": "token", "frames_sent": 542}}
    state.run_metadata["utm_clear_execution"] = execution
    state.run_metadata["utm_verifications"] = {"run_id": "run-test", "loop_id": 0,
        "specimen_id": "s1", "verification_1": {"confirmed": True}}
    path = tmp_path / "run-test/runtime/loops/loop-000001/vision_agent/attempt-000001/result.json"
    path.parent.mkdir(parents=True)
    from utils.agent_artifact_archive import _public
    path.write_text(json.dumps({"status": "failed", "data": {
        "utm_clear_execution": _public(execution),
        "utm_verification_2": {"run_id": "run-test", "loop_id": 0, "specimen_id": "s1",
            "session_id": "clear-test", "record": {"confirmed": False, "evidence": {
                "status": "unknown", "registered": False, "clear_confirmed": False,
                "unknown_reason": "capture_profile_material_or_registration_invalid"}}}}}))
    return state, path


@pytest.mark.asyncio
async def test_archived_tail_uses_analysis_then_design_without_fabrication(tmp_path, monkeypatch):
    from app.run_recovery import continue_archived_postprocessing, PostprocessingTools
    from utils.utm_clear_cycle import merge_utm_clear_cycle
    from orchestrator.state import Stage
    from dataclasses import dataclass
    from types import SimpleNamespace
    from agents.vision import decision as vision
    from agents.manipulation import decision as manipulation
    state, _, _, request = historical_fixture(tmp_path)
    state.run_metadata["archived_postprocessing_request"] = request
    @dataclass
    class Context:
        tools: object
    context = Context(SimpleNamespace(call=lambda *args: pytest.fail("device dispatch")))
    seen = []
    async def accept(*args, **kwargs):
        assert isinstance(args[1].tools, PostprocessingTools)
        return {"status": "accepted", "scope_valid": True, "llm_used": True}
    monkeypatch.setattr(vision, "review_visual_evidence", accept)
    monkeypatch.setattr(manipulation, "review_manipulation_result", accept)
    async def emit(*args): pass
    async def tail(spec, **kwargs):
        assert kwargs["resume_stage"] == Stage.ANALYSIS
        seen.append("analysis_bo")
        state.run_metadata.pop("archived_postprocessing_request", None)
        return {"ok": True, "decision": "continue"}
    async def design(**kwargs):
        seen.append("design")
        return {"specimen_id": "next-specimen"}
    controller = SimpleNamespace(_state=state, _deps=SimpleNamespace(run_root=tmp_path, agent_context=context),
        _emit_control_event=emit, _merge_planning_agent_data=lambda stage, data: merge_utm_clear_cycle(state, stage, data),
        _planning_cycle_limit=lambda spec: 20, _run_planning_loop_tail=tail,
        _closed_loop_static_design_constraints=lambda constraints: constraints,
        _run_planning_design_stage=design, _store_planning_resume_context=lambda **kwargs: None)
    result = await continue_archived_postprocessing(controller, first_spec=state.current_experiment_spec,
        design_constraints={}, start_cycle=1)
    assert seen == ["analysis_bo", "design"]
    assert result["decision"] == "paused_after_design"
    assert state.is_paused and state.stage == Stage.DESIGN
    assert controller._deps.agent_context is context
    assert state.run_metadata["completed_recovery_design_limit"]["reached"] is True


def test_clearance_review_retry_preserves_motion_completion_and_blocks_replay(tmp_path):
    from app import run_recovery
    from utils.utm_clear_cycle import merge_utm_clear_cycle, clearance_missing
    from orchestrator.state import Stage
    state, _ = clearance_review_fixture(tmp_path)
    restored = run_recovery.prepare_clearance_review_retry(state, tmp_path)
    clear = restored.run_metadata["utm_clear_execution"]
    assert state.stage == Stage.COMPLETE
    assert state.run_metadata["utm_clear_execution"]["state"] == "error"
    assert restored.stage == Stage.ERROR
    assert clear["state"] == "waiting" and clear["success"] is None
    assert clear["replay_completed_at"] == 100
    assert clear["replay_evidence"] == state.run_metadata["utm_clear_execution"]["replay_evidence"]
    assert clear["pending_deadline_at"] > 120
    assert clearance_missing(restored)
    merge_utm_clear_cycle(restored, Stage.EQUIPMENT, {})
    assert restored.run_metadata["utm_clear_next_stage"] == "vision"
    assert clear["state"] != "requested"


def test_clearance_retry_accepts_missing_frame_without_replaying(tmp_path):
    from app import run_recovery
    state, path = clearance_review_fixture(tmp_path)
    saved = json.loads(path.read_text())
    saved["data"]["utm_verification_2"]["record"]["evidence"] = {
        "status": "frame_unavailable", "failure_code": "ROS_IMAGE_FRAME_UNAVAILABLE"}
    path.write_text(json.dumps(saved))
    restored = run_recovery.prepare_clearance_review_retry(state, tmp_path)
    clear = restored.run_metadata["utm_clear_execution"]
    assert clear["state"] == "waiting"
    assert clear["replay_execution_verified"] is True
    assert clear["replay_evidence"] == state.run_metadata["utm_clear_execution"]["replay_evidence"]
    assert "frame_wait_deadline_at" not in clear


def test_retry_after_intervening_readonly_failure_retains_same_replay_proof(tmp_path):
    from app import run_recovery
    state, path = clearance_review_fixture(tmp_path)
    first = run_recovery.prepare_clearance_review_retry(state, tmp_path)
    second = run_recovery.prepare_clearance_review_retry(first, tmp_path)
    assert second.run_metadata["utm_clear_execution"]["replay_evidence"] == state.run_metadata["utm_clear_execution"]["replay_evidence"]
    assert second.run_metadata["utm_clear_execution"]["state"] == "waiting"
    path.write_text("{}")
    with pytest.raises(ValueError):
        run_recovery.prepare_clearance_review_retry(first, tmp_path)


@pytest.mark.parametrize("invalid", ["identity", "home", "open_follower", "other_error", "changed_evidence", "stop"])
def test_clearance_retry_refuses_unproven_completion_or_changed_scope(tmp_path, invalid):
    from app import run_recovery
    state, _ = clearance_review_fixture(tmp_path)
    clear = state.run_metadata["utm_clear_execution"]
    if invalid == "identity": clear["specimen_id"] = "other"
    elif invalid == "home": clear["replay_execution_verified"] = False
    elif invalid == "open_follower": clear["replay_evidence"]["follower_closed"] = False
    elif invalid == "other_error": clear["failure_code"] = "UTM_CLEAR_REPLAY_FAILED_OR_STOPPED"
    elif invalid == "stop": state.safe_stop_requested = True
    else: clear["replay_evidence"]["frames_sent"] = 543
    with pytest.raises(ValueError):
        run_recovery.prepare_clearance_review_retry(state, tmp_path)


@pytest.mark.asyncio
async def test_draft_only_preserves_guardian_stop_and_consumes_only_one_off_request(tmp_path):
    from app.run_recovery import finish_archived_design, PostprocessingTools, _hash
    from types import SimpleNamespace
    state, _, _, request = historical_fixture(tmp_path)
    state.run_metadata["guardian"] = {"decision": "stop", "action": "safe_stop", "reason": "Old physical observation"}
    run = tmp_path / state.run_id
    source = run / "bo.json"
    source.write_text(json.dumps({"status": "completed", "data": {"bo_result": {
        "ok": True, "run_id": state.run_id, "experiment_id": state.experiment_id},
        "experiment_spec_update": {"cell_size_mm": 8.9}}}))
    request.update(phase="design_only", bo_result_relative="bo.json", bo_result_sha256=_hash(source))
    recovery = run / "recovery"
    recovery.mkdir()
    (recovery / "archived_postprocessing.json").write_text(json.dumps(request))
    async def design(**kwargs):
        assert state.run_metadata["guardian"]["decision"] == "stop"
        assert kwargs["cycle_index"] == 2
        return {"specimen_id": "new-draft"}
    controller = SimpleNamespace(_state=state, _deps=SimpleNamespace(run_root=tmp_path,
        agent_context=SimpleNamespace(tools=PostprocessingTools(None))),
        _planning_cycle_limit=lambda spec: 20, _closed_loop_static_design_constraints=lambda value: value,
        _run_planning_design_stage=design, _store_planning_resume_context=lambda **kwargs: None)
    result = await finish_archived_design(controller, request=request, first_spec=state.current_experiment_spec,
        design_constraints={}, start_cycle=1)
    assert result["specimen_id"] == "new-draft"
    assert state.run_metadata["guardian"]["decision"] == "stop"
    assert state.is_paused
    assert not (recovery / "archived_postprocessing.json").exists()
    assert (recovery / "archived_postprocessing.json.consumed").is_file()


def test_checkpoint_preserves_csv_and_rejects_changed_source(tmp_path):
    from app.run_recovery import save_checkpoint, read_checkpoint
    run = tmp_path / "run-test"
    attempt = run / "runtime/loops/loop-000001/equipment_agent/attempt-000001"
    attempt.mkdir(parents=True)
    csv = tmp_path / "compression.csv"
    csv.write_bytes(b"time_s,force_N,displacement_mm\n0,0,0\n1,10,1\n")
    digest = hashlib.sha256(csv.read_bytes()).hexdigest()
    (attempt / "result.json").write_text(json.dumps({"status": "failed", "data": {
        "equipment_workflow_execution_id": "equipment-" + "a" * 32,
        "equipment_handoff": {"failure_code": "EQUIPMENT_WORKFLOW_REVIEW_REQUIRED"},
        "raw_data_export": {"path": str(csv), "sha256": digest}}}))
    snapshot = {"is_running": False, "state": {"run_id": "run-test", "stage": "error"}}
    save_checkpoint(snapshot, {}, tmp_path, "run-test")
    loaded = read_checkpoint(tmp_path, "run-test")
    assert loaded["snapshot"] == snapshot
    assert loaded["csv_sha256"] == digest
    assert (run / "recovery/compression.csv").read_bytes() == csv.read_bytes()
    csv.write_bytes(b"replaced")
    with pytest.raises(ValueError, match="CSV"):
        read_checkpoint(tmp_path, "run-test")


@pytest.mark.parametrize("state", [
    {"run_id": "other", "stage": "error"},
    {"run_id": "run-test", "stage": "equipment"},
    {"run_id": "run-test", "stage": "error", "emergency_stop_requested": True},
])
def test_checkpoint_rejects_wrong_run_or_unsafe_boundary(tmp_path, state):
    from app.run_recovery import save_checkpoint
    with pytest.raises(ValueError):
        save_checkpoint({"is_running": False, "state": state}, {}, tmp_path, "run-test")


@pytest.mark.parametrize('historical_tail_request', [False, True])
def test_restore_rebinds_original_setup_and_transcript_after_new_server_session(tmp_path, monkeypatch, historical_tail_request):
    from app.bootstrap import load_runtime
    from app import run_recovery
    from orchestrator.state import Stage
    from orchestrator.experimental_setup import SetupStore
    controller = load_runtime()
    controller._deps.run_root = tmp_path
    old_path = tmp_path / "original-conversation/live_planning_transcript.jsonl"
    old_path.parent.mkdir()
    latest_message = {"role": "operator", "message": "Already saved after the checkpoint", "transcript_index": 0}
    old_path.write_text(json.dumps(latest_message) + "\n")
    original = SetupStore(old_path.parent, "original-session")
    original.ensure_block("goal", "orchestrator", {"metric": "energy_density"})
    new_path = tmp_path / "new-conversation/live_planning_transcript.jsonl"
    new_path.parent.mkdir()
    controller._canonical_planning_transcript_path = new_path
    controller._planning_session_id = "new-session"
    controller._setup_store()
    state = controller._state.model_copy(deep=True)
    state.run_id = 'saved-run'
    state.stage = Stage.ERROR
    if historical_tail_request:
        recovery = tmp_path / state.run_id / 'recovery'
        recovery.mkdir(parents=True)
        (recovery / 'equipment_tail_request.json').write_text('{}')
    saved = {"snapshot": {"state": state.model_dump(mode="json")},
        "csv_sha256": "preserved", "planning": {"planning_session_id": "original-session",
        "transcript_path": str(old_path), "messages": [], "message_total": 0}}
    monkeypatch.setattr(run_recovery, "read_checkpoint", lambda *args: saved)
    monkeypatch.setattr(run_recovery, "prepare_error_resume", lambda *args: "execution")
    run_recovery.restore_checkpoint(controller, state.run_id)
    assert controller._state.run_id == 'saved-run'
    assert controller._planning_transcript_path() == old_path
    assert controller._setup_store()._session_id == "original-session"
    assert len(controller._setup_store().snapshot()["blocks"]) == 1
    assert controller._planning_messages == [latest_message]
    assert controller._planning_message_total == 1
