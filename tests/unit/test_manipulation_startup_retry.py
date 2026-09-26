"""A dead startup must return to its owner, never silently poll or replay motion."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agents.manipulation.agent import ManipulationAgent
from agents.manipulation.decision import claim_skill_execution
from agents.vision.agent import VisionAgent
from device_bridges.lerobot.bridge import LeRobotBridge
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode, OrchestratorState, Stage


CONNECT_FAILURE = '''Traceback (most recent call last):
  File "/lerobot/scripts/lerobot_record.py", line 487, in record
    robot.connect()
  File "/lerobot/robots/omx_follower/omx_follower.py", line 101, in connect
    self.calibrate()
ConnectionError: Failed to write 'Homing_Offset': There is no status packet!
'''


def failed_status():
    session = {"workflow": "rollout", "status": "FAILED", "returncode": 1, "pid": 123}
    return {**session, "ok": True, "session_id": "old", "log_path": "old.log",
            "runtime": LeRobotBridge._runtime_status_from_log(None, session, CONNECT_FAILURE)}


def state():
    s = OrchestratorState(run_id="retry", experiment_id="exp", mode=Mode.TEST, stage=Stage.VISION,
        current_experiment_spec={"specimen_id": "s1", "manipulation_strategy": "lerobot_policy"},
        run_metadata={"specimen_result": {"ok": True, "specimen_id": "s1"}})
    for key in ("manipulation_result", "robot_task_result"):
        s.run_metadata[key] = {"run_id": s.run_id, "loop_id": s.loop_count, "specimen_id": "s1",
            "ok": True, "workflow": "rollout", "status": "POLICY_ACTIVE", "session_id": "old",
            "rollout_session_id": "old", "handoff_status": "needs_post_place_vision",
            "completion_status": "awaiting_post_place_home"}
    assert claim_skill_execution(s, "transfer_to_utm", {"session_id": "old"})
    s.latest_observations = {"observation_id": "pickup-1", "transfer_readiness": {"ready": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=180)).isoformat()}}
    return s


def context(response):
    tools = ToolRegistry()
    tools.register("lerobot.rollout.status", lambda payload: deepcopy(response))
    return SimpleNamespace(tools=tools)


@pytest.mark.parametrize("text,code,want", [
    (CONNECT_FAILURE, 1, True),
    ("camera disconnected", 1, False),
    (CONNECT_FAILURE, None, False),
    (CONNECT_FAILURE, -999, False),
    ("[ATR_ACTION] count=3 max_abs_delta=0.1\n" + CONNECT_FAILURE, 1, False),
    ("Recording episode 0\n" + CONNECT_FAILURE, 1, False),
])
def test_startup_proof_requires_terminal_connect_trace_not_missing_action_counter(text, code, want):
    runtime = LeRobotBridge._runtime_status_from_log(None,
        {"workflow": "rollout", "status": "FAILED", "returncode": code}, text)
    assert runtime.get("failed_before_policy_start", False) is want


@pytest.mark.asyncio
async def test_failed_zero_action_rollout_routes_to_man_owner_not_utm_wait():
    s = state()
    from agents.manipulation.startup_retry import admit_vision
    admit_vision(s, "old")
    result = await VisionAgent().run(s, context(failed_status()))
    assert result.success
    assert result.data["requested_next_stage"] == "manipulation"
    assert s.run_metadata["manipulation_startup_retry"]["status"] == "owner_review"
    assert result.data["transition_decision"] != "vision_utm_monitoring"


@pytest.mark.asyncio
async def test_owner_rechecks_exit_then_reuses_admitted_vision_without_recapture():
    s = state()
    from agents.manipulation.startup_retry import admit_vision, prepare_retry
    admit_vision(s, "old")
    original = deepcopy(s.latest_observations)
    await VisionAgent().run(s, context(failed_status()))
    s.stage = Stage.MANIPULATION
    result = await prepare_retry(s, context(failed_status()))
    assert result is None
    assert not VisionAgent._post_manipulation_handoff_requested(s)
    assert s.latest_observations == original
    assert claim_skill_execution(s, "transfer_to_utm", {"session_id": "new"})
    assert not claim_skill_execution(s, "transfer_to_utm", {"session_id": "another"})
    attempt = next(iter(s.run_metadata["manipulation_skill_attempts"].values()))
    assert attempt["history"][0]["session_id"] == "old"
    assert attempt["session_id"] == "new"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["actions", "unknown", "alive", "foreign", "stop"])
async def test_unproven_or_changed_failure_never_authorizes_retry(change):
    s = state()
    status = failed_status()
    if change == "actions":
        status["runtime"].update(action_count=20, action_count_observed=True)
    elif change == "unknown":
        status["runtime"].pop("failed_before_policy_start", None)
    elif change == "alive":
        status.update(returncode=None, status="POLICY_ACTIVE")
    elif change == "foreign":
        status["session_id"] = "other"
    else:
        s.stop_requested = True
    result = await VisionAgent().run(s, context(status))
    assert result.data.get("requested_next_stage") != "manipulation"
    assert not claim_skill_execution(s, "transfer_to_utm", {"session_id": "new"})


@pytest.mark.asyncio
async def test_failure_after_motion_is_reported_not_left_waiting_forever():
    s = state()
    status = failed_status()
    status["runtime"].update(action_count=20, action_count_observed=True)
    result = await VisionAgent().run(s, context(status))
    assert result.success is False
    assert result.data["failure_code"] == "MANIPULATION_ROLLOUT_FAILED"


@pytest.mark.asyncio
async def test_normal_man_path_retries_without_capture_and_preserves_source_evidence(tmp_path, monkeypatch):
    from tests.unit.test_manipulation_lerobot_agent import _CtxStub, _isolate_manipulation_profile
    from agents.manipulation.startup_retry import admit_vision
    from policies.guardian_gate import guardian_gate, gate_blocks_execution
    from graphs.schema import load_graph_config
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    s = state()
    admit_vision(s, "old")
    original = deepcopy(s.latest_observations)
    tools = ToolRegistry()
    calls = []
    def status(payload):
        calls.append(("status", payload["session_id"]))
        return failed_status()
    def start(payload):
        calls.append(("start", payload["session_id"]))
        assert payload["session_id"] != "old"
        return {"ok": True, "workflow": "rollout", "status": "POLICY_ACTIVE", "session_id": payload["session_id"]}
    tools.register("lerobot.rollout.status", status)
    tools.register("lerobot.rollout.start", start)
    ctx = _CtxStub(tools)
    result = await VisionAgent().run(s, ctx)
    gate = guardian_gate(state=s, stage="vision", phase="post", payload=result.data)
    assert not gate_blocks_execution(gate), gate
    graph = load_graph_config(__import__('pathlib').Path("graphs/configs/atr_closed_loop.yaml"))
    assert graph.next_stage("vision", state_metadata={"agent_result": result.data}) == "manipulation"
    s.stage = Stage.MANIPULATION
    result = await ManipulationAgent().run(s, ctx)
    assert result.success, result.data
    assert result.data["manipulation"]["status"] == "POLICY_ACTIVE"
    assert result.data["requested_next_stage"] == "vision"
    assert [name for name, _ in calls] == ["status", "status", "status", "start"]
    assert s.latest_observations == original
    assert s.run_metadata["manipulation_startup_retry"]["status"] == "started"


def test_original_expiry_is_retained_but_loading_does_not_expire_admission(monkeypatch):
    from agents.manipulation.startup_retry import admit_vision
    import agents.manipulation.agent as module
    s = state()
    original = deepcopy(s.latest_observations)
    assert ManipulationAgent._vision_signal_freshness(s)["fresh"]
    admit_vision(s, "old")
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr(module, "datetime", Later)
    assert ManipulationAgent._vision_signal_freshness(s)["fresh"]
    assert s.latest_observations == original
    s.loop_count += 1
    assert not ManipulationAgent._vision_signal_freshness(s)["fresh"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["alive", "scope", "stop", "new_image", "budget"])
async def test_owner_refuses_retry_if_proof_changes_before_launch(change):
    from agents.manipulation.startup_retry import admit_vision, prepare_retry
    s = state()
    admit_vision(s, "old")
    await VisionAgent().run(s, context(failed_status()))
    s.stage = Stage.MANIPULATION
    status = failed_status()
    if change == "alive":
        status.update(status="POLICY_ACTIVE", returncode=None)
    elif change == "scope":
        s.loop_count += 1
    elif change == "stop":
        s.emergency_stop_requested = True
    elif change == "new_image":
        s.latest_observations["observation_id"] = "new-conflicting-image"
    else:
        next(iter(s.run_metadata["manipulation_skill_attempts"].values()))["history"] = [{}, {}]
    result = await prepare_retry(s, context(status))
    if change == "scope":
        # A prior cycle must neither authorize nor block this cycle's own admission.
        assert result is None
        assert not next(iter(s.run_metadata["manipulation_skill_attempts"].values())).get("retry_ready")
        return
    assert result is not None and result.success is False
    assert not claim_skill_execution(s, "transfer_to_utm", {"session_id": "new"})


def test_real_actions_start_validity_clock_once_and_prohibit_startup_reuse(monkeypatch):
    from agents.manipulation.startup_retry import admit_vision, observe_rollout
    s = state()
    admit_vision(s, "old")
    snapshot = deepcopy(s.latest_observations)
    active = {"ok": True, "session_id": "old", "status": "POLICY_ACTIVE"}
    observe_rollout(s, active, {"observed": False, "action_count": 0})
    lease = s.run_metadata["manipulation_vision_admission"]
    assert lease["policy_start_observed_at"] is None
    observe_rollout(s, active, {"observed": True, "action_count": 1})
    anchored = deepcopy(lease)
    observe_rollout(s, active, {"observed": True, "action_count": 2})
    assert lease == anchored
    assert lease["execution_expires_at"] > lease["policy_start_observed_at"]
    assert s.latest_observations == snapshot
    import agents.manipulation.startup_retry as module
    class AfterExecutionWindow(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr(module, "datetime", AfterExecutionWindow)
    assert not ManipulationAgent._vision_signal_freshness(s)["fresh"]
    result = observe_rollout(s, failed_status(), {"observed": False, "action_count": 0})
    assert result.success is False


@pytest.mark.asyncio
async def test_stop_or_new_observation_during_status_read_cannot_grant_retry():
    from agents.manipulation.startup_retry import admit_vision, prepare_retry
    s = state()
    admit_vision(s, "old")
    await VisionAgent().run(s, context(failed_status()))
    s.stage = Stage.MANIPULATION
    def changed(_payload):
        s.latest_observations = {"observation_id": "new-observation"}
        return failed_status()
    tools = ToolRegistry()
    tools.register("lerobot.rollout.status", changed)
    result = await prepare_retry(s, SimpleNamespace(tools=tools))
    assert result.success is False
    assert s.latest_observations == {"observation_id": "new-observation"}


@pytest.mark.asyncio
async def test_model_rejection_revokes_startup_admission(tmp_path, monkeypatch):
    from tests.unit.test_manipulation_lerobot_agent import _state, _isolate_manipulation_profile
    _isolate_manipulation_profile(tmp_path, monkeypatch)
    s = _state()
    class RejectContext:
        tools = ToolRegistry()
        force_real_llm_in_test = True
        async def complete(self, *args, **kwargs):
            raise RuntimeError("model unavailable")
    result = await ManipulationAgent().run(s, RejectContext())
    assert not result.success
    assert not s.run_metadata.get("manipulation_vision_admission")


def test_stop_revokes_held_evidence_even_after_flags_clear():
    from agents.manipulation.startup_retry import admit_vision, held_vision_freshness
    s = state()
    admit_vision(s, "old")
    s.emergency_stop_requested = True
    assert held_vision_freshness(s) is None
    s.emergency_stop_requested = False
    assert held_vision_freshness(s) is None


def test_runtime_compaction_preserves_retry_authority_and_admitted_observation():
    from app.controller import MainController
    from agents.manipulation.startup_retry import admit_vision
    s = state()
    admit_vision(s, "old")
    s.run_metadata["manipulation_startup_retry"] = {"status": "owner_review"}
    keys = ("manipulation_skill_attempts", "manipulation_startup_retry", "manipulation_vision_admission")
    records = {key: s.run_metadata[key] for key in keys}
    controller = MainController.__new__(MainController)
    controller._state = s
    controller._compact_planning_runtime_state()
    for key, record in records.items():
        assert s.run_metadata.get(key) is record
