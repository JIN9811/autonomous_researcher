"""3DP placement API/UI coverage without launching slicers or devices."""
from html.parser import HTMLParser
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_3dp_exposes_placement_and_removes_standalone_motion_controls():
    from app.main import app

    class Controls(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = set()

        def handle_starttag(self, tag, attrs):
            value = dict(attrs).get("id")
            if value:
                self.ids.add(value)

    response = TestClient(app).get("/printer")
    assert response.status_code == 200
    controls = Controls()
    controls.feed(response.text)
    assert {"printer-placement-mode", "printer-placement-x", "printer-placement-y"} <= controls.ids
    for direction in ("left", "center", "right"):
        assert f"btn-printer-autoejection-validate-{direction}" not in controls.ids
        assert f"btn-printer-eject-{direction}" not in controls.ids
    assert "btn-printer-autoejection-patch-artifact" in controls.ids
    assert "btn-printer-autoejection-completion-audit" in controls.ids


def test_slice_api_uses_saved_placement_unless_operator_overrides(monkeypatch):
    from app import main
    captured = []
    manager = SimpleNamespace(config=SimpleNamespace(slicer=None),
        fleet_selection=lambda: (SimpleNamespace(provider="bambulab_x2d"), "fixture"),
        _selected_printer_payload=lambda *args: {})
    monkeypatch.setattr(main, "_printer_bridge_manager", lambda: manager)
    monkeypatch.setattr(main, "load_prusa_print_profile", lambda: {"specimen_placement": {
        "mode": "custom", "center_x_mm": 110, "center_y_mm": 145}})

    class Runner:
        def __init__(self, *args, **kwargs):
            pass

        def slice(self, **kwargs):
            captured.append(kwargs)
            return {"ok": True, "slicer": {"available": True}, "specimen_placement": kwargs.get("specimen_placement")}

    monkeypatch.setattr(main, "BambuStudioSlicerRunner", Runner)
    client = TestClient(main.app)
    saved = client.post("/api/printer/bambu-slice-artifact", json={"source_path": "cube.stl"})
    assert saved.status_code == 200
    assert saved.json()["specimen_placement"] == {"mode": "custom", "center_x_mm": 110, "center_y_mm": 145}
    override = client.post("/api/printer/bambu-slice-artifact", json={"source_path": "cube.stl", "specimen_placement": {"mode": "bed_center"}})
    assert override.json()["specimen_placement"]["mode"] == "bed_center"
    bad = client.post("/api/printer/bambu-slice-artifact", json={"source_path": "cube.stl", "specimen_placement": {"mode": "custom", "center_x_mm": -4}})
    assert bad.status_code == 422
    assert len(captured) == 2


def test_controller_defaults_keep_placement_for_design_handoff(monkeypatch):
    from app import controller
    from utils.printer_profile import DEFAULT_PRUSA_PRINT_PROFILE
    from orchestrator.state import Mode
    placement = {"mode": "custom", "center_x_mm": 110, "center_y_mm": 145}
    monkeypatch.setattr(controller, "load_prusa_print_profile", lambda: {**DEFAULT_PRUSA_PRINT_PROFILE, "specimen_placement": placement})
    obj = object.__new__(controller.MainController)
    obj._state = SimpleNamespace(loop_count=0, run_id="placement-fixture", mode=Mode.TEST)
    assert obj._validated_printer_defaults()["specimen_placement"] == placement
    assert obj._default_test_constraints({})["specimen_placement"] == placement
    assert obj._build_planning_spec(base_spec={}, constraints={})["specimen_placement"] == placement


async def test_design_preserves_operator_placement_across_bo_redesign():
    from agents.design_agent import DesignAgent
    from orchestrator.state import Mode, OrchestratorState, Stage
    placement = {"mode": "custom", "center_x_mm": 110, "center_y_mm": 145}
    state = OrchestratorState(run_id="placement-fixture", experiment_id="fixture", mode=Mode.TEST,
        stage=Stage.DESIGN, active_goal="compression energy", current_experiment_spec={"specimen_placement": placement},
        run_metadata={"bo_recommended_constraints": {"cell_size_mm": 5, "relative_density": 0.32}})
    ctx = SimpleNamespace(force_real_llm_in_test=False, failure_memory=SimpleNamespace(recent=lambda **kwargs: []))
    result = await DesignAgent().run(state, ctx)
    assert result.success
    assert result.data["experiment_spec"]["specimen_placement"] == placement
