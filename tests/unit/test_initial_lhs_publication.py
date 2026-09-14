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
    assert contract["requested_parameters"] == {
        key: contract["initial_design"]["points"][0]["parameters"][key]
        for key in ("cell_size_mm", "relative_density")}


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
