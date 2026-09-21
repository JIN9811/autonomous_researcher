"""Test-only BO preset snapshot and ordinary chat admission; no hardware I/O."""
from copy import deepcopy
import json

import pytest

from app.bootstrap import load_runtime
from app.planning_dialogue import dialogue_for
from tests.unit.test_planning_dialogue import response

pytestmark = pytest.mark.usefixtures("handoff_no_external")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    import app.test_bo_settings as settings
    path = tmp_path / "bo_workspace_settings.json"
    monkeypatch.setattr(settings, "WORKSPACE_SETTINGS_PATH", path)
    path.write_text(json.dumps({"initial_design_size": 12, "parameter_space": {
        "cell_size_mm": [6, 9], "wall_thickness_mm": [0.7, 1.1]},
        "mode": "live", "objective_direction": "minimize"}))
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["virtual_bridge", "installed_printer", "physical_print"])
async def test_test_entry_snapshots_only_bo_inputs(workspace, monkeypatch, path):
    c = load_runtime()
    captured = {}
    monkeypatch.setattr(c._test_scenario, "start", lambda **kw: captured.update(kw) or True)
    result = await c._run_test_mode_planning(goal=None, constraints={"printer_test_path": path}, operator_message="테스트 모드")
    assert result["ok"]
    values = captured["constraints"]
    assert values["initial_design_size"] == 12
    assert values["cell_size_bounds_mm"] == [6, 9]
    assert values["wall_thickness_bounds_mm"] == [0.7, 1.1]
    assert values["objective_direction"] == "maximize"
    assert values.get("mode") != "live"
    assert values["printer_test_path"] == path
    assert "cell_size_mm" not in values  # A search range is not a fixed candidate.
    assert "wall_thickness_mm" not in values
    snapshot = deepcopy(dialogue_for(c).test_bo_defaults)
    workspace.write_text(json.dumps({"initial_design_size": 3}))
    assert dialogue_for(c).test_bo_defaults == snapshot
    assert captured["constraints"]["initial_design_size"] == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("test_mode", [True, False])
async def test_chat_overrides_snapshot_and_reaches_bo(workspace, monkeypatch, test_mode):
    from agents.bo.agent import BOAgent
    from utils.gyroid_contract import parameter_space
    c = load_runtime()
    c._bind_planning_session(None)
    c._planning_setup_projection()
    if test_mode:
        monkeypatch.setattr(c._test_scenario, "start", lambda **kw: True)
        await c._run_test_mode_planning(goal=None, constraints={}, operator_message="테스트 모드")
    d = dialogue_for(c)
    values = {"goal": "Maximize SEA", "material": "PLA", "specimen_size_mm": [30, 30, 30],
              "geometry_type": "gyroid", "cell_size_bounds_mm": [5.5, 8.5],
              "wall_thickness_bounds_mm": [0.8, 1.0], "initial_design_size": 5}
    utterance = " ".join(str(value) for value in values.values())
    replies = iter([response("review", "조건 확인 후 시작할까요?", [
        {"field": key, "value": value, "source_quote": str(value)} for key, value in values.items()]),
        response("execute", "시작하겠습니다.")])
    async def model(**kw):
        return next(replies), "ok"
    admitted = {}
    async def boundary(**kw):
        admitted.update(kw["constraints"])
        return {"ok": True}
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    monkeypatch.setattr(c, "_planning_message_locked", boundary)
    assert (await d.turn(utterance, intent="change_setup"))["ok"], getattr(d, "last_error", None)
    assert (await d.turn("네 시작", intent="confirm_pending"))["ok"], getattr(d, "last_error", None)
    assert admitted["design_optimization"]["initial_design"]["size"] == 5
    assert parameter_space(admitted) == {"cell_size_mm": [5.5, 8.5], "wall_thickness_mm": [0.8, 1.0]}
    c._state.current_experiment_spec = deepcopy(admitted)
    c._state.run_metadata["bo_settings"] = {"parameter_space": parameter_space(admitted)}
    request = BOAgent.initial_design_request(c._state)
    assert len(request["points"]) == 5
    for point in request["points"]:
        assert 5.5 <= point["parameters"]["cell_size_mm"] <= 8.5
        assert 0.8 <= point["parameters"]["wall_thickness_mm"] <= 1.0


def test_missing_file_preserves_defaults(workspace):
    from app.test_bo_settings import load_test_bo_defaults
    workspace.unlink()
    assert load_test_bo_defaults() == {"initial_design_size": 8,
        "cell_size_bounds_mm": [5.0, 10.0], "wall_thickness_bounds_mm": [0.6, 1.2]}


@pytest.mark.asyncio
async def test_invalid_saved_settings_do_not_start(workspace, monkeypatch):
    workspace.write_text('{"initial_design_size": -2}')
    c = load_runtime()
    monkeypatch.setattr(c._test_scenario, "start", lambda **kw: pytest.fail("Invalid preset started"))
    result = await c._run_test_mode_planning(goal=None, constraints={}, operator_message="테스트 모드")
    assert not result["ok"]
    assert "BO" in result["message"]


@pytest.mark.asyncio
async def test_chat_lhs_count_is_supported_and_validated():
    d = dialogue_for(load_runtime())
    assert d._updates([{"field": "initial_design_size", "value": 6, "source_quote": "6"}], "LHS 6", "change_setup") == {"initial_design_size": 6}
    with pytest.raises(ValueError):
        d._updates([{"field": "initial_design_size", "value": 1, "source_quote": "1"}], "LHS 1", "change_setup")


@pytest.mark.asyncio
@pytest.mark.parametrize("test_mode", [True, False])
async def test_saved_defaults_review_admission_contract_and_lhs(workspace, monkeypatch, test_mode):
    c = load_runtime()
    c._bind_planning_session(None)
    c._planning_setup_projection()
    if test_mode:
        monkeypatch.setattr(c._test_scenario, "start", lambda **kw: True)
        await c._run_test_mode_planning(goal=None, constraints={}, operator_message="테스트 모드")
    else:
        # Real experiment must not even try to read the workspace file.
        monkeypatch.setattr("app.test_bo_settings.load_test_bo_defaults", lambda: pytest.fail("Read test preset in live mode"))
    d = dialogue_for(c)
    spoken = {"goal": "Maximize SEA", "material": "PLA", "specimen_size_mm": [30, 30, 30], "geometry_type": "gyroid"}
    if not test_mode:
        spoken.update(cell_size_bounds_mm=[5, 10], wall_thickness_bounds_mm=[0.6, 1.2])
    monkeypatch.setattr(d, "values", lambda: deepcopy(spoken))
    async def model(*, prompt):
        packet = json.loads(prompt)
        if test_mode:
            assert packet["agreed_inputs"]["initial_design_size"] == 12
            assert packet["agreed_inputs"]["cell_size_bounds_mm"] == [6, 9]
        else:
            assert "initial_design_size" not in packet["agreed_inputs"]
        return response("execute" if d.pending else "review", "조건을 확인했습니다."), "ok"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    admitted = {}
    async def boundary(**kw):
        admitted.update(kw["constraints"])
        c._publish_orchestrator_design_contract(admitted, cycle_index=1, total_cycles=20)
        return {"ok": True}
    monkeypatch.setattr(c, "_planning_message_locked", boundary)
    assert (await d.turn("조건 검토", intent="change_setup"))["ok"], getattr(d, "last_error", None)
    workspace.write_text(json.dumps({"initial_design_size": 3}))
    assert (await d.turn("네 시작", intent="confirm_pending"))["ok"], getattr(d, "last_error", None)
    contract = c._state.run_metadata["orchestrator_design_contract"]
    assert contract["initial_design"]["target"] == (12 if test_mode else 8)
    assert contract["parameter_space"]["cell_size_mm"] == ([6, 9] if test_mode else [5, 10])
    if not test_mode:
        assert "design_optimization" not in admitted


@pytest.mark.asyncio
async def test_explicit_request_overrides_saved_preset(workspace, monkeypatch):
    c = load_runtime()
    c._bind_planning_session(None)
    captured = {}
    monkeypatch.setattr(c._test_scenario, "start", lambda **kw: captured.update(kw) or True)
    result = await c._run_test_mode_planning(goal=None, operator_message="테스트 모드", constraints={
        "design_optimization": {"initial_design": {"size": 4, "seed": 11}},
        "cell_size_bounds_mm": [5.5, 8.5], "wall_thickness_bounds_mm": [0.8, 1.0]})
    assert result["ok"]
    assert captured["constraints"]["initial_design_size"] == 4
    assert captured["constraints"]["design_optimization"]["initial_design"]["seed"] == 11
    assert dialogue_for(c).test_bo_defaults["cell_size_bounds_mm"] == [5.5, 8.5]


@pytest.mark.asyncio
async def test_new_test_preset_wins_over_previous_conversation(workspace, monkeypatch):
    c = load_runtime()
    c._bind_planning_session(None)
    c._planning_setup_projection()
    d = dialogue_for(c)
    old = {"initial_design_size": 4, "cell_size_bounds_mm": [5, 8], "wall_thickness_bounds_mm": [0.8, 1.0]}
    monkeypatch.setattr(d, "values", lambda: deepcopy(old))
    monkeypatch.setattr(c._test_scenario, "start", lambda **kw: True)
    await c._run_test_mode_planning(goal=None, constraints={}, operator_message="테스트 모드")
    async def model(*, prompt):
        packet = json.loads(prompt)
        assert packet["agreed_inputs"]["initial_design_size"] == 12
        assert packet["agreed_inputs"]["cell_size_bounds_mm"] == [6, 9]
        return response("collect", "재료와 목표는 무엇인가요?"), "ok"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    assert (await d.turn("테스트 계획", intent="change_setup"))["ok"]


def test_new_lhs_count_beats_retained_run_metadata():
    from app.test_bo_settings import with_initial_design
    c = load_runtime()
    c._state.run_metadata["bo_settings"] = {"initial_design_size": 8}
    c._state.run_metadata["orchestrator_design_contract"] = {"optimization": {"initial_design": {"size": 8}}}
    c._state.current_experiment_spec = {"design_optimization": {"initial_design": {"size": 8}}}
    constraints = with_initial_design({"initial_design_size": 12,
        "cell_size_bounds_mm": [6, 9], "wall_thickness_bounds_mm": [0.7, 1.1]})
    c._publish_orchestrator_design_contract(constraints, cycle_index=1, total_cycles=20)
    contract = c._state.run_metadata["orchestrator_design_contract"]
    assert contract["initial_design"]["target"] == 12
    assert len(contract["initial_design"]["points"]) == 12


@pytest.mark.asyncio
async def test_initial_trigger_values_reach_validated_dialogue(workspace, monkeypatch):
    from types import SimpleNamespace
    c = load_runtime()
    c._bind_planning_session(None)
    c._planning_setup_projection()
    monkeypatch.setattr(c._test_scenario, "start", lambda **kw: True)
    trigger = "테스트 모드, LHS 4개로"
    await c._run_test_mode_planning(goal=None, constraints={}, operator_message=trigger)
    driver = c._test_scenario
    driver.goal = "Maximize SEA"
    driver.constraints = {"initial_design_size": 12}
    driver.trigger_message = trigger
    driver.session_id = c._planning_session_id
    d = dialogue_for(c)
    pending = {"kind": "conversation", "pending_id": "inputs", "purpose": "provide_inputs"}
    d.pending = pending
    async def model(*, prompt):
        packet = json.loads(prompt)
        if packet["operation"] == "test_scenario_reply":
            return SimpleNamespace(text=json.dumps({"action": "reply", "fields": [], "message": "조건을 정할게요."})), "ok"
        assert trigger in packet["message"]
        return response("collect", "재료는 무엇인가요?", [{"field": "initial_design_size", "value": 4, "source_quote": "4"}]), "ok"
    async def shared_chat(message, **kw):
        return await d.turn(message, intent="confirm_pending")
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    monkeypatch.setattr(c, "planning_message", shared_chat)
    assert await driver.answer_pending(pending)
    assert d.test_bo_defaults["initial_design_size"] == 4
    assert d.values()["initial_design_size"] == 4
