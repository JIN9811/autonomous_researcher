"""Behavior tests for BO's bounded local decision boundary."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from threading import Event
from time import monotonic

import pytest

from agents.bo_decision import run_bo_decision


class _Response:
    def __init__(self, payload, *, mock: bool = False) -> None:
        self.text = payload if isinstance(payload, str) else json.dumps(payload)
        self.model = "registered-test-model"
        self.raw = {"mock": mock} if mock else {}


class _Context:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    async def complete(self, task_type, prompt, *, timeout_s=None):
        self.calls.append((task_type, prompt, timeout_s))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return _Response(response)


def _request(tool, arguments, refs):
    return {
        "tool": tool,
        "arguments": arguments,
        "reason": f"exercise {tool}",
        "evidence_refs": refs,
    }


def _decision_context():
    return {
        "run_id": "run-bo-decision",
        "loop_number": 2,
        "goal": "optimize the measured compression objective",
        "objective": {
            "objective_id": "objective-1",
            "objective_hash": "sha256:objective-1",
            "metric_name": "energy_density_50pct_MJ_per_m3",
            "direction": "maximize",
        },
        "parameter_space": {
            "cell_size_mm": [6.2, 9.1],
            "relative_density": [0.27, 0.39],
            "wall_thickness_mm": [1.2],
        },
        "observations": [
            {"candidate_id": "measured-1", "parameters": {"cell_size_mm": 6.5, "relative_density": 0.28}, "score": 0.41, "ok_for_bo": True},
            {"candidate_id": "measured-2", "parameters": {"cell_size_mm": 8.8, "relative_density": 0.38}, "score": 0.66, "ok_for_bo": True},
        ],
        "knowledge": {"memory_summary": "Local manufacturing notes are available."},
    }


def _optimizer_result():
    return {
        "ok": True,
        "candidate_id": "solver-candidate-007",
        "parameters": {"cell_size_mm": 7.137891, "relative_density": 0.347281, "wall_thickness_mm": 1.2},
        "numeric": {"surrogate_mean": 0.72, "uncertainty": 0.08, "acquisition_value": 0.11},
    }


@pytest.mark.asyncio
async def test_configured_policy_inspects_retrieves_runs_once_and_accepts_solver_candidate():
    responses = [
        _request("inspect_diagnostics", {}, ["context:observations"]),
        _request("retrieve_knowledge", {"query": "gyroid printability", "top_k": 2}, ["context:request"]),
        _request("run_optimizer", {}, ["context:request", "context:observations", "knowledge:local-1"]),
        _request("accept_recommendation", {"candidate_id": "solver-candidate-007"}, ["candidate:solver-candidate-007"]),
    ]
    ctx = _Context(responses)
    context = _decision_context()
    original = deepcopy(context)
    optimizer_calls = []

    async def optimizer(strategy_settings):
        optimizer_calls.append(dict(strategy_settings))
        return _optimizer_result()

    async def retrieve(query, top_k):
        assert (query, top_k) == ("gyroid printability", 2)
        return [{"source_id": "local-1", "source": "Project_guide.md", "text": "Keep walls printable."}]

    decision = await run_bo_decision(
        context=context,
        ctx=ctx,
        settings={"strategy_control": "configured", "acquisition": "upper_confidence_bound", "kappa": 2.4},
        run_optimizer=optimizer,
        retrieve_knowledge=retrieve,
    )

    assert context == original
    assert optimizer_calls == [{"acquisition": "upper_confidence_bound", "kappa": 2.4}]
    assert decision["status"] == "accepted"
    assert decision["candidate_id"] == "solver-candidate-007"
    assert decision["optimizer_result"] == _optimizer_result()
    assert decision["diagnostics"]["observation_count"] == 2
    assert decision["diagnostics"]["duplicate_count"] == 0
    assert decision["diagnostics"]["domain_coverage"] > 0.7
    assert decision["knowledge"][0]["source_id"] == "local-1"
    assert all(call[0] == "bo_policy" for call in ctx.calls)


@pytest.mark.asyncio
async def test_adaptive_policy_may_change_only_bounded_numeric_strategy_settings():
    ctx = _Context([
        _request("inspect_diagnostics", {}, ["context:observations"]),
        _request(
            "run_optimizer",
            {"acquisition": "probability_of_improvement", "xi": 0.08, "exploration_weight": 0.4, "exploitation_weight": 0.6},
            ["context:request", "diagnostics:current"],
        ),
        _request("accept_recommendation", {"candidate_id": "solver-candidate-007"}, ["candidate:solver-candidate-007"]),
    ])
    seen = []

    async def optimizer(strategy_settings):
        seen.append(dict(strategy_settings))
        return _optimizer_result()

    decision = await run_bo_decision(
        context=_decision_context(),
        ctx=ctx,
        settings={"strategy_control": "adaptive", "acquisition": "expected_improvement", "xi": 0.01},
        run_optimizer=optimizer,
    )

    assert decision["status"] == "accepted"
    assert seen == [{
        "acquisition": "probability_of_improvement",
        "xi": 0.08,
        "exploration_weight": 0.4,
        "exploitation_weight": 0.6,
    }]


@pytest.mark.asyncio
async def test_identical_solver_candidate_can_be_accepted_or_returned_to_owner():
    async def run(final_request):
        ctx = _Context([
            _request("inspect_diagnostics", {}, ["context:observations"]),
            _request("run_optimizer", {}, ["context:request", "diagnostics:current"]),
            final_request,
        ])

        async def optimizer(_settings):
            return _optimizer_result()

        return await run_bo_decision(
            context=_decision_context(), ctx=ctx,
            settings={"strategy_control": "configured", "acquisition": "expected_improvement"},
            run_optimizer=optimizer,
        )

    accepted = await run(_request("accept_recommendation", {"candidate_id": "solver-candidate-007"}, ["candidate:solver-candidate-007"]))
    returned = await run(_request("return_to_owner", {}, ["candidate:solver-candidate-007"]))

    assert accepted["status"] == "accepted"
    assert returned["status"] == "returned"
    assert returned["optimizer_result"] == accepted["optimizer_result"]


@pytest.mark.asyncio
async def test_return_to_owner_before_optimization_does_not_dispatch_numeric_tool():
    ctx = _Context([
        _request("return_to_owner", {}, ["context:request"]),
    ])
    calls = []

    async def optimizer(settings):
        calls.append(settings)
        return _optimizer_result()

    decision = await run_bo_decision(
        context=_decision_context(), ctx=ctx,
        settings={"strategy_control": "configured", "acquisition": "expected_improvement"},
        run_optimizer=optimizer,
    )

    assert decision["status"] == "returned"
    assert decision["optimizer_result"] is None
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("blocking_callback", ["optimizer", "knowledge"])
async def test_sync_callbacks_cannot_block_decision_deadline_responsiveness(blocking_callback):
    responses = (
        [_request("inspect_diagnostics", {}, ["context:observations"]),
         _request("run_optimizer", {}, ["context:request", "diagnostics:current"])]
        if blocking_callback == "optimizer"
        else [_request("retrieve_knowledge", {"query": "local evidence", "top_k": 1}, ["context:request"])]
    )
    ctx = _Context(responses)
    release = Event()

    def optimizer(_settings):
        if blocking_callback == "optimizer":
            release.wait(1.0)
        return _optimizer_result()

    def retrieve(_query, _top_k):
        if blocking_callback == "knowledge":
            release.wait(1.0)
        return []

    started = monotonic()
    decision = await run_bo_decision(
        context=_decision_context(), ctx=ctx,
        settings={
            "strategy_control": "configured", "acquisition": "expected_improvement",
            "decision_call_timeout_s": 0.03, "decision_total_timeout_s": 0.1,
        },
        run_optimizer=optimizer,
        retrieve_knowledge=retrieve,
    )
    elapsed = monotonic() - started
    release.set()

    assert elapsed < 0.2
    assert decision["status"] == "failed"
    assert decision["failure_code"] == "BO_DECISION_TIMEOUT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_request",
    [
        "not-json",
        _request("shell", {}, ["context:request"]),
        _request("run_optimizer", {}, ["unknown:evidence"]),
        _request("run_optimizer", {"cell_size_mm": 8.0}, ["context:request"]),
        _request("run_optimizer", {"objective": {"metric_name": "other"}}, ["context:request"]),
        _request("run_optimizer", {"parameter_space": {"cell_size_mm": [8.0, 9.0]}}, ["context:request"]),
    ],
)
async def test_invalid_requests_are_archived_as_failed_without_optimizer_dispatch(bad_request):
    ctx = _Context([bad_request])
    calls = []

    async def optimizer(settings):
        calls.append(settings)
        return _optimizer_result()

    decision = await run_bo_decision(
        context=_decision_context(), ctx=ctx,
        settings={"strategy_control": "adaptive", "acquisition": "expected_improvement"},
        run_optimizer=optimizer,
    )

    assert calls == []
    assert decision["status"] == "failed"
    assert decision["failure_code"] == "BO_DECISION_INVALID"
    assert decision["trace"][-1]["status"] == "invalid"


@pytest.mark.asyncio
async def test_configured_operator_numeric_strategy_is_preserved_without_adaptive_caps():
    ctx = _Context([
        _request("inspect_diagnostics", {}, ["context:observations"]),
        _request("run_optimizer", {}, ["context:request", "diagnostics:current"]),
        _request("accept_recommendation", {"candidate_id": "solver-candidate-007"}, ["candidate:solver-candidate-007"]),
    ])
    calls = []

    async def optimizer(settings):
        calls.append(settings)
        return _optimizer_result()

    decision = await run_bo_decision(
        context=_decision_context(), ctx=ctx,
        settings={"strategy_control": "configured", "acquisition": "expected_improvement", "kappa": 25.0, "xi": 1.2},
        run_optimizer=optimizer,
    )

    assert calls == [{"acquisition": "expected_improvement", "kappa": 25.0, "xi": 1.2}]
    assert decision["status"] == "accepted"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("control", "configured_kappa", "arguments"),
    [
        ("adaptive", 2.0, {"kappa": 99.0}),
        ("configured", float("inf"), {}),
    ],
)
async def test_invalid_model_bounds_or_nonfinite_configured_values_block_dispatch(control, configured_kappa, arguments):
    ctx = _Context([
        _request("inspect_diagnostics", {}, ["context:observations"]),
        _request("run_optimizer", arguments, ["context:request", "diagnostics:current"]),
    ])
    calls = []

    async def optimizer(settings):
        calls.append(settings)
        return _optimizer_result()

    decision = await run_bo_decision(
        context=_decision_context(), ctx=ctx,
        settings={"strategy_control": control, "acquisition": "expected_improvement", "kappa": configured_kappa},
        run_optimizer=optimizer,
    )

    assert calls == []
    assert decision["status"] == "failed"
    assert decision["failure_code"] == "BO_DECISION_INVALID"


@pytest.mark.asyncio
async def test_second_optimizer_request_fails_without_a_second_dispatch():
    ctx = _Context([
        _request("inspect_diagnostics", {}, ["context:observations"]),
        _request("run_optimizer", {}, ["context:request", "diagnostics:current"]),
        _request("run_optimizer", {}, ["candidate:solver-candidate-007"]),
    ])
    calls = 0

    async def optimizer(_settings):
        nonlocal calls
        calls += 1
        return _optimizer_result()

    decision = await run_bo_decision(
        context=_decision_context(), ctx=ctx,
        settings={"strategy_control": "configured", "acquisition": "expected_improvement"},
        run_optimizer=optimizer,
    )

    assert calls == 1
    assert decision["status"] == "failed"
    assert decision["failure_code"] == "BO_DECISION_INVALID"


@pytest.mark.asyncio
async def test_unknown_or_modified_candidate_cannot_be_accepted():
    ctx = _Context([
        _request("inspect_diagnostics", {}, ["context:observations"]),
        _request("run_optimizer", {}, ["context:request", "diagnostics:current"]),
        _request("accept_recommendation", {"candidate_id": "invented", "parameters": {"cell_size_mm": 8.0}}, ["candidate:solver-candidate-007"]),
    ])

    async def optimizer(_settings):
        return _optimizer_result()

    decision = await run_bo_decision(
        context=_decision_context(), ctx=ctx,
        settings={"strategy_control": "configured", "acquisition": "expected_improvement"},
        run_optimizer=optimizer,
    )

    assert decision["status"] == "failed"
    assert decision["optimizer_result"]["parameters"]["cell_size_mm"] == 7.137891


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["undeclared_parameter", "nonfinite_numeric"])
async def test_invalid_numeric_optimizer_artifact_is_preserved_but_cannot_be_accepted(mutation):
    ctx = _Context([
        _request("inspect_diagnostics", {}, ["context:observations"]),
        _request("run_optimizer", {}, ["context:request", "diagnostics:current"]),
    ])
    invalid = _optimizer_result()
    if mutation == "undeclared_parameter":
        invalid["parameters"]["arbitrary_coordinate"] = 4.2
    else:
        invalid["numeric"]["acquisition_value"] = float("inf")

    async def optimizer(_settings):
        return invalid

    decision = await run_bo_decision(
        context=_decision_context(), ctx=ctx,
        settings={"strategy_control": "configured", "acquisition": "expected_improvement"},
        run_optimizer=optimizer,
    )

    assert decision["status"] == "failed"
    assert decision["failure_code"] == "BO_DECISION_INVALID"
    assert decision["optimizer_result"] == invalid
    assert decision["trace"][-1]["result"]["candidate_id"] == "solver-candidate-007"


@pytest.mark.asyncio
async def test_mock_or_failed_llm_is_not_silently_replaced_by_a_successful_decision():
    class MockContext(_Context):
        async def complete(self, task_type, prompt, *, timeout_s=None):
            return _Response(_request("run_optimizer", {}, ["context:request"]), mock=True)

    calls = []

    async def optimizer(settings):
        calls.append(settings)
        return _optimizer_result()

    decision = await run_bo_decision(
        context=_decision_context(), ctx=MockContext([]),
        settings={"strategy_control": "configured", "acquisition": "expected_improvement"},
        run_optimizer=optimizer,
    )

    assert calls == []
    assert decision["status"] == "failed"
    assert decision["provenance"] == "llm"


@pytest.mark.asyncio
async def test_virtual_test_uses_the_same_dispatch_and_records_virtual_provenance():
    class NeverComplete:
        async def complete(self, *args, **kwargs):
            raise AssertionError("virtual decision should not require inference")

    calls = []

    async def optimizer(settings):
        calls.append(dict(settings))
        return _optimizer_result()

    decision = await run_bo_decision(
        context=_decision_context(), ctx=NeverComplete(),
        settings={"strategy_control": "configured", "acquisition": "expected_improvement", "kappa": 2.0},
        run_optimizer=optimizer,
        virtual_test=True,
    )

    assert calls == [{"acquisition": "expected_improvement", "kappa": 2.0}]
    assert [entry["request"]["tool"] for entry in decision["trace"]] == [
        "inspect_diagnostics", "run_optimizer", "accept_recommendation"
    ]
    assert decision["status"] == "accepted"
    assert decision["provenance"] == "virtual_test"


@pytest.mark.asyncio
async def test_lhs_candidate_with_unavailable_posterior_fields_is_valid_not_nonfinite():
    class NeverComplete:
        async def complete(self, *args, **kwargs):
            raise AssertionError

    lhs_result = _optimizer_result()
    lhs_result["numeric"] = {}
    lhs_result["phase"] = "initial_design"

    async def optimizer(_settings):
        return lhs_result

    decision = await run_bo_decision(
        context=_decision_context(), ctx=NeverComplete(),
        settings={"strategy_control": "configured", "acquisition": "expected_improvement"},
        run_optimizer=optimizer, virtual_test=True,
    )

    assert decision["status"] == "accepted"
    assert decision["optimizer_result"]["phase"] == "initial_design"
    assert decision["diagnostics"]["optimizer_result_finite"] is None


@pytest.mark.asyncio
async def test_cancelled_optimizer_propagates_cancellation():
    ctx = _Context([
        _request("inspect_diagnostics", {}, ["context:observations"]),
        _request("run_optimizer", {}, ["context:request", "diagnostics:current"]),
    ])

    async def optimizer(_settings):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_bo_decision(
            context=_decision_context(), ctx=ctx,
            settings={"strategy_control": "configured", "acquisition": "expected_improvement"},
            run_optimizer=optimizer,
        )
