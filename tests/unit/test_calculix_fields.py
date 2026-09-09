"""Contract tests for strict CalculiX ASCII field conversion."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from utils.calculix_fields import postprocess_fields
from device_bridges.calculix_bridge import CalculiXBridge, CalculiXBridgeConfig


TETRA_INP = """*Heading
strict tetra fixture
*Node
10, 0, 0, 0
30, 1, 0, 0
20, 0, 1, 0
40, 0, 0, 1
*Element, type=C3D4, elset=VOLUME
77, 10, 30, 20, 40
"""


TETRA_FRD = """    1CSTRICT
    2C                             4                                     1
 -1        10 0.00000E+00 0.00000E+00 0.00000E+00
 -1        30 1.00000E+00 0.00000E+00 0.00000E+00
 -1        20 0.00000E+00 1.00000E+00 0.00000E+00
 -1        40 0.00000E+00 0.00000E+00 1.00000E+00
 -3
    3C                             1                                     1
 -1        77    3    0    1
 -2        10        30        20        40
 -3
    1PSTEP                         3           2           1
  100CL  101 2.00000E-01           4                     0    2           1
 -4  DISP        4    1
 -5  D1          1    2    1    0
 -5  D2          1    2    2    0
 -5  D3          1    2    3    0
 -5  ALL         1    2    0    0    1ALL
 -1        10 0.00000E+00 0.00000E+00-2.00000E-01
 -1        30 1.00000E-02 0.00000E+00-2.00000E-01
 -1        20 0.00000E+00 2.00000E-02-2.00000E-01
 -1        40 0.00000E+00 0.00000E+00-3.00000E-01
 -3
    1PSTEP                         1           1           1
  100CL  101 5.00000E-01           4                     0    1           1
 -4  DISP        4    1
 -5  D1          1    2    1    0
 -5  D2          1    2    2    0
 -5  D3          1    2    3    0
 -5  ALL         1    2    0    0    1ALL
 -1        10 0.00000E+00 0.00000E+00-1.00000E-01
 -1        30 1.00000E-02 0.00000E+00-1.00000E-01
 -1        20 0.00000E+00 2.00000E-02-1.00000E-01
 -1        40 0.00000E+00 0.00000E+00-2.00000E-01
 -3
    1PSTEP                         2           1           1
  100CL  101 5.00000E-01           4                     0    1           1
 -4  STRESS      6    1
 -5  SXX         1    4    1    1
 -5  SYY         1    4    2    2
 -5  SZZ         1    4    3    3
 -5  SXY         1    4    1    2
 -5  SYZ         1    4    2    3
 -5  SZX         1    4    3    1
 -1        10 1.00000E+02 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00
 -1        30 0.00000E+00 1.00000E+02 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00
 -1        20 0.00000E+00 0.00000E+00 1.00000E+02 0.00000E+00 0.00000E+00 0.00000E+00
 -1        40 1.00000E+02 1.00000E+02 1.00000E+02 0.00000E+00 0.00000E+00 0.00000E+00
 -3
 9999
"""


def _write_case(tmp_path: Path, inp: str, frd: str) -> tuple[Path, Path]:
    inp_path = tmp_path / "case.inp"
    frd_path = tmp_path / "case.frd"
    inp_path.write_text(inp, encoding="ascii")
    frd_path.write_text(frd, encoding="ascii")
    return inp_path, frd_path


def test_real_calculix_pe_scalar_maps_to_equivalent_plastic_strain(tmp_path):
    """CCX 2.21 emits dataset PE, component PE for requested PEEQ."""
    block = """    1PSTEP                         4           1           1
  100CL  101 5.00000E-01           4                     0    1           1
 -4  PE          1    1
 -5  PE          1    1    0    0
 -1        10 1.00000E-02
 -1        30 2.00000E-02
 -1        20 3.00000E-02
 -1        40 4.00000E-02
 -3
"""
    paths = _write_case(tmp_path, TETRA_INP, TETRA_FRD.replace(' 9999\n', block+' 9999\n'))
    result = postprocess_fields(*paths, tmp_path/'fields')
    assert result['status'] == 'complete', result.get('errors')
    fields = next(frame['fields'] for frame in result['frames'] if frame['value'] == 0.5)
    assert fields['PEEQ']['components'] == ['PEEQ']
    assert fields['PEEQ']['values'] == [[0.01], [0.02], [0.03], [0.04]]
    assert 'U' in fields and 'S_MISES' in fields


def test_frd_coordinate_rounding_is_not_geometry_mismatch(tmp_path):
    inp = TETRA_INP.replace('30, 1, 0, 0', '30, 1.23456789, 0, 0')
    frd = TETRA_FRD.replace('30 1.00000E+00', '30 1.23457E+00')
    paths = _write_case(tmp_path, inp, frd)
    result = postprocess_fields(*paths, tmp_path / 'fields')
    assert result['status'] == 'complete'
    assert result['geometry']['points'][1][0] == 1.23456789
    paths = _write_case(tmp_path, inp, frd.replace('30 1.23457E+00', '30 1.23467E+00'))
    assert postprocess_fields(*paths, tmp_path / 'bad')['failure_code'] == 'CALCULIX_FIELD_MESH_MISMATCH'


def test_export_io_failure_is_field_failure_not_exception(tmp_path, monkeypatch):
    import utils.calculix_fields as module
    paths = _write_case(tmp_path, TETRA_INP, TETRA_FRD)
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(module, '_write_assets', fail)
    result = module.postprocess_fields(*paths, tmp_path / 'fields')
    assert result['status'] == 'failed'
    assert result['failure_code'] == 'CALCULIX_FIELD_IO_FAILED'


def test_converter_budget_is_explicit(tmp_path, monkeypatch):
    import utils.calculix_fields as module
    paths = _write_case(tmp_path, TETRA_INP, TETRA_FRD)
    monkeypatch.setattr(module, 'MAX_FIELD_FILE_BYTES', 20, raising=False)
    assert module.postprocess_fields(*paths, tmp_path / 'fields')['failure_code'] == 'CALCULIX_FIELD_BUDGET_EXCEEDED'


def test_duplicate_cell_connectivity_is_not_valid_internal_volume(tmp_path):
    inp = TETRA_INP + '78, 10, 30, 20, 40\n'
    frd = TETRA_FRD.replace(' -2        10        30        20        40\n', ' -2        10        30        20        40\n -1        78    3    0    1\n -2        10        30        20        40\n', 1)
    paths = _write_case(tmp_path, inp, frd)
    result = postprocess_fields(*paths, tmp_path / 'fields')
    assert result['failure_code'] == 'CALCULIX_FIELD_MESH_INVALID'


def test_postprocess_maps_original_ids_orders_frames_and_derives_mises(tmp_path: Path) -> None:
    """Catch positional-ID mapping, file-order frame sorting, or tensor-order regressions."""
    inp_path, frd_path = _write_case(tmp_path, TETRA_INP, TETRA_FRD)

    result = postprocess_fields(inp_path, frd_path, tmp_path / "fields")

    assert result["schema"] == "cae_fields.v1"
    assert result["status"] == "complete"
    assert result["geometry"]["node_ids"] == [10, 30, 20, 40]
    assert result["geometry"]["elements"] == [
        {"id": 77, "type": "C3D4", "connectivity": [10, 30, 20, 40]}
    ]
    assert len(result["geometry"]["surface"]["triangles"]) == 4
    assert result["geometry"]["surface"]["owner_element_ids"] == [77, 77, 77, 77]
    assert [(frame["step"], frame["increment"], frame["value"]) for frame in result["frames"]] == [
        (1, 1, 0.5),
        (1, 2, 0.2),
    ]
    first = result["frames"][0]
    assert first["fields"]["U"]["values"] == [
        [0.0, 0.0, -0.1],
        [0.01, 0.0, -0.1],
        [0.0, 0.02, -0.1],
        [0.0, 0.0, -0.2],
    ]
    assert first["fields"]["U"]["association"] == "point"
    assert first["fields"]["U"]["units"] == "mm"
    assert first["fields"]["S"]["components"] == ["SXX", "SYY", "SZZ", "SXY", "SYZ", "SZX"]
    assert first["fields"]["S"]["association"] == "point"
    assert first["fields"]["S"]["averaging"] == "solver_extrapolated_and_nodal_averaged"
    assert first["fields"]["S_MISES"]["values"] == [[100.0], [100.0], [100.0], [0.0]]
    assert first["fields"]["S_MISES"]["derived_from"] == "S"
    assert result["mesh_evidence"]["validity"]["status"] == "valid"
    assert result["mesh_evidence"]["volume"]["minimum_mm3"] == pytest.approx(1.0 / 6.0)
    assert "combined_score" not in result["mesh_evidence"]["quality"]
    assert Path(result["geometry_path"]).is_file()
    assert Path(result["frames_path"]).is_file()
    assert json.loads(Path(result["field_asset_path"]).read_text(encoding="utf-8"))["schema"] == "cae_fields.v1"
    assert result["field_asset_path"].endswith(".fields.json")


def test_postprocess_does_not_fill_missing_full_node_displacement(tmp_path: Path) -> None:
    """Catch fabricated zero/interpolated displacement for nodes absent from FRD output."""
    missing = TETRA_FRD.replace(
        " -1        40 0.00000E+00 0.00000E+00-2.00000E-01\n -3\n    1PSTEP                         2",
        " -3\n    1PSTEP                         2",
    ).replace(
        "  100CL  101 5.00000E-01           4                     0    1           1",
        "  100CL  101 5.00000E-01           3                     0    1           1",
        1,
    )
    inp_path, frd_path = _write_case(tmp_path, TETRA_INP, missing)

    result = postprocess_fields(inp_path, frd_path, tmp_path / "fields")

    assert result["status"] == "failed"
    assert result["failure_code"] == "CALCULIX_FIELD_DISPLACEMENT_INCOMPLETE"
    assert result["errors"][0]["missing_node_ids"] == [40]
    assert "U" not in result["frames"][0]["fields"]


def test_postprocess_rejects_connectivity_to_unknown_node(tmp_path: Path) -> None:
    """Catch geometry export that leaves dangling connectivity."""
    invalid_inp = TETRA_INP.replace("77, 10, 30, 20, 40", "77, 10, 30, 20, 999")
    inp_path, frd_path = _write_case(tmp_path, invalid_inp, TETRA_FRD)

    result = postprocess_fields(inp_path, frd_path, tmp_path / "fields")

    assert result["status"] == "failed"
    assert result["failure_code"] == "CALCULIX_FIELD_CONNECTIVITY_INVALID"
    assert result["errors"] == [{"element_id": 77, "unknown_node_ids": [999]}]
    assert result["field_asset_path"] == ""


def test_postprocess_rejects_high_order_tetra_without_linearizing(tmp_path: Path) -> None:
    """Catch silently discarding midside nodes from a C3D10 element."""
    inp = TETRA_INP.replace(
        "40, 0, 0, 1\n*Element, type=C3D4, elset=VOLUME\n77, 10, 30, 20, 40",
        "40, 0, 0, 1\n50, .5, 0, 0\n60, .5, .5, 0\n70, 0, .5, 0\n80, 0, 0, .5\n90, .5, 0, .5\n100, 0, .5, .5\n*Element, type=C3D10, elset=VOLUME\n77, 10, 30, 20, 40, 50, 60, 70, 80, 90, 100",
    )
    inp_path, frd_path = _write_case(tmp_path, inp, TETRA_FRD)

    result = postprocess_fields(inp_path, frd_path, tmp_path / "fields")

    assert result["status"] == "unsupported"
    assert result["failure_code"] == "CALCULIX_FIELD_TOPOLOGY_UNSUPPORTED"
    assert result["unsupported_topologies"] == ["C3D10"]
    assert result["geometry_path"] == ""


def test_postprocess_rejects_frd_mesh_that_does_not_match_input(tmp_path: Path) -> None:
    """Catch field values being attached to a different result-file mesh."""
    mismatched = TETRA_FRD.replace(
        " -2        10        30        20        40",
        " -2        10        20        30        40",
    )
    inp_path, frd_path = _write_case(tmp_path, TETRA_INP, mismatched)

    result = postprocess_fields(inp_path, frd_path, tmp_path / "fields")

    assert result["status"] == "failed"
    assert result["failure_code"] == "CALCULIX_FIELD_MESH_MISMATCH"
    assert result["errors"][0]["element_id"] == 77


def test_calculix_postprocess_propagates_field_assets(tmp_path: Path) -> None:
    """Catch bridge responses that retain FRD but drop viewer field artifacts."""
    inp_path, frd_path = _write_case(tmp_path, TETRA_INP, TETRA_FRD)
    bridge = CalculiXBridge(CalculiXBridgeConfig(artifact_dir=tmp_path / "artifacts"))

    result = bridge.postprocess({"inp_path": str(inp_path), "frd_path": str(frd_path)})

    assert result["ok"] is True
    assert result["field_status"] == "complete"
    assert result["field_manifest"]["schema"] == "cae_fields.v1"
    assert result["field_asset_path"].endswith(".fields.json")
    assert Path(result["geometry_path"]).is_file()
    assert Path(result["frames_path"]).is_file()


def test_nested_computation_limits_bound_timeout_and_solver_threads(tmp_path: Path) -> None:
    """Catch per-call budgets being ignored or allowed to widen configured limits."""
    fake_ccx = tmp_path / "ccx"
    fake_ccx.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys, time\n"
        "if sys.argv[1] == '-v':\n"
        "    print('CalculiX fixture')\n"
        "    raise SystemExit(0)\n"
        "pathlib.Path('solver-env.txt').write_text(os.environ.get('OMP_NUM_THREADS', ''))\n"
        "time.sleep(1)\n",
        encoding="utf-8",
    )
    fake_ccx.chmod(0o755)
    inp_path = tmp_path / "limited.inp"
    inp_path.write_text("*Heading\n", encoding="utf-8")
    bridge = CalculiXBridge(
        CalculiXBridgeConfig(
            executable_path=str(fake_ccx),
            runtime_solver_enabled=True,
            timeout_s=0.08,
            artifact_dir=tmp_path / "artifacts",
        )
    )

    result = bridge.solve(
        {
            "inp_path": str(inp_path),
            "runtime_solver_enabled": True,
            "computation_limits": {"timeout_s": 0.05, "threads": 2},
        }
    )

    assert result["failure_code"] == "CALCULIX_TIMEOUT"
    assert result["computation_limits"] == {"timeout_s": 0.05, "threads": 2}
    assert (tmp_path / "solver-env.txt").read_text(encoding="utf-8") == "2"

    wider = bridge.solve(
        {
            "inp_path": str(inp_path),
            "runtime_solver_enabled": True,
            "computation_limits": {"timeout_s": 5.0, "threads": 2},
        }
    )

    assert wider["failure_code"] == "CALCULIX_TIMEOUT"
    assert wider["computation_limits"]["timeout_s"] == 0.08


def test_mesh_element_limit_blocks_oversized_generated_mesh(tmp_path: Path) -> None:
    """Catch a per-call mesh budget being recorded but not enforced before solve."""
    fake_gmsh = tmp_path / "gmsh"
    fake_gmsh.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "if '--version' in sys.argv:\n"
        "    print('fixture gmsh')\n"
        "    raise SystemExit(0)\n"
        "output = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "output.write_text('*Node\\n1,0,0,0\\n2,1,0,0\\n3,0,1,0\\n4,0,0,1\\n5,1,1,1\\n'"
        "+ '*Element,type=C3D4,elset=VOLUME\\n1,1,2,3,4\\n2,2,3,4,5\\n')\n",
        encoding="utf-8",
    )
    fake_gmsh.chmod(0o755)
    stl_path = tmp_path / "fixture.stl"
    stl_path.write_text("solid fixture\nendsolid fixture\n", encoding="utf-8")
    bridge = CalculiXBridge(
        CalculiXBridgeConfig(gmsh_path=str(fake_gmsh), artifact_dir=tmp_path / "artifacts")
    )

    result = bridge.mesh_stl(
        {
            "stl_path": str(stl_path),
            "run_id": "limited",
            "specimen_id": "tetra",
            "computation_limits": {"max_mesh_elements": 1},
        }
    )

    assert result["ok"] is False
    assert result["failure_code"] == "CAE_MESH_ELEMENT_LIMIT_EXCEEDED"
    assert result["mesh_element_count"] == 2
    assert result["computation_limits"]["max_mesh_elements"] == 1
