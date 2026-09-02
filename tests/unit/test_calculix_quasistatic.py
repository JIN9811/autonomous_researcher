"""Behavior tests for CalculiX quasi-static compression transforms."""

from __future__ import annotations

import pytest

from utils.calculix_quasistatic import (
    build_compression_deck,
    curve_metrics,
    parse_gmsh_inp_mesh,
    parse_reaction_history,
    select_frictionless_boundary_nodes,
)


CUBE_MESH = """*Heading
cube
*Node
1, 0, 0, 0
2, 10, 0, 0
3, 10, 10, 0
4, 0, 10, 0
5, 0, 0, 10
6, 10, 0, 10
7, 10, 10, 10
8, 0, 10, 10
*Element, type=C3D4, elset=VOLUME
1, 1, 2, 3, 5
2, 1, 3, 4, 8
3, 1, 3, 8, 5
4, 3, 5, 7, 8
5, 3, 5, 6, 7
"""


def test_frictionless_boundaries_constrain_faces_only_in_compression_axis() -> None:
    nodes, _ = parse_gmsh_inp_mesh(CUBE_MESH)

    boundary = select_frictionless_boundary_nodes(nodes, tolerance_mm=1e-6)

    assert boundary["bottom_nodes"] == [1, 2, 3, 4]
    assert boundary["top_nodes"] == [5, 6, 7, 8]
    assert boundary["anchor_xy_node"] == 1
    assert boundary["anchor_y_node"] == 2
    assert boundary["height_mm"] == pytest.approx(10.0)


def test_compression_deck_uses_nlgeom_ramp_and_frictionless_face_sets() -> None:
    deck, manifest = build_compression_deck(
        CUBE_MESH,
        material={
            "elastic_modulus_mpa": 1800.0,
            "poisson_ratio": 0.35,
            "yield_strength_mpa": 35.0,
            "plastic_curve": [[35.0, 0.0], [42.0, 0.08]],
        },
        target_displacement_mm=5.0,
        increments={
            "initial": 0.01,
            "time_period": 1.0,
            "minimum": 1e-7,
            "maximum": 0.02,
            "max_increments": 500,
        },
        boundary_tolerance_mm=1e-6,
    )

    assert "*STEP,NLGEOM,INC=500" in deck
    assert "*STATIC\n0.01,1,1e-07,0.02" in deck
    assert "*AMPLITUDE,NAME=QS_RAMP" in deck
    assert "*BOUNDARY,AMPLITUDE=QS_RAMP" in deck
    assert "BOTTOM,3,3,0" in deck
    assert "TOP,3,3,-5" in deck
    assert "ANCHOR_XY,1,2,0" in deck
    assert "ANCHOR_Y,2,2,0" in deck
    assert "BOTTOM,1,2,0" not in deck
    assert "TOP,1,2,0" not in deck
    assert "*NODE PRINT,NSET=TOP,TOTALS=ONLY,FREQUENCY=1" in deck
    assert "\nRF\n" in deck
    assert manifest["target_displacement_mm"] == pytest.approx(5.0)
    assert manifest["frictionless_faces"] is True
    assert manifest["top_in_plane_constrained_dofs"] == 0
    assert manifest["bottom_in_plane_stabilizer_dofs"] == 3


CONVERGED_DAT = """
 displacements (vx,vy,vz) for set TOP and time  5.0000000E-01

 5  0.0000000E+00  0.0000000E+00 -2.5000000E+00
 6  0.0000000E+00  0.0000000E+00 -2.5000000E+00

 forces (fx,fy,fz) for set TOP and time  5.0000000E-01
 total force (fx,fy,fz)
 0.0000000E+00  0.0000000E+00 -1.0000000E+02

 displacements (vx,vy,vz) for set TOP and time  1.0000000E+00

 5  0.0000000E+00  0.0000000E+00 -5.0000000E+00
 6  0.0000000E+00  0.0000000E+00 -5.0000000E+00

 forces (fx,fy,fz) for set TOP and time  1.0000000E+00
 total force (fx,fy,fz)
 0.0000000E+00  0.0000000E+00 -3.0000000E+02
"""


def test_reaction_history_builds_positive_compression_curve_and_energy() -> None:
    result = parse_reaction_history(
        CONVERGED_DAT,
        target_displacement_mm=5.0,
        endpoint_tolerance_mm=1e-6,
    )

    assert result["endpoint_reached"] is True
    assert result["curve"] == [
        {"step_time": 0.0, "displacement_mm": 0.0, "force_N": 0.0},
        {"step_time": 0.5, "displacement_mm": 2.5, "force_N": 100.0},
        {"step_time": 1.0, "displacement_mm": 5.0, "force_N": 300.0},
    ]
    assert result["metrics"]["peak_reaction_force_N"] == pytest.approx(300.0)
    assert result["metrics"]["energy_absorption_50pct_mJ"] == pytest.approx(625.0)


def test_reaction_history_parses_native_calculix_totals_before_displacements() -> None:
    native_dat = """
 total force (fx,fy,fz) for set TOP and time  0.5000000E+00

       -9.0E-16  8.0E-16 -1.000000E+02

 displacements (vx,vy,vz) for set TOP and time  0.5000000E+00

       5  0.0  0.0 -2.500000E+00
       6  0.0  0.0 -2.500000E+00

 total force (fx,fy,fz) for set TOP and time  0.1000000E+01

       0.0  0.0 -3.000000E+02

 displacements (vx,vy,vz) for set TOP and time  0.1000000E+01

       5  0.0  0.0 -5.000000E+00
       6  0.0  0.0 -5.000000E+00
"""

    result = parse_reaction_history(native_dat, target_displacement_mm=5.0)

    assert result["endpoint_reached"] is True
    assert result["curve"][1] == {
        "step_time": 0.5,
        "displacement_mm": 2.5,
        "force_N": 100.0,
    }
    assert result["curve"][-1] == {
        "step_time": 1.0,
        "displacement_mm": 5.0,
        "force_N": 300.0,
    }


def test_partial_reaction_curve_does_not_extrapolate_target_energy() -> None:
    metrics = curve_metrics(
        [
            {"step_time": 0.0, "displacement_mm": 0.0, "force_N": 0.0},
            {"step_time": 1.0, "displacement_mm": 4.9, "force_N": 290.0},
        ],
        target_displacement_mm=5.0,
        endpoint_tolerance_mm=1e-6,
    )

    assert metrics["endpoint_reached"] is False
    assert metrics["last_converged_displacement_mm"] == pytest.approx(4.9)
    assert metrics["energy_absorption_50pct_mJ"] is None
