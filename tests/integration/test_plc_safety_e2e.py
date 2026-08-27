"""Virtual full-path proof for PLC safety API and Controller integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time

import pytest
from httpx import ASGITransport, AsyncClient, Response
from fastapi.testclient import TestClient

import app.main as main_module
from app.bootstrap import load_runtime
from device_bridges.plc_bridge import PLCBridge, VirtualPLCTransport
from orchestrator.state import Mode, Stage
from utils.plc_bridge_service import PLCBridgeService


@dataclass
class VirtualRuntime:
    controller: object
    service: PLCBridgeService
    transport: VirtualPLCTransport


class NoopWorker:
    def start(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


class NoopDeviceBridge:
    def shutdown(self) -> None:
        return None


def _virtual_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> VirtualRuntime:
    controller = load_runtime()
    transport = VirtualPLCTransport()
    service = PLCBridgeService(
        PLCBridge(transport),
        controller,
        state_path=tmp_path / "plc-e2e-state.json",
    )
    controller.set_terminal_error_notifier(service.set_terminal_estop)
    monkeypatch.setattr(main_module, "controller", controller)
    monkeypatch.setattr(main_module, "_PLC_BRIDGE_SERVICE", service)
    return VirtualRuntime(controller=controller, service=service, transport=transport)


def _assert_transition(
    response: Response,
    runtime: VirtualRuntime,
    *,
    words: tuple[int, int, int],
    safety_state: str,
    controller_latched: bool,
    controller_sources: set[str],
) -> None:
    assert response.status_code == 200
    payload = response.json()
    snapshot = payload["register_snapshot"]
    assert (snapshot["d100"], snapshot["d101"], snapshot["d102"]) == words
    assert payload["status"] == safety_state

    controller_state = runtime.controller.snapshot()["state"]
    assert controller_state["emergency_stop_requested"] is controller_latched
    active_sources = controller_state["run_metadata"].get("active_safety_sources", {})
    assert set(active_sources) == controller_sources


@pytest.mark.asyncio
async def test_virtual_public_paths_cover_resume_reset_and_terminal_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _virtual_runtime(monkeypatch, tmp_path)
    transport = ASGITransport(app=main_module.app)
    resume_invoked = asyncio.Event()
    resume_contexts: list[dict[str, object]] = []

    async def resume_without_device_work(context: dict[str, object]) -> dict[str, object]:
        resume_contexts.append(context)
        resume_invoked.set()
        return {"ok": True}

    monkeypatch.setattr(
        runtime.controller,
        "_resume_planning_handoff_from_context",
        resume_without_device_work,
    )

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            normal = await client.post("/api/plc/preflight")
            _assert_transition(
                normal,
                runtime,
                words=(0, 0, 0),
                safety_state="normal",
                controller_latched=False,
                controller_sources=set(),
            )

            pb2_before_resume = await client.post(
                "/api/plc/virtual/input", json={"action": "estop"}
            )
            _assert_transition(
                pb2_before_resume,
                runtime,
                words=(0, 1, 0),
                safety_state="estop_latched",
                controller_latched=True,
                controller_sources={"plc_pb2"},
            )

            runtime.controller._state.run_metadata["_planning_resume_context"] = {
                "kind": "planning_cycle_series",
                "goal": "virtual PLC E2E resume",
                "current_spec": {"candidate_id": "virtual-plc-e2e"},
                "design_constraints": {},
                "cycle_index": 2,
                "total_cycles": 4,
                "interrupted_stage": "equipment",
            }

            pb1_resume = await client.post(
                "/api/plc/virtual/input", json={"action": "resume"}
            )
            _assert_transition(
                pb1_resume,
                runtime,
                words=(0, 0, 1),
                safety_state="handshake_asserted",
                controller_latched=True,
                controller_sources={"plc_pb2"},
            )

            await runtime.service.accept_snapshot(words=(0, 0, 1))
            resume_complete = await client.post("/api/plc/preflight")
            _assert_transition(
                resume_complete,
                runtime,
                words=(0, 0, 0),
                safety_state="normal",
                controller_latched=False,
                controller_sources=set(),
            )
            await asyncio.wait_for(resume_invoked.wait(), timeout=1.0)
            assert len(resume_contexts) == 1
            assert resume_contexts[0]["cycle_index"] == 2
            assert resume_contexts[0]["interrupted_stage"] == "equipment"
            assert resume_contexts[0]["current_spec"] == {
                "candidate_id": "virtual-plc-e2e"
            }

            pb2_before_reset = await client.post(
                "/api/plc/virtual/input", json={"action": "estop"}
            )
            _assert_transition(
                pb2_before_reset,
                runtime,
                words=(0, 1, 0),
                safety_state="estop_latched",
                controller_latched=True,
                controller_sources={"plc_pb2"},
            )

            reset_before = runtime.controller.snapshot()["state"]
            runtime.controller._state.stage = Stage.EQUIPMENT
            runtime.controller._state.active_goal = "stale goal before PLC Reset"
            runtime.controller._state.current_experiment_spec = {"stale": True}
            runtime.controller._state.latest_analysis = {"stale": True}
            runtime.controller._state.retry_counters = {"equipment": 3}
            runtime.controller._state.loop_count = 7
            runtime.controller._state.run_metadata["e2e_reset_stale_marker"] = True

            pb1_reset = await client.post(
                "/api/plc/virtual/input", json={"action": "reset"}
            )
            _assert_transition(
                pb1_reset,
                runtime,
                words=(0, 0, 1),
                safety_state="handshake_asserted",
                controller_latched=True,
                controller_sources={"plc_pb2"},
            )

            await runtime.service.accept_snapshot(words=(0, 0, 1))
            reset_complete = await client.post("/api/plc/preflight")
            _assert_transition(
                reset_complete,
                runtime,
                words=(0, 0, 0),
                safety_state="normal",
                controller_latched=False,
                controller_sources=set(),
            )
            reset_state = runtime.controller.snapshot()["state"]
            assert reset_state["run_id"] != reset_before["run_id"]
            assert reset_state["experiment_id"] != reset_before["experiment_id"]
            assert reset_state["stage"] == "idle"
            assert reset_state["active_goal"] == "Build and run autonomous AI researcher loop"
            assert reset_state["current_experiment_spec"] == {}
            assert reset_state["latest_analysis"] == {}
            assert reset_state["retry_counters"] == {}
            assert reset_state["loop_count"] == 0
            assert "e2e_reset_stale_marker" not in reset_state["run_metadata"]

            class PlannedCompletionRunLoop:
                def __init__(self, *, state: object, **_: object) -> None:
                    self._state = state

                async def run(self) -> None:
                    self._state.stage = Stage.COMPLETE

            monkeypatch.setattr("app.controller.RunLoop", PlannedCompletionRunLoop)
            started = await runtime.controller.start(
                mode=Mode.TEST,
                goal="planned virtual completion must not set D101",
            )
            assert started["ok"] is True
            await runtime.controller._run_task

            planned_complete = await client.post("/api/plc/preflight")
            _assert_transition(
                planned_complete,
                runtime,
                words=(0, 0, 0),
                safety_state="normal",
                controller_latched=False,
                controller_sources=set(),
            )

            class TerminalErrorRunLoop:
                def __init__(self, *, state: object, on_event: object, **_: object) -> None:
                    self._state = state
                    self._on_event = on_event

                async def run(self) -> None:
                    await self._on_event(
                        {
                            "event_type": "hardware.alert",
                            "severity": "critical",
                            "payload": {
                                "hardware_alert": {
                                    "failure_code": "VIRTUAL_PLC_E2E_FAULT",
                                    "severity": "critical",
                                }
                            },
                        }
                    )
                    self._state.stage = Stage.ERROR

            monkeypatch.setattr("app.controller.RunLoop", TerminalErrorRunLoop)
            started = await runtime.controller.start(
                mode=Mode.TEST,
                goal="qualifying virtual terminal error",
            )
            assert started["ok"] is True
            await runtime.controller._run_task

            controller_state = runtime.controller.snapshot()["state"]
            assert controller_state["emergency_stop_requested"] is True
            assert set(controller_state["run_metadata"]["active_safety_sources"]) == {
                "runtime_terminal_error"
            }

            terminal_error = await client.post("/api/plc/preflight")
            _assert_transition(
                terminal_error,
                runtime,
                words=(0, 1, 0),
                safety_state="estop_latched",
                controller_latched=True,
                controller_sources={"runtime_terminal_error"},
            )

            for device in runtime.controller._state.device_health:
                runtime.controller._state.device_health[device] = "ready"
            terminal_pb1_reset = await client.post(
                "/api/plc/virtual/input", json={"action": "reset"}
            )
            _assert_transition(
                terminal_pb1_reset,
                runtime,
                words=(0, 0, 1),
                safety_state="handshake_asserted",
                controller_latched=True,
                controller_sources={"runtime_terminal_error"},
            )

            await runtime.service.accept_snapshot(words=(0, 0, 1))
            terminal_reset_complete = await client.post("/api/plc/preflight")
            _assert_transition(
                terminal_reset_complete,
                runtime,
                words=(0, 0, 0),
                safety_state="normal",
                controller_latched=False,
                controller_sources=set(),
            )
            assert runtime.service.status()["active_estop_sources"] == []
    finally:
        await runtime.service.shutdown()
        runtime.controller.set_terminal_error_notifier(None)


@pytest.mark.asyncio
async def test_normal_disconnect_preserves_offline_legacy_controller_behavior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _virtual_runtime(monkeypatch, tmp_path)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        normal = await client.post("/api/plc/preflight")
        _assert_transition(
            normal,
            runtime,
            words=(0, 0, 0),
            safety_state="normal",
            controller_latched=False,
            controller_sources=set(),
        )

        disconnected = await client.post("/api/plc/disconnect")
        _assert_transition(
            disconnected,
            runtime,
            words=(0, 0, 0),
            safety_state="disconnected",
            controller_latched=False,
            controller_sources=set(),
        )
        status = (await client.get("/api/plc/status")).json()
        assert status["connection_state"] == "offline"
        assert status["legacy_controls_available"] is True

    stopped = await runtime.controller.emergency_stop(source="gui")
    assert stopped["ok"] is True
    assert set(stopped["state"]["run_metadata"]["active_safety_sources"]) == {"gui"}
    resumed = await runtime.controller.emergency_resume(source="gui")
    assert resumed["ok"] is True
    assert resumed["state"]["emergency_stop_requested"] is False
    assert resumed["state"]["run_metadata"]["active_safety_sources"] == {}
    runtime.controller.set_terminal_error_notifier(None)


@pytest.mark.asyncio
async def test_mouse_gui_estop_recovers_without_touching_plc_registers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _virtual_runtime(monkeypatch, tmp_path)
    transport = ASGITransport(app=main_module.app)
    reset_calls: list[tuple[str, str | None]] = []
    original_reset = runtime.controller.emergency_reset

    async def recording_reset(
        source: str = "gui",
        transaction_id: str | None = None,
    ) -> dict[str, object]:
        reset_calls.append((source, transaction_id))
        return await original_reset(source=source, transaction_id=transaction_id)

    monkeypatch.setattr(runtime.controller, "emergency_reset", recording_reset)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.post("/api/plc/preflight")).json()["ok"] is True
            stopped = await client.post("/api/run/emergency-stop")
            assert stopped.status_code == 200
            assert stopped.json()["ok"] is True
            stopped_status = runtime.service.status()
            assert stopped_status["register_snapshot"]["d100"] == 0
            assert stopped_status["register_snapshot"]["d101"] == 0
            assert stopped_status["register_snapshot"]["d102"] == 0
            assert stopped_status["safety_state"] == "normal"
            assert stopped_status["active_estop_sources"] == []
            stopped_controller_state = runtime.controller.snapshot()["state"]
            assert stopped_controller_state["emergency_stop_requested"] is True
            assert set(
                stopped_controller_state["run_metadata"]["active_safety_sources"]
            ) == {"gui_estop"}

            reset = await client.post("/api/run/emergency-reset")

            assert reset.status_code == 200
            assert reset.json()["ok"] is True
            assert reset_calls == [("gui_estop", None)]
            controller_state = runtime.controller.snapshot()["state"]
            assert controller_state["emergency_stop_requested"] is False
            assert controller_state["run_metadata"].get("active_safety_sources", {}) == {}
            completed = runtime.service.status()
            assert completed["safety_state"] == "normal"
            assert completed["active_estop_sources"] == []
            assert completed["register_snapshot"]["d100"] == 0
            assert completed["register_snapshot"]["d101"] == 0
            assert completed["register_snapshot"]["d102"] == 0
    finally:
        await runtime.service.shutdown()
        runtime.controller.set_terminal_error_notifier(None)


def test_virtual_lifespan_uses_single_poller_for_estop_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catches virtual E2E bypassing the application-owned monitoring path."""
    runtime = _virtual_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(main_module, "_cleanup_bambu_video_stream_processes", lambda **_: None)
    monkeypatch.setattr(main_module, "_read_api_key_settings", lambda **_: {})

    async def fake_apply_settings(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {}

    monkeypatch.setattr(main_module, "_apply_runtime_api_key_settings", fake_apply_settings)
    monkeypatch.setattr(main_module, "_knowledge_reconciliation_worker", lambda: NoopWorker())
    monkeypatch.setattr(main_module, "_lerobot_bridge", lambda: NoopDeviceBridge())
    monkeypatch.setattr(main_module, "_utm_runtime_bridge", lambda: NoopDeviceBridge())
    monkeypatch.setattr(main_module, "_LOCAL_PYAUTOGUI_BRIDGE_SUPERVISOR", None)
    monkeypatch.setattr(main_module, "_KNOWLEDGE_RECONCILIATION_WORKER", None)
    monkeypatch.setattr(main_module, "_KNOWLEDGE_RECONCILIATION_KNOWLEDGE_SERVICE", None)

    with TestClient(main_module.app) as client:
        deadline = time.monotonic() + 2.0
        status = client.get("/api/plc/status").json()
        while status["connection_state"] != "online" and time.monotonic() < deadline:
            time.sleep(0.01)
            status = client.get("/api/plc/status").json()
        assert status["connection_state"] == "online"

        runtime.transport.words["D101"] = 1
        controller_state = runtime.controller.snapshot()["state"]
        while (
            not controller_state["emergency_stop_requested"]
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
            controller_state = runtime.controller.snapshot()["state"]

        status = client.get("/api/plc/status").json()
        assert controller_state["emergency_stop_requested"] is True
        assert set(controller_state["run_metadata"]["active_safety_sources"]) == {
            "plc_pb2"
        }
        assert status["active_estop_sources"] == ["plc_pb2"]
        assert status["poll_worker_starts"] == 1
        assert status["monitor_state"] == "running"


@pytest.mark.asyncio
async def test_latched_disconnect_retains_plc_source_and_blocks_gui_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _virtual_runtime(monkeypatch, tmp_path)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/plc/preflight")
        pb2 = await client.post("/api/plc/virtual/input", json={"action": "estop"})
        _assert_transition(
            pb2,
            runtime,
            words=(0, 1, 0),
            safety_state="estop_latched",
            controller_latched=True,
            controller_sources={"plc_pb2"},
        )

        disconnected = await client.post("/api/plc/disconnect")
        _assert_transition(
            disconnected,
            runtime,
            words=(0, 1, 0),
            safety_state="estop_latched",
            controller_latched=True,
            controller_sources={"plc_pb2"},
        )
        status = (await client.get("/api/plc/status")).json()
        assert status["connection_state"] == "offline"
        assert status["legacy_controls_available"] is False

    gui_resume = await runtime.controller.emergency_resume(source="gui")
    assert gui_resume["ok"] is False
    assert gui_resume["failure_code"] == "PLC_PHYSICAL_RECOVERY_REQUIRED"
    assert gui_resume["state"]["emergency_stop_requested"] is True
    assert set(gui_resume["state"]["run_metadata"]["active_safety_sources"]) == {
        "plc_pb2"
    }
    runtime.controller.set_terminal_error_notifier(None)
