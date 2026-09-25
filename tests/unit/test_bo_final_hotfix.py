"""Code-only publication must refuse an in-flight BO call and retain the run."""
from types import SimpleNamespace

import pytest

from orchestrator.state import OrchestratorState, Stage


def test_hotfix_refuses_bo_boundary_and_keeps_state():
    from app.bo_final_hotfix import assert_boundary
    state = OrchestratorState(run_id="unchanged", experiment_id="exp", stage=Stage.BO)
    controller = SimpleNamespace(_state=state)
    with pytest.raises(ValueError, match="BO"):
        assert_boundary(controller)
    state.stage = Stage.SPECIMEN
    assert_boundary(controller)
    assert state.run_id == "unchanged"
    assert controller._state is state


def test_staging_does_not_execute_source_module_and_publishes_in_place(tmp_path):
    from app.bo_final_hotfix import stage_function, publish
    def old(value):
        return value + 1
    alias = old
    path = tmp_path / "source.py"
    path.write_text('raise RuntimeError("must not execute module")\n'
                    'def old(value):\n    return value + 2\n')
    candidate = stage_function(old, path)
    assert old(1) == 2
    publish([(old, candidate)])
    assert alias(1) == 3
