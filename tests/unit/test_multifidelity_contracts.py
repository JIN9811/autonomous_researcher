"""Unit tests for Improvement 15 multi-fidelity contracts."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from device_bridges.calculix_bridge import CalculiXBridge, CalculiXBridgeConfig
from device_bridges.pinn_bridge import PINNBridge, PINNBridgeConfig
from experiments.schemas import (
    FEAResult,
    MultifidelityJob,
    PINNModelRecord,
    TrustScore,
    UTMRecord,
)
from mcp_tools.calculix_tools import register_calculix_tools
from mcp_tools.pinn_tools import register_pinn_tools
from mcp_tools.tool_registry import ToolRegistry


def test_multifidelity_schema_models_are_additive() -> None:
    trust = TrustScore(score=0.82, gate="allow_bo", components={"q_data": 1.0})
    utm = UTMRecord(specimen_id="specimen-1", displacement_mm=[0.0, 1.0], force_n=[0.0, 120.0])
    fea = FEAResult(specimen_id="specimen-1", solver_meta={"solver": "calculix"})
    pinn = PINNModelRecord(model_id="pinn-fixture", family="pinn")
    job = MultifidelityJob(job_type="analysis_compare", specimen_id="specimen-1", trust_score=trust)

    assert trust.schema == "trust_score.v1"
    assert utm.schema == "utm_record.v1"
    assert fea.schema == "fea_result.v1"
    assert pinn.schema == "pinn_model_record.v1"
    assert job.schema == "multifidelity_job.v1"
    assert job.trust_score.gate == "allow_bo"


def test_calculix_bridge_contract_blocks_without_runtime_solver(tmp_path: Path) -> None:
    bridge = CalculiXBridge(
        CalculiXBridgeConfig(
            enabled=True,
            mode="live",
            runtime_solver_enabled=False,
            artifact_dir=tmp_path,
        )
    )

    health = bridge.health()
    prepared = bridge.prepare_input({"specimen_id": "specimen-1", "inp_text": "*Heading\n"})
    result = bridge.run_job({"specimen_id": "specimen-1", "inp_text": "*Heading\n"})

    assert health["tool"] == "calculix.health"
    assert prepared["ok"] is True
    assert prepared["inp_path"].endswith(".inp")
    assert result["ok"] is False
    assert result["failure_code"] == "CALCULIX_RUNTIME_SOLVER_DISABLED"
    assert result["status"] == "blocked"


def test_calculix_health_reports_solver_and_mesher_versions(tmp_path: Path) -> None:
    fake_ccx = tmp_path / "ccx"
    fake_ccx.write_text(f"#!{sys.executable}\nprint('CalculiX 2.21')\n", encoding="utf-8")
    fake_ccx.chmod(0o755)
    fake_gmsh = tmp_path / "gmsh"
    fake_gmsh.write_text(f"#!{sys.executable}\nprint('4.12.1')\n", encoding="utf-8")
    fake_gmsh.chmod(0o755)
    bridge = CalculiXBridge(
        CalculiXBridgeConfig(
            executable_path=str(fake_ccx),
            gmsh_path=str(fake_gmsh),
            artifact_dir=tmp_path / "artifacts",
        )
    )

    health = bridge.health()

    assert health["calculix"]["version"] == "CalculiX 2.21"
    assert health["gmsh"]["version"] == "4.12.1"


def test_calculix_health_version_probe_is_filesystem_isolated(tmp_path: Path, monkeypatch) -> None:
    fake_ccx = tmp_path / "ccx"
    fake_ccx.write_text(
        f"#!{sys.executable}\n"
        "import pathlib\n"
        "pathlib.Path('-v.dat').write_text('probe side effect')\n"
        "print('CalculiX test probe')\n",
        encoding="utf-8",
    )
    fake_ccx.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    bridge = CalculiXBridge(
        CalculiXBridgeConfig(executable_path=str(fake_ccx), artifact_dir=tmp_path / "artifacts")
    )

    health = bridge.health()

    assert health["calculix"]["version"] == "CalculiX test probe"
    assert not (tmp_path / "-v.dat").exists()


def test_calculix_timeout_retains_partial_dat_and_frd_paths(tmp_path: Path) -> None:
    fake_ccx = tmp_path / "ccx"
    fake_ccx.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys, time\n"
        "if sys.argv[1] == '-v':\n"
        "    print('CalculiX 2.21')\n"
        "    raise SystemExit(0)\n"
        "job = pathlib.Path(sys.argv[1])\n"
        "pathlib.Path(job.name + '.dat').write_text('partial history')\n"
        "pathlib.Path(job.name + '.frd').write_text('partial field')\n"
        "time.sleep(2)\n",
        encoding="utf-8",
    )
    fake_ccx.chmod(0o755)
    inp_path = tmp_path / "partial.inp"
    inp_path.write_text("*Heading\n", encoding="utf-8")
    bridge = CalculiXBridge(
        CalculiXBridgeConfig(
            executable_path=str(fake_ccx),
            runtime_solver_enabled=True,
            artifact_dir=tmp_path / "artifacts",
        )
    )

    result = bridge.solve(
        {"inp_path": str(inp_path), "runtime_solver_enabled": True, "timeout_s": 0.05}
    )

    assert result["failure_code"] == "CALCULIX_TIMEOUT"
    assert result["dat_path"].endswith("partial.dat")
    assert result["frd_path"].endswith("partial.frd")
    assert Path(result["dat_path"]).exists()


def test_calculix_job_returns_parsed_partial_curve_after_timeout(tmp_path: Path) -> None:
    dat_path = tmp_path / "partial.dat"
    dat_path.write_text(
        "total force (fx,fy,fz) for set TOP and time  0.5000000E+00\n"
        "0 0 -100\n"
        "displacements (vx,vy,vz) for set TOP and time  0.5000000E+00\n"
        "5 0 0 -2.5\n",
        encoding="utf-8",
    )
    inp_path = tmp_path / "partial.inp"
    inp_path.write_text("*Heading\n", encoding="utf-8")

    class _TimedOutBridge(CalculiXBridge):
        def prepare_quasistatic_input(self, payload):
            return {
                "ok": True,
                "inp_path": str(inp_path),
                "target_displacement_mm": 5.0,
                "mesh_inp_path": str(tmp_path / "mesh.inp"),
                "geo_path": str(tmp_path / "mesh.geo"),
                "manifest_path": str(tmp_path / "manifest.json"),
            }

        def solve(self, payload=None):
            return {
                "ok": False,
                "status": "failed",
                "failure_code": "CALCULIX_TIMEOUT",
                "inp_path": str(inp_path),
                "dat_path": str(dat_path),
                "frd_path": "",
            }

    bridge = _TimedOutBridge(CalculiXBridgeConfig(artifact_dir=tmp_path))

    result = bridge.run_job(
        {
            "analysis_type": "quasistatic_compression",
            "specimen_id": "partial",
            "target_strain": 0.5,
        }
    )

    assert result["ok"] is False
    assert result["status"] == "partial"
    assert result["failure_code"] == "CALCULIX_TIMEOUT"
    assert result["metrics"]["last_converged_displacement_mm"] == 2.5
    assert result["metrics"]["energy_absorption_50pct_mJ"] is None
    assert Path(result["artifacts"]["curve_json_path"]).exists()


def test_calculix_job_rejects_malformed_reaction_history(tmp_path: Path) -> None:
    dat_path = tmp_path / "malformed.dat"
    dat_path.write_text("solver banner without requested history\n", encoding="utf-8")
    inp_path = tmp_path / "malformed.inp"
    inp_path.write_text("*Heading\n", encoding="utf-8")

    class _MalformedBridge(CalculiXBridge):
        def prepare_quasistatic_input(self, payload):
            return {
                "ok": True,
                "inp_path": str(inp_path),
                "target_displacement_mm": 5.0,
                "mesh_inp_path": "",
                "geo_path": "",
                "manifest_path": "",
            }

        def solve(self, payload=None):
            return {
                "ok": True,
                "status": "completed",
                "failure_code": None,
                "inp_path": str(inp_path),
                "dat_path": str(dat_path),
                "frd_path": "",
            }

    result = _MalformedBridge(CalculiXBridgeConfig(artifact_dir=tmp_path)).run_job(
        {"analysis_type": "quasistatic_compression", "specimen_id": "malformed"}
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["failure_code"] == "CALCULIX_RESULT_PARSE_FAILED"


def test_pinn_bridge_contract_returns_unavailable_without_active_model(tmp_path: Path) -> None:
    bridge = PINNBridge(PINNBridgeConfig(enabled=True, mode="test", artifact_dir=tmp_path))

    health = bridge.health()
    dataset = bridge.build_dataset({"specimen_id": "specimen-1", "utm_curve": [{"x": 0, "y": 0}]})
    prediction = bridge.predict({"specimen_id": "specimen-1"})

    assert health["tool"] == "pinn.health"
    assert dataset["ok"] is True
    assert dataset["dataset_path"].endswith(".json")
    assert prediction["ok"] is False
    assert prediction["status"] == "unavailable"
    assert prediction["failure_code"] == "PINN_MODEL_UNAVAILABLE"


def test_multifidelity_tools_are_registered(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_calculix_tools(registry, {"devices": {"calculix": {"enabled": True, "mode": "test", "artifact_dir": str(tmp_path / "ccx")}}}, repo_root=tmp_path)
    register_pinn_tools(registry, {"devices": {"pinn": {"enabled": True, "mode": "test", "artifact_dir": str(tmp_path / "pinn")}}}, repo_root=tmp_path)

    tools = set(registry.list_tools())

    assert {"calculix.health", "calculix.prepare_input", "calculix.run_job"}.issubset(tools)
    assert {"pinn.health", "pinn.dataset.build", "pinn.predict", "pinn.registry"}.issubset(tools)
    assert registry.call("pinn.predict", {"specimen_id": "specimen-1"})["failure_code"] == "PINN_MODEL_UNAVAILABLE"


def test_calculix_bridge_runs_quasistatic_mesh_solve_and_postprocess(tmp_path: Path) -> None:
    fake_gmsh = tmp_path / "gmsh"
    fake_gmsh.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "output = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "output.write_text('''*Heading\n*Node\n"
        "1,0,0,0\n2,10,0,0\n3,10,10,0\n4,0,10,0\n"
        "5,0,0,10\n6,10,0,10\n7,10,10,10\n8,0,10,10\n"
        "*Element,type=C3D4,elset=VOLUME\n1,1,2,3,5\n''')\n",
        encoding="utf-8",
    )
    fake_gmsh.chmod(0o755)
    fake_ccx = tmp_path / "ccx"
    fake_ccx.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "job = pathlib.Path(sys.argv[1])\n"
        "pathlib.Path(job.name + '.dat').write_text('''"
        "displacements (vx,vy,vz) for set TOP and time  5.0000000E-01\n"
        "5 0 0 -2.5\n6 0 0 -2.5\n"
        "forces (fx,fy,fz) for set TOP and time  5.0000000E-01\n"
        "total force (fx,fy,fz)\n0 0 -100\n"
        "displacements (vx,vy,vz) for set TOP and time  1.0000000E+00\n"
        "5 0 0 -5\n6 0 0 -5\n"
        "forces (fx,fy,fz) for set TOP and time  1.0000000E+00\n"
        "total force (fx,fy,fz)\n0 0 -300\n''')\n"
        "pathlib.Path(job.name + '.frd').write_text('fake frd')\n",
        encoding="utf-8",
    )
    fake_ccx.chmod(0o755)
    stl_path = tmp_path / "cube.stl"
    stl_path.write_text("solid cube\nendsolid cube\n", encoding="utf-8")
    bridge = CalculiXBridge(
        CalculiXBridgeConfig(
            enabled=True,
            mode="live",
            executable_path=str(fake_ccx),
            gmsh_path=str(fake_gmsh),
            runtime_solver_enabled=True,
            artifact_dir=tmp_path / "artifacts",
        )
    )

    result = bridge.run_job(
        {
            "analysis_type": "quasistatic_compression",
            "run_id": "run-quasistatic",
            "specimen_id": "cube",
            "stl_path": str(stl_path),
            "specimen_size_mm": [10.0, 10.0, 10.0],
            "mesh_size_mm": 2.0,
            "target_strain": 0.5,
            "material": {"elastic_modulus_mpa": 1800.0, "poisson_ratio": 0.35, "yield_strength_mpa": 35.0},
            "runtime_solver_enabled": True,
        }
    )

    assert result["ok"] is True
    assert result["solver_mode"] == "calculix_quasistatic"
    assert result["target_displacement_mm"] == 5.0
    assert result["metrics"]["endpoint_reached"] is True
    assert result["metrics"]["energy_absorption_50pct_mJ"] == 625.0
    assert Path(result["artifacts"]["mesh_inp_path"]).exists()
    assert Path(result["artifacts"]["curve_json_path"]).exists()
    geo_text = Path(result["artifacts"]["geo_path"]).read_text(encoding="utf-8")
    assert "ClassifySurfaces" not in geo_text
    assert "CreateGeometry" not in geo_text
    assert "Mesh 3" not in geo_text
    assert json.loads(Path(result["artifacts"]["curve_json_path"]).read_text(encoding="utf-8"))["metrics"]["endpoint_reached"] is True
