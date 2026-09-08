"""Behavioral tests for the bounded Design decision layer; no device tools."""
import json
import asyncio
from types import SimpleNamespace

import pytest

from agents.design_agent import DesignAgent
from orchestrator.state import Mode, OrchestratorState, Stage


def state_for_test():
    return OrchestratorState(run_id="", experiment_id="decision-test", mode=Mode.TEST,
                             stage=Stage.DESIGN, active_goal="maximize energy absorption")


def request(tool, candidate_id=None, **extra):
    return {"tool": tool, "arguments": {"candidate_id": candidate_id} if candidate_id else {},
            "reason": "Review available design evidence", "evidence_refs":
            [f"candidate:{candidate_id}"] if candidate_id else ["context:request"], **extra}


class ModelContext:
    force_real_llm_in_test = True
    tools = None

    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    async def complete(self, task_type, prompt, **kwargs):
        self.prompts.append(prompt)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(text=json.dumps(response), model="controlled-test-model", raw={})


@pytest.mark.asyncio
async def test_model_selects_nonfirst_candidate_and_legacy_scores_are_not_evidence():
    ctx = ModelContext([request("inspect_candidate", "cand-1-08"), request("accept_candidate", "cand-1-08")])
    result = await DesignAgent().run(state_for_test(), ctx)
    assert result.success
    assert result.data["experiment_spec"]["candidate_id"] == "cand-1-08"
    assert len(ctx.prompts) == 2
    assert "expected_objective_proxy_score" not in "".join(ctx.prompts)
    assert "information_gain_score" not in "".join(ctx.prompts)
    evaluation = result.data["experiment_spec"]["design_evaluation"]
    assert evaluation["validity"]["status"] == "pass"
    assert evaluation["performance"]["status"] == "unassessed"
    assert evaluation["cost"]["mass"]["unit"] == "g"
    assert len(result.data["design_decision"]["trace"]) == 2
    assert result.data["handoff_packet"]["experiment_spec"]["candidate_id"] == "cand-1-08"


@pytest.mark.asyncio
async def test_model_can_escalate_after_inspection_without_emitting_ready_spec():
    ctx = ModelContext([request("inspect_candidate", "cand-1-08"), request("return_to_owner")])
    result = await DesignAgent().run(state_for_test(), ctx)
    assert not result.success
    assert "experiment_spec" not in result.data
    assert result.data["design_decision"]["status"] == "returned"
    assert len(ctx.prompts) == 2
    assert result.data["design_report"]["handoff_to_specimen"]["required_fields_present"] is False
    assert result.data["design_agent_report"]["status"] == "returned"
    from policies.validation_policy import validate_agent_output
    assert validate_agent_output("design", result.data) == (True, "ok")


@pytest.mark.asyncio
async def test_history_cannot_be_cited_before_it_is_read():
    ctx = ModelContext([request("return_to_owner", evidence_refs=["context:history"])])
    result = await DesignAgent().run(state_for_test(), ctx)
    assert result.data["design_decision"]["failure_code"] == "DESIGN_DECISION_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [request("printer.start"), request("accept_candidate", "unknown"),
    request("accept_candidate", "cand-1-08", arguments={"candidate_id":"cand-1-08", "relative_density":0.1}),
    request("accept_candidate", "cand-1-08", evidence_refs=["fabricated:evidence"]),
    {"tool":"accept_candidate"}])
async def test_invalid_requests_never_emit_ready_handoff(response):
    result = await DesignAgent().run(state_for_test(), ModelContext([response]))
    assert not result.success
    assert "experiment_spec" not in result.data
    assert result.data["design_decision"]["status"] == "failed"


@pytest.mark.asyncio
async def test_forced_llm_timeout_does_not_silently_select_a_candidate():
    result = await DesignAgent().run(state_for_test(), ModelContext([TimeoutError("model timeout")]))
    assert not result.success
    assert "experiment_spec" not in result.data


@pytest.mark.asyncio
async def test_empty_valid_pool_is_not_repaired_into_unchecked_success():
    state = state_for_test()
    state.current_experiment_spec = {"constraints":{"max_mass_g":0.01}}
    result = await DesignAgent().run(state, ModelContext([request("accept_candidate", "cand-1-safe")]))
    assert not result.success
    assert "experiment_spec" not in result.data


@pytest.mark.asyncio
async def test_locked_bo_request_is_preserved_in_model_selected_design():
    state = state_for_test()
    state.run_metadata["orchestrator_design_contract"] = {
        "contract_id":"locked", "requested_parameters":{"cell_size_mm":6.0,"relative_density":0.37}}
    result = await DesignAgent().run(state, ModelContext([request("accept_candidate", "cand-1-08")]))
    assert result.success
    spec = result.data["experiment_spec"]
    assert spec["cell_size_mm"] == 6.0
    assert spec["relative_density"] == 0.37
    assert spec["requested_parameters"] == spec["realized_parameters"]


@pytest.mark.asyncio
async def test_repeated_inspections_end_at_configured_budget():
    state = state_for_test()
    state.run_metadata["design_decision_settings"] = {"max_calls":2, "timeout_s":5}
    ctx = ModelContext([request("inspect_candidate", "cand-1-08")]*3)
    result = await DesignAgent().run(state, ctx)
    assert not result.success
    assert len(ctx.prompts) == 2
    assert result.data["design_decision"]["failure_code"] == "DESIGN_DECISION_BUDGET_EXHAUSTED"


@pytest.mark.asyncio
async def test_cancellation_propagates_without_handoff():
    class CancelContext(ModelContext):
        async def complete(self, *args, **kwargs):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await DesignAgent().run(state_for_test(), CancelContext([]))


@pytest.mark.asyncio
async def test_evidence_is_archived_separately_for_each_loop(tmp_path):
    state = state_for_test()
    state.run_id = "archive-design-decision"
    for loop_index in (0, 1):
        state.loop_count = loop_index
        # Generate the IDs from the caller's loop identity, not the implementation's winner.
        cid = f"cand-{loop_index + 1}-01"
        ctx = ModelContext([request("accept_candidate", cid)])
        ctx.artifact_run_root = str(tmp_path)
        result = await DesignAgent().run(state, ctx)
        assert result.success
        assert result.data["design_decision"]["loop_number"] == loop_index + 1
    reports = list(tmp_path.rglob("result.json"))
    assert len(reports) == 2
    saved = [json.loads(p.read_text()) for p in reports]
    assert {r["data"]["design_decision"]["loop_number"] for r in saved} == {1, 2}


@pytest.mark.asyncio
async def test_cancellation_keeps_completed_tool_evidence(tmp_path):
    state = state_for_test()
    state.run_id = "cancelled-design-decision"

    class CancelContext(ModelContext):
        async def complete(self, task_type, prompt, **kwargs):
            if self.prompts:
                raise asyncio.CancelledError()
            return await super().complete(task_type, prompt, **kwargs)

    ctx = CancelContext([request("inspect_candidate", "cand-1-08")])
    ctx.artifact_run_root = str(tmp_path)
    with pytest.raises(asyncio.CancelledError):
        await DesignAgent().run(state, ctx)
    events = "\n".join(p.read_text() for p in tmp_path.rglob("*.jsonl"))
    assert "design.inspect_candidate" in events
    assert "design_evaluation.v1" in events


def test_guardian_does_not_compare_measured_objective_to_marked_legacy_proxy():
    from agents.guardian_agent import GuardianAgent
    args = dict(latest_analysis={"objective_score":0.1}, latest_observations={},
                uncertainty=0, retry_pressure=0)
    legacy = GuardianAgent._consistency_check(spec={"expected_objective_proxy_score":0.9}, **args)
    assert any("proxy" in w for w in legacy["warnings"])
    current = GuardianAgent._consistency_check(spec={"expected_objective_proxy_score":0.9,
        "score_semantics":"legacy_heuristic_compatibility_only"}, **args)
    assert not any("proxy" in w for w in current["warnings"])


def test_controller_display_keeps_new_evidence_instead_of_only_legacy_score():
    from app.controller import MainController
    spec = {"candidate_id":"c1", "score_semantics":"legacy_heuristic_compatibility_only",
            "design_evaluation":{"schema":"design_evaluation.v1", "validity":{"status":"pass"}}}
    assert MainController._planning_display_spec(spec) == spec


def test_existing_cap_policy_does_not_reuse_evidence_for_changed_geometry():
    from app.controller import MainController
    agent = DesignAgent()
    source = agent._deterministic_spec(state_for_test(), ModelContext([]))
    source["test_mode_llm_generated"] = True
    controller = MainController.__new__(MainController)
    adapted = controller._apply_test_cycle_surface_cap_policy(source, cycle_index=1)
    assert adapted["bottom_cap_enabled"] is False
    final = agent.reconcile_planning_evidence(source, adapted)
    assert final["bottom_cap_enabled"] is False
    assert final["candidate_fingerprint"] == agent._candidate_fingerprint(final)
    evidence = final["design_evaluation"]
    assert evidence["validity"]["status"] == "unassessed"
    assert evidence["selection_evaluation"]["validity"]["status"] == "pass"
    assert evidence["candidate_fingerprint"] != evidence["selection_evaluation"]["candidate_fingerprint"]
    assert "bottom_cap_enabled" in evidence["adapted_fields"]
    assert evidence["cost"]["mass"]["value"] is None


@pytest.mark.asyncio
async def test_history_tool_returns_knowledge_without_relabeling_old_scores_as_predictions():
    state = state_for_test()
    state.run_metadata["knowledge"] = {"summary":"Previous specimen had a disconnected shell; inspect geometry."}
    ctx = ModelContext([request("inspect_history"), request("return_to_owner")])
    result = await DesignAgent().run(state, ctx)
    observation = result.data["design_decision"]["trace"][0]["result"]
    assert "disconnected shell" in json.dumps(observation)
    assert result.data["design_decision"]["status"] == "returned"


@pytest.mark.asyncio
async def test_initial_prompt_contains_only_authorized_candidate_details():
    ctx = ModelContext([request("accept_candidate", "cand-1-08")])
    await DesignAgent().run(state_for_test(), ctx)
    context = json.loads(ctx.prompts[0][ctx.prompts[0].index('{"context"'):])["context"]
    assert {c["candidate_id"] for c in context["candidates"]} == {"cand-1-01", "cand-1-08"}
    assert len(context["other_candidates"]) == 10


@pytest.mark.asyncio
async def test_previous_spec_is_context_not_a_new_lock_on_all_generated_variables():
    state = state_for_test()
    for loop in range(3):
        state.loop_count = loop
        state.run_metadata["orchestrator_design_contract"] = {"contract_id":f"loop-{loop}",
            "requested_parameters":{"cell_size_mm":6.0,"relative_density":0.3+0.02*loop}}
        result = await DesignAgent().run(state, ModelContext([request("accept_candidate", f"cand-{loop+1}-01")]))
        assert result.success
        state.current_experiment_spec = result.data["experiment_spec"]
        assert state.current_experiment_spec["relative_density"] == pytest.approx(0.3+0.02*loop)
