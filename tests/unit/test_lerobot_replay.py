"""Non-actuating tests for managed, local-only replay."""
import json
import asyncio
import signal
import subprocess
import threading
from types import SimpleNamespace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig


def dataset_at(root):
    (root / "meta").mkdir(parents=True)
    (root / "data/chunk-000").mkdir(parents=True)
    names = ["shoulder_pan.pos", "shoulder_lift.pos"]
    (root / "meta/info.json").write_text(json.dumps({
        "codebase_version": "v2.1", "robot_type": "omx_follower", "fps": 15,
        "total_episodes": 1, "total_frames": 2, "chunks_size": 1000,
        "features": {key: {"names": names} for key in ("action", "observation.state")},
    }))
    (root / "meta/episodes.jsonl").write_text(json.dumps({"episode_index": 0, "length": 2}) + "\n")
    pq.write_table(pa.table({"episode_index": [0, 0], "frame_index": [0, 1],
        "action": [[0., 180.], [2., 180.]], "observation.state": [[0., 80.], [2., 80.]]}),
        root / "data/chunk-000/episode_000000.parquet")
    return root


class FakeProcess:
    pid = 987654321
    returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({"lerobot": {
        "default_profile_id": "omx", "session_memory_path": str(tmp_path / "sessions.json"),
        "session_log_root": str(tmp_path / "logs"), "profiles": {"omx": {
            "profile_id": "omx", "display_name": "Fake OMX", "robot_family": "robotis_omx",
            "robot_type": "omx_follower", "teleop_type": "omx_leader",
            "robot_port": "/dev/fake", "robot_id": "omx_follower_arm", "calibration_dir": "",
            "safety_limits": {"live_enabled": True, "allow_policy_rollout": True},
        }}}}, repo_root=tmp_path))
    launched = []
    def popen(argv, **kwargs):
        assert isinstance(argv, list) and not kwargs.get("shell")
        process = FakeProcess()
        launched.append((argv, process))
        return process
    monkeypatch.setattr("device_bridges.lerobot_bridge.subprocess.Popen", popen)
    monkeypatch.setattr("device_bridges.lerobot_bridge.time.sleep", lambda _: None)
    monkeypatch.setattr(bridge, "_device_port_available", lambda _: True)
    monkeypatch.setattr(bridge, "_device_port_occupants", lambda _: [])
    monkeypatch.setattr(bridge, "_project_lerobot_pids", lambda _: [])
    monkeypatch.setattr(bridge, "_lerobot_display_viewer_pids", lambda _: [])
    monkeypatch.setattr(bridge, "_terminate_live_process", lambda p, sig: setattr(p, "returncode", -int(sig)))
    payload = {"mode": "live", "confirm_live_execute": True, "profile_id": "omx",
        "dataset_repo_id": "jin/utm_clear", "dataset_path": str(dataset_at(tmp_path / "dataset")),
        "session_id": "clear-child", "run_id": "run-1", "loop_id": "loop-1", "specimen_id": "sp-1"}
    return bridge, payload, launched


def test_replay_tracks_session_and_explicit_stop(boundary):
    bridge, payload, launched = boundary
    started = bridge.replay_start(payload)
    assert started["ok"] and started["workflow"] == "replay"
    assert started["run_id"] == "run-1" and started["replay_episode"] == 0
    assert len(launched) == 1 and any("lerobot_managed_replay.py" in arg for arg in launched[0][0])
    assert not any("camera" in arg or "policy.path" in arg for arg in launched[0][0])
    assert bridge.replay_status({"session_id": started["session_id"]})["session_id"] == "clear-child"
    assert bridge.replay_stop({"session_id": "clear-child"})["status"] == "STOPPED"
    assert launched[0][1].returncode == -signal.SIGTERM


def test_duplicate_session_never_reexecutes_even_after_completion(boundary):
    bridge, payload, launched = boundary
    bridge.replay_start(payload)
    assert bridge.replay_start(payload)["idempotent"] is True
    launched[0][1].returncode = 0
    assert bridge.replay_start(payload)["idempotent"] is True
    assert len(launched) == 1
    assert not bridge.replay_start({**payload, "specimen_id": "wrong"})["ok"]


@pytest.mark.parametrize("workflow", ["record", "rollout", "teleoperate", "replay"])
def test_active_motion_session_blocks_replay(boundary, workflow):
    bridge, payload, launched = boundary
    bridge._sessions["occupied"] = {"session_id": "occupied", "workflow": workflow,
        "profile_id": "omx", "mode": "live", "status": "RUNNING", "returncode": None}
    assert bridge.replay_start(payload)["ok"] is False
    assert not launched


@pytest.mark.parametrize("changes", [{"confirm_live_execute": False}, {"replay_episode": 3},
    {"dataset_path": "/missing/replay"}, {"dataset_repo_id": ""}, {"session_id": "../escape"}])
def test_invalid_replay_cannot_launch(boundary, changes):
    bridge, payload, launched = boundary
    assert bridge.replay_start({**payload, **changes})["ok"] is False
    assert not launched


def test_incomplete_episode_cannot_launch(boundary):
    bridge, payload, launched = boundary
    (Path(payload["dataset_path"]) / "meta/episodes.jsonl").write_text('{"episode_index":0,"length":3}\n')
    assert not bridge.replay_start(payload)["ok"]
    assert not launched


def test_external_port_occupant_blocks_replay(boundary, monkeypatch):
    bridge, payload, launched = boundary
    monkeypatch.setattr(bridge, "_device_port_occupants", lambda _: [{"pid": 42}])
    assert not bridge.replay_start(payload)["ok"]
    assert not launched


@pytest.mark.parametrize("exit_code", [0, 2])
def test_exit_does_not_prove_home(boundary, exit_code):
    bridge, payload, launched = boundary
    bridge.replay_start(payload)
    launched[0][1].returncode = exit_code
    status = bridge.replay_status({"session_id": "clear-child"})
    assert status["status"] == ("COMPLETED" if exit_code == 0 else "FAILED")
    assert status["ok"] is (exit_code == 0)
    assert status["exit_code"] == exit_code
    assert status["replay_home_verified"] is False


def test_unknown_session_does_not_return_or_stop_another_replay(boundary):
    bridge, payload, launched = boundary
    bridge.replay_start(payload)
    assert not bridge.replay_status({"session_id": "wrong"})["ok"]
    assert not bridge.replay_stop({"session_id": "wrong"})["ok"]
    assert launched[0][1].poll() is None


def test_global_cleanup_stops_managed_replay(boundary):
    bridge, payload, launched = boundary
    bridge.replay_start(payload)
    bridge.cleanup_all_lerobot_processes()
    assert launched[0][1].poll() == -signal.SIGTERM
    assert bridge.replay_status({"session_id": "clear-child"})["status"] == "STOPPED"


def test_replay_blocks_other_live_motion_start(boundary):
    bridge, payload, _ = boundary
    bridge.replay_start(payload)
    result = bridge._live_port_block_if_needed(tool="lerobot.rollout.start", mode="live",
        profile=bridge._profile("omx"), workflow="rollout")
    assert result and not result["ok"]


def test_integer_loop_identity_is_preserved(boundary):
    bridge, payload, _ = boundary
    result = bridge.replay_start({**payload, "loop_id": 0})
    assert result["ok"] and result["loop_id"] == 0


def test_explicit_stop_of_old_session_does_not_stop_new_session(boundary):
    bridge, payload, launched = boundary
    bridge.replay_start(payload)
    launched[0][1].returncode = 0
    bridge.replay_start({**payload, "session_id": "next-child"})
    bridge.replay_stop({"session_id": "clear-child"})
    assert launched[1][1].returncode is None


def test_explicit_stop_waits_for_launched_session_registration(boundary, monkeypatch):
    """A caller's stop must not miss a child inside its startup poll window."""
    bridge, payload, launched = boundary
    child_ready = threading.Event()
    allow_registration = threading.Event()
    stop_reached_lock_or_returned = threading.Event()
    results = {}
    failures = []
    original_lock = bridge._replay_start_lock

    class ObservedLock:
        def __enter__(self):
            if threading.current_thread().name == "replay-stop":
                stop_reached_lock_or_returned.set()
            original_lock.acquire()
            return self

        def __exit__(self, *_):
            original_lock.release()

    def pause_after_launch(_seconds):
        assert "clear-child" in bridge._processes
        assert "clear-child" not in bridge._sessions
        child_ready.set()
        assert allow_registration.wait(3), "test did not release startup poll"

    def start():
        try:
            results["start"] = bridge.replay_start(payload)
        except BaseException as exc:
            failures.append(exc)

    def stop():
        try:
            results["stop"] = bridge.replay_stop({"session_id": "clear-child"})
        except BaseException as exc:
            failures.append(exc)
        finally:
            stop_reached_lock_or_returned.set()

    monkeypatch.setattr(bridge, "_replay_start_lock", ObservedLock())
    monkeypatch.setattr("device_bridges.lerobot_bridge.time.sleep", pause_after_launch)
    start_thread = threading.Thread(target=start, name="replay-start")
    stop_thread = threading.Thread(target=stop, name="replay-stop")
    start_thread.start()
    try:
        assert child_ready.wait(3), "fake child did not reach startup polling"
        stop_thread.start()
        assert stop_reached_lock_or_returned.wait(3), "stop did not enter its boundary"
    finally:
        allow_registration.set()
        start_thread.join(3)
        if stop_thread.ident is not None:
            stop_thread.join(3)
    assert not start_thread.is_alive() and not stop_thread.is_alive()
    assert not failures
    assert results["start"]["ok"]
    assert results["stop"]["ok"] and results["stop"]["status"] == "STOPPED"
    assert launched[0][1].returncode == -signal.SIGTERM
    assert bridge.replay_status({"session_id": "clear-child"})["status"] == "STOPPED"


def test_live_replay_is_reported_as_active_control(boundary):
    bridge, payload, _ = boundary
    bridge.replay_start(payload)
    assert any(row["workflow"] == "replay" for row in bridge._active_live_control_sessions(mode="live"))


class FakeBus:
    is_connected = False
    def __init__(self):
        self.events = []
    def connect(self):
        self.is_connected = True
        self.events.append("connect")
    def enable_torque(self):
        self.events.append("enable")
    def disconnect(self, disable_torque=True):
        assert disable_torque
        self.is_connected = False
        self.events.append("disconnect")


class FakeRobot:
    calibration = {"saved": True}
    cameras = {}
    action_features = {"shoulder_pan.pos": float, "shoulder_lift.pos": float}
    def __init__(self, failure=None):
        self.bus = FakeBus()
        self.sent = []
        self.failure = failure
    def send_action(self, action):
        self.sent.append(action)
        if self.failure:
            raise self.failure
    def get_observation(self):
        return {"shoulder_pan.pos": 2., "shoulder_lift.pos": 80.}


def test_runner_uses_recorded_observation_and_preserves_actions(tmp_path):
    from scripts.lerobot_managed_replay import load_episode, run_episode
    episode = load_episode(dataset_at(tmp_path / "dataset"), 0)
    robot = FakeRobot()
    result = run_episode(robot, episode, sleep=lambda _: None)
    assert result["replay_home_verified"] is True
    assert result["home_evidence"]["target_state"]["shoulder_lift.pos"] == 80.
    assert robot.sent[-1]["shoulder_lift.pos"] == 180.
    assert robot.bus.events == ["connect", "enable", "disconnect"]


@pytest.mark.parametrize("failure", [RuntimeError("send failed"), KeyboardInterrupt()])
def test_runner_closes_follower_after_failure_or_interrupt(tmp_path, failure):
    from scripts.lerobot_managed_replay import load_episode, run_episode
    robot = FakeRobot(failure)
    result = run_episode(robot, load_episode(dataset_at(tmp_path / "dataset"), 0), sleep=lambda _: None)
    assert not result["replay_home_verified"] and not result["ok"]
    assert not robot.bus.is_connected
    assert robot.bus.events[-1] == "disconnect"


def test_runner_missing_readback_is_not_verified(tmp_path):
    from scripts.lerobot_managed_replay import load_episode, run_episode
    robot = FakeRobot()
    robot.get_observation = lambda: {}
    result = run_episode(robot, load_episode(dataset_at(tmp_path / "dataset"), 0),
        sleep=lambda _: None, home_timeout_s=0)
    assert result["ok"] and not result["replay_home_verified"]


@pytest.mark.parametrize("corrupt", [None, "token", "target", "missing_measurement", "run_mode"])
def test_home_evidence_requires_current_identity_and_actual_measurements(boundary, corrupt):
    bridge, payload, launched = boundary
    started = bridge.replay_start(payload)
    session = bridge._sessions["clear-child"]
    evidence = {"session_id": "clear-child", "dataset_repo_id": "jin/utm_clear",
        "dataset_path": payload["dataset_path"], "replay_episode": 0,
        "evidence_token": session["replay_evidence_token"], "ok": True,
        "follower_closed": True, "replay_home_verified": True,
        "home_evidence": {"reference": "recorded_end_observation.state", "tolerance": 5.,
            "target_state": {"shoulder_pan.pos": 2., "shoulder_lift.pos": 80.},
            "measured_state": {"shoulder_pan.pos": 2., "shoulder_lift.pos": 80.}}}
    if corrupt == "token":
        evidence["evidence_token"] = "stale"
    elif corrupt == "target":
        evidence["home_evidence"]["target_state"]["shoulder_lift.pos"] = 180.
    elif corrupt == "missing_measurement":
        evidence["home_evidence"].pop("measured_state")
    elif corrupt == "run_mode":
        assert not bridge.replay_start({**payload, "mode": "test"})["ok"]
        return
    Path(started["replay_result_path"]).write_text(json.dumps(evidence))
    launched[0][1].returncode = 0
    assert bridge.replay_status({"session_id": "clear-child"})["replay_home_verified"] is (corrupt is None)


def test_replay_stop_escalates_a_stuck_process(boundary, monkeypatch):
    bridge, payload, launched = boundary
    bridge.replay_start(payload)
    signals = []
    def terminate(process, sig):
        signals.append(sig)
        if sig == signal.SIGKILL:
            process.returncode = -int(sig)
    monkeypatch.setattr(bridge, "_terminate_live_process", terminate)
    assert bridge.replay_stop({"session_id": "clear-child"})["status"] == "STOPPED"
    assert signals == [signal.SIGTERM, signal.SIGKILL]


@pytest.mark.parametrize("stop_kind", ["stop", "safe_stop", "emergency_stop", "plc"])
def test_controller_stop_paths_stop_managed_replay(boundary, stop_kind):
    from app.controller import MainController
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.state import Mode, OrchestratorState
    bridge, payload, launched = boundary
    bridge.replay_start(payload)
    registry = ToolRegistry()
    registry.register("lerobot.replay.stop", bridge.replay_stop)
    registry.register("lerobot.rollout.stop", lambda _: {"ok": True})
    controller = MainController.__new__(MainController)
    controller._deps = SimpleNamespace(agent_context=SimpleNamespace(tools=registry))
    controller._state = OrchestratorState(run_id="run-1", experiment_id="exp", mode=Mode.TEST)
    controller._run_task = controller._planning_handoff_task = None
    controller._cancel_operator_teleop_handoffs = lambda **_: None
    controller._capture_planning_resume_context = lambda **_: {}
    controller._trace = SimpleNamespace(snapshot=lambda: {})
    async def emit(*args, **kwargs):
        pass
    controller._emit_control_event = emit
    if stop_kind == "plc":
        controller.request_plc_fast_stop({})
    else:
        asyncio.run(getattr(controller, stop_kind)())
    assert launched[0][1].poll() == -signal.SIGTERM


def test_runner_closes_port_when_torque_disable_fails(tmp_path):
    from scripts.lerobot_managed_replay import load_episode, run_episode
    robot = FakeRobot()
    def disconnect(**kwargs):
        raise RuntimeError("torque disable failed")
    robot.bus.disconnect = disconnect
    robot.bus.port_handler = SimpleNamespace(closePort=lambda: setattr(robot.bus, "is_connected", False))
    result = run_episode(robot, load_episode(dataset_at(tmp_path / "dataset"), 0), sleep=lambda _: None)
    assert not result["ok"] and not result["replay_home_verified"]
    assert result["follower_closed"] and not robot.bus.is_connected


@pytest.mark.parametrize("persistent_failure", [True, False])
def test_runner_attempts_later_motors_after_early_torque_disable_failure(tmp_path, persistent_failure):
    """Native sequential disconnect's first failure must not skip later motors."""
    from scripts.lerobot_managed_replay import load_episode, run_episode

    class EarlyFailBus(FakeBus):
        motors = {"shoulder_pan": object(), "shoulder_lift": object()}

        def __init__(self):
            super().__init__()
            self.torque_attempts = []
            self.enabled_motors = set(self.motors)
            self.first_attempt_failed = False
            self.port_handler = SimpleNamespace(closePort=self.close_port)

        def disable_torque(self, motors=None, num_retry=0):
            selected = list(self.motors) if motors is None else [motors]
            for motor in selected:
                self.torque_attempts.append((motor, num_retry))
                if motor == "shoulder_pan" and (persistent_failure or not self.first_attempt_failed):
                    self.first_attempt_failed = True
                    raise RuntimeError("first motor disable failed")
                self.enabled_motors.discard(motor)

        def disconnect(self, disable_torque=True):
            if disable_torque:
                # Mirrors installed native early-abort behavior, not the fix.
                self.disable_torque(num_retry=5)
            self.close_port()

        def close_port(self):
            self.is_connected = False
            self.events.append("close_port")

    robot = FakeRobot()
    robot.bus = EarlyFailBus()
    result = run_episode(robot, load_episode(dataset_at(tmp_path / "dataset"), 0), sleep=lambda _: None)
    assert "shoulder_lift" not in robot.bus.enabled_motors
    assert robot.bus.torque_attempts == [("shoulder_pan", 5), ("shoulder_pan", 0), ("shoulder_lift", 0)]
    assert not result["ok"] and not result["replay_home_verified"]
    assert "first motor disable failed" in result["cleanup_error"]
    assert result["follower_closed"] and not robot.bus.is_connected
    assert robot.bus.events[-1] == "close_port"


def test_replay_guardian_requires_confirmation_and_dataset_not_policy():
    from orchestrator.state import Mode, OrchestratorState
    from policies.guardian_gate import guardian_gate, tool_requires_action_shield
    assert tool_requires_action_shield("lerobot.replay.start")
    assert not tool_requires_action_shield("lerobot.replay.stop")
    assert not tool_requires_action_shield("lerobot.replay.status")
    state = OrchestratorState(run_id="r", experiment_id="e", mode=Mode.LIVE)
    def gate(payload):
        return guardian_gate(state=state, stage="manipulation", phase="action",
            tool="lerobot.replay.start", action="pre_tool", payload=payload)
    missing = gate({"mode": "live", "dry_run": False})
    reasons = {a["reason_code"] for a in missing["alarms"]}
    assert "HUMAN_APPROVAL_REQUIRED" in reasons and "MISSING_REQUIRED_INPUT" in reasons
    valid = gate({"mode": "live", "dry_run": False, "confirm_live_execute": True,
        "dataset_repo_id": "jin/utm_clear", "dataset_path": "/local/dataset"})
    assert valid["decision"] in {"allow", "allow_with_warning"}
    misleading_dry_run = gate({"mode": "live", "dry_run": True})
    assert any(a["reason_code"] == "MISSING_REQUIRED_INPUT" for a in misleading_dry_run["alarms"])


def test_runner_rejects_missing_robot_joints_before_connect(tmp_path):
    from scripts.lerobot_managed_replay import load_episode, run_episode
    robot = FakeRobot()
    robot.action_features = {**robot.action_features, "wrist_flex.pos": float}
    result = run_episode(robot, load_episode(dataset_at(tmp_path / "dataset"), 0))
    assert not result["ok"] and not robot.bus.events
