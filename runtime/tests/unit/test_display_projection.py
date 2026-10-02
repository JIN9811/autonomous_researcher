"""Display polling must not serialize discarded control/history payloads."""
import json

from app.controller import MainController
from app.bootstrap import load_runtime


def test_display_projection_skips_full_state_dump_and_detaches(monkeypatch):
    controller = load_runtime()
    controller._state.current_experiment_spec = {"candidate_id": "test", "specimen_size_mm": [30, 30, 30]}
    # Snapshot export is deliberately still full-fidelity; GUI projection is not.
    def forbidden(*args, **kwargs):
        raise AssertionError("Display serialized the complete control state")
    monkeypatch.setattr(type(controller._state), "model_dump", forbidden)
    payload = controller.display_snapshot()
    assert isinstance(payload["state"]["stage"], str)
    json.dumps(payload)
    payload["state"]["current_experiment_spec"]["specimen_size_mm"][0] = 999
    assert controller._state.current_experiment_spec["specimen_size_mm"][0] == 30


def test_receipt_projection_ignores_archived_history():
    class NeverVisit(dict):
        def items(self):
            raise AssertionError("Traversed archived history")
    projected = MainController._compact_planning_run_metadata({
        "orchestrator_checkpoints": NeverVisit({"huge": {}}),
    })
    assert "orchestrator_checkpoints" not in projected


def test_display_reuses_owner_resolution_only_within_one_call(monkeypatch):
    import app.controller as module
    controller = load_runtime()
    calls = []
    original = module.load_graph_config
    def load(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(module, "load_graph_config", load)
    controller._planning_setup_projection()
    assert len(calls) == 1
    controller._planning_setup_projection()
    assert len(calls) == 2  # New file resolution for every new request.
    assert module._DISPLAY_OWNER_CATALOG.get() is None
