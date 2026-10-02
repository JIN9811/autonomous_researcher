"""Final-cycle reporting must fit the last measurement without proposing experiment N+1."""
from copy import deepcopy

import pytest

from learning.bo_parameter_space import BOParameterSpace
from learning.botorch_backend import propose_next
from agents.bo.agent import BOAgent
from orchestrator.state import OrchestratorState, Mode, Stage
from tests.unit.test_bo_agent import _CtxStub, _add_completed_lhs_observations


def forbid(*args, **kwargs):
    raise AssertionError("Final reporting must not request another experiment")


def test_final_fit_does_not_optimize_or_fabricate_candidate(monkeypatch):
    import botorch.optim
    monkeypatch.setattr(botorch.optim, "optimize_acqf", forbid)
    monkeypatch.setattr(botorch.optim, "optimize_acqf_mixed", forbid)
    result = propose_next(parameter_space=BOParameterSpace.from_mapping({
        "cell_size_mm": [5., 10.], "wall_thickness_mm": [.6, 1.2]}),
        observations=[{"parameters": {"cell_size_mm": x, "wall_thickness_mm": w}, "score": y}
                      for x, w, y in [(5., .6, 1.), (7., .9, 3.), (10., 1.2, 2.)]],
        report_only=True, fit_max_iter=5).to_dict()
    assert result["candidate"] == {}
    assert result["model"]["observation_count"] == 3
    assert result["optimizer"]["function"] == "not_run_final_report"
    assert result["projection"]["response_surface"]["mean"]
    assert result["projection"]["objective_path"].get("next_point_coordinate") is None


@pytest.mark.asyncio
async def test_final_agent_updates_posterior_and_artifacts_without_design_handoff(monkeypatch, tmp_path):
    import agents.bo.agent as module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(BOAgent, "_artifact_dir", staticmethod(lambda state: tmp_path / "bo"))
    monkeypatch.setattr(module, "run_bo_decision", forbid)
    state = OrchestratorState(run_id="final-run", experiment_id="final-exp", mode=Mode.TEST,
                              stage=Stage.BO, loop_count=14)
    state.run_metadata["planning_cycle_contract"] = {
        "schema": "planning_cycle_contract.v1", "total_cycles": 15, "mode": "test"}
    state.run_metadata["next_design_request"] = {"candidate_id": "stale"}
    state.run_metadata["bo_recommended_constraints"] = {"cell_size_mm": 5.}
    _add_completed_lhs_observations(state, count=15)
    before = deepcopy(state.experiment_evaluations)
    result = await BOAgent().run_with_settings(state, _CtxStub(), {
        "parameter_space": {"cell_size_mm": [5., 10.], "wall_thickness_mm": [.6, 1.6]}})
    assert result.success, result
    report = result.data["bo_result"]
    assert report["optimization_phase"] == "final_report"
    assert report["recommendation"] == {}
    assert not state.run_metadata.get("next_design_request")
    assert not state.run_metadata.get("bo_recommended_constraints")
    assert report["visualization"]["backend"]["training_count"] == 15
    assert not report["visualization"]["next_point"].get("parameters")
    assert report["visualization"]["step"] == 15
    assert report["artifacts"]
    assert any(name.endswith("_2d.png") for name in report["artifacts"])
    assert any(name.endswith("_3d.png") for name in report["artifacts"])
    assert state.experiment_evaluations == before


def test_final_chat_describes_completion_not_next_candidate():
    from app.controller import MainController
    text = MainController._format_planning_bo_message(object.__new__(MainController), {"bo_result": {
        "optimization_phase": "final_report", "model": {"observation_count": 15}, "budget": 15}})
    assert "15" in text
    assert "다음 후보를 생성하지" in text


@pytest.mark.asyncio
async def test_final_report_does_not_block_guardian_completion():
    from agents.core.guardian.agent import GuardianAgent
    from tests.unit.test_guardian_agent import _CtxStub as GuardianContext, _valid_spec
    state = OrchestratorState(run_id="final-guardian", experiment_id="exp", mode=Mode.TEST,
        stage=Stage.GUARDIAN, loop_count=14, current_experiment_spec=_valid_spec())
    state.run_metadata["bo_agent"] = {"ok": True, "optimization_phase": "final_report", "recommendation": {}}
    result = await GuardianAgent().run(state, GuardianContext())
    assert result.success
    assert result.data["guardian"]["decision"] in {"continue", "stop"}
    assert "fail" not in result.data["guardian"]["reason"].lower()


@pytest.mark.asyncio
async def test_no_measurements_cannot_claim_final_assessment(monkeypatch, tmp_path):
    monkeypatch.setattr(BOAgent, "_artifact_dir", staticmethod(lambda state: tmp_path))
    state = OrchestratorState(run_id="no-evidence", experiment_id="exp", mode=Mode.TEST,
                              stage=Stage.BO, loop_count=14)
    state.run_metadata["planning_cycle_contract"] = {
        "schema": "planning_cycle_contract.v1", "total_cycles": 15}
    result = await BOAgent().run_with_settings(state, _CtxStub(), {})
    assert not result.success
    assert result.data["bo_result"]["failure_code"] == "BO_VALID_OBSERVATION_REQUIRED"
