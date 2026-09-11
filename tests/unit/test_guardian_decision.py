"""Behavior tests for Guardian's bounded evidence decision layer."""

from __future__ import annotations

import asyncio
import json
import math
import threading
from time import monotonic
from typing import Any

import pytest

from agents.guardian_agent import GuardianAgent
from knowledge.failure_memory import FailureMemory, FailureRecord
from orchestrator.state import Mode, OrchestratorState, Stage


def _valid_spec() -> dict[str, object]:
    return {
        "candidate_id": "candidate-current",
        "specimen_id": "specimen-current",
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


def _state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-current",
        experiment_id="experiment-current",
        mode=Mode.LIVE,
        stage=Stage.GUARDIAN,
        current_experiment_spec=_valid_spec(),
        latest_observations={"anomaly": False},
        latest_analysis={"objective_score": 0.7, "uncertainty": 0.1},
    )


class _Response:
    def __init__(self, request: dict[str, Any] | str) -> None:
        self.text = json.dumps(request) if isinstance(request, dict) else request
        self.model = "guardian-test-model"
        self.raw: dict[str, object] = {}


class _Tools:
    def __init__(
        self,
        *,
        health: list[dict[str, Any]] | None = None,
        queue: dict[str, Any] | BaseException | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.health = list(health or [])
        self.queue = queue if queue is not None else {"ok": True, "queued": 0, "running": 0}

    def call(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((name, dict(payload or {})))
        if name == "device.health":
            if self.health:
                return self.health.pop(0)
            return {
                "ok": True,
                "printer": "ready",
                "camera": "ready",
                "robot": "ready",
                "utm": "ready",
                "simulator": "active",
            }
        if name == "experiment.queue.status":
            if isinstance(self.queue, BaseException):
                raise self.queue
            return dict(self.queue)
        raise KeyError(name)


class _Context:
    def __init__(
        self,
        responses: list[dict[str, Any] | str],
        *,
        tools: _Tools | None = None,
        on_complete: Any = None,
    ) -> None:
        self.failure_memory = FailureMemory()
        self.tools = tools or _Tools()
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.on_complete = on_complete

    async def complete(self, task_type: str, user_prompt: str, *, timeout_s: float | None = None) -> _Response:
        assert task_type == "guardian_reasoning"
        self.prompts.append(user_prompt)
        if self.on_complete is not None:
            await self.on_complete(len(self.prompts))
        return _Response(self.responses.pop(0))


class _BlockingContext(_Context):
    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def complete(self, task_type: str, user_prompt: str, *, timeout_s: float | None = None) -> _Response:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("unreachable")


class _BlockingQueueTools(_Tools):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def call(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if name == "experiment.queue.status":
            self.calls.append((name, dict(payload or {})))
            self.entered.set()
            self.release.wait(timeout=2.0)
            return {"ok": True, "queued": 0}
        return super().call(name, payload)


class _BlockingInitialHealthTools(_Tools):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def call(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((name, dict(payload or {})))
        if name != "device.health":
            raise KeyError(name)
        self.entered.set()
        self.release.wait(timeout=0.7)
        return {"ok": True, "printer": "ready", "robot": "ready"}


@pytest.mark.asyncio
async def test_structured_review_escalates_normal_guardian_route_to_recover() -> None:
    ctx = _Context(
        [
            {"tool": "guardian.evidence.read", "arguments": {"section": "baseline"}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "review",
                    "reason": "The current run needs operator review.",
                    "evidence_refs": ["baseline:action"],
                },
            },
        ]
    )

    result = await GuardianAgent().run(_state(), ctx)
    guardian = result.data["guardian"]

    assert guardian["decision"] == "continue"
    assert guardian["action"] == "recover"
    assert guardian["llm_decision"]["status"] == "accepted"
    assert guardian["llm_decision"]["llm_used"] is True
    assert guardian["llm_decision"]["action"] == "review"
    assert guardian["llm_decision"]["trace"][0]["tool"] == "guardian.evidence.read"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed",
    [
        "not json",
        '{"tool":"guardian.decision.submit","arguments":{},"tool":"device.health"}',
        '{"tool":"guardian.decision.submit","arguments":{}} trailing',
        '{"tool":"guardian.decision.submit","arguments":{"action":"continue","reason":"x","evidence_refs":[],"score":NaN}}',
    ],
)
async def test_malformed_model_output_holds_for_review(malformed: str) -> None:
    result = await GuardianAgent().run(_state(), _Context([malformed]))

    guardian = result.data["guardian"]
    assert guardian["decision"] == "continue"
    assert guardian["action"] == "recover"
    assert guardian["llm_decision"]["status"] == "review_required"


@pytest.mark.asyncio
async def test_preexisting_stop_skips_model() -> None:
    state = _state()
    state.stop_requested = True
    ctx = _Context([])

    result = await GuardianAgent().run(state, ctx)

    assert result.data["guardian"]["action"] == "safe_stop"
    assert result.data["guardian"]["llm_decision"]["status"] == "skipped"
    assert ctx.prompts == []
    assert ctx.tools.calls == []


@pytest.mark.asyncio
async def test_stop_interrupts_initial_health_read_promptly() -> None:
    state = _state()
    tools = _BlockingInitialHealthTools()
    ctx = _Context([], tools=tools)

    def request_stop() -> None:
        tools.entered.wait(timeout=0.2)
        state.stop_requested = True

    stopper = threading.Thread(target=request_stop)
    stopper.start()
    started = monotonic()
    try:
        result = await GuardianAgent().run(state, ctx)
    finally:
        tools.release.set()
        stopper.join(timeout=0.2)

    assert monotonic() - started < 0.5
    assert result.data["guardian"]["action"] == "safe_stop"
    assert ctx.prompts == []


@pytest.mark.asyncio
async def test_concurrent_stop_interrupts_waiting_model_promptly() -> None:
    state = _state()
    ctx = _BlockingContext()
    task = asyncio.create_task(GuardianAgent().run(state, ctx))
    await asyncio.wait_for(ctx.started.wait(), timeout=0.2)

    state.stop_requested = True
    result = await asyncio.wait_for(task, timeout=0.5)

    assert result.data["guardian"]["action"] == "safe_stop"
    assert ctx.cancelled.is_set()


@pytest.mark.asyncio
async def test_caller_cancellation_is_not_swallowed() -> None:
    ctx = _BlockingContext()
    task = asyncio.create_task(GuardianAgent().run(_state(), ctx))
    await asyncio.wait_for(ctx.started.wait(), timeout=0.2)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ctx.cancelled.is_set()


@pytest.mark.asyncio
async def test_structured_continue_cannot_clear_existing_recovery_gate() -> None:
    state = _state()
    state.run_metadata["guardian_gates"] = [
        {
            "gate_id": "gate-current",
            "stage": "analysis",
            "decision": "block",
            "reason_code": "DATA_QUALITY_LOW",
        }
    ]
    ctx = _Context(
        [
            {"tool": "guardian.evidence.read", "arguments": {"section": "graph_gates"}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "The gate is visible.",
                    "evidence_refs": ["validation:graph_gates"],
                },
            },
        ]
    )

    result = await GuardianAgent().run(state, ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_device_health_observation_can_escalate_to_safe_stop() -> None:
    ctx = _Context(
        [
            {"tool": "device.health", "arguments": {}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "safe_stop",
                    "reason": "Fresh health reports the robot offline.",
                    "evidence_refs": ["health:fresh"],
                },
            },
        ],
        tools=_Tools(
            health=[
                {"ok": True, "printer": "ready", "robot": "ready"},
                {"ok": True, "printer": "ready", "robot": "offline"},
            ]
        ),
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "safe_stop"
    assert "robot:offline" in str(result.data["guardian"]["llm_decision"]["trace"])
    assert "health:fresh" in ctx.prompts[1]


@pytest.mark.asyncio
async def test_fresh_health_fault_cannot_support_structured_continue() -> None:
    ctx = _Context(
        [
            {"tool": "device.health", "arguments": {}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "Continue after the fresh health read.",
                    "evidence_refs": ["health:fresh"],
                },
            },
        ],
        tools=_Tools(
            health=[
                {"ok": True, "printer": "ready", "robot": "ready"},
                {"ok": True, "printer": "ready", "robot": "offline"},
            ]
        ),
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "safe_stop"
    assert result.data["guardian"]["health_validation"]["status"] == "fail"


@pytest.mark.asyncio
async def test_initial_unknown_health_floor_is_not_lost_on_final_local_recheck() -> None:
    state = _state()
    ctx = _Context(
        [
            {"tool": "guardian.evidence.read", "arguments": {"section": "health"}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "Continue despite unavailable health.",
                    "evidence_refs": ["validation:health"],
                },
            },
        ],
        tools=_Tools(health=[]),
    )

    def unavailable_health(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx.tools.calls.append((name, dict(payload or {})))
        raise RuntimeError("health unavailable")

    ctx.tools.call = unavailable_health  # type: ignore[method-assign]
    result = await GuardianAgent().run(state, ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["health_validation"]["status"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "health_payload",
    [
        {},
        {"status": "unavailable"},
        {"printer": None},
        {"printer": math.nan},
        {"printer": math.inf},
    ],
)
async def test_empty_or_unavailable_health_payload_cannot_support_continue(
    health_payload: dict[str, Any],
) -> None:
    ctx = _Context(
        [
            {"tool": "guardian.evidence.read", "arguments": {"section": "health"}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "Continue from the health response.",
                    "evidence_refs": ["validation:health"],
                },
            },
        ],
        tools=_Tools(health=[health_payload]),
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["health_validation"]["status"] == "unknown"
    assert result.data["guardian"]["health_validation"]["query_status"] == "unavailable"


@pytest.mark.asyncio
async def test_production_nested_printer_health_ready_can_support_continue() -> None:
    ctx = _Context(
        [
            {"tool": "guardian.evidence.read", "arguments": {"section": "health"}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "The production-shaped health evidence is ready.",
                    "evidence_refs": ["validation:health"],
                },
            },
        ],
        tools=_Tools(
            health=[{
                "ok": True,
                "printer": {"ok": True, "state": "SIMULATED_READY", "provider": "prusa_mk4s"},
                "camera": "ready",
                "robot": "ready",
                "utm": "ready",
                "simulator": "active",
            }]
        ),
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "continue"
    assert result.data["guardian"]["health_validation"]["status"] == "pass"


@pytest.mark.asyncio
async def test_production_nested_printer_health_offline_forces_safe_stop() -> None:
    ctx = _Context(
        [],
        tools=_Tools(
            health=[{
                "ok": False,
                "printer": {
                    "ok": False,
                    "state": "offline",
                    "provider": "prusa_mk4s",
                    "failure_code": "PRINTER_UNREACHABLE",
                },
                "camera": "ready",
                "robot": "ready",
                "utm": "ready",
                "simulator": "mixed",
            }]
        ),
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "safe_stop"
    assert result.data["guardian"]["health_validation"]["status"] == "fail"
    assert "printer:offline" in result.data["guardian"]["health_validation"]["unhealthy_devices"]
    assert ctx.prompts == []


@pytest.mark.asyncio
async def test_nested_health_false_flag_cannot_be_masked_by_ready_state() -> None:
    ctx = _Context(
        [],
        tools=_Tools(
            health=[{
                "ok": True,
                "printer": {"ok": False, "state": "ready", "provider": "prusa_mk4s"},
                "camera": "ready",
                "robot": "ready",
                "utm": "ready",
                "simulator": "active",
            }]
        ),
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "safe_stop"
    assert "printer:failed" in result.data["guardian"]["health_validation"]["unhealthy_devices"]
    assert ctx.prompts == []


@pytest.mark.asyncio
async def test_nonfinite_current_evidence_holds_for_review_instead_of_raising() -> None:
    state = _state()
    state.latest_observations["sensor_score"] = math.nan
    ctx = _Context([])

    result = await GuardianAgent().run(state, ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["status"] == "review_required"
    assert result.data["guardian"]["llm_decision"]["failure_code"] == "GUARDIAN_EVIDENCE_INVALID"
    assert ctx.prompts == []


@pytest.mark.asyncio
async def test_identity_only_evidence_cannot_support_continue() -> None:
    ctx = _Context(
        [
            {"tool": "guardian.evidence.read", "arguments": {"section": "identity"}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "The identity is current.",
                    "evidence_refs": ["identity:current"],
                },
            },
        ]
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["status"] == "review_required"


@pytest.mark.asyncio
async def test_current_observation_detail_is_available_to_model_after_read() -> None:
    state = _state()
    state.latest_observations["review_note"] = "fresh camera-vs-analysis conflict"
    ctx = _Context(
        [
            {"tool": "guardian.evidence.read", "arguments": {"section": "observations"}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "review",
                    "reason": "The current evidence conflicts.",
                    "evidence_refs": ["observations:current"],
                },
            },
        ]
    )

    result = await GuardianAgent().run(state, ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert "fresh camera-vs-analysis conflict" in ctx.prompts[1]


@pytest.mark.asyncio
async def test_failed_queue_query_cannot_be_followed_by_continue() -> None:
    ctx = _Context(
        [
            {"tool": "experiment.queue.status", "arguments": {}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "Continue despite missing queue evidence.",
                    "evidence_refs": ["baseline:action"],
                },
            },
        ],
        tools=_Tools(queue=RuntimeError("unavailable")),
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["status"] == "review_required"


@pytest.mark.asyncio
async def test_stop_interrupts_waiting_synchronous_readonly_tool() -> None:
    state = _state()
    tools = _BlockingQueueTools()
    ctx = _Context([{"tool": "experiment.queue.status", "arguments": {}}], tools=tools)
    task = asyncio.create_task(GuardianAgent().run(state, ctx))
    entered = await asyncio.to_thread(tools.entered.wait, 0.3)
    assert entered is True

    state.stop_requested = True
    try:
        result = await asyncio.wait_for(task, timeout=0.5)
    finally:
        tools.release.set()

    assert result.data["guardian"]["action"] == "safe_stop"


@pytest.mark.asyncio
async def test_queue_query_is_code_bound_to_current_identity() -> None:
    ctx = _Context(
        [
            {"tool": "experiment.queue.status", "arguments": {}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "The current queue is clear.",
                    "evidence_refs": ["queue:shared_runtime_status"],
                },
            },
        ]
    )

    result = await GuardianAgent().run(_state(), ctx)

    queue_calls = [call for call in ctx.tools.calls if call[0] == "experiment.queue.status"]
    assert queue_calls == [
        (
            "experiment.queue.status",
            {
                "run_id": "run-current",
                "experiment_id": "experiment-current",
                "loop_count": 0,
                "loop_id": 0,
                "specimen_id": "specimen-current",
            },
        )
    ]
    assert result.data["guardian"]["action"] == "continue"
    assert result.data["guardian"]["llm_decision"]["schema"] == "guardian_evidence_decision.v1"


@pytest.mark.asyncio
async def test_foreign_queue_identity_cannot_support_continue() -> None:
    ctx = _Context(
        [
            {"tool": "experiment.queue.status", "arguments": {}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "The reported queue is clear.",
                    "evidence_refs": ["queue:shared_runtime_status"],
                },
            },
        ],
        tools=_Tools(queue={"ok": True, "run_id": "run-foreign", "queued": 0}),
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["status"] == "review_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "queue",
    [
        {"ok": True, "loop_id": 99, "queued": 0},
        {"ok": True, "specimen_id": "specimen-foreign", "queued": 0},
        {"ok": False, "status": "failed", "queued": 0},
        {"ok": True, "queued": math.nan},
        {"ok": True, "queued": math.inf},
    ],
)
async def test_failed_or_foreign_queue_observation_cannot_support_continue(queue: dict[str, Any]) -> None:
    ctx = _Context(
        [
            {"tool": "experiment.queue.status", "arguments": {}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "Continue from the queue result.",
                    "evidence_refs": ["queue:shared_runtime_status"],
                },
            },
        ],
        tools=_Tools(queue=queue),
    )

    result = await GuardianAgent().run(_state(), ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["status"] == "review_required"


@pytest.mark.asyncio
async def test_duplicate_request_budget_holds_for_review() -> None:
    state = _state()
    state.run_metadata["guardian_settings"] = {"max_duplicate_requests": 0}
    ctx = _Context(
        [
            {"tool": "guardian.evidence.read", "arguments": {"section": "baseline"}},
            {"tool": "guardian.evidence.read", "arguments": {"section": "baseline"}},
        ]
    )

    result = await GuardianAgent().run(state, ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["failure_code"] == "GUARDIAN_DUPLICATE_BUDGET"


@pytest.mark.asyncio
async def test_state_mutation_during_decision_holds_for_review() -> None:
    state = _state()

    async def mutate_on_second_call(call_number: int) -> None:
        if call_number == 2:
            state.latest_observations["anomaly"] = True

    ctx = _Context(
        [
            {"tool": "guardian.evidence.read", "arguments": {"section": "baseline"}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "continue",
                    "reason": "No issue in the earlier snapshot.",
                    "evidence_refs": ["baseline:action"],
                },
            },
        ],
        on_complete=mutate_on_second_call,
    )

    result = await GuardianAgent().run(state, ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["failure_code"] == "GUARDIAN_SCOPE_CHANGED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings",
    [
        {"max_turns": 0},
        {"max_duplicate_requests": -1},
        {"call_timeout_s": math.nan},
        {"call_timeout_s": 0},
        {"total_timeout_s": math.inf},
    ],
)
async def test_invalid_guardian_settings_hold_without_calling_model(settings: dict[str, Any]) -> None:
    state = _state()
    state.run_metadata["guardian_settings"] = settings
    ctx = _Context([])

    result = await GuardianAgent().run(state, ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["failure_code"] == "GUARDIAN_SETTINGS_INVALID"
    assert ctx.prompts == []


@pytest.mark.asyncio
async def test_turn_budget_expiry_holds_for_review() -> None:
    state = _state()
    state.run_metadata["guardian_settings"] = {"max_turns": 1}
    ctx = _Context([{"tool": "guardian.evidence.read", "arguments": {"section": "baseline"}}])

    result = await GuardianAgent().run(state, ctx)

    assert result.data["guardian"]["action"] == "recover"
    assert result.data["guardian"]["llm_decision"]["failure_code"] == "GUARDIAN_DECISION_BUDGET"


@pytest.mark.asyncio
async def test_historical_failures_are_labeled_unresolved_context() -> None:
    ctx = _Context(
        [
            {"tool": "guardian.failures.read", "arguments": {"limit": 1}},
            {
                "tool": "guardian.decision.submit",
                "arguments": {
                    "action": "review",
                    "reason": "The historical fault warrants review.",
                    "evidence_refs": ["failures:historical"],
                },
            },
        ]
    )
    ctx.failure_memory.add(
        FailureRecord(stage="equipment", failure_type="old_fault", context={"run_id": "run-old"})
    )

    result = await GuardianAgent().run(_state(), ctx)

    observation = result.data["guardian"]["llm_decision"]["trace"][0]["observation"]
    assert observation["historical"] is True
    assert observation["resolved"] is False
    assert observation["failures"][0]["failure_type"] == "old_fault"
