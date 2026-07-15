"""
Unit tests for GuardianAgent safety and decision policies.
"""

from __future__ import annotations

import pytest

from agents.guardian_agent import GuardianAgent
from knowledge.failure_memory import FailureMemory
from orchestrator.state import Mode, OrchestratorState, Stage


def _valid_spec() -> dict[str, object]:
    return {
        "candidate_id": "cand-1-01",
        "specimen_id": "specimen-cand-1-01",
        "geometry_type": "lattice_bcc",
        "specimen_size_mm": [30.0, 30.0, 30.0],
        "cell_size_mm": 6.0,
        "wall_thickness_mm": 1.2,
        "expected_mass_g": 8.5,
        "expected_print_time_min": 60.0,
        "expected_objective_proxy_score": 0.72,
        "top_bottom_cap": True,
        "constraints": {
            "max_specimen_size_mm": [30.0, 30.0, 30.0],
            "utm_fixture_limit_mm": [40.0, 40.0, 60.0],
            "nozzle_diameter_mm": 0.4,
            "minimum_feature_size_mm": 0.8,
            "max_mass_g": 50.0,
            "max_print_time_min": 120.0,
            "require_flat_compression_faces": True,
        },
    }


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text


class _ToolsStub:
    def __init__(self, *, health: dict[str, object] | None = None) -> None:
        self._health = health or {
            "ok": True,
            "printer": "ready",
            "camera": "ready",
            "robot": "ready",
            "utm": "ready",
            "simulator": "active",
        }
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call(self, name: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append((name, dict(payload or {})))
        if name != "device.health":
            raise KeyError(name)
        return dict(self._health)


class _CtxStub:
    def __init__(self, *, health: dict[str, object] | None = None, policy_note: str = "guardian policy") -> None:
        self.failure_memory = FailureMemory()
        self.tools = _ToolsStub(health=health)
        self._policy_note = policy_note

    async def complete(self, task_type: str, user_prompt: str, *, timeout_s: float | None = None) -> _Response:
        return _Response(self._policy_note)


def _state(
    *,
    mode: Mode = Mode.TEST,
    loop_count: int = 0,
    spec: dict[str, object] | None = None,
    precursor: float = 0.2,
    recovery_suggested: bool = False,
    uncertainty: float = 0.1,
    objective_score: float = 0.7,
    anomaly: bool = False,
) -> OrchestratorState:
    return OrchestratorState(
        run_id="run-test",
        experiment_id="exp-test",
        mode=mode,
        stage=Stage.GUARDIAN,
        current_experiment_spec=spec or _valid_spec(),
        latest_observations={"anomaly": anomaly},
        latest_analysis={
            "objective_score": objective_score,
            "uncertainty": uncertainty,
            "sarm": {
                "failure_precursor": precursor,
                "recovery_suggested": recovery_suggested,
                "progress_score": 0.8,
            },
        },
        loop_count=loop_count,
    )


@pytest.mark.asyncio
async def test_guardian_passes_valid_spec_with_continue_action() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    result = await agent.run(_state(), ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "continue"
    assert guardian["action"] == "continue"
    assert guardian["design_validation"]["status"] == "pass"


@pytest.mark.asyncio
async def test_guardian_health_preserves_live_gui_installed_printer_route() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    spec = {
        **_valid_spec(),
        "test_mode_autofill": True,
        "printer_test_path": "installed_printer",
        "allow_test_printer_live": True,
        "test_printer_transport": "real",
        "printer_profile": "bambulab_x2d_pla_0p4_nozzle",
    }

    result = await agent.run(_state(mode=Mode.LIVE, spec=spec), ctx)

    assert result.success is True
    assert ctx.tools.calls
    name, payload = ctx.tools.calls[0]
    assert name == "device.health"
    assert payload["runtime_mode"] == "test"
    assert payload["printer_test_path"] == "installed_printer"
    assert payload["test_printer_path"] == "installed_printer"
    assert payload["allow_test_printer_live"] is True
    assert payload["test_printer_transport"] == "real"
    assert payload["printer_profile"] == "bambulab_x2d_pla_0p4_nozzle"


@pytest.mark.asyncio
async def test_guardian_stops_on_design_validation_failure() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    broken_spec = _valid_spec()
    broken_spec.pop("candidate_id")

    result = await agent.run(_state(spec=broken_spec), ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "stop"
    assert guardian["action"] == "safe_stop"
    assert guardian["design_validation"]["status"] == "fail"
    assert any(item.failure_type == "guardian_design_validation" for item in ctx.failure_memory.recent(10))


@pytest.mark.asyncio
async def test_guardian_stops_on_high_precursor() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()

    result = await agent.run(_state(mode=Mode.LIVE, precursor=0.95), ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "stop"
    assert guardian["action"] == "safe_stop"
    assert any(item.failure_type == "high_precursor" for item in ctx.failure_memory.recent(10))


@pytest.mark.asyncio
async def test_guardian_uses_recover_action_when_recovery_signal_present() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()

    result = await agent.run(_state(mode=Mode.LIVE, precursor=0.68, recovery_suggested=True), ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "continue"
    assert guardian["action"] == "recover"


@pytest.mark.asyncio
async def test_guardian_uses_retry_action_on_high_uncertainty() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()

    result = await agent.run(_state(uncertainty=0.36, precursor=0.2), ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "continue"
    assert guardian["action"] == "retry"


@pytest.mark.asyncio
async def test_guardian_stops_on_unhealthy_device() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub(health={"ok": True, "printer": "ready", "camera": "ready", "robot": "offline", "utm": "ready"})

    result = await agent.run(_state(mode=Mode.LIVE), ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "stop"
    assert guardian["action"] == "safe_stop"
    assert guardian["health_validation"]["status"] == "fail"

@pytest.mark.asyncio
async def test_guardian_stops_on_blocking_hardware_alert_metadata() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    state = _state(mode=Mode.LIVE)
    state.run_metadata["hardware_alerts"] = [
        {
            "schema": "hardware_alert.v1",
            "device_class": "robot",
            "component": "robot_io_port",
            "failure_code": "LEROBOT_DEVICE_PORT_REQUIRED",
            "blocks_workflow": True,
        }
    ]
    state.device_health["robot"] = "blocking:LEROBOT_DEVICE_PORT_REQUIRED"

    result = await agent.run(state, ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "stop"
    assert guardian["action"] == "safe_stop"
    assert guardian["health_validation"]["status"] == "fail"
    assert guardian["health_validation"]["active_hardware_alerts"][0]["component"] == "robot_io_port"

@pytest.mark.asyncio
async def test_guardian_recovers_when_analysis_blocks_utm_data_quality() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    state = _state(mode=Mode.LIVE, objective_score=0.0, uncertainty=0.2, precursor=0.2)
    state.latest_analysis.update(
        {
            "ok": False,
            "failure_code": "UTM_DATA_NO_FORCE_SIGNAL",
            "failure_tags": ["UTM_DATA_NO_FORCE_SIGNAL"],
            "equipment_handoff_gate": {"status": "ready_for_analysis", "blockers": []},
        }
    )

    result = await agent.run(state, ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "continue"
    assert guardian["action"] == "recover"
    assert guardian["consistency"]["status"] == "fail"
    assert any("analysis blocked" in item for item in guardian["consistency"]["issues"])
    assert any("UTM data/evidence" in item for item in guardian["consistency"]["warnings"])


@pytest.mark.asyncio
async def test_guardian_recovers_when_equipment_handoff_gate_blocked() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    state = _state(mode=Mode.LIVE, objective_score=0.0, uncertainty=0.2, precursor=0.2)
    state.latest_analysis.update(
        {
            "ok": False,
            "failure_code": "EQUIPMENT_HANDOFF_NOT_READY",
            "failure_tags": ["EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:request_audit_log_available"],
            "equipment_handoff_gate": {
                "status": "blocked",
                "failure_code": "EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:request_audit_log_available",
                "blockers": ["EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:request_audit_log_available"],
            },
        }
    )

    result = await agent.run(state, ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "continue"
    assert guardian["action"] == "recover"
    assert guardian["consistency"]["status"] == "fail"
    assert any("equipment handoff gate blocked" in item for item in guardian["consistency"]["issues"])


@pytest.mark.asyncio
async def test_guardian_recovers_when_multifidelity_trust_gate_blocks_bo() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    state = _state(mode=Mode.LIVE, objective_score=0.7, uncertainty=0.18, precursor=0.2)
    state.latest_analysis.update(
        {
            "ok": True,
            "trust_score": {
                "schema": "trust_score.v1",
                "score": 0.42,
                "gate": "block",
                "reasons": ["utm_fea_agreement_low"],
            },
            "multifidelity_comparison": {
                "schema": "multifidelity_comparison.v1",
                "curve": {"peak_force_error_pct": 58.0},
            },
        }
    )

    result = await agent.run(state, ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "continue"
    assert guardian["action"] == "recover"
    assert guardian["consistency"]["status"] == "fail"
    assert guardian["consistency"]["trust_score"]["gate"] == "block"
    assert any("multi-fidelity trust gate blocked" in item for item in guardian["consistency"]["issues"])


@pytest.mark.asyncio
async def test_guardian_recovers_on_blocking_graph_gate_metadata() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    state = _state(mode=Mode.LIVE, precursor=0.2, uncertainty=0.1)
    state.run_metadata["guardian_gates"] = [
        {
            "schema": "guardian_gate_result.v1",
            "gate_id": "gate-blocked-001",
            "stage": "analysis",
            "phase": "post",
            "decision": "block",
            "status": "blocked",
            "reason_code": "DATA_QUALITY_LOW",
            "risk_score": 0.78,
        }
    ]

    result = await agent.run(state, ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "continue"
    assert guardian["action"] == "recover"
    assert guardian["graph_gate_pressure"]["status"] == "fail"
    assert guardian["graph_gate_pressure"]["active_gate_count"] == 1


@pytest.mark.asyncio
async def test_guardian_safe_stops_on_graph_gate_safe_stop() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    state = _state(mode=Mode.LIVE, precursor=0.2, uncertainty=0.1)
    state.run_metadata["guardian_gates"] = [
        {
            "schema": "guardian_gate_result.v1",
            "gate_id": "gate-stop-001",
            "stage": "manipulation",
            "phase": "action",
            "decision": "safe_stop",
            "status": "blocked",
            "reason_code": "OPERATOR_STOP_REQUESTED",
            "risk_score": 0.93,
        }
    ]

    result = await agent.run(state, ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "stop"
    assert guardian["action"] == "safe_stop"
    assert any(item.failure_type == "guardian_gate_safe_stop" for item in ctx.failure_memory.recent(10))

@pytest.mark.asyncio
async def test_guardian_test_loop_cap_overrides_recoverable_graph_gate_pressure() -> None:
    agent = GuardianAgent()
    ctx = _CtxStub()
    state = _state(mode=Mode.TEST, loop_count=GuardianAgent.TEST_LOOP_CYCLE_LIMIT - 1, precursor=0.2, uncertainty=0.1)
    state.run_metadata["guardian_gates"] = [
        {
            "schema": "guardian_gate_result.v1",
            "gate_id": "gate-recoverable-001",
            "stage": "analysis",
            "phase": "post",
            "decision": "block",
            "status": "blocked",
            "reason_code": "DATA_QUALITY_LOW",
            "risk_score": 0.78,
        }
    ]

    result = await agent.run(state, ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "stop"
    assert guardian["action"] == "safe_stop"
    assert "5-cycle loop cap" in guardian["reason"]
