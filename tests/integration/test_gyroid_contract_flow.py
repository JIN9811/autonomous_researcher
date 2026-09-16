"""Isolated contract/cycle verification. No network, device, or live server I/O."""
import json
from types import SimpleNamespace
from pathlib import Path
import pytest

from utils.gyroid_contract import parameter_space, validate_candidate

@pytest.mark.parametrize("bounds", [[.8, 1.6], [.9, 1.4], [.87321, 1.37654]])
def test_continuous_contract_endpoints(bounds):
    values = {"cell_size_bounds_mm": [5.123, 9.987], "wall_thickness_bounds_mm": bounds}
    space = parameter_space(values, required=True)
    for cell in values["cell_size_bounds_mm"]:
        for density in bounds:
            validate_candidate({"cell_size_mm": cell, "wall_thickness_mm": density}, space)
    with pytest.raises(ValueError):
        validate_candidate({"wall_thickness_mm": bounds[0] - .000001}, space)

@pytest.mark.asyncio
@pytest.mark.usefixtures("handoff_no_external")
@pytest.mark.parametrize("test_mode", [True, False])
async def test_dialogue_setup_contract_lhs_design_cycle(monkeypatch, tmp_path, test_mode):
    from app.bootstrap import load_runtime
    from app.planning_dialogue import ResearchDialogue, missing_inputs
    from agents.design.agent import DesignAgent
    from tests.unit.test_design_agent import _DeterministicCtxStub
    from orchestrator.state import Mode, Stage
    c = load_runtime()
    c._bind_planning_session(None)
    d = ResearchDialogue(c)
    values = dict(goal="maximize SEA", material="PLA", geometry_type="gyroid", specimen_size_mm=[30,30,30])
    assert set(missing_inputs(values)) == {"cell_size_bounds_mm", "wall_thickness_bounds_mm"}
    values.update(cell_size_bounds_mm=[5.0,10.0], wall_thickness_bounds_mm=[.8,1.6])
    text = "maximize SEA PLA gyroid 30 mm cell 5 to 10 wall 0.8 to 1.6"
    quotes = dict(goal="maximize SEA", material="PLA", geometry_type="gyroid", specimen_size_mm="30 mm",
                  cell_size_bounds_mm="5 to 10", wall_thickness_bounds_mm="0.8 to 1.6")
    async def model(*, prompt):
        packet=json.loads(prompt)
        assert "0.4 mm" in packet["gyroid_research_policy"]
        return SimpleNamespace(model="isolated-model-fixture", raw={}, text=json.dumps(dict(action="review",
            answer="These ranges are ready. Candidates below the 0.4 mm wall limit will be rejected. Shall we run?",
            language="en", updates=[dict(field=k,value=v,source_quote=quotes[k]) for k,v in values.items()]))), "ok"
    monkeypatch.setattr(c,"_complete_live_planning_prompt",model)
    result=await d.turn(text,intent="change_setup")
    assert result["ok"], getattr(d,"last_error",None)
    assert d.values()==values
    blocks=c._planning_setup_projection()["blocks"]
    assert any(b["draft_values"].get("wall_thickness_bounds_mm")==[.8,1.6] for b in blocks)
    # Follow the real contract publisher and DSN preparation; no device dispatch.
    c._state.mode=Mode.TEST if test_mode else Mode.LIVE
    constraints={**values,"fdm_min_wall_thickness_mm":.4}
    if test_mode:
        constraints["test_mode_autofill"]=True
    admitted=c._publish_orchestrator_design_contract(constraints,cycle_index=1,total_cycles=3)
    contract=c._state.run_metadata["orchestrator_design_contract"]
    assert contract["parameter_space"]["wall_thickness_mm"]==[.8,1.6]
    assert contract["manufacturing_constraints"]["minimum_actual_wall_mm"]==.4
    assert c._state.run_metadata["bo_settings"]["parameter_space"]==parameter_space(values)
    c._state.current_experiment_spec={"constraints":admitted}
    c._state.stage=Stage.DESIGN
    from tests.unit.test_design_decision import ModelContext, request
    ctx=ModelContext([request("accept_candidate", "cand-1-01")])
    ctx.artifact_run_root=tmp_path
    design=await DesignAgent().run(c._state,ctx)
    assert design.success
    spec=design.data["experiment_spec"]
    for key,value in contract["requested_parameters"].items():
        assert spec[key]==value
    assert spec["design_space"]["wall_thickness_mm"]==[.8,1.6]
    assert spec["design_space"]["cell_size_mm"]==[5.,10.]
    # Enter SPC with the exact DSN handoff, retaining the actual geometry gate.
    from agents.specimen.agent import SpecimenMakingAgent
    from tests.unit.test_specimen_agent import _CtxStub
    from agents.base_agent import AgentResult
    if test_mode:
        spec["printer_test_path"]="virtual_bridge"
    c._state.current_experiment_spec=spec
    c._state.stage=Stage.SPECIMEN
    spc=_CtxStub()
    spc.tools.register("printer.prepare",lambda p:pytest.fail("Preparation must not actuate"))
    monkeypatch.setattr(SpecimenMakingAgent,"_artifact_dir",lambda *args:tmp_path/"cycle-geometry")
    prepared=SpecimenMakingAgent()._prepare_fabrication(c._state,spc)
    assert not isinstance(prepared, AgentResult), prepared
    assert prepared["manufacturability_result"]["manufacturability_status"]=="pass"
    assert c._state.current_experiment_spec["cell_size_mm"]==contract["requested_parameters"]["cell_size_mm"]
    assert c._state.current_experiment_spec["wall_thickness_mm"]==contract["requested_parameters"]["wall_thickness_mm"]

@pytest.mark.parametrize("mode", ["live", "virtual_bridge", "installed_printer", "physical_print"])
def test_spc_all_modes_enforce_same_bounds_before_geometry(mode, tmp_path, monkeypatch):
    from agents.specimen.agent import SpecimenMakingAgent
    from orchestrator.state import OrchestratorState, Mode
    from tests.unit.test_specimen_agent import _valid_spec, _CtxStub
    spec={**_valid_spec(), "cell_size_bounds_mm":[5.,10.], "wall_thickness_bounds_mm":[.8,1.6],
          "wall_thickness_mm":.7999, "printer_test_path":mode}
    if mode == "live":
        spec.pop("printer_test_path")
    state=OrchestratorState(run_id="isolated",experiment_id="isolated",mode=Mode.LIVE if mode=="live" else Mode.TEST,
        current_experiment_spec=spec)
    ctx=_CtxStub()
    ctx.tools.call=lambda *a,**kw: pytest.fail("Invalid design reached a tool")
    with pytest.raises(ValueError,match="outside user contract"):
        SpecimenMakingAgent()._prepare_fabrication(state,ctx)

@pytest.mark.parametrize("cell,density", [(5.,.8),(5.,1.6),(10.,.8),(10.,1.6)])
def test_real_mesh_all_test_corners(tmp_path,cell,density):
    import trimesh
    from mcp_tools.tpms_geometry import write_smooth_gyroid_stl
    from mcp_tools.wall_thickness import inspect_wall_thickness
    path=tmp_path / "specimen.stl"
    geometry=write_smooth_gyroid_stl(stl_path=path,name="isolated-corner",specimen_size_mm=[30]*3,
        wall_thickness_mm=density,cell_size_mm=cell,resolution=160)
    mesh=trimesh.load_mesh(path)
    assert mesh.is_watertight
    assert mesh.extents==pytest.approx([30]*3,abs=1e-5)
    assert geometry["cell_size_requested_mm"]==cell
    assert geometry["target_wall_thickness_mm"]==density
    assert 0 < geometry["realized_relative_density_without_caps"] < 1
    wall=inspect_wall_thickness(path,minimum_mm=.4,max_samples=4096)
    assert wall["status"] == "pass"
    (tmp_path / "verification.json").write_text(json.dumps({"geometry":geometry,"wall":wall},indent=2))

@pytest.mark.asyncio
@pytest.mark.usefixtures("handoff_no_external")
@pytest.mark.parametrize("mode", ["live", "virtual_bridge", "installed_printer", "physical_print"])
async def test_valid_mesh_reaches_each_printer_dispatch_without_actuation(mode,tmp_path,monkeypatch):
    from agents.specimen.agent import SpecimenMakingAgent
    from orchestrator.state import OrchestratorState, Mode, Stage
    from tests.unit.test_specimen_agent import _valid_spec, _CtxStub
    from mcp_tools.mock_tools import _printer_prepare
    spec={**_valid_spec(), "cell_size_mm":10., "wall_thickness_mm":1.2, "tpms_resolution":96,
          "cell_size_bounds_mm":[5.,10.], "wall_thickness_bounds_mm":[.8,1.6],
          "fdm_min_wall_thickness_mm":.4,"constraints":{"minimum_feature_size_mm":.4},
          "top_cap_enabled":False,"bottom_cap_enabled":False,"top_bottom_cap":False,"skin_thickness_mm":0.,
          "printer_profile":"bambulab_x2d_pla_0p4_nozzle"}
    if mode!="live":
        spec.update(printer_test_path=mode,test_mode_llm_generated=True)
    state=OrchestratorState(run_id="isolated-"+mode,experiment_id="offline",mode=Mode.LIVE,
        stage=Stage.SPECIMEN,current_experiment_spec=spec)
    ctx=_CtxStub();ctx.artifact_run_root=tmp_path
    received=[]
    def dispatch(payload):
        received.append(payload)
        assert Path(payload["stl_path"]).is_file()
        assert payload["experiment_spec"]["wall_thickness_mm"]==1.2
        assert payload["experiment_spec"]["cell_size_mm"]==10.
        return _printer_prepare(payload)
    ctx.tools.register("printer.prepare",dispatch)
    monkeypatch.setattr(SpecimenMakingAgent,"_artifact_dir",lambda *args:tmp_path/"geometry")
    result=await SpecimenMakingAgent().run(state,ctx)
    assert result.success and len(received)==1
    if mode!="live":
        assert received[0]["test_printer_path"]==mode
        assert received[0]["allow_test_printer_live"] is (mode!="virtual_bridge")
    if mode in {"installed_printer","physical_print"}:
        assert received[0]["print"]["use_ejection_only_project_file"] is (mode=="installed_printer")
    (tmp_path/"dispatch.json").write_text(json.dumps(received[0],indent=2,default=str))

@pytest.mark.asyncio
@pytest.mark.usefixtures("handoff_no_external")
async def test_rejected_wall_is_reported_without_print_or_parameter_repair(tmp_path,monkeypatch):
    from agents.specimen.agent import SpecimenMakingAgent
    from orchestrator.state import OrchestratorState, Mode
    from tests.unit.test_specimen_agent import _valid_spec, _CtxStub
    spec={**_valid_spec(),"cell_size_mm":5.,"wall_thickness_mm":.8,"tpms_resolution":160,
        "top_cap_enabled":False,"bottom_cap_enabled":False,"top_bottom_cap":False,"skin_thickness_mm":0.,
        "constraints":{"minimum_feature_size_mm":2.0},"cell_size_bounds_mm":[5.,10.],"wall_thickness_bounds_mm":[.8,1.6]}
    state=OrchestratorState(run_id="rejected-corner",experiment_id="offline",mode=Mode.LIVE,current_experiment_spec=spec)
    ctx=_CtxStub();ctx.artifact_run_root=tmp_path
    ctx.tools.register("printer.prepare",lambda p:pytest.fail("Rejected wall reached printer"))
    monkeypatch.setattr(SpecimenMakingAgent,"_artifact_dir",lambda *args:tmp_path/"geometry")
    result=await SpecimenMakingAgent().run(state,ctx)
    assert result.success is False
    gate=next(g for g in result.data["fabrication_report"]["quality_gates"] if g["gate"]=="manufacturability")
    assert gate["status"]=="fail"
    assert gate["evidence"]["wall_thickness_verification"]["minimum_sampled_mm"]<2.0
    assert state.current_experiment_spec["wall_thickness_mm"]==.8
    assert state.current_experiment_spec["cell_size_mm"]==5.
