"""Initial DSN intake publishes BO's real LHS before any measurements exist."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.bootstrap import load_runtime
from orchestrator.state import Mode, Stage


@pytest.mark.parametrize("test_mode", [True, False])
def test_design_intake_requests_configured_lhs_in_test_and_live(test_mode):
    controller = load_runtime()
    controller._state.mode = Mode.TEST if test_mode else Mode.LIVE
    constraints = controller._default_test_constraints({}) if test_mode else {}
    constraints["design_optimization"] = {
        "initial_design": {"sampler": "latin_hypercube", "size": 3, "seed": 11}}
    controller._publish_orchestrator_design_contract(constraints, cycle_index=1, total_cycles=20)
    contract = controller._state.run_metadata["orchestrator_design_contract"]
    assert len(contract["initial_design"]["points"]) == 3
    if test_mode:
        for point in contract["initial_design"]["points"]:
            assert 0.6 <= point["parameters"]["wall_thickness_mm"] <= 1.2
            assert 5.0 <= point["parameters"]["cell_size_mm"] <= 10.0
    assert contract["requested_parameters"] == {
        key: contract["initial_design"]["points"][0]["parameters"][key]
        for key in ("cell_size_mm", "wall_thickness_mm")}


@pytest.mark.asyncio
async def test_initial_lhs_publishes_real_figure_once_before_bo_result(tmp_path, monkeypatch):
    controller = load_runtime()
    controller._logger_bundle = replace(controller._logger_bundle, run_dir=tmp_path)
    controller._state.run_id = "initial-lhs-test"
    constraints = controller._default_test_constraints({})
    controller._publish_orchestrator_design_contract(constraints, cycle_index=1, total_cycles=20)
    assert not controller._state.run_metadata.get("bo_agent")
    async def design_step():
        # Stub only actual agent execution: publication must happen before entry.
        assert controller._state.run_metadata.get("lhs_visualization", {}).get("artifacts", {}).get("png_url")
        controller._state.stage = Stage.SPECIMEN
    monkeypatch.setattr(controller, "_new_execution_run_loop", lambda **kwargs:
                        SimpleNamespace(step=design_step, _state=controller._state))
    await controller._run_planning_langgraph_stage(Stage.DESIGN)
    payload = controller._state.run_metadata["lhs_visualization"]
    assert payload["run_id"] == "initial-lhs-test"
    assert payload["initial_design"]["completed"] == 0
    assert len(payload["initial_design"]["points"]) == 8
    assert payload["artifacts"]["png_url"].startswith("/api/runs/initial-lhs-test/artifact-file/")
    pngs = list(tmp_path.rglob("*.png"))
    assert len(pngs) == 1 and pngs[0].read_bytes().startswith(b"\x89PNG")
    timestamp = pngs[0].stat().st_mtime_ns
    await controller._publish_initial_lhs_visualization()
    assert pngs[0].stat().st_mtime_ns == timestamp
    assert len(controller._state.run_metadata["lhs_visualization_steps"]) == 1
    events = [e for e in controller.recent_events() if e.get("event_type") == "lhs.visualization.updated"]
    assert len(events) == 1
    assert events[0]["payload"]["visualization"]["run_id"] == "initial-lhs-test"


@pytest.mark.asyncio
async def test_design_completion_revises_same_step_without_faking_measurements(tmp_path):
    from copy import deepcopy
    from experiments.lhs_progress import record_design_ready
    controller = load_runtime()
    controller._logger_bundle = replace(controller._logger_bundle, run_dir=tmp_path)
    state = controller._state
    state.run_id = "lhs-design-progress-test"
    controller._publish_orchestrator_design_contract(controller._default_test_constraints({}), cycle_index=1, total_cycles=20)
    await controller._publish_initial_lhs_visualization()
    before = deepcopy(state.run_metadata["lhs_visualization"])
    spec = before["initial_design"]["points"][0]["parameters"]
    await record_design_ready(state, controller._deps.agent_context, spec)
    after = state.run_metadata["lhs_visualization"]
    assert after["step"] == before["step"]
    assert after["revision"] > before["revision"]
    assert after["artifacts"]["png_url"] != before["artifacts"]["png_url"]
    assert after["initial_design"]["designed"] == 1
    assert after["initial_design"]["completed"] == 0
    assert after["initial_design"]["points"][0]["status"] == "designed"
    assert state.experiment_evaluations == []
    measured = deepcopy(after)
    measured["initial_design"]["points"][0]["status"] = "measured"
    await controller.emit_lhs_visualization(measured, source="test-measurement")
    await controller._publish_initial_lhs_visualization()
    assert state.run_metadata["lhs_visualization"]["initial_design"]["completed"] == 1
    stale = deepcopy(measured)
    stale["run_id"] = "different-run"
    assert (await controller.emit_lhs_visualization(stale, source="test"))["reason"] == "stale_run"
