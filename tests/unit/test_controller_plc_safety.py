"""Source-aware PLC safety integration tests for MainController."""

from __future__ import annotations

import asyncio

import pytest

from app.bootstrap import load_runtime
from orchestrator.state import Stage


@pytest.fixture
def controller():
    return load_runtime()


@pytest.mark.asyncio
async def test_start_cannot_replace_active_plc_estop_state(
    controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    await controller.emergency_stop(source="plc_pb2", details={"sequence": 42})
    before = controller.snapshot()["state"]
    runtime_started = asyncio.Event()
    release = asyncio.Event()

    async def inert_run() -> None:
        runtime_started.set()
        await release.wait()

    monkeypatch.setattr(controller, "_run_live_or_test", inert_run)

    try:
        result = await controller.start(mode=controller._state.mode, goal="must remain blocked")
        await asyncio.sleep(0)

        assert result["ok"] is False
        assert result["status"] == "blocked"
        assert result["failure_code"] == "SAFETY_LATCH_ACTIVE"
        assert result["active_safety_sources"] == ["plc_pb2"]
        assert runtime_started.is_set() is False
        after = controller.snapshot()["state"]
        assert after["run_id"] == before["run_id"]
        assert after["emergency_stop_requested"] is True
        assert after["run_metadata"]["active_safety_sources"] == before["run_metadata"]["active_safety_sources"]
    finally:
        release.set()
        task = controller._run_task
        if task is not None and not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_public_planning_handoff_blocks_before_design_when_plc_latched(
    controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planning requests cannot clear a PLC-originated E-STOP latch."""
    await controller.emergency_stop(source="plc_pb2", details={"sequence": 43})
    controller.set_plc_safety_status_provider(
        lambda: {
            "active_estop_sources": ["plc_pb2"],
            "safety_state": "estop_latched",
        }
    )
    before = controller.snapshot()["state"]
    design_started = False

    async def fail_if_design_starts(**_kwargs):
        nonlocal design_started
        design_started = True
        raise AssertionError("PLC-latched planning must not enter Design")

    monkeypatch.setattr(controller, "_run_planning_design_stage", fail_if_design_starts)

    result = await controller.planning_message(
        message="실험 수행",
        goal="maximize compressive energy absorption",
        constraints={
            "material": "PLA",
            "specimen_size_mm": [30, 30, 30],
            "geometry_type": "gyroid",
        },
    )

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["failure_code"] == "PLC_SERVICE_SAFETY_LATCH_ACTIVE"
    assert design_started is False
    after = controller.snapshot()["state"]
    assert after["stage"] == before["stage"]
    assert after["emergency_stop_requested"] is True
    assert after["stop_requested"] is True
    assert after["run_metadata"]["active_safety_sources"] == before["run_metadata"]["active_safety_sources"]


@pytest.mark.asyncio
async def test_no_argument_emergency_controls_keep_gui_compatibility(controller) -> None:
    stopped = await controller.emergency_stop()

    assert stopped["ok"] is True
    assert stopped["state"]["run_metadata"]["active_safety_sources"]["gui"]["source"] == "gui"

    resumed = await controller.emergency_resume()

    assert resumed["ok"] is True
    assert resumed["state"]["run_metadata"]["active_safety_sources"] == {}


@pytest.mark.asyncio
async def test_repeated_source_does_not_duplicate_estop_lifecycle(controller) -> None:
    await controller.emergency_stop(source="plc_pb2", details={"sequence": 10})
    await controller.emergency_stop(source="plc_pb2", details={"sequence": 11})

    estop_events = [
        event for event in controller.recent_events()
        if event.get("event_type") == "run_emergency_stop"
    ]
    source = controller.snapshot()["state"]["run_metadata"]["active_safety_sources"]["plc_pb2"]
    assert len(estop_events) == 1
    assert source["details"] == {"sequence": 11}


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["resume", "reset"])
async def test_gui_cannot_recover_plc_originated_estop(controller, command: str) -> None:
    await controller.emergency_stop(source="plc_pb2")

    operation = controller.emergency_resume if command == "resume" else controller.emergency_reset
    result = await operation(source="gui")

    assert result["ok"] is False
    assert result["failure_code"] == "PLC_PHYSICAL_RECOVERY_REQUIRED"
    assert result["state"]["emergency_stop_requested"] is True
    assert "plc_pb2" in result["state"]["run_metadata"]["active_safety_sources"]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["resume", "reset"])
async def test_gui_can_recover_lone_offline_terminal_error(controller, command: str) -> None:
    await controller.emergency_stop(source="runtime_terminal_error", details={"category": "fatal"})

    operation = controller.emergency_resume if command == "resume" else controller.emergency_reset
    result = await operation(source="gui")

    assert result["ok"] is True
    assert result["state"]["emergency_stop_requested"] is False
    assert result["state"]["run_metadata"].get("active_safety_sources", {}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["resume", "reset"])
async def test_plc_recovery_clears_paired_terminal_error_source(
    controller, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    await controller.emergency_stop(source="runtime_terminal_error")
    await controller.emergency_stop(source="plc_pb2")
    if command == "resume":
        controller._state.run_metadata["_planning_resume_context"] = {
            "kind": "planning_cycle_series",
            "goal": "paired physical recovery",
            "current_spec": {"candidate_id": "paired-source"},
            "design_constraints": {},
            "cycle_index": 1,
            "total_cycles": 2,
            "interrupted_stage": "equipment",
        }

        async def resume_from_context(_context: dict) -> dict:
            return {"ok": True}

        monkeypatch.setattr(controller, "_resume_planning_handoff_from_context", resume_from_context)

    operation = controller.emergency_resume if command == "resume" else controller.emergency_reset
    result = await operation(source="plc", transaction_id=f"plc-paired-{command}")

    assert result["ok"] is True
    assert result["state"]["emergency_stop_requested"] is False
    assert result["state"]["run_metadata"].get("active_safety_sources", {}) == {}
    task = controller._planning_handoff_task
    if task is not None:
        await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_plc_recovery_requires_transaction_id(controller) -> None:
    await controller.emergency_stop(source="plc_pb2")

    result = await controller.emergency_resume(source="plc")

    assert result["ok"] is False
    assert result["failure_code"] == "PLC_TRANSACTION_REQUIRED"
    assert result["state"]["emergency_stop_requested"] is True


@pytest.mark.asyncio
async def test_plc_resume_without_checkpoint_preserves_paired_latch(controller) -> None:
    await controller.emergency_stop(source="runtime_terminal_error")
    await controller.emergency_stop(source="plc_pb2")

    result = await controller.emergency_resume(source="plc", transaction_id="plc-no-checkpoint")

    assert result["ok"] is False
    assert result["failure_code"] == "PLC_RESUME_CONTEXT_UNAVAILABLE"
    assert result["state"]["emergency_stop_requested"] is True
    assert set(result["state"]["run_metadata"]["active_safety_sources"]) == {
        "plc_pb2",
        "runtime_terminal_error",
    }
    assert controller._planning_handoff_task is None


@pytest.mark.asyncio
async def test_plc_resume_uses_saved_checkpoint_and_existing_decision_reset(
    controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    await controller.emergency_stop(source="plc_pb2")
    controller._state.stage = Stage.COMPLETE
    controller._state.run_metadata["_planning_resume_context"] = {
        "kind": "planning_cycle_series",
        "goal": "resume physical checkpoint",
        "current_spec": {"candidate_id": "plc-candidate"},
        "design_constraints": {},
        "cycle_index": 3,
        "total_cycles": 7,
        "interrupted_stage": "equipment",
    }
    controller._state.run_metadata["orchestrator_decision_register"] = [{"decision": "stale"}]
    resumed = asyncio.Event()

    async def resume_from_context(context: dict) -> dict:
        assert context["cycle_index"] == 3
        resumed.set()
        return {"ok": True}

    monkeypatch.setattr(controller, "_resume_planning_handoff_from_context", resume_from_context)

    result = await controller.emergency_resume(source="plc", transaction_id="plc-tx-1")
    await asyncio.wait_for(resumed.wait(), timeout=1.0)

    assert result["ok"] is True
    assert result["resume"]["started"] is True
    assert result["resume"]["cycle_index"] == 3
    assert result["state"]["run_metadata"]["orchestrator_decision_register"] == []
    assert result["state"]["run_metadata"]["active_safety_sources"] == {}
    task = controller._planning_handoff_task
    assert task is not None
    await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_plc_reset_reuses_fresh_state_reset(controller) -> None:
    old_run_id = controller.snapshot()["state"]["run_id"]
    await controller.emergency_stop(source="plc_pb2")
    controller._state.run_metadata["task_4_stale_marker"] = True

    result = await controller.emergency_reset(source="plc_pb2", transaction_id="plc-tx-2")

    assert result["ok"] is True
    assert result["state"]["run_id"] != old_run_id
    assert result["state"]["stage"] == "idle"
    assert result["state"]["emergency_stop_requested"] is False
    assert "task_4_stale_marker" not in result["state"]["run_metadata"]


@pytest.mark.asyncio
async def test_plc_recovery_readiness_requires_latch_and_resume_context(controller) -> None:
    inactive = await controller.plc_recovery_readiness("reset")
    await controller.emergency_stop(source="plc_pb2")
    idle_resume = await controller.plc_recovery_readiness("resume")
    reset_ready = await controller.plc_recovery_readiness("reset")

    assert inactive == {"ok": False, "failure_code": "PLC_ESTOP_NOT_ACTIVE"}
    assert idle_resume["ok"] is True
    assert idle_resume["failure_code"] is None
    assert reset_ready["ok"] is True
    assert reset_ready["failure_code"] is None
    assert reset_ready["physical_safety"]["ok"] is True


@pytest.mark.asyncio
async def test_plc_resume_without_checkpoint_remains_blocked_after_active_runtime(controller) -> None:
    controller._run_task = asyncio.create_task(asyncio.sleep(60))

    await controller.emergency_stop(source="plc_pb2")
    result = await controller.plc_recovery_readiness("resume")

    assert result == {"ok": False, "failure_code": "PLC_RESUME_CONTEXT_UNAVAILABLE"}


@pytest.mark.asyncio
async def test_plc_idle_resume_without_checkpoint_clears_latch_without_starting_work(controller) -> None:
    await controller.emergency_stop(source="plc_pb2")

    result = await controller.emergency_resume(
        source="plc",
        transaction_id="plc-idle-resume",
    )

    assert result["ok"] is True
    assert result["resume"] == {"started": False, "reason": "no_resume_context"}
    assert result["state"]["emergency_stop_requested"] is False
    assert controller._planning_handoff_task is None


@pytest.mark.asyncio
async def test_plc_idle_resume_can_clear_paired_gui_estop_without_checkpoint(controller) -> None:
    await controller.emergency_stop(source="gui_estop")
    await controller.emergency_stop(source="plc_pb2")

    readiness = await controller.plc_recovery_readiness("resume")
    result = await controller.emergency_resume(
        source="plc",
        transaction_id="plc-idle-gui-resume",
    )

    assert readiness["ok"] is True
    assert result["ok"] is True
    assert result["resume"] == {"started": False, "reason": "no_resume_context"}
    assert result["state"]["run_metadata"]["active_safety_sources"] == {}


@pytest.mark.asyncio
async def test_plc_recovery_readiness_rejects_another_active_source(controller) -> None:
    await controller.emergency_stop(source="gui")
    await controller.emergency_stop(source="plc_pb2")

    result = await controller.plc_recovery_readiness("reset")

    assert result == {"ok": False, "failure_code": "ACTIVE_SAFETY_SOURCE_REMAINS"}


def _install_resume_context(controller) -> None:
    controller._state.run_metadata["_planning_resume_context"] = {
        "kind": "planning_cycle_series",
        "goal": "physical readiness regression",
        "current_spec": {"candidate_id": "readiness"},
        "design_constraints": {},
        "cycle_index": 1,
        "total_cycles": 2,
        "interrupted_stage": "equipment",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["resume", "reset"])
async def test_plc_recovery_readiness_rejects_active_physical_command(
    controller,
    command: str,
) -> None:
    """Catches acknowledging PB1 while a side-effecting command is unresolved."""
    await controller.emergency_stop(source="plc_pb2")
    _install_resume_context(controller)
    controller._state.run_metadata["tool_call_records"] = [
        {
            "schema": "tool_call_record.v1",
            "call_id": "tool-call-active",
            "tool": "equipment.pyautogui.run",
            "status": "requested",
            "failure_code": "",
        }
    ]

    result = await controller.plc_recovery_readiness(command)

    assert result["ok"] is False
    assert result["failure_code"] == "PLC_PHYSICAL_COMMAND_ACTIVE"
    assert result["physical_safety"]["active_command_ids"] == ["tool-call-active"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result_status",
    ["started", "running", "active", "executing", "in_progress", "modified"],
)
async def test_plc_recovery_readiness_rejects_active_result_status(
    controller,
    result_status: str,
) -> None:
    """Catches a completed call record hiding an active physical result."""
    await controller.emergency_stop(source="plc_pb2")
    controller._state.run_metadata["tool_call_records"] = [
        {
            "schema": "tool_call_record.v1",
            "call_id": "tool-call-active-result",
            "tool": "equipment.pyautogui.run",
            "status": "completed",
            "result_status": result_status,
            "failure_code": "",
        }
    ]

    result = await controller.plc_recovery_readiness("reset")

    assert result["ok"] is False
    assert result["failure_code"] == "PLC_PHYSICAL_COMMAND_ACTIVE"
    assert result["physical_safety"]["active_command_ids"] == [
        "tool-call-active-result"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["resume", "reset"])
@pytest.mark.parametrize("health", ["unknown", "critical:UTM_DRIVE_FAULT"])
async def test_plc_recovery_readiness_rejects_unknown_or_critical_device_health(
    controller,
    command: str,
    health: str,
) -> None:
    """Catches treating unknown or critical physical-device health as ready."""
    await controller.emergency_stop(source="plc_pb2")
    _install_resume_context(controller)
    controller._state.device_health["utm"] = health

    result = await controller.plc_recovery_readiness(command)

    assert result["ok"] is False
    assert result["failure_code"] == "PLC_DEVICE_HEALTH_UNSAFE"
    assert result["physical_safety"]["unsafe_device_health"] == {"utm": health}


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["resume", "reset"])
async def test_plc_recovery_readiness_rejects_uncertain_command_effect(
    controller,
    command: str,
) -> None:
    """Catches a failed physical command with uncertain effect being treated as quiescent."""
    await controller.emergency_stop(source="plc_pb2")
    _install_resume_context(controller)
    controller._state.run_metadata["tool_call_records"] = [
        {
            "schema": "tool_call_record.v1",
            "call_id": "tool-call-uncertain",
            "tool": "lerobot.rollout.start",
            "status": "failed",
            "failure_code": "ROBOT_COMMAND_TIMEOUT",
        }
    ]

    result = await controller.plc_recovery_readiness(command)

    assert result["ok"] is False
    assert result["failure_code"] == "PLC_DEVICE_EFFECT_UNRESOLVED"
    assert result["physical_safety"]["uncertain_command_ids"] == ["tool-call-uncertain"]


@pytest.mark.asyncio
async def test_start_rejects_service_latch_even_if_controller_state_was_lost(controller) -> None:
    """Catches a new run replacing a fail-closed latch retained only by the PLC service."""
    controller.set_plc_safety_status_provider(
        lambda: {
            "safety_state": "estop_latched",
            "active_estop_sources": ["runtime_terminal_error"],
            "failure_code": "PLC_RECONCILIATION_REQUIRED",
        }
    )

    result = await controller.start(mode=controller._state.mode, goal="must remain blocked")

    assert result["ok"] is False
    assert result["failure_code"] == "PLC_SERVICE_SAFETY_LATCH_ACTIVE"
    assert result["active_safety_sources"] == ["runtime_terminal_error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event", "expected_category"),
    [
        (
            {
                "event_type": "fatal_error",
                "level": "ERROR",
                "message": "Stage=equipment exceeded retry budget: attempt 3 failed",
                "payload": {
                    "agent": "equipment_agent",
                    "node_id": "equipment",
                    "status": "error",
                    "error": "attempt 3 failed",
                    "module_runtime": {"module_id": "equipment"},
                    "retry_policy": {"max_attempts": 2, "backoff_s": 0.0},
                    "guardian_gate": {
                        "phase": "exception",
                        "decision": "continue",
                    },
                },
            },
            "retry_exhausted_agent_exception",
        ),
        (
            {
                "event_type": "hardware.alert",
                "severity": "critical",
                "payload": {
                    "status": "failed",
                    "hardware_alert": {"failure_code": "UTM_DRIVE_FAULT", "severity": "critical"},
                },
            },
            "critical_hardware_failure",
        ),
        (
            {
                "event_type": "hardware.alert",
                "level": "ERROR",
                "payload": {
                    "hardware_alert": {
                        "failure_code": "UNKNOWN_PHYSICAL_DEVICE_STATE",
                        "severity": "blocking",
                    }
                },
            },
            "unknown_physical_device_state",
        ),
        (
            {
                "event_type": "hardware.alert",
                "level": "ERROR",
                "payload": {
                    "hardware_alert": {
                        "failure_code": "SAFETY_INTERLOCK_VIOLATION",
                        "severity": "blocking",
                    }
                },
            },
            "safety_violation",
        ),
        (
            {
                "event_type": "physical_process_exit",
                "level": "ERROR",
                "payload": {"status": "unexpected", "process": "lerobot"},
            },
            "unexpected_physical_process_exit",
        ),
    ],
)
async def test_terminal_run_events_latch_locally_then_notify(
    controller,
    monkeypatch: pytest.MonkeyPatch,
    event: dict,
    expected_category: str,
) -> None:
    notifications: list[dict[str, object]] = []

    async def notifier(details: dict[str, object]) -> None:
        state = controller.snapshot()["state"]
        assert state["emergency_stop_requested"] is True
        assert "runtime_terminal_error" in state["run_metadata"]["active_safety_sources"]
        notifications.append(details)

    controller.set_terminal_error_notifier(notifier)

    class TerminalRunLoop:
        def __init__(self, *, state, on_event, **_: object) -> None:
            self._state = state
            self._on_event = on_event

        async def run(self) -> None:
            await self._on_event(event)
            self._state.stage = Stage.ERROR

    monkeypatch.setattr("app.controller.RunLoop", TerminalRunLoop)

    await controller._run_live_or_test()

    assert [item["category"] for item in notifications] == [expected_category]
    assert controller.snapshot()["state"]["emergency_stop_requested"] is True


@pytest.mark.asyncio
async def test_critical_hardware_terminal_safe_stop_still_notifies(
    controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifications: list[dict[str, object]] = []

    async def notifier(details: dict[str, object]) -> None:
        notifications.append(details)

    controller.set_terminal_error_notifier(notifier)

    class CriticalHardwareSafeStopRunLoop:
        def __init__(self, *, state, on_event, **_: object) -> None:
            self._state = state
            self._on_event = on_event

        async def run(self) -> None:
            await self._on_event(
                {
                    "event_type": "hardware.alert",
                    "severity": "critical",
                    "payload": {
                        "hardware_alert": {
                            "failure_code": "UTM_NO_MOTION_AFTER_START",
                            "severity": "critical",
                        }
                    },
                }
            )
            self._state.stage = Stage.COMPLETE

    monkeypatch.setattr("app.controller.RunLoop", CriticalHardwareSafeStopRunLoop)

    await controller._run_live_or_test()

    assert [item["category"] for item in notifications] == ["critical_hardware_failure"]
    assert controller.snapshot()["state"]["emergency_stop_requested"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        {"event_type": "run_complete", "payload": {"status": "complete"}},
        {"event_type": "safe_stop", "payload": {"reason": "test_loop_cap"}},
        {"event_type": "operator_waiting", "payload": {"status": "waiting"}},
        {"event_type": "guardian_blocked", "payload": {"status": "blocked"}},
        {"event_type": "retry", "payload": {"status": "retry", "retry_count": 1}},
        {"event_type": "llm_timeout_recovered", "payload": {"status": "recovered"}},
        {"event_type": "safe_stop", "payload": {"reason": "operator_requested"}},
        {
            "event_type": "fatal_error",
            "level": "ERROR",
            "message": "Human approval rejected for stage=equipment",
            "payload": {
                "agent": "equipment_agent",
                "node_id": "equipment",
                "module_id": "equipment",
                "status": "error",
                "approval_id": "approval-1",
                "gate_key": "equipment:equipment",
                "decision": "rejected",
            },
        },
        {
            "event_type": "fatal_error",
            "level": "ERROR",
            "message": "Operator outcome blocked the active stage",
            "payload": {"status": "blocked", "decision": "blocked"},
        },
        {
            "event_type": "fatal_error",
            "level": "ERROR",
            "message": "Operation cancelled by operator",
            "payload": {"status": "cancelled", "decision": "cancelled"},
        },
    ],
)
async def test_nonqualifying_terminal_events_do_not_latch_or_notify(
    controller, monkeypatch: pytest.MonkeyPatch, event: dict
) -> None:
    notifications: list[dict[str, object]] = []

    async def notifier(details: dict[str, object]) -> None:
        notifications.append(details)

    controller.set_terminal_error_notifier(notifier)

    class ExpectedTerminalRunLoop:
        def __init__(self, *, state, on_event, **_: object) -> None:
            self._state = state
            self._on_event = on_event

        async def run(self) -> None:
            await self._on_event(event)
            self._state.stage = Stage.COMPLETE

    monkeypatch.setattr("app.controller.RunLoop", ExpectedTerminalRunLoop)

    await controller._run_live_or_test()

    assert notifications == []
    assert controller.snapshot()["state"]["emergency_stop_requested"] is False


@pytest.mark.asyncio
async def test_expected_physical_process_exit_does_not_qualify(
    controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifications: list[dict[str, object]] = []

    async def notifier(details: dict[str, object]) -> None:
        notifications.append(details)

    controller.set_terminal_error_notifier(notifier)

    class ExpectedProcessExitRunLoop:
        def __init__(self, *, state, on_event, **_: object) -> None:
            self._state = state
            self._on_event = on_event

        async def run(self) -> None:
            await self._on_event(
                {
                    "event_type": "physical_process_exit",
                    "level": "INFO",
                    "payload": {"status": "expected", "process": "lerobot"},
                }
            )
            self._state.stage = Stage.ERROR

    monkeypatch.setattr("app.controller.RunLoop", ExpectedProcessExitRunLoop)

    await controller._run_live_or_test()

    assert notifications == []
    assert controller.snapshot()["state"]["emergency_stop_requested"] is False


@pytest.mark.asyncio
async def test_unhandled_active_run_exception_notifies_without_self_await(
    controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifications: list[dict[str, object]] = []

    async def notifier(details: dict[str, object]) -> None:
        notifications.append(details)

    controller.set_terminal_error_notifier(notifier)

    class ExplodingRunLoop:
        def __init__(self, **_: object) -> None:
            pass

        async def run(self) -> None:
            raise RuntimeError("active run exploded")

    monkeypatch.setattr("app.controller.RunLoop", ExplodingRunLoop)
    task = asyncio.create_task(controller._run_live_or_test())
    controller._run_task = task

    with pytest.raises(RuntimeError, match="active run exploded"):
        await task

    assert [item["category"] for item in notifications] == ["unhandled_active_run_exception"]
    assert controller.snapshot()["state"]["emergency_stop_requested"] is True


@pytest.mark.asyncio
async def test_exception_after_normal_completion_does_not_notify(
    controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    notifications: list[dict[str, object]] = []

    async def notifier(details: dict[str, object]) -> None:
        notifications.append(details)

    controller.set_terminal_error_notifier(notifier)

    class PostCompletionExceptionRunLoop:
        def __init__(self, *, state, **_: object) -> None:
            self._state = state

        async def run(self) -> None:
            self._state.stage = Stage.COMPLETE
            raise RuntimeError("post-completion cleanup failed")

    monkeypatch.setattr("app.controller.RunLoop", PostCompletionExceptionRunLoop)

    with pytest.raises(RuntimeError, match="post-completion cleanup failed"):
        await controller._run_live_or_test()

    assert notifications == []
    assert controller.snapshot()["state"]["emergency_stop_requested"] is False
