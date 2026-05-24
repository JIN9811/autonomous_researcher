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

    def call(self, name: str, payload: dict[str, object] | None = None) -> dict[str, object]:
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
