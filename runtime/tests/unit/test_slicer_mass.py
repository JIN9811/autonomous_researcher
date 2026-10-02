import json
from pathlib import Path
import zipfile

import pytest

from agents.analysis.agent import AnalysisAgent
from agents.specimen.agent import SpecimenMakingAgent
from tests.unit.test_analysis_agent import _CtxStub, _state
from tests.unit.test_analysis_sea_interval import curve
from tests.unit.test_specimen_agent import _valid_spec
from utils.slicer_mass import sliced_mass_grams, slicer_mass_evidence


def artifact(tmp_path, *, metadata=True):
    path = tmp_path / "specimen.gcode.3mf"
    with zipfile.ZipFile(path, "w") as archive:
        if metadata:
            archive.writestr("Metadata/slice_info.config", '''<config>
              <plate><metadata key="index" value="1"/><metadata key="weight" value="18.19"/></plate>
              <plate><metadata key="index" value="2"/><metadata key="weight" value="7.25"/></plate>
            </config>''')
        archive.writestr("Metadata/plate_1.gcode", "; total filament weight [g] : 18.19\nG28\n")
    return path


def test_mass_reads_selected_plate_not_another_plate(tmp_path):
    path = artifact(tmp_path)
    assert sliced_mass_grams(path) == 18.19
    assert sliced_mass_grams(path, 2) == 7.25
    assert sliced_mass_grams(path, 3) is None
    assert slicer_mass_evidence({"slicer_result": {"ok": True, "sliced_artifact_path": str(path)}})["mass_g"] == 18.19


def test_mass_supports_gcode_header_without_metadata(tmp_path):
    assert sliced_mass_grams(artifact(tmp_path, metadata=False)) == 18.19
    path = tmp_path / "specimen.gcode"
    path.write_text("; filament used [g] = 8.0, 2.5\n")
    assert sliced_mass_grams(path) == 10.5


@pytest.mark.parametrize("value", [None, 0, -1, True, float("nan"), float("inf"), "invalid"])
def test_mass_does_not_accept_invalid_values_or_design_estimates(value):
    assert slicer_mass_evidence({"expected_mass_g": 55, "slicer_result": {"estimated_mass_g": value}})["mass_g"] is None


def test_analysis_uses_slicer_mass_even_if_old_design_and_measured_mass_exist(tmp_path):
    state = _state()
    state.current_experiment_spec.update(expected_mass_g=18.766, measured_mass_g=99)
    state.run_metadata["specimen_result"] = {
        "run_id": state.run_id, "specimen_id": state.current_experiment_spec["specimen_id"],
        "loop_id": state.loop_count, "slicer_result": {"ok": True, "sliced_artifact_path": str(artifact(tmp_path))},
    }
    geometry = AnalysisAgent()._specimen_geometry(state)
    assert geometry["mass_g"] == 18.19
    assert geometry["mass_source"] == "slicer"
    assert geometry["mass_evidence"]["estimated"] is True


@pytest.mark.parametrize("stale", [{"run_id": "old"}, {"specimen_id": "old"}, {"loop_id": 999}])
def test_analysis_rejects_stale_mass(stale):
    state = _state()
    state.run_metadata["specimen_result"] = {**stale, "slicer_result": {"estimated_mass_g": 18.19}}
    assert AnalysisAgent()._specimen_geometry(state)["mass_g"] == 0


def test_spc_report_uses_slicer_mass(tmp_path):
    state = _state()
    report = SpecimenMakingAgent()._build_fabrication_report(
        state=state, spec={**_valid_spec(), "expected_mass_g": 99}, candidate="candidate", specimen_id="specimen",
        geometry_result={"ok": True}, mesh_result={"ok": True, "mesh_status": "pass"},
        manufacturability_result={"ok": True, "expected_mass_g": 88},
        handoff_result={}, experiment_response={},
        printer_response={"ok": True, "slicer_result": {"ok": True, "sliced_artifact_path": str(artifact(tmp_path))}},
        printer_payload={}, protocol_note="", live_gui_test_spec=False,
        printer_test_path="physical_print", top_cap_enabled=False, bottom_cap_enabled=False, geometry_payload={},
    )
    assert report["process_plan"]["estimated_mass_g"] == 18.19
    assert report["process_plan"]["mass_evidence"]["source"] == "slicer"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_mass", [True, False])
async def test_slicer_mass_reaches_sea_bo_knowledge_and_archive(tmp_path, monkeypatch, with_mass):
    monkeypatch.setattr("agents.analysis.agent.resolve_path", lambda value: tmp_path / value)
    state = _state(equipment_result={"ok": True, "utm_data": curve(16)})
    state.current_experiment_spec.update(specimen_size_mm=[30, 30, 30], objective_type="SEA", expected_mass_g=99)
    if with_mass:
        state.run_metadata["specimen_result"] = {"run_id": state.run_id,
            "specimen_id": state.current_experiment_spec["specimen_id"],
            "slicer_result": {"ok": True, "sliced_artifact_path": str(artifact(tmp_path))}}
    result = await AnalysisAgent().run(state, _CtxStub())
    assert result.success
    expected = pytest.approx(112.5 / 18.19) if with_mass else None
    assert result.data["bo_observation"]["objective_score"] == expected
    assert result.data["bo_observation"]["ok_for_bo"] is with_mass
    assert result.data["knowledge_payload"]["metrics"]["specific_energy_absorption_J_per_g"] == expected
    saved = json.loads(Path(result.data["analysis"]["analysis_artifacts"]["experiment_evaluation"]).read_text())
    assert saved["objective_score"] == expected
