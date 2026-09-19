from app.controller import MainController
from orchestrator.state import OrchestratorState


def test_saved_experiment_clock_survives_gui_projection_and_checkpoint_roundtrip():
    clock = {"run_id": "clock-run", "started_at": "2026-09-18T10:52:39+00:00",
             "source": "workflow_trigger_accepted"}
    state = OrchestratorState(run_id="clock-run", experiment_id="experiment",
                              run_metadata={"run_clock": clock})
    restored = OrchestratorState.model_validate_json(state.model_dump_json())
    projected = MainController._compact_planning_state_for_display(restored.model_dump(mode="json"))
    assert projected["run_metadata"]["run_clock"] == clock
