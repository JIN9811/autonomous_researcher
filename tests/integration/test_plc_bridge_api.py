from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from httpx import Response as HTTPXResponse

import app.main as main_module
from device_bridges.plc_bridge import PLCBridge, VirtualPLCTransport
from utils.plc_bridge_service import PLCBridgeService


MUTATION_KEYS = {
    "ok",
    "status",
    "failure_code",
    "message",
    "transaction_id",
    "register_snapshot",
    "connection_state",
    "step_trace",
}


class OfflineTransport:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.read_calls = 0
        self.available = False
        self.connected = False
        self.writes: list[tuple[str, int]] = []

    def connect(self, host: str, port: int) -> None:
        del host, port
        self.connect_calls += 1
        if not self.available:
            raise ConnectionError("fake PLC is offline")
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def read_words(self, headdevice: str, readsize: int) -> list[int]:
        self.read_calls += 1
        if not self.connected:
            raise ConnectionError("fake PLC is offline")
        assert headdevice == "D100"
        assert readsize == 3
        return [0, 0, 0]

    def _write_word(self, device: str, value: int) -> None:
        if not self.connected:
            raise ConnectionError("fake PLC is offline")
        self.writes.append((device, value))


class RecordingVirtualPLCTransport(VirtualPLCTransport):
    def __init__(self, *, d100: int = 0, d101: int = 0, d102: int = 0) -> None:
        super().__init__(d100=d100, d101=d101, d102=d102)
        self.writes: list[tuple[str, int]] = []

    def _write_word(self, device: str, value: int) -> None:
        self.writes.append((device, value))
        super()._write_word(device, value)


class ControllerProbe:
    def __init__(self) -> None:
        self.recovery_calls: list[tuple[str, str, str | None]] = []

    async def emergency_stop(
        self, source: str, details: dict[str, object]
    ) -> dict[str, object]:
        del source, details
        return {"ok": True}

    async def plc_recovery_readiness(self, command: str) -> bool:
        del command
        return True

    async def emergency_resume(
        self, source: str, transaction_id: str | None = None
    ) -> dict[str, object]:
        self.recovery_calls.append(("resume", source, transaction_id))
        return {"ok": True, "message": "probe resumed"}

    async def emergency_reset(
        self, source: str, transaction_id: str | None = None
    ) -> dict[str, object]:
        self.recovery_calls.append(("reset", source, transaction_id))
        return {"ok": True, "message": "probe reset"}


class NoopWorker:
    def start(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


class NoopBridge:
    def shutdown(self) -> None:
        return None


def _config_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "transport": "pymcprotocol_type3e",
        "host": "192.168.50.90",
        "port": 4999,
        "poll_interval_s": 0.2,
        "stale_after_s": 1.0,
        "handshake_timeout_s": 5.0,
        "runtime_environment": "plc",
    }
    payload.update(overrides)
    return payload


def _assert_validation_contract(response: HTTPXResponse, failure_code: str) -> None:
    assert response.status_code == 422
    payload = response.json()
    assert MUTATION_KEYS <= payload.keys()
    assert payload["ok"] is False
    assert payload["failure_code"] == failure_code


@pytest.fixture
def plc_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[PLCBridgeService, OfflineTransport, list[object]]:
    transport = OfflineTransport()
    service = PLCBridgeService(
        PLCBridge(transport),
        ControllerProbe(),
        poll_interval_s=0.05,
        state_path=tmp_path / "plc-state.json",
    )
    registered_notifiers: list[object] = []

    monkeypatch.setattr(main_module, "_PLC_BRIDGE_SERVICE", service, raising=False)
    monkeypatch.setattr(main_module, "PLC_CONFIG_PATH", tmp_path / "plc.yaml", raising=False)
    monkeypatch.setattr(
        main_module,
        "PLC_CONFIG_MEMORY_PATH",
        tmp_path / "plc-config.json",
        raising=False,
    )
    (tmp_path / "plc.yaml").write_text(
        "schema: plc_bridge_config.v1\n"
        "transport: pymcprotocol_type3e\n"
        "host: 192.168.50.90\n"
        "port: 4999\n"
        "poll_interval_s: 0.2\n"
        "stale_after_s: 1.0\n"
        "handshake_timeout_s: 5.0\n"
        "runtime_environment: plc\n"
        "registers:\n"
        "  command: D100\n"
        "  estop: D101\n"
        "  recovery_ack: D102\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(main_module, "_cleanup_bambu_video_stream_processes", lambda **_: None)
    monkeypatch.setattr(main_module, "_read_api_key_settings", lambda **_: {})

    async def fake_apply_settings(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {}

    monkeypatch.setattr(main_module, "_apply_runtime_api_key_settings", fake_apply_settings)
    monkeypatch.setattr(main_module, "_knowledge_reconciliation_worker", lambda: NoopWorker())
    monkeypatch.setattr(main_module, "_lerobot_bridge", lambda: NoopBridge())
    monkeypatch.setattr(main_module, "_utm_runtime_bridge", lambda: NoopBridge())
    monkeypatch.setattr(main_module, "_LOCAL_PYAUTOGUI_BRIDGE_SUPERVISOR", None)
    monkeypatch.setattr(main_module, "_KNOWLEDGE_RECONCILIATION_WORKER", None)
    monkeypatch.setattr(main_module, "_KNOWLEDGE_RECONCILIATION_KNOWLEDGE_SERVICE", None)
    monkeypatch.setattr(
        main_module.controller,
        "set_terminal_error_notifier",
        registered_notifiers.append,
    )
    return service, transport, registered_notifiers


@pytest.fixture
def client(
    plc_runtime: tuple[PLCBridgeService, OfflineTransport, list[object]],
) -> Iterator[TestClient]:
    del plc_runtime
    with TestClient(main_module.app) as test_client:
        yield test_client


def test_status_distinguishes_reconnecting_monitor_from_stopped_transport(
    client: TestClient,
) -> None:
    payload = client.get("/api/plc/status").json()
    assert payload["connection_state"] == "reconnecting"
    assert payload["monitor_state"] == "running"
    assert payload["legacy_controls_available"] is True
    assert payload["transport"] == "pymcprotocol_type3e"
    assert payload["last_latency_ms"] is None
    assert payload["sample_age_s"] is None
    assert payload["event_revision"] == 0


def test_lifespan_starts_one_service_and_registers_terminal_notifier(
    client: TestClient,
    plc_runtime: tuple[PLCBridgeService, OfflineTransport, list[object]],
) -> None:
    service, _, registered_notifiers = plc_runtime

    assert client.get("/").status_code == 200
    assert service.status()["poll_worker_starts"] == 1
    assert registered_notifiers == [service.set_terminal_estop]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("poll_interval_s", 0.049),
        ("poll_interval_s", 5.001),
        ("stale_after_s", 0.099),
        ("stale_after_s", 60.001),
        ("handshake_timeout_s", 0.999),
        ("handshake_timeout_s", 60.001),
    ],
)
def test_config_rejects_values_outside_exact_bounds(
    client: TestClient,
    field: str,
    value: float,
) -> None:
    response = client.post("/api/plc/config", json=_config_payload(**{field: value}))
    _assert_validation_contract(response, "PLC_CONFIG_VALIDATION_FAILED")


def test_config_requires_stale_window_of_two_poll_intervals(client: TestClient) -> None:
    response = client.post(
        "/api/plc/config",
        json=_config_payload(poll_interval_s=0.6, stale_after_s=1.1),
    )
    _assert_validation_contract(response, "PLC_CONFIG_VALIDATION_FAILED")


def test_config_cannot_switch_production_to_virtual_transport(client: TestClient) -> None:
    response = client.post(
        "/api/plc/config",
        json=_config_payload(transport="virtual", runtime_environment="test"),
    )
    _assert_validation_contract(response, "PLC_CONFIG_VALIDATION_FAILED")


def test_invalid_virtual_input_returns_mutation_contract(client: TestClient) -> None:
    response = client.post("/api/plc/virtual/input", json={"action": "write"})
    _assert_validation_contract(response, "PLC_VIRTUAL_INPUT_VALIDATION_FAILED")


def test_config_persists_valid_bounds_and_returns_mutation_contract(client: TestClient) -> None:
    stopped = client.post("/api/plc/disconnect")
    assert stopped.status_code == 200
    assert stopped.json()["connection_state"] == "offline"
    response = client.post(
        "/api/plc/config",
        json=_config_payload(
            host="10.20.30.40",
            poll_interval_s=0.05,
            stale_after_s=0.1,
            handshake_timeout_s=60.0,
        ),
    )

    assert response.status_code == 200
    assert MUTATION_KEYS <= response.json().keys()
    config = client.get("/api/plc/config").json()
    assert config["host"] == "10.20.30.40"
    assert config["poll_interval_s"] == 0.05
    assert main_module._plc_bridge_service()._stale_after_s == 0.1
    assert config["registers"] == {
        "command": "D100",
        "estop": "D101",
        "recovery_ack": "D102",
    }


def test_config_rejects_transport_offline_while_monitor_is_reconnecting(
    client: TestClient,
) -> None:
    response = client.post("/api/plc/config", json=_config_payload())

    assert response.status_code == 409
    assert response.json()["failure_code"] == "PLC_CONFIG_MONITOR_RUNNING"


def test_config_rejects_active_runtime_even_after_monitor_stops(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post("/api/plc/disconnect").status_code == 200
    original_snapshot = main_module.controller.snapshot

    def active_snapshot() -> dict[str, object]:
        snapshot = original_snapshot()
        snapshot["is_running"] = True
        return snapshot

    monkeypatch.setattr(main_module.controller, "snapshot", active_snapshot)

    response = client.post("/api/plc/config", json=_config_payload())

    assert response.status_code == 409
    assert response.json()["failure_code"] == "PLC_CONFIG_ACTIVE_RUN"


def test_config_rejects_active_handshake_even_after_monitor_stops(
    client: TestClient,
) -> None:
    assert client.post("/api/plc/disconnect").status_code == 200
    service = main_module._plc_bridge_service()
    service._transaction = {
        "transaction_id": "plc-config-handshake",
        "command": "resume",
        "phase": "acknowledged",
    }

    response = client.post("/api/plc/config", json=_config_payload())

    assert response.status_code == 409
    assert response.json()["failure_code"] == "PLC_CONFIG_HANDSHAKE_ACTIVE"


def test_disconnect_rejects_active_runtime(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_snapshot = main_module.controller.snapshot

    def active_snapshot() -> dict[str, object]:
        snapshot = original_snapshot()
        snapshot["is_running"] = True
        return snapshot

    monkeypatch.setattr(main_module.controller, "snapshot", active_snapshot)

    response = client.post("/api/plc/disconnect")

    assert response.status_code == 409
    assert response.json()["failure_code"] == "PLC_DISCONNECT_ACTIVE_RUN"
    assert main_module._plc_bridge_service().status()["monitor_state"] == "running"


def test_disconnect_rejects_active_handshake(
    client: TestClient,
) -> None:
    service = main_module._plc_bridge_service()
    service._transaction = {
        "transaction_id": "plc-active-handshake",
        "command": "reset",
        "phase": "acknowledged",
    }

    response = client.post("/api/plc/disconnect")

    assert response.status_code == 409
    assert response.json()["failure_code"] == "PLC_DISCONNECT_HANDSHAKE_ACTIVE"
    assert service.status()["monitor_state"] == "running"


@pytest.mark.parametrize(
    "route_template",
    [
        "/api/run/emergency-stop",
        "/api/runtime/emergency-stop",
        "/api/runs/{run_id}/emergency-stop",
    ],
)
def test_all_gui_estop_routes_remain_local_and_do_not_write_plc_latch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    route_template: str,
) -> None:
    order: list[str] = []
    observed_sources: list[str] = []
    observed_route_families: list[str] = []

    async def local_stop(
        source: str = "gui",
        details: dict[str, object] | None = None,
    ) -> dict[str, object]:
        order.append("controller")
        observed_sources.append(source)
        observed_route_families.append(str((details or {})["route_family"]))
        return {"ok": True, "state": {"emergency_stop_requested": True}}

    async def forbidden_sync(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("mouse E-STOP must not write the PLC D101 latch")

    monkeypatch.setattr(main_module.controller, "emergency_stop", local_stop)
    monkeypatch.setattr(
        main_module._plc_bridge_service(),
        "sync_estop",
        forbidden_sync,
        raising=False,
    )
    run_id = str(main_module.controller.snapshot()["state"]["run_id"])
    route = route_template.format(run_id=run_id)

    response = client.post(route)

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["plc_sync_ok"] is True
    assert payload["plc_sync_skipped"] is True
    assert payload["plc_sync_failure_code"] is None
    assert order == ["controller"]
    assert observed_sources == ["gui_estop"]
    assert observed_route_families == [route.split("/")[2]]


@pytest.mark.parametrize(
    "route_template",
    [
        "/api/run/emergency-{action}",
        "/api/runtime/emergency-{action}",
        "/api/runs/{run_id}/emergency-{action}",
    ],
)
@pytest.mark.parametrize("action", ["resume", "reset"])
@pytest.mark.parametrize(
    ("service_state", "failure_code"),
    [
        ("latched", "PLC_PHYSICAL_RECOVERY_REQUIRED"),
        ("handshake", "PLC_RECOVERY_HANDSHAKE_ACTIVE"),
    ],
)
def test_gui_recovery_route_rejects_service_latch_and_incomplete_handshake(
    client: TestClient,
    route_template: str,
    action: str,
    service_state: str,
    failure_code: str,
) -> None:
    service = main_module._plc_bridge_service()
    probe = service._callbacks
    assert isinstance(probe, ControllerProbe)
    if service_state == "latched":
        service._active_estop_sources.add("gui_estop")
    else:
        service._transaction = {
            "transaction_id": "plc-gui-recovery-active",
            "command": action,
            "phase": "acknowledged",
            "source_set": ["gui_estop"],
        }
    transaction_before = dict(service._transaction or {})
    calls_before = list(probe.recovery_calls)
    run_id = str(main_module.controller.snapshot()["state"]["run_id"])
    route = route_template.format(run_id=run_id, action=action)

    response = client.post(route)

    assert response.status_code == 409
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["failure_code"] == failure_code
    assert payload["message"]
    assert probe.recovery_calls == calls_before
    assert service._transaction == transaction_before or service_state == "latched"


@pytest.mark.parametrize("action", ["resume", "reset"])
def test_disconnected_plc_does_not_block_mouse_estop_gui_recovery(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    service = main_module._plc_bridge_service()
    probe = service._callbacks
    assert isinstance(probe, ControllerProbe)

    async def local_stop(
        source: str = "gui",
        details: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del source, details
        return {"ok": True, "state": {"emergency_stop_requested": True}}

    monkeypatch.setattr(main_module.controller, "emergency_stop", local_stop)
    stopped = client.post("/api/run/emergency-stop")
    assert stopped.json()["plc_sync_skipped"] is True
    assert service.status()["active_estop_sources"] == []
    run_id = str(main_module.controller.snapshot()["state"]["run_id"])

    for route_template in (
        "/api/run/emergency-{action}",
        "/api/runtime/emergency-{action}",
        "/api/runs/{run_id}/emergency-{action}",
    ):
        response = client.post(route_template.format(run_id=run_id, action=action))

        assert response.status_code == 200
        assert response.json()["ok"] is True

    assert probe.recovery_calls == [
        (action, "gui_estop", None),
        (action, "gui_estop", None),
        (action, "gui_estop", None),
    ]


def test_virtual_input_is_rejected_for_live_transport(client: TestClient) -> None:
    response = client.post("/api/plc/virtual/input", json={"action": "estop"})
    assert response.status_code == 409
    assert MUTATION_KEYS <= response.json().keys()
    assert response.json()["failure_code"] == "PLC_VIRTUAL_INPUT_UNAVAILABLE"


def test_virtual_input_operates_only_on_explicit_virtual_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = PLCBridgeService(
        PLCBridge(VirtualPLCTransport()),
        ControllerProbe(),
        state_path=tmp_path / "virtual-plc-state.json",
    )
    monkeypatch.setattr(main_module, "_PLC_BRIDGE_SERVICE", service, raising=False)

    test_client = TestClient(main_module.app)
    assert test_client.post("/api/plc/preflight").status_code == 200
    response = test_client.post(
        "/api/plc/virtual/input",
        json={"action": "estop"},
    )

    assert response.status_code == 200
    assert response.json()["register_snapshot"]["d101"] == 1


def test_status_reports_virtual_transport_and_cached_sample_timing_only_for_virtual_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = PLCBridgeService(
        PLCBridge(VirtualPLCTransport()),
        ControllerProbe(),
        state_path=tmp_path / "virtual-plc-status.json",
    )
    monkeypatch.setattr(main_module, "_PLC_BRIDGE_SERVICE", service, raising=False)

    with TestClient(main_module.app) as test_client:
        assert test_client.post("/api/plc/preflight").status_code == 200
        payload = test_client.get("/api/plc/status").json()

    assert payload["transport"] == "virtual"
    assert isinstance(payload["last_latency_ms"], float)
    assert payload["last_latency_ms"] >= 0
    assert isinstance(payload["sample_age_s"], float)
    assert payload["sample_age_s"] >= 0
    assert payload["event_revision"] >= 1


def test_preflight_orphan_ack_is_read_only_over_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = RecordingVirtualPLCTransport(d102=1)
    service = PLCBridgeService(
        PLCBridge(transport),
        ControllerProbe(),
        state_path=tmp_path / "virtual-plc-preflight-state.json",
    )
    monkeypatch.setattr(main_module, "_PLC_BRIDGE_SERVICE", service, raising=False)

    response = TestClient(main_module.app).post("/api/plc/preflight")

    assert response.status_code == 200
    assert response.json()["register_snapshot"]["d102"] == 1
    assert transport.writes == []
    assert transport.words == {"D100": 0, "D101": 0, "D102": 1}
    assert service._transaction is None
    assert service.status()["active_estop_sources"] == []


def test_bounded_routes_return_status_events_and_mutation_envelopes(client: TestClient) -> None:
    assert client.get("/api/plc/events").status_code == 200
    for route in ("connect", "disconnect", "preflight"):
        response = client.post(f"/api/plc/{route}")
        assert response.status_code == 200
        assert MUTATION_KEYS <= response.json().keys()


def test_preflight_reopens_io_after_disconnect_without_starting_another_poller(
    client: TestClient,
    plc_runtime: tuple[PLCBridgeService, OfflineTransport, list[object]],
) -> None:
    service, transport, _ = plc_runtime
    assert client.post("/api/plc/connect").status_code == 200
    assert client.post("/api/plc/disconnect").json()["ok"] is True
    transport.available = True

    response = client.post("/api/plc/preflight")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["connection_state"] == "online"
    assert response.json()["register_snapshot"]["d100"] == 0
    assert service.status()["poll_worker_starts"] == 1
    assert main_module._plc_bridge_service() is service


def test_preflight_handshake_rejects_without_io_or_reconciliation(
    client: TestClient,
    plc_runtime: tuple[PLCBridgeService, OfflineTransport, list[object]],
) -> None:
    service, transport, _ = plc_runtime
    assert client.post("/api/plc/disconnect").status_code == 200
    service._active_estop_sources.add("gui_estop")
    service._transaction = {
        "transaction_id": "plc-preflight-active",
        "command": "reset",
        "phase": "acknowledged",
        "source_set": ["gui_estop"],
    }
    transaction_before = dict(service._transaction)
    io_before = (transport.connect_calls, transport.read_calls, list(transport.writes))

    response = client.post("/api/plc/preflight")

    assert response.status_code == 409
    assert response.json()["failure_code"] == "PLC_PREFLIGHT_HANDSHAKE_ACTIVE"
    assert (transport.connect_calls, transport.read_calls, transport.writes) == io_before
    assert service._transaction == transaction_before


@pytest.mark.asyncio
async def test_preflight_handshake_gate_does_not_invert_lifecycle_lock(
    tmp_path: Path,
) -> None:
    service = PLCBridgeService(
        PLCBridge(OfflineTransport()),
        ControllerProbe(),
        state_path=tmp_path / "plc-preflight-lock-order.json",
    )
    preflight_task: asyncio.Task[dict[str, object]] | None = None
    sync_task: asyncio.Task[dict[str, object]] | None = None
    try:
        async with service._lifecycle_lock:
            preflight_task = asyncio.create_task(service.preflight())
            await asyncio.sleep(0)
            sync_task = asyncio.create_task(
                service.sync_estop("gui_estop", {"reason": "lock_order_probe"})
            )
            await asyncio.wait_for(asyncio.shield(sync_task), timeout=0.1)
    finally:
        if preflight_task is not None:
            preflight_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await preflight_task
        if sync_task is not None and not sync_task.done():
            await sync_task
        await service.shutdown()


def test_gui_recovery_route_blocks_persisted_no_write_sync_failure(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "plc-no-write-sync-failure.json"
    state_path.write_text(
        '{"schema":"plc_bridge_transaction.v1",'
        '"transaction_id":"plc-old-offline-sync",'
        '"phase":"estop_sync_failed",'
        '"source":"gui_estop",'
        '"source_set":["gui_estop"],'
        '"write_evidence":[],"final_outcome":"failed"}',
        encoding="utf-8",
    )
    probe = ControllerProbe()
    service = PLCBridgeService(
        PLCBridge(OfflineTransport()),
        probe,
        state_path=state_path,
    )

    try:
        assert service.status()["active_estop_sources"] == ["gui_estop"]

        result = asyncio.run(service.request_gui_recovery("resume"))

        assert result["ok"] is False
        assert result["failure_code"] == "PLC_PHYSICAL_RECOVERY_REQUIRED"
        assert probe.recovery_calls == []
    finally:
        asyncio.run(service.shutdown())


def test_plc_workspace_route_targets_later_ui_shell(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered: dict[str, object] = {}

    def fake_template_response(
        *, request: object, name: str, context: dict[str, object]
    ) -> HTMLResponse:
        rendered.update({"request": request, "name": name, "context": context})
        return HTMLResponse("<main>PLC workspace</main>")

    monkeypatch.setattr(main_module.templates, "TemplateResponse", fake_template_response)

    assert client.get("/plc").status_code == 200
    assert rendered["name"] == "plc.html"


def test_plc_workspace_dashboard_and_openapi_contract(client: TestClient) -> None:
    workspace = client.get("/plc")
    dashboard = client.get("/")
    plc_paths = {
        path: set(methods)
        for path, methods in main_module.app.openapi()["paths"].items()
        if path.startswith("/api/plc/")
    }

    assert workspace.status_code == 200
    assert 'id="plc-workspace"' in workspace.text
    assert dashboard.status_code == 200
    assert 'id="btn-open-plc" class="btn primary" href="/plc"' in dashboard.text
    assert plc_paths == {
        "/api/plc/config": {"get", "post"},
        "/api/plc/connect": {"post"},
        "/api/plc/disconnect": {"post"},
        "/api/plc/events": {"get"},
        "/api/plc/preflight": {"post"},
        "/api/plc/status": {"get"},
        "/api/plc/virtual/input": {"post"},
    }
    assert "/api/plc/write" not in main_module.app.openapi()["paths"]
    assert client.post("/api/plc/write", json={"device": "D200", "value": 1}).status_code == 404
